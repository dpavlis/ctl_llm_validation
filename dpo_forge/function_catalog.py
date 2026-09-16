"""CTL2 built-in function catalog — deterministic, in-process documentation lookup.

Ported from the examples_validator project (src/ctl_examples_validator/
function_catalog.py, snapshot 2026-09-06) with three deliberate changes:

  * `jsonschema` is optional here. When importable it validates the model's
    tool arguments exactly as upstream does; otherwise a small hand-rolled
    check covers the same shape, so a thin environment can still run the
    judge.
  * Upstream's ConfigError / ResponseValidationError are collapsed onto
    CatalogError / CatalogQueryError (dpo_forge has no shared errors module).
  * `openai_tool()` / `anthropic_tool()` emit the provider-specific tool
    declarations ReviewJudgeClient needs; upstream's `discover()` shape is
    kept underneath as the single source of truth for name/description/schema.

The library file (resources/ctl-function-library.json) is generated upstream
from the CloverDX CTL2 .adoc documentation plus runtime probes, and carries,
per function and per OVERLOAD: canonical signature, parameter types and
positions, arity bounds, return type and nullability, documented runtime
errors, and — the part the judge cannot reliably derive on its own —
PARAMETER-SPECIFIC null behavior (`returns_null`, `runtime_error`, ...).

The catalog never compiles anything and never leaves the process: every
lookup is a dict access against the loaded JSON, so it is free, deterministic
and safe to call inside a judge tool loop.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence

try:  # optional — see module docstring
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import ValidationError as _JSONSchemaValidationError
except ModuleNotFoundError:  # pragma: no cover - thin environment
    Draft202012Validator = None
    _JSONSchemaValidationError = None


class CatalogError(RuntimeError):
    """The library file is missing, unreadable, or not a valid catalog."""


class CatalogQueryError(RuntimeError):
    """The model sent tool arguments that do not match the query schema."""


FUNCTION_INFO_TOOL_NAME = "ctl_function_info"
_DEFAULT_LIBRARY_PATH = Path(__file__).parent.parent / "resources" / "ctl-function-library.json"
SUPPORTED_SCHEMA_VERSION = "1.0.0"
_SPACE = re.compile(r"\s+")


def _load_library(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        raise CatalogError(f"function lookup library not found: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError as exc:
        raise CatalogError(f"function lookup library is not valid UTF-8: {path}") from exc
    except json.JSONDecodeError as exc:
        raise CatalogError(
            f"function lookup library is not valid JSON at line {exc.lineno}: {path}"
        ) from exc
    except OSError as exc:
        raise CatalogError(f"cannot read function lookup library {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CatalogError("function lookup library root must be an object")
    return value


def validate_function_library(path: Path) -> Dict[str, Any]:
    library = _load_library(path)
    if library.get("schema_version") != SUPPORTED_SCHEMA_VERSION:
        raise CatalogError(
            "function lookup library schema_version must be "
            f"{SUPPORTED_SCHEMA_VERSION!r}: {path}"
        )
    if library.get("library_id") != "cloverdx-ctl2-builtins":
        raise CatalogError(
            "function lookup library_id must be 'cloverdx-ctl2-builtins': "
            f"{path}"
        )
    functions = library.get("functions")
    if not isinstance(functions, dict) or not functions:
        raise CatalogError("function lookup library functions must be a non-empty object")
    for name, function in functions.items():
        where = f"functions.{name}"
        if not isinstance(name, str) or not name:
            raise CatalogError("function lookup library contains an invalid function key")
        if not isinstance(function, dict) or function.get("name") != name:
            raise CatalogError(f"{where}.name must exactly match its function key")
        overloads = function.get("overloads")
        if not isinstance(overloads, list) or not overloads:
            raise CatalogError(f"{where}.overloads must be a non-empty array")
        ids: set[str] = set()
        for index, overload in enumerate(overloads):
            location = f"{where}.overloads[{index}]"
            if not isinstance(overload, dict):
                raise CatalogError(f"{location} must be an object")
            overload_id = overload.get("id")
            if not isinstance(overload_id, str) or not overload_id:
                raise CatalogError(f"{location}.id must be a non-empty string")
            if overload_id in ids:
                raise CatalogError(f"{where} contains duplicate overload id {overload_id!r}")
            ids.add(overload_id)
            if not isinstance(overload.get("canonical_signature"), str):
                raise CatalogError(f"{location}.canonical_signature must be a string")
            if not isinstance(overload.get("parameters"), list):
                raise CatalogError(f"{location}.parameters must be an array")
            arity = overload.get("arity")
            if not isinstance(arity, dict):
                raise CatalogError(f"{location}.arity must be an object")
            minimum = arity.get("minimum")
            maximum = arity.get("maximum")
            if not isinstance(minimum, int) or isinstance(minimum, bool) or minimum < 0:
                raise CatalogError(f"{location}.arity.minimum must be a non-negative integer")
            if not (
                (isinstance(maximum, int) and not isinstance(maximum, bool) and maximum >= minimum)
                or maximum == "unbounded"
            ):
                raise CatalogError(
                    f"{location}.arity.maximum must be >= minimum or 'unbounded'"
                )
            if not isinstance(overload.get("returns"), dict):
                raise CatalogError(f"{location}.returns must be an object")
    return library


def _normalize_type(value: str) -> str:
    normalized = _SPACE.sub("", value)
    return "number" if normalized == "double" else normalized


def _split_map(value: str) -> tuple[str, str] | None:
    if not value.startswith("map[") or not value.endswith("]"):
        return None
    inner = value[4:-1]
    depth = 0
    for index, char in enumerate(inner):
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
        elif char == "," and depth == 0:
            return inner[:index], inner[index + 1 :]
    return None


def _type_matches(
    query: str,
    documented: Mapping[str, Any],
    bindings: Dict[str, str],
) -> bool:
    query = _normalize_type(query)
    if query in {"unknown", "null"}:
        return True
    display = documented.get("display")
    if isinstance(display, str) and query == _normalize_type(display):
        return True
    kind = documented.get("kind")
    if kind == "any":
        return True
    if kind == "type_variable":
        name = documented.get("name")
        if not isinstance(name, str):
            return False
        bound = bindings.get(name)
        if bound is None or query in {"unknown", "null"}:
            if query not in {"unknown", "null"}:
                bindings[name] = query
            return True
        return bound == query
    if kind == "named":
        name = documented.get("name")
        return isinstance(name, str) and query == _normalize_type(name)
    if kind == "family":
        members = documented.get("members")
        return isinstance(members, list) and query in {
            _normalize_type(item) for item in members if isinstance(item, str)
        }
    if kind == "union":
        options = documented.get("options")
        return isinstance(options, list) and any(
            isinstance(option, dict) and _type_matches(query, option, bindings)
            for option in options
        )
    if kind == "list" and query.endswith("[]"):
        element = documented.get("element")
        return isinstance(element, dict) and _type_matches(
            query[:-2], element, bindings
        )
    if kind == "map":
        parts = _split_map(query)
        key = documented.get("key")
        value = documented.get("value")
        return (
            parts is not None
            and isinstance(key, dict)
            and isinstance(value, dict)
            and _type_matches(parts[0], key, bindings)
            and _type_matches(parts[1], value, bindings)
        )
    return False


def _accepts_arity(overload: Mapping[str, Any], arity: int) -> bool:
    bounds = overload["arity"]
    maximum = bounds["maximum"]
    return arity >= bounds["minimum"] and (
        maximum == "unbounded" or arity <= maximum
    )


def _parameter_for_argument(
    parameters: Sequence[Mapping[str, Any]], index: int
) -> Mapping[str, Any] | None:
    if index < len(parameters):
        return parameters[index]
    if parameters and parameters[-1].get("variadic") is True:
        return parameters[-1]
    return None


def _matches_argument_types(
    overload: Mapping[str, Any], argument_types: Sequence[str]
) -> bool:
    if not _accepts_arity(overload, len(argument_types)):
        return False
    parameters = overload["parameters"]
    bindings: Dict[str, str] = {}
    for index, argument_type in enumerate(argument_types):
        parameter = _parameter_for_argument(parameters, index)
        if parameter is None:
            return False
        documented_type = parameter.get("type")
        if not isinstance(documented_type, dict) or not _type_matches(
            argument_type, documented_type, bindings
        ):
            return False
    return True


def _compact_overload(overload: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        key: copy.deepcopy(overload[key])
        for key in (
            "id",
            "canonical_signature",
            "type_parameters",
            "parameters",
            "arity",
            "returns",
            "description",
            "null_interactions",
            "errors",
            "data_quality",
        )
        if key in overload
    }


class FunctionCatalog:
    def __init__(
        self,
        path: Path,
        *,
        max_queries_per_call: int = 20,
    ) -> None:
        self.path = path
        self.library = validate_function_library(path)
        self.max_queries_per_call = max_queries_per_call
        self.functions: Dict[str, Dict[str, Any]] = self.library["functions"]
        self.input_schema: Dict[str, Any] = {
            "type": "object",
            "additionalProperties": False,
            "required": ["queries"],
            "properties": {
                "queries": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": max_queries_per_call,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["name"],
                        "properties": {
                            "name": {"type": "string", "minLength": 1},
                            "overload_id": {"type": "string", "minLength": 1},
                            "arity": {"type": "integer", "minimum": 0},
                            "argument_types": {
                                "type": "array",
                                "items": {"type": "string", "minLength": 1},
                            },
                            "detail": {
                                "type": "string",
                                "enum": ["core", "full"],
                                "default": "core",
                            },
                        },
                    },
                }
            },
        }
        if Draft202012Validator is not None:
            Draft202012Validator.check_schema(self.input_schema)
            self._validator = Draft202012Validator(self.input_schema)
        else:
            self._validator = None
        # Diagnostics for the run log — how much the judge actually leaned on
        # the catalog during a run, and how often it asked for something the
        # catalog does not have.
        self.stats: Dict[str, int] = {
            "calls": 0, "queries": 0, "not_found": 0, "no_matching_overload": 0,
            "ambiguous_overload": 0, "invalid_query": 0,
        }

    def discover(self) -> Dict[str, Any]:
        return {
            "name": FUNCTION_INFO_TOOL_NAME,
            "description": (
                "Look up authoritative CTL2 built-in function documentation from the "
                "local catalog. Use exact case-sensitive names. Returns existing "
                "overloads, parameter descriptions, return behavior, runtime errors, "
                "and parameter-specific NULL behavior. Batch related queries in one "
                "call. Use argument_types only as normalized catalog-type filters; "
                "use 'unknown' or 'null' when the static type is unavailable."
            ),
            "input_schema": copy.deepcopy(self.input_schema),
            "output_schema": None,
        }

    def _function_result(
        self,
        function: Mapping[str, Any],
        overloads: Sequence[Mapping[str, Any]],
        detail: str,
    ) -> Dict[str, Any]:
        if detail == "full":
            result = copy.deepcopy(dict(function))
            result["overloads"] = copy.deepcopy(list(overloads))
            return result
        result = {
            key: copy.deepcopy(function[key])
            for key in (
                "name",
                "category",
                "summary",
                "description",
                "availability",
                "data_quality",
            )
            if key in function
        }
        result["overloads"] = [_compact_overload(item) for item in overloads]
        return result

    def _lookup_one(self, query: Mapping[str, Any]) -> Dict[str, Any]:
        query_copy = copy.deepcopy(dict(query))
        name = query["name"]
        function = self.functions.get(name)
        if function is None:
            return {
                "query": query_copy,
                "status": "not_found",
                "message": f"No CTL2 built-in function exists with exact name {name!r}.",
            }
        overloads = function["overloads"]
        available_ids = [item["id"] for item in overloads]
        has_selector = any(
            key in query for key in ("overload_id", "arity", "argument_types")
        )
        selected = list(overloads)
        overload_id = query.get("overload_id")
        if isinstance(overload_id, str):
            selected = [item for item in selected if item["id"] == overload_id]
        arity = query.get("arity")
        argument_types = query.get("argument_types")
        if isinstance(argument_types, list):
            if isinstance(arity, int) and arity != len(argument_types):
                return {
                    "query": query_copy,
                    "status": "invalid_query",
                    "message": "arity must equal the number of argument_types when both are supplied.",
                    "available_overload_ids": available_ids,
                }
            selected = [
                item for item in selected if _matches_argument_types(item, argument_types)
            ]
        elif isinstance(arity, int):
            selected = [item for item in selected if _accepts_arity(item, arity)]

        if not selected:
            return {
                "query": query_copy,
                "status": "no_matching_overload",
                "message": "The function exists, but no overload matches all supplied filters.",
                "available_overload_ids": available_ids,
            }
        if not has_selector:
            status = "function_found"
        elif len(selected) == 1:
            status = "exact_overload"
        else:
            status = "ambiguous_overload"
        return {
            "query": query_copy,
            "status": status,
            "matched_overload_ids": [item["id"] for item in selected],
            "available_overload_ids": available_ids,
            "function": self._function_result(
                function, selected, query.get("detail", "core")
            ),
        }

    def _validate_arguments(self, arguments: Any) -> None:
        """Validate the model's tool arguments against self.input_schema.

        Uses jsonschema when available (identical to upstream). The fallback
        checks the same invariants the lookup code below actually relies on:
        a non-empty `queries` list, within the per-call cap, each entry an
        object with a non-empty string `name` and correctly typed selectors."""
        if self._validator is not None:
            try:
                self._validator.validate(arguments)
            except _JSONSchemaValidationError as exc:
                raise CatalogQueryError(
                    f"invalid {FUNCTION_INFO_TOOL_NAME} arguments at "
                    f"{list(exc.absolute_path)}: {exc.message}"
                ) from exc
            return
        if not isinstance(arguments, dict):
            raise CatalogQueryError(f"invalid {FUNCTION_INFO_TOOL_NAME} arguments: not an object")
        queries = arguments.get("queries")
        if not isinstance(queries, list) or not queries:
            raise CatalogQueryError("queries must be a non-empty array")
        if len(queries) > self.max_queries_per_call:
            raise CatalogQueryError(
                f"queries holds {len(queries)} entries; at most "
                f"{self.max_queries_per_call} are allowed per call"
            )
        for index, query in enumerate(queries):
            where = f"queries[{index}]"
            if not isinstance(query, dict):
                raise CatalogQueryError(f"{where} must be an object")
            unknown = set(query) - {"name", "overload_id", "arity", "argument_types", "detail"}
            if unknown:
                raise CatalogQueryError(f"{where} has unknown properties: {sorted(unknown)}")
            if not isinstance(query.get("name"), str) or not query["name"]:
                raise CatalogQueryError(f"{where}.name must be a non-empty string")
            if "overload_id" in query and not isinstance(query["overload_id"], str):
                raise CatalogQueryError(f"{where}.overload_id must be a string")
            if "arity" in query and (
                not isinstance(query["arity"], int) or isinstance(query["arity"], bool)
                or query["arity"] < 0
            ):
                raise CatalogQueryError(f"{where}.arity must be a non-negative integer")
            if "argument_types" in query and (
                not isinstance(query["argument_types"], list)
                or not all(isinstance(item, str) and item for item in query["argument_types"])
            ):
                raise CatalogQueryError(f"{where}.argument_types must be an array of non-empty strings")
            if "detail" in query and query["detail"] not in ("core", "full"):
                raise CatalogQueryError(f"{where}.detail must be 'core' or 'full'")

    def call(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        self._validate_arguments(arguments)
        results = [self._lookup_one(query) for query in arguments["queries"]]
        self.stats["calls"] += 1
        self.stats["queries"] += len(results)
        for result in results:
            status = result.get("status")
            if status in self.stats:
                self.stats[status] += 1
        return {
            "library": {
                "library_id": self.library["library_id"],
                "schema_version": self.library["schema_version"],
                "generated_date": self.library.get("generated_date"),
                "target": copy.deepcopy(self.library.get("target")),
                "sources": copy.deepcopy(self.library.get("sources", [])),
            },
            "results": results,
        }

    # ------------------------------------------------------------------
    # Provider-specific tool declarations
    # ------------------------------------------------------------------

    def openai_tool(self) -> Dict[str, Any]:
        """Tool declaration for OpenAI chat.completions (`tools=[...]`)."""
        tool = self.discover()
        return {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["input_schema"],
            },
        }

    def responses_tool(self) -> Dict[str, Any]:
        """Tool declaration for the OpenAI Responses API (`tools=[...]`).

        Flat, unlike chat.completions: name/description/parameters sit directly
        on the tool object rather than under a nested "function" key."""
        tool = self.discover()
        return {
            "type": "function",
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["input_schema"],
            "strict": False,
        }

    def anthropic_tool(self) -> Dict[str, Any]:
        """Tool declaration for the Anthropic Messages API (`tools=[...]`)."""
        tool = self.discover()
        return {
            "name": tool["name"],
            "description": tool["description"],
            "input_schema": tool["input_schema"],
        }

    # ------------------------------------------------------------------
    # Direct (non-tool) queries — used by the deterministic claim checks in
    # review_judge.py, which need catalog facts without a model turn.
    # ------------------------------------------------------------------

    def has(self, name: str) -> bool:
        """Whether a built-in with this exact, case-sensitive name exists."""
        return name in self.functions

    def return_types(self, name: str, arity: Optional[int] = None) -> Optional[set[str]]:
        """The documented return types of `name`, narrowed to the overloads that
        accept `arity` arguments when given.

        Returns None when the function is unknown, when no overload accepts that
        arity, or when any matching overload documents a return type this code
        cannot read as a plain type name (a type variable, union, container, ...)
        — in each of those cases the caller must not draw a conclusion. Types
        come back normalized, so `double` reads as `number`."""
        function = self.functions.get(name)
        if function is None:
            return None
        overloads = [
            item for item in function["overloads"]
            if arity is None or _accepts_arity(item, arity)
        ]
        if not overloads:
            return None
        types: set[str] = set()
        for overload in overloads:
            documented = (overload.get("returns") or {}).get("type") or {}
            if documented.get("kind") != "named":
                return None  # generic/union/container — not a single knowable type
            display = documented.get("display") or documented.get("name")
            if not isinstance(display, str):
                return None
            types.add(_normalize_type(display))
        return types

    def describe(self) -> str:
        """One-line provenance summary for the run log."""
        target = self.library.get("target") or {}
        return (
            f"{self.library['library_id']} schema={self.library['schema_version']} "
            f"generated={self.library.get('generated_date')} "
            f"functions={len(self.functions)} "
            f"target={target.get('product')}/{target.get('language')}"
        )


# One catalog per library path, shared by every ReviewJudgeClient in the
# process — the JSON is ~2.7 MB and parsing it per client would be wasteful.
_CATALOG_CACHE: Dict[Path, "FunctionCatalog"] = {}


def get_function_catalog(
    library: Optional[str | Path] = None, *, max_queries_per_call: int = 20
) -> "FunctionCatalog":
    """Load (or reuse) the catalog for `library`, defaulting to
    resources/ctl-function-library.json next to the repo root."""
    path = Path(library) if library else _DEFAULT_LIBRARY_PATH
    path = path.expanduser()
    if not path.is_absolute():
        path = (Path(__file__).parent.parent / path).resolve()
    cached = _CATALOG_CACHE.get(path)
    if cached is not None:
        return cached
    catalog = FunctionCatalog(path, max_queries_per_call=max_queries_per_call)
    _CATALOG_CACHE[path] = catalog
    return catalog
