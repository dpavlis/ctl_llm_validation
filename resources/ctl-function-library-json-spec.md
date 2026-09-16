# CTL2 Function Library JSON Specification

Status: implementation handoff specification  
Schema version: `1.0.0`

## 1. Objective

Create one deterministic JSON database containing the CTL2 built-in function catalog. A later in-process `ctl_function_info` lookup will read this file and return exact function, overload, parameter, return-value, error, compatibility, and null-behavior information to the validation LLM.

The database must be factual data, not model-generated interpretation. It must preserve overload-specific and parameter-specific behavior and make undocumented behavior explicit.

Expected output file:

`knowledge/ctl-function-library.json`

This task does **not** implement `ctl_function_info`, modify the validator tool loop, or remove any existing prompt knowledge.

## 2. Source material and authority

Build the database from these repository sources:

1. `ctl_doc/ctl2-container-functions.adoc`
2. `ctl_doc/ctl2-conversion-functions.adoc`
3. `ctl_doc/ctl2-date-functions.adoc`
4. `ctl_doc/ctl2-mathematical-functions.adoc`
5. `ctl_doc/ctl2-string-functions.adoc`
6. `ctl_doc/ctl2-null-behavior.txt`
7. `ctl2-data-service-http-library-functions.adoc`
8. `ctl2-lookup-table-functions.adoc`
9. `ctl2-mapping-functions.adoc`
10. `ctl2-miscellaneous-functions.adoc`
11. `ctl2-record-functions.adoc`
12. `ctl2-sequence-functions.adoc`
13. `ctl2-subgraph-functions.adoc`
14. `ctl2-list-of-functions.adoc` (required-subset validation index)


Use the ADOC files for canonical function names, signatures, descriptions, parameter meanings, return behavior, examples, compatibility notes, and general errors. Use `ctl2-null-behavior.txt` for the normalized parameter-specific null behavior. Runtime probes are observational evidence and must be identified as such; they must not silently be presented as documentation claims.

If sources conflict:

- do not silently choose one;
- preserve the conflict in `data_quality.issues` on the affected function or overload;
- include both pieces of evidence;
- set the affected semantic field to the best-supported value only when the source priority is unambiguous;
- otherwise use an explicit `undocumented` or `conflicting` classification.

Do not infer behavior from a similar function, another overload, a return type, Java intuition, or the behavior of a different parameter.

## 3. File-level requirements

- UTF-8 JSON, not JSONL.
- Exactly one top-level JSON object.
- Two-space indentation and a final newline.
- No comments or trailing commas.
- Function keys sorted by exact canonical CTL2 name.
- Overloads sorted by `canonical_signature`.
- Parameter arrays remain in call order.
- All IDs must be stable across regenerations when the underlying function or overload has not changed.
- Do not use JSON `null` to mean “not documented.” Use the explicit semantic classifications defined below. JSON `null` is allowed only for genuinely unknown library metadata such as an unspecified CloverDX version.

## 4. Root object

```json
{
  "schema_version": "1.0.0",
  "library_id": "cloverdx-ctl2-builtins",
  "generated_date": "2026-08-31",
  "target": {
    "language": "CTL2",
    "product": "CloverDX",
    "product_version": null
  },
  "sources": [],
  "functions": {}
}
```

### Root fields

| Field | Type | Required | Meaning |
|---|---|---:|---|
| `schema_version` | string | yes | Version of this JSON contract. Must initially be `1.0.0`. |
| `library_id` | string | yes | Stable identifier. Must be `cloverdx-ctl2-builtins`. |
| `generated_date` | string | yes | ISO date on which the database was generated or last rebuilt. |
| `target` | object | yes | Language/product applicability. |
| `sources` | array | yes | Source registry used by evidence references. |
| `functions` | object | yes | Catalog keyed by exact, case-sensitive canonical function name. |

`functions` must be an object rather than an array so exact-name lookup is deterministic and constant-time after JSON loading. Each key must equal the contained function object's `name`.

## 5. Source registry

Each source is registered once at the root:

```json
{
  "id": "ctl2-string-functions",
  "path": "ctl_doc/ctl2-string-functions.adoc",
  "kind": "documentation",
  "sha256": "<lowercase SHA-256 hex>",
  "description": "CloverDX CTL2 string-function documentation."
}
```

Required source fields:

| Field | Type | Allowed values / rule |
|---|---|---|
| `id` | string | Unique stable kebab-case identifier. |
| `path` | string | Repository-relative path. |
| `kind` | string | `documentation`, `normalized_summary`, or `runtime_probe`. |
| `sha256` | string | SHA-256 of the exact source bytes. |
| `description` | string | Short factual description. |

## 6. Function object

Each member of `functions` has this shape:

```json
{
  "name": "contains",
  "category": "string",
  "summary": "Tests whether one string contains another string.",
  "description": "Complete normalized description of the function.",
  "availability": {
    "status": "supported",
    "since": null,
    "deprecated_since": null,
    "replacement": null
  },
  "overloads": [],
  "compatibility": [],
  "see_also": ["endsWith", "startsWith", "substring"],
  "evidence": [],
  "data_quality": {
    "status": "complete",
    "issues": []
  }
}
```

### Function fields

| Field | Type | Required | Rule |
|---|---|---:|---|
| `name` | string | yes | Exact case-sensitive CTL2 name. |
| `category` | string | yes | One of `container`, `conversion`, `data_service_http`, `date`, `lookup_table`, `mapping`, `mathematical`, `miscellaneous`, `record`, `sequence`, `string`, or `subgraph`, according to the source document that defines the function. |
| `summary` | string | yes | One sentence suitable for a lookup result. |
| `description` | string | yes | Complete plain-text or Markdown-normalized description. Remove unresolved ADOC anchors/macros. |
| `availability` | object | yes | Support and deprecation state. |
| `overloads` | array | yes | At least one overload. |
| `compatibility` | array | yes | Version-specific behavioral notes; empty when none are documented. |
| `see_also` | array of strings | yes | Canonical function names only; empty when none. |
| `evidence` | array | yes | Evidence supporting function-level description/availability. |
| `data_quality` | object | yes | Completeness/conflict tracking. |

Allowed `availability.status` values:

- `supported`
- `deprecated`
- `removed`
- `unknown`

Allowed `data_quality.status` values:

- `complete`
- `partial`
- `conflicting`

Each `data_quality.issues` entry is a short factual string. Do not hide missing parameter descriptions, ambiguous signatures, or source conflicts.

## 7. Overload object

An overload represents one callable signature family. Optional trailing parameters and a trailing variadic parameter may remain in one overload. Semantically different parameter-type combinations must be separate overloads.

```json
{
  "id": "contains(string,string)",
  "canonical_signature": "boolean contains(string input, string substring)",
  "type_parameters": [],
  "parameters": [],
  "arity": {
    "minimum": 2,
    "maximum": 2
  },
  "returns": {},
  "description": "Tests whether input contains substring.",
  "null_interactions": [],
  "errors": [],
  "side_effects": [],
  "examples": [],
  "compatibility": [],
  "evidence": [],
  "data_quality": {
    "status": "complete",
    "issues": []
  }
}
```

### Overload rules

- `id` must be the function name followed by normalized parameter type expressions in parentheses, without parameter names or spaces.
- For an optional parameter, append `?` to its normalized type in the ID.
- For a variadic parameter, append `...` to its normalized type in the ID.
- If two documented overloads would still produce the same ID, suffix both with a stable discriminator such as `#1` and `#2`, and record why in `data_quality.issues`.
- `canonical_signature` is a human-readable normalized CTL2 signature and must include return type, exact function name, parameter types, parameter names, optional markers, and variadic markers.
- `arity.maximum` is an integer for fixed/optional signatures and the string `"unbounded"` for a variadic signature.
- `null_interactions` stores behavior that depends on two or more parameters being null or on one parameter's null behavior being conditioned by another parameter. More-specific cases must appear before fallback cases.

## 8. CTL2 type expression

Every parameter and return type uses a structured `type` object. Every type object also has a `display` string preserving the normalized human-readable form.

### Named type

```json
{
  "kind": "named",
  "name": "string",
  "display": "string"
}
```

Canonical named types currently include:

`boolean`, `byte`, `cbyte`, `date`, `decimal`, `integer`, `long`, `number`, `record`, `string`, `unit`, `variant`, and `void`.

Normalize documented `double` to canonical `number`, but preserve `double` in `source_spelling` when it appears in the source:

```json
{
  "kind": "named",
  "name": "number",
  "display": "number",
  "source_spelling": "double"
}
```

### Type variable

```json
{
  "kind": "type_variable",
  "name": "T",
  "display": "T"
}
```

Declare every type variable in the overload's `type_parameters`:

```json
{
  "name": "T",
  "constraint": {
    "kind": "any",
    "display": "any"
  }
}
```

### Type family

Use a family when the documentation intentionally describes a constrained set rather than separate overloads:

```json
{
  "kind": "family",
  "name": "numeric",
  "members": ["integer", "long", "number", "decimal"],
  "display": "numeric"
}
```

Allowed initial family names are `numeric`, `structured`, and `any`. Do not create a family merely to shorten data entry when the documentation lists distinct overloads with distinct behavior.

### List

```json
{
  "kind": "list",
  "element": {
    "kind": "type_variable",
    "name": "T",
    "display": "T"
  },
  "display": "T[]"
}
```

### Map

```json
{
  "kind": "map",
  "key": {
    "kind": "type_variable",
    "name": "K",
    "display": "K"
  },
  "value": {
    "kind": "type_variable",
    "name": "V",
    "display": "V"
  },
  "display": "map[K,V]"
}
```

### Union

Use a union only when one documented overload accepts several interchangeable types with identical semantics:

```json
{
  "kind": "union",
  "options": [
    {"kind": "named", "name": "byte", "display": "byte"},
    {"kind": "named", "name": "string", "display": "string"}
  ],
  "display": "byte|string"
}
```

### Any

```json
{
  "kind": "any",
  "display": "any"
}
```

## 9. Parameter object

```json
{
  "position": 0,
  "name": "input",
  "type": {
    "kind": "named",
    "name": "string",
    "display": "string"
  },
  "optional": false,
  "variadic": false,
  "default": {
    "kind": "none",
    "description": "No default; the parameter is required."
  },
  "description": "String to search.",
  "constraints": [],
  "null_behavior": {},
  "evidence": []
}
```

Rules:

- `position` is zero-based.
- `name` uses the documentation's semantic parameter name, normalized consistently across overloads when the source varies only cosmetically.
- Optional parameters must be trailing except for a final variadic parameter.
- Only the last parameter may be variadic.
- `default.kind` is one of `none`, `literal`, `system_default`, `derived`, or `undocumented`.
- A literal default stores `value` as a JSON scalar plus a human-readable `description`.
- `constraints` contains documented non-null constraints such as ranges, valid enum/constants, index rules, or required formats. It is an array of strings, not inferred rules.
- Every parameter must contain `null_behavior`, including parameters whose behavior is undocumented.

## 10. Null behavior

### Non-conditional behavior

```json
{
  "kind": "runtime_error",
  "description": "A NULL substring causes the function to fail at runtime.",
  "evidence": [
    {
      "source_id": "ctl2-null-behavior",
      "section": "contains",
      "basis": "documentation"
    }
  ]
}
```

Allowed non-conditional `kind` values:

| Kind | Meaning |
|---|---|
| `runtime_error` | The call fails at runtime when this parameter is null. This is not a compile error. |
| `returns_null` | The function returns CTL null. |
| `returns_value` | The function returns a documented non-null value or sentinel. Include `result`. |
| `uses_default` | A documented default behavior/value is used. Include the default in `description` and `result` when representable. |
| `accepted` | Null is accepted without an error, but a more specific return/mutation category is not appropriate. |
| `ignored` | The null argument is ignored. |
| `omitted` | A null variadic/member argument is omitted from processing/output. |
| `mutates_with_null` | Null is stored or appended as part of a mutation. |
| `undocumented` | The available documentation and probes do not establish behavior. |
| `conflicting` | Sources disagree and the conflict is unresolved. |

For `returns_value`, encode the result without confusing CTL null and the string `"null"`:

```json
{
  "kind": "returns_value",
  "description": "Returns the integer sentinel -1.",
  "result": {
    "kind": "literal",
    "type": "integer",
    "value": -1,
    "display": "-1"
  },
  "evidence": []
}
```

```json
{
  "kind": "returns_value",
  "description": "Returns the string value null.",
  "result": {
    "kind": "literal",
    "type": "string",
    "value": "null",
    "display": "\"null\""
  },
  "evidence": []
}
```

`returns_null` must not include `result.value: null`; its `kind` already represents CTL null unambiguously.

### Conditional behavior

Use `conditional` when null behavior depends on other arguments, input content, overload state, or multiple null arguments:

```json
{
  "kind": "conditional",
  "description": "Behavior depends on the strict parameter.",
  "cases": [
    {
      "condition": "strict == true",
      "behavior": {
        "kind": "runtime_error",
        "description": "A NULL map causes a runtime error in strict mode."
      },
      "evidence": []
    },
    {
      "condition": "otherwise",
      "behavior": {
        "kind": "returns_value",
        "description": "Returns -1 outside strict mode.",
        "result": {
          "kind": "literal",
          "type": "integer",
          "value": -1,
          "display": "-1"
        }
      },
      "evidence": []
    }
  ],
  "evidence": []
}
```

Conditional cases are ordered from most specific to fallback. `condition` is concise normalized text for the LLM; version 1 does not require an executable condition language. A case's nested behavior must not itself be `conditional`, `undocumented`, or `conflicting`.

### Multiple-null interactions

Use overload-level `null_interactions` for behavior that cannot be truthfully represented independently on a single parameter, for example `min(null, value)`, `min(value, null)`, and `min(null, null)`.

```json
{
  "condition": "arg1 == NULL && arg2 == NULL",
  "behavior": {
    "kind": "returns_null",
    "description": "Returns NULL when both scalar arguments are NULL."
  },
  "evidence": []
}
```

The lookup consumer must treat `null_interactions` as more specific than individual parameter behavior. The database author must not invent the combined outcome when it is undocumented.

## 11. Return object

```json
{
  "type": {
    "kind": "named",
    "name": "boolean",
    "display": "boolean"
  },
  "description": "True when the substring occurs; otherwise false.",
  "nullable": {
    "kind": "never",
    "description": "The documented return values are true or false."
  },
  "evidence": []
}
```

Allowed `returns.nullable.kind` values:

- `never`
- `always`
- `conditional`
- `undocumented`
- `conflicting`

For `conditional`, include ordered `cases` using the same shape as conditional null behavior. Return nullability describes the overall function result; it does not replace parameter-specific null behavior.

## 12. Errors, side effects, examples, and compatibility

### Error

```json
{
  "kind": "runtime_error",
  "condition": "substring == NULL",
  "description": "The function fails when substring is NULL.",
  "evidence": []
}
```

Allowed initial error kinds are `runtime_error`, `invalid_argument`, and `undocumented_failure`. Never label documented runtime failure as a compile error.

### Side effect

```json
{
  "kind": "mutates_parameter",
  "parameter": "target",
  "description": "Appends the item to target.",
  "evidence": []
}
```

Allowed initial side-effect kinds are `none`, `mutates_parameter`, `global_state`, and `other`.

### Example

```json
{
  "code": "contains(null, \"pine\")",
  "result": {
    "kind": "literal",
    "type": "boolean",
    "value": false,
    "display": "false"
  },
  "description": "A NULL input string returns false.",
  "evidence": []
}
```

Examples must be CTL expressions or calls exactly as documented or probed. Do not synthesize examples merely to fill the array.

### Compatibility entry

```json
{
  "applies_to": "CloverETL 3.5.x and earlier",
  "description": "A NULL input argument caused a runtime error in these versions.",
  "evidence": []
}
```

Do not collapse historical behavior into current behavior. Keep it in `compatibility` unless the entire database explicitly targets that historical version.

## 13. Evidence object

Every non-obvious semantic claim must be traceable:

```json
{
  "source_id": "ctl2-string-functions",
  "section": "contains",
  "basis": "documentation",
  "detail": "Optional short note identifying the relevant source statement."
}
```

Fields:

| Field | Type | Required | Rule |
|---|---|---:|---|
| `source_id` | string | yes | Must reference a root `sources[].id`. |
| `section` | string | yes | Function heading, anchor, or stable probe identifier. Do not rely only on line numbers. |
| `basis` | string | yes | `documentation`, `normalized_summary`, or `runtime_probe`. |
| `detail` | string | no | Short disambiguating note; do not copy large source passages. |

## 14. Complete example: `contains`

This example is normative for object shape but illustrative in wording:

```json
{
  "name": "contains",
  "category": "string",
  "summary": "Tests whether one string contains another string.",
  "description": "Returns whether substring occurs within input.",
  "availability": {
    "status": "supported",
    "since": null,
    "deprecated_since": null,
    "replacement": null
  },
  "overloads": [
    {
      "id": "contains(string,string)",
      "canonical_signature": "boolean contains(string input, string substring)",
      "type_parameters": [],
      "parameters": [
        {
          "position": 0,
          "name": "input",
          "type": {"kind": "named", "name": "string", "display": "string"},
          "optional": false,
          "variadic": false,
          "default": {
            "kind": "none",
            "description": "No default; the parameter is required."
          },
          "description": "String to search.",
          "constraints": [],
          "null_behavior": {
            "kind": "returns_value",
            "description": "A NULL input returns false.",
            "result": {
              "kind": "literal",
              "type": "boolean",
              "value": false,
              "display": "false"
            },
            "evidence": [
              {
                "source_id": "ctl2-null-behavior",
                "section": "contains",
                "basis": "normalized_summary"
              }
            ]
          },
          "evidence": []
        },
        {
          "position": 1,
          "name": "substring",
          "type": {"kind": "named", "name": "string", "display": "string"},
          "optional": false,
          "variadic": false,
          "default": {
            "kind": "none",
            "description": "No default; the parameter is required."
          },
          "description": "Substring to find.",
          "constraints": [],
          "null_behavior": {
            "kind": "runtime_error",
            "description": "A NULL substring causes a runtime error.",
            "evidence": [
              {
                "source_id": "ctl2-null-behavior",
                "section": "contains",
                "basis": "normalized_summary"
              }
            ]
          },
          "evidence": []
        }
      ],
      "arity": {"minimum": 2, "maximum": 2},
      "returns": {
        "type": {"kind": "named", "name": "boolean", "display": "boolean"},
        "description": "True when substring occurs; otherwise false.",
        "nullable": {
          "kind": "never",
          "description": "The documented return values are true or false."
        },
        "evidence": []
      },
      "description": "Tests whether input contains substring.",
      "null_interactions": [],
      "errors": [
        {
          "kind": "runtime_error",
          "condition": "substring == NULL",
          "description": "The function fails when substring is NULL.",
          "evidence": []
        }
      ],
      "side_effects": [],
      "examples": [],
      "compatibility": [],
      "evidence": [],
      "data_quality": {"status": "complete", "issues": []}
    }
  ],
  "compatibility": [],
  "see_also": ["endsWith", "startsWith", "substring"],
  "evidence": [],
  "data_quality": {"status": "complete", "issues": []}
}
```

## 15. Completeness and validation requirements

The producing agent must verify all of the following before delivery:

1. Every function heading in the twelve listed `ctl2-*-functions.adoc` source files has exactly one matching key in `functions`. A source with no function headings or canonical signatures, such as the sequence-method reference, must contribute only verbatim documented callable forms, marked `partial` with a data-quality issue; the producer must not infer typed signatures or additional callable records.
2. Every documented overload is represented exactly once.
3. Every overload has a unique stable `id`, a canonical signature, valid arity, parameters in call order, and a return object.
4. Every parameter has a description, structured type, optional/variadic flags, default object, constraints array, null behavior, and evidence array.
5. Every null-behavior entry in `ctl2-null-behavior.txt` maps to the appropriate overload and parameter or to overload-level `null_interactions`.
6. Functions with no input parameters still have an overload with `parameters: []`, arity zero, and no fabricated null behavior.
7. “Not documented” remains `undocumented`; it is never converted into safe behavior or runtime failure.
8. Runtime failure is never described as a compile error.
9. Compatibility behavior is not mixed into current behavior.
10. Every evidence reference resolves to a registered root source.
11. Every `see_also` value resolves to another function key, unless a data-quality issue explicitly records that the referenced function is outside the current source scope.
12. Every source hash matches the current repository file.
13. The output parses with a standard JSON parser and contains no duplicate object keys.
14. Rebuilding from unchanged inputs produces byte-identical output except for an intentionally changed `generated_date`.

The producing agent must report counts for:

- source documents;
- functions by category;
- total functions;
- total overloads;
- total parameters;
- parameters by null-behavior kind;
- conditional/multiple-null interactions;
- undocumented null behaviors;
- compatibility entries;
- partial or conflicting function/overload records.

## 16. Design constraints for the later lookup implementation

These are data-shape constraints only; `ctl_function_info` is not part of this task.

- Exact function-name lookup must not require scanning an array.
- The consumer must be able to return all overloads when argument types are absent.
- The consumer must be able to filter overloads by arity and normalized argument types without parsing prose signatures.
- The consumer must be able to distinguish an unknown function, an ambiguous overload, and an exact overload match.
- The consumer must be able to return concise results while retaining provenance and detailed descriptions on request.
- A negative exact-name lookup must remain negative. Future fuzzy suggestions must be explicitly labeled suggestions and must never establish that a function exists.
- Reference lookup calls are semantic evidence, not compiler evidence, and must not be reported as `ctl_validate` compiler checks.
