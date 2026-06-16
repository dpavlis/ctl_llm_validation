"""Stage 3b — Per-candidate execution runner.

For each candidate CTL the runner:
  1. Writes transform.ctl to the CloverDX work tree (via MCP, no LLM)
  2. Calls job_run with the params from the SetupBundle
  3. Awaits completion
  4. Fetches tracking counts + edge debug records
  5. Diffs candidate output against the in-memory golden (component-aware)
  6. Returns an ExecResult classifying the outcome as L1/L2/L3

This is purely deterministic Python — no LLM involved.

Phase 1 stub: run_candidate() always returns a STUB L1_fail result.
Phase 2: uncomment _run_live() call.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from .mcp_client import MCPClient
from .setup_agent import SetupBundle


# ---------------------------------------------------------------------------
# Required CTL entry-point functions per component type
# ---------------------------------------------------------------------------

# Each value is a list of (regex_pattern, human_readable_name) pairs.
# ALL entries must match for the candidate to pass the pre-check.
_ENTRY_POINTS: dict[str, list[tuple[str, str]]] = {
    "DATA_GENERATOR": [
        (r"function\s+integer\s+generate\s*\(", "function integer generate(...)"),
    ],
    "REFORMAT": [
        (r"function\s+integer\s+transform\s*\(", "function integer transform(...)"),
    ],
    # EXT_FILTER uses a bare boolean expression — no function wrapper.
    # No pre-check enforced; the CloverDX validator catches invalid CTL at runtime.

    "EXT_HASH_JOIN": [
        (r"function\s+integer\s+transform\s*\(", "function integer transform(...)"),
    ],
    "PARTITION": [
        (r"function\s+integer\s+getOutputPort\s*\(", "function integer getOutputPort(...)"),
    ],
    "NORMALIZER": [
        (r"function\s+integer\s+count\s*\(",     "function integer count(...)"),
        (r"function\s+integer\s+transform\s*\(", "function integer transform(...)"),
    ],
    "DENORMALIZER": [
        (r"function\s+integer\s+append\s*\(",    "function integer append(...)"),
        (r"function\s+integer\s+transform\s*\(", "function integer transform(...)"),
    ],
    "ROLLUP": [
        (r"function\s+void\s+initGroup\s*\(",          "function void initGroup(<accumulator>)"),
        (r"function\s+boolean\s+updateGroup\s*\(",      "function boolean updateGroup(<accumulator>)"),
        (r"function\s+integer\s+updateTransform\s*\(",  "function integer updateTransform(integer counter, <accumulator>)"),
        (r"function\s+boolean\s+finishGroup\s*\(",      "function boolean finishGroup(<accumulator>)"),
        (r"function\s+integer\s+transform\s*\(",        "function integer transform(integer counter, <accumulator>)"),
    ],
}


def check_entry_points(text: str, component_type: str) -> str:
    """Return error string listing missing required entry-point functions, or '' if OK."""
    required = _ENTRY_POINTS.get(component_type, [])
    missing = [name for pat, name in required if not re.search(pat, text, re.IGNORECASE)]
    if not missing:
        return ""
    return "Missing required CTL entry point(s): " + ", ".join(missing)


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

ExecLevel = str  # L1_fail | L2_fail | L3_mismatch | L3_pass


@dataclass
class ExecResult:
    candidate_index: int
    exec_level: ExecLevel
    run_status: str            # FINISHED_OK | ERROR | ABORTED | TIMEOUT | STUB
    tracking: dict = field(default_factory=dict)
    output_records: list[dict] = field(default_factory=list)
    log_excerpt: str = ""      # first ERROR line from job log (≤200 chars)
    output_diff: str = ""      # brief human-readable diff for L3_mismatch
    run_id: Optional[int] = None


# Components whose output order is not deterministic (compare as multiset)
_UNORDERED_COMPONENTS = {"EXT_HASH_JOIN", "ROLLUP"}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_candidate(
    candidate_text: str,
    candidate_index: int,
    bundle: SetupBundle,
    mcp: MCPClient,
    await_timeout_s: int = 60,
) -> ExecResult:
    """
    Execute one candidate CTL against the CloverDX skeleton.

    Phase 1 stub — always returns L1_fail/STUB. Replace in Phase 2.
    """
    return _run_live(candidate_text, candidate_index, bundle, mcp, await_timeout_s)


# ---------------------------------------------------------------------------
# Phase 2 implementation
# ---------------------------------------------------------------------------

def _run_live(
    candidate_text: str,
    candidate_index: int,
    bundle: SetupBundle,
    mcp: MCPClient,
    await_timeout_s: int,
) -> ExecResult:
    # 0a. Pre-check: required CTL entry-point functions present?
    ep_error = check_entry_points(candidate_text, bundle.component_type)
    if ep_error:
        return ExecResult(
            candidate_index=candidate_index,
            exec_level="L1_fail",
            run_status="ENTRY_POINT_MISSING",
            log_excerpt=ep_error,
        )

    # 1. Overwrite transform.ctl with candidate
    # sandbox_write_file takes sandboxPath (dir) + filename separately
    ctl_path = f"{bundle.work_dir}/ctl/{bundle.component_type}/transform.ctl"
    ctl_dir, ctl_filename = ctl_path.rsplit("/", 1)
    mcp.call_tool("sandbox_write_file", {
        "sandboxCode": bundle.sandbox,
        "sandboxPath": ctl_dir,
        "filename": ctl_filename,
        "content": candidate_text,
    })

    # 0b. Validate the graph (catches CTL compilation errors before a full run)
    val_raw = mcp.call_tool("job_validate", {
        "sandboxCode": bundle.sandbox,
        "jobFile": bundle.skeleton_path,
        "timeoutSeconds": 30,
    })
    val_ok, val_msg = _parse_validate(val_raw)
    if not val_ok:
        return ExecResult(
            candidate_index=candidate_index,
            exec_level="L1_fail",
            run_status="VALIDATE_FAIL",
            log_excerpt=val_msg[:200],
        )

    # 2. job_run
    run_resp = mcp.call_tool("job_run", {
        "jobFile": bundle.skeleton_path,
        "sandboxCode": bundle.sandbox,
        "debug": True,
        "params": bundle.run_params,
    })
    run_id = _extract_run_id(run_resp)
    if run_id is None:
        return ExecResult(
            candidate_index=candidate_index,
            exec_level="L2_fail",
            run_status="ERROR",
            log_excerpt="job_run did not return a runId",
        )

    # 3. job_await
    await_resp = mcp.call_tool("job_await", {
        "runId": run_id,
        "timeoutSeconds": await_timeout_s,
    })
    status = _extract_status(await_resp)

    if status != "FINISHED_OK":
        log_raw = str(mcp.call_tool("job_get_log", {"runId": run_id}))
        excerpt = _first_error(log_raw)
        level = "L1_fail" if _is_compile_error(excerpt) else "L2_fail"
        return ExecResult(
            candidate_index=candidate_index,
            exec_level=level,
            run_status=status,
            log_excerpt=excerpt,
            run_id=run_id,
        )

    # 4. Read output
    tracking_raw = mcp.call_tool("job_get_tracking", {"runId": run_id, "detailed": True})
    if isinstance(tracking_raw, dict):
        tracking = tracking_raw
    elif isinstance(tracking_raw, str):
        try:
            tracking = json.loads(tracking_raw)
        except Exception:
            tracking = {}
    else:
        tracking = {}

    edge_id = _primary_edge(bundle.component_type)
    edge_raw = mcp.call_tool("job_get_edge_debug_data", {
        "runId": run_id,
        "edgeId": edge_id,
        "recordCount": 500,
    })
    records = _extract_records(edge_raw)

    # 5. Diff vs golden
    diff = _diff_records(records, bundle.golden_records, bundle.component_type)
    level = "L3_mismatch" if diff else "L3_pass"

    return ExecResult(
        candidate_index=candidate_index,
        exec_level=level,
        run_status=status,
        tracking=tracking,
        output_records=records,
        output_diff=diff,
        run_id=run_id,
    )


# ---------------------------------------------------------------------------
# Helpers — status / id extraction
# ---------------------------------------------------------------------------

def _parse_validate(resp: Any) -> tuple[bool, str]:
    """Parse job_validate response. Returns (is_valid, message)."""
    raw = resp if isinstance(resp, dict) else {}
    if isinstance(resp, str):
        try:
            raw = json.loads(resp)
        except Exception:
            # Plain text — treat "valid" / "ok" as success
            lower = resp.lower()
            if any(w in lower for w in ("valid", "ok", "success", "no error")):
                return True, resp[:200]
            if any(w in lower for w in ("error", "invalid", "fail", "exception")):
                return False, resp[:200]
            return True, resp[:200]  # unknown text → optimistically pass

    # Structured response
    status = str(raw.get("status", raw.get("result", ""))).upper()
    errors = raw.get("errors") or raw.get("validationErrors") or []
    if isinstance(errors, list) and errors:
        msg = "; ".join(str(e) for e in errors[:3])
        return False, msg
    if status in ("OK", "VALID", "SUCCESS", "FINISHED_OK"):
        return True, status
    if status in ("ERROR", "INVALID", "FAILED"):
        msg = raw.get("message") or raw.get("detail") or status
        return False, str(msg)[:200]
    # No explicit error indicators — pass
    return True, str(resp)[:100]


def _extract_run_id(resp: Any) -> Optional[int]:
    if isinstance(resp, (int, float)):
        return int(resp)
    if isinstance(resp, dict):
        v = resp.get("runId") or resp.get("run_id")
        return int(v) if v is not None else None
    if isinstance(resp, str):
        try:
            return _extract_run_id(json.loads(resp))
        except Exception:
            pass
    return None


def _extract_status(resp: Any) -> str:
    if isinstance(resp, dict):
        return resp.get("status", "UNKNOWN")
    if isinstance(resp, str):
        try:
            return _extract_status(json.loads(resp))
        except Exception:
            # May be a plain status string
            if resp.strip() in ("FINISHED_OK", "ERROR", "ABORTED", "TIMEOUT"):
                return resp.strip()
    return "UNKNOWN"


def _first_error(log: str) -> str:
    for line in log.splitlines():
        if re.search(r"\bERROR\b|Exception|Error loading", line, re.IGNORECASE):
            return line[:200]
    return log[:200]


_COMPILE_PATTERNS = re.compile(
    r"CTL compilation|CompilationException|Compilation error|"
    r"unresolved field|type error.*init|Error loading job file",
    re.IGNORECASE,
)


def _is_compile_error(excerpt: str) -> bool:
    return bool(_COMPILE_PATTERNS.search(excerpt))


def _primary_edge(component_type: str) -> str:
    return {
        "EXT_FILTER":  "EdgeOut0",   # port 0 = accepted records
        "PARTITION":   "EdgeOut0",   # port 0 = first partition bucket
        "DATAGEN":     "EdgeOut",    # filename alias for DATA_GENERATOR skeleton
    }.get(component_type, "EdgeOut")


def _extract_records(raw: Any) -> list[dict]:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        return raw.get("records", raw.get("data", []))
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return _extract_records(parsed)
        except Exception:
            pass
    return []


# ---------------------------------------------------------------------------
# Component-aware output diff (§18.5.1)
# ---------------------------------------------------------------------------

def _diff_records(
    candidate: list[dict],
    golden: list[dict],
    component_type: str,
) -> str:
    """Return a brief diff summary string, or '' if records match."""
    if len(candidate) != len(golden):
        return f"row count: expected {len(golden)}, got {len(candidate)}"

    if not golden:
        return ""

    if component_type in _UNORDERED_COMPONENTS:
        # Compare as multisets (order not guaranteed for joins / rollups)
        cand_set = _to_multiset(candidate)
        gold_set = _to_multiset(golden)
        missing = gold_set - cand_set
        extra   = cand_set - gold_set
        if not missing and not extra:
            return ""
        parts = []
        if missing:
            parts.append(f"missing rows: {list(missing)[:2]}")
        if extra:
            parts.append(f"extra rows: {list(extra)[:2]}")
        return "; ".join(parts)

    # Ordered comparison
    diffs: list[str] = []
    for i, (c_row, g_row) in enumerate(zip(candidate, golden)):
        fd = _field_diff(c_row, g_row)
        if fd:
            diffs.append(f"row {i}: {fd}")
        if len(diffs) >= 3:
            diffs.append("(more differences omitted)")
            break
    return "\n".join(diffs)


def _to_multiset(records: list[dict]) -> frozenset:
    return frozenset(_canon_row(r) for r in records)


def _canon_row(row: dict) -> str:
    return json.dumps(
        {k: _canon_val(v) for k, v in sorted(row.items()) if k != "__meta"},
        ensure_ascii=False,
        sort_keys=True,
    )


def _canon_val(v: Any) -> Any:
    """Normalize values for comparison: scale-aware decimals, null passthrough."""
    if v is None:
        return None
    if isinstance(v, str):
        stripped = v.strip()
        if stripped == "":
            return ""
        try:
            return str(Decimal(stripped).normalize())
        except InvalidOperation:
            pass
    return v


def _field_diff(cand: dict, gold: dict) -> str:
    diffs = []
    for k, gv in gold.items():
        if k == "__meta":
            continue
        cv = _canon_val(cand.get(k))
        gv_c = _canon_val(gv)
        if cv != gv_c:
            diffs.append(f"{k}: expected {gv_c!r} got {cv!r}")
        if len(diffs) >= 3:
            break
    return ", ".join(diffs)
