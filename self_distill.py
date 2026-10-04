#!/usr/bin/env python3
"""
self_distill.py — build a self-distilled phase-3 reasoning dataset.

Implements spec/self_distillation_spec.md. The teacher is the model phase 3 will
train on top of (the SFT+DPO export). For each training prompt it samples k
thinking-ON completions under the eval-time inference configuration, keeps a
sample only if its answer passes a cheap format / function-library / compile
check AND a reference-comparison judge, then keeps one accepted sample per
prompt — the model's own trace paired with the model's own answer. Authored
traces are never used; only the prompt and the reference answer are read from a
training record.

Prompts come from ctl_lora_training/sft_training_data/CTL_LoRAT_*.json (records
that generate, validate or fix CTL2 for a named component), with fix topped up
from CTL_LoRA_fix_this_code.json.

Stages (each resumable; files live in data/self_distill/<run>/):

  python self_distill.py select     --run NAME [--pilot] [--seed 0] [--exclude-runs RUN,...]
  python self_distill.py check-refs --run NAME [--no-compile]
  CUDA_VISIBLE_DEVICES=1 python self_distill.py sample --run NAME --shard 0/2
  CUDA_VISIBLE_DEVICES=2 python self_distill.py sample --run NAME --shard 1/2
  python self_distill.py filter     --run NAME [--no-compile] [--judge-workers 4]
  python self_distill.py rejudge    --run NAME --n 20
  python self_distill.py assemble   --run NAME [--cutoff 8192]

  select      choose prompts        -> prompts.jsonl, select_report.json
  check-refs  run the cheap checks on the REFERENCE answers (checker sanity)
                                    -> refcheck.jsonl, refcheck_report.json
  sample      k samples per prompt  -> samples.shard<i>.jsonl, sample_stats.shard<i>.json
  filter      format/library/compile/judge -> judged.jsonl
  rejudge     independent second judge pass on a random subset -> rejudge.jsonl,
              rejudge_report.json
  assemble    one accepted sample per prompt -> the final products:
                selfdistill_<run>_train.json    the phase-3 training file (<think>
                                                tags, via convert_think --only-reasoning);
                                                register THIS one in dataset_info.json
                selfdistill_<run>_records.json  the same records with reasoning_content
                                                and full provenance, before tagging
              plus gaps.json, audit_sample.jsonl, report.json, report.md
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import random
import re
import statistics
import sys
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Load .env before any config is read: load_config() expands ${OPENAI_API_KEY}.
try:
    from dotenv import load_dotenv
    for _env_candidate in (REPO_ROOT / ".env", REPO_ROOT / "dpo_forge" / ".env"):
        if _env_candidate.exists():
            load_dotenv(_env_candidate, override=False)
            break
except ImportError:
    pass

# The repo's test.py (shadows the stdlib `test` package, as in tests/): reused
# so the teacher sees exactly the eval-time prompt — same config loading, same
# LlamaFactory template resolution, same LocalMUTClient.
import test as eval_harness  # noqa: E402
from dpo_forge.generator import split_thinking  # noqa: E402
from dpo_forge.review_judge import (  # noqa: E402
    _FUNCTION_LOOKUP_NOTE,
    _ISSUE_LINE_RE,
    _VERDICT_RE,
    infer_component_type_from_prompt,
    normalize_component_type,
)
from dpo_forge.judge import infer_component_type as infer_component_type_from_code  # noqa: E402
from dpo_forge.runner import has_ctl2_header  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TRAIN_DIR = REPO_ROOT / "ctl_lora_training" / "sft_training_data"
EVAL_DIR = REPO_ROOT / "ctl_lora_training" / "sft_eval_data"
SOURCE_GLOB = "CTL_LoRAT_*.json"
# Non-thinking files used only to top fix up to its quota. Their answers serve
# as judge references; they carry no trace, and none is ever needed.
FIX_TOPUP_FILES = ("CTL_LoRA_fix_this_code.json",)
EXCLUDE_FILES = (
    EVAL_DIR / "CTL_LoRA_eval_data.json",
    EVAL_DIR / "CTL_LoRA_eval_data_think_src.json",
    EVAL_DIR / "CTL_LoRA_eval_data_think.json",
    EVAL_DIR / "CTL_LoRA_DPO_eval.jsonl",
)
SUITE_FILES = tuple(REPO_ROOT / "resources" / f"ctl2_test_suite_v{v}.json" for v in (2, 3, 4))
CTL2_REFERENCE_FILE = REPO_ROOT / "resources" / "ctl2-basics.md"
RUNS_DIR = REPO_ROOT / "data" / "self_distill"
DEFAULT_EVAL_CONFIG = REPO_ROOT / "configs" / "eval_T04_fix6_sftdpo_think.yaml"

TASK_TYPES = ("fix", "validate", "generate")
# Full-run mix, set from the pilot2 per-group yields (see
# spec/validate_multifinding_coverage_spec.md). (task, group, count); None
# takes the whole group. Groups the pilots showed the teacher cannot do yet
# are left out rather than sampled for ~0 yield: validate with >=3 findings
# (0/20 samples accepted) and PASS-with-warnings (0/12). They come back once
# the corpus covers them and a retrained teacher can answer them.
FULL_PLAN = (
    ("fix", "fix_tier0", None),          # every fix-to-spec record
    ("fix", "fix_tier1", None),          # every other CTL_LoRAT fix record
    ("fix", "fix_tier2", 20),            # CTL_LoRA_fix_this_code, capped: 5/28 accepted in pilot2
    ("validate", "validate_pass_clean", 40),
    ("validate", "validate_pass_warn", 30),  # 19/48 accepted in passwarn1 once the instruction stated the severity rule
    ("validate", "validate_1", 46),
    ("validate", "validate_2", None),    # all 34
    ("generate", "generate_lifecycle", 70),
    ("generate", "generate_other", 30),
)
FULL_EXCLUDED_GROUPS = {
    "validate_multi3": "1/34 samples accepted across pilots 1-2; needs corpus coverage first",
}
# References shown to be wrong (spec/validate_multifinding_coverage_spec.md,
# Part A). Never sampled: the judge would enforce the wrong answer. Remove an
# id once its record is corrected in the corpus.
KNOWN_WRONG_REFERENCES = frozenset({
    "trolluppbd_25",           # calls writing $out.1 on an unconnected port dead code; it does not compile
    "trollupu62_contrast_02",  # same
    "tvalidat22_37",           # grades a stated-requirement violation (credit_amount not preserved) WARNING
})
# The pilot is stratified rather than a scaled-down full run: every kind of
# prompt the full run will draw must show up, so its problems surface here.
# (task, group, count); groups are assigned by pilot_group().
PILOT_PLAN = (
    ("fix", "fix_tier0", 7),            # fix-to-spec
    ("fix", "fix_tier1", 7),            # other CTL_LoRAT fix
    ("fix", "fix_tier2", 7),            # CTL_LoRA_fix_this_code top-up
    ("validate", "validate_pass_clean", 5),
    ("validate", "validate_multi3", 5),
    ("validate", "validate_pass_warn", 3),
    ("validate", "validate_2", 4),
    ("validate", "validate_1", 4),
    ("generate", "generate_ROLLUP", 3),
    ("generate", "generate_DENORMALIZER", 3),
    ("generate", "generate_NORMALIZER", 3),
    ("generate", "generate_JOIN", 3),
    ("generate", "generate_other", 6),  # spread over the remaining components
)
LIFECYCLE_COMPONENTS = ("ROLLUP", "DENORMALIZER", "NORMALIZER", "JOIN")
DEFAULT_K = 4
DEFAULT_CUTOFF = 8192
# Chat-template tokens around the response that the prompt/response token
# counts recorded at sampling time do not include (<|im_end|>, newline).
CUTOFF_MARGIN_TOKENS = 8

MCP_DEFAULTS = {"enabled": True, "url": "http://localhost:8083/clover/mcp/mcp", "timeout_s": 30}

JUDGE_PURPOSES = tuple(f"selfdistill_{t}" for t in TASK_TYPES) + ("selfdistill_claims",)
JUDGE_DEFAULTS: dict = {
    "provider": "openai",
    "api": "auto",
    "model": "gpt-6-sol",
    "max_retries": 2,
    "max_completion_tokens": 8192,
    "reasoning_effort": "medium",
    "prompt_cache_key": "ctl-selfdistill:v1",
    "prompt_cache_retention": "24h",
    "request_timeout_s": 300,
    "function_lookup": {
        "enabled": True,
        "library": "resources/ctl-function-library.json",
        "max_queries_per_call": 20,
        "max_rounds_per_call": 3,
        "purposes": list(JUDGE_PURPOSES),
    },
}

# ---------------------------------------------------------------------------
# Small I/O helpers
# ---------------------------------------------------------------------------


def norm_ws(text: str) -> str:
    """Whitespace normalisation used for every prompt comparison
    (the same check spec/eval_sets_spec.md uses)."""
    return " ".join((text or "").split())


def make_prompt_id(user: str) -> str:
    """Same id scheme as mut_validate._make_example_id."""
    return hashlib.sha256(norm_ws(user).encode("utf-8")).hexdigest()[:16]


def read_records(path: Path) -> list:
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return []
    try:
        data = json.loads(text)
        return data if isinstance(data, list) else [data]
    except json.JSONDecodeError:
        return [json.loads(line) for line in text.splitlines() if line.strip()]


def read_jsonl(path: Path) -> list[dict]:
    """Read JSONL, tolerating a torn last line from a crash mid-write."""
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            print(f"  [warn] skipping unreadable line in {path.name}")
    return rows


_write_lock = threading.Lock()


def append_jsonl(path: Path, rows: list[dict]) -> None:
    """Append rows in one write so a prompt's k samples land together."""
    payload = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    with _write_lock:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())


def write_json(path: Path, data: Any, ensure_ascii: bool = False) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=ensure_ascii, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def run_dir(args) -> Path:
    d = Path(args.runs_dir) / args.run
    d.mkdir(parents=True, exist_ok=True)
    return d


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def rel(path: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


# ---------------------------------------------------------------------------
# CTL text helpers
# ---------------------------------------------------------------------------

# Fenced blocks. The language tag is captured so XML metadata fences in a
# prompt are never mistaken for CTL.
_FENCE_RE = re.compile(r"```[ \t]*([A-Za-z0-9_+-]*)[^\n]*\n([\s\S]*?)```")
_CTL_LANGS = {"", "ctl", "ctl2"}


def ctl_blocks(text: str) -> list[str]:
    blocks = []
    for m in _FENCE_RE.finditer(text or ""):
        lang = m.group(1).lower()
        body = m.group(2)
        if lang in _CTL_LANGS and (lang or "//#CTL2" in body or "function " in body or "$in." in body):
            blocks.append(body.strip("\n"))
    return blocks


def main_ctl_block(text: str) -> str:
    """The complete program in an answer: the longest CTL block, preferring
    one with a //#CTL2 header. A fix answer may quote the broken line in a
    small block before the corrected program."""
    blocks = ctl_blocks(text)
    if not blocks:
        return ""
    headed = [b for b in blocks if has_ctl2_header(b)]
    return max(headed or blocks, key=len)


def strip_fences(text: str) -> str:
    return _FENCE_RE.sub(" ", text or "")


def user_has_ctl_program(user: str) -> bool:
    return bool(ctl_blocks(user)) or "//#CTL2" in (user or "")


_ISSUES_HEADER_RE = re.compile(r"^\s*ISSUES\s*:", re.IGNORECASE | re.MULTILINE)
_SUGGESTIONS_HEADER_RE = re.compile(r"^\s*SUGGESTIONS\s*:", re.IGNORECASE | re.MULTILINE)
_VERDICT_LINE_RE = re.compile(r"^\s*VERDICT\s*:\s*(PASS|FAIL)\b", re.IGNORECASE | re.MULTILINE)


def parse_validate_answer(text: str) -> Optional[dict]:
    """Strict parse of an ISSUES / SUGGESTIONS / VERDICT answer.

    Deliberately not review_judge._parse_review: that drops issues which
    retract themselves, which would hide exactly the false claim this
    pipeline must reject. Returns None when the format is not present.
    """
    text = text or ""
    issues_m = _ISSUES_HEADER_RE.search(text)
    verdicts = _VERDICT_LINE_RE.findall(text)
    if not issues_m or not verdicts:
        return None
    sugg_m = _SUGGESTIONS_HEADER_RE.search(text, issues_m.end())
    verdict_m = _VERDICT_LINE_RE.search(text, issues_m.end())
    issues_end = min(m.start() for m in (sugg_m, verdict_m) if m) if (sugg_m or verdict_m) else len(text)
    issues_text = text[issues_m.end():issues_end]
    issues = [(m.group(1).upper(), m.group(2).strip()) for m in _ISSUE_LINE_RE.finditer(issues_text)]
    suggestions = ""
    if sugg_m:
        end = verdict_m.start() if verdict_m and verdict_m.start() > sugg_m.end() else len(text)
        suggestions = text[sugg_m.end():end]
    findings = [i for i in issues if i[0] in ("ERROR", "WARNING")]
    return {
        "issues": issues,
        "findings": len(findings),
        "errors": sum(1 for s, _ in issues if s == "ERROR"),
        "warnings": sum(1 for s, _ in issues if s == "WARNING"),
        "suggestions": suggestions,
        "verdict": verdicts[-1].upper(),
        "verdict_count": len(verdicts),
    }


# --- function-library check -------------------------------------------------

# Strings and comments in one alternation, so a `//` inside a string or a quote
# inside a comment is handled in a single left-to-right pass.
_STR_OR_COMMENT_RE = re.compile(
    r'"""[\s\S]*?"""'
    r'|"(?:\\.|[^"\\\n])*"'
    r"|'(?:\\.|[^'\\\n])*'"
    r"|//[^\n]*"
    r"|/\*[\s\S]*?\*/"
)
_CALL_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
# Lazy up to the first identifier directly followed by "(": the return type
# (record names, `string[]`, `map[string, integer]`) never is.
_FUNC_DEF_RE = re.compile(r"\bfunction\b[^(){};]*?\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
# Language keywords and constructs that look like calls but are not library
# functions. lookup(Name) / sequence(Name) are language constructs; their
# methods (get, next, count, ...) are ordinary catalog entries.
_NOT_FUNCTIONS = frozenset({
    "if", "else", "while", "for", "foreach", "do", "switch", "case", "return",
    "catch", "try", "function", "new", "lookup", "sequence", "CTL2",
    # Component entry points and hooks: user-defined, never library calls, but
    # review suggestions name them ("emit the row from `transform()`").
    "transform", "transformOnError", "getOutputPort", "getOutputPortOnError",
    "generate", "generateOnError", "initGroup", "initGroupOnError", "updateGroup",
    "updateGroupOnError", "finishGroup", "finishGroupOnError", "updateTransform",
    "updateTransformOnError", "clean", "init", "preExecute", "postExecute",
    "countOnError", "appendOnError",
})
_BACKTICK_RE = re.compile(r"`([^`\n]+)`")


def strip_strings_and_comments(code: str) -> str:
    def _sub(m: re.Match) -> str:
        return '""' if m.group(0)[0] in "\"'" else " "
    return _STR_OR_COMMENT_RE.sub(_sub, code or "")


def called_functions(code: str) -> set[str]:
    cleaned = strip_strings_and_comments(code)
    local_defs = {m.group(1) for m in _FUNC_DEF_RE.finditer(cleaned)}
    calls = {m.group(1) for m in _CALL_RE.finditer(cleaned)}
    return {c for c in calls if c not in local_defs and c not in _NOT_FUNCTIONS}


_catalog = None


def _get_catalog():
    global _catalog
    if _catalog is None:
        from dpo_forge.function_catalog import get_function_catalog
        _catalog = get_function_catalog()
    return _catalog


def unknown_functions(names: set[str], ignore: set[str] = frozenset()) -> list[str]:
    catalog = _get_catalog()
    return sorted(n for n in names if n not in ignore and not catalog.has(n))


# ---------------------------------------------------------------------------
# Stage: select
# ---------------------------------------------------------------------------

_FIX_VERB_RE = re.compile(
    r"\b(fix(?:es|ed|ing)?|correct(?:ed)?\s+(?:it|this|the\s+code|version)|repair|debug"
    r"|what'?s\s+wrong|doesn'?t\s+(?:compile|work)|does\s+not\s+(?:compile|work)"
    r"|won'?t\s+compile|compil(?:e|ation)\s+errors?|broken|bugs?)\b",
    re.IGNORECASE,
)
_EXTRA_COMPONENT_ALIASES = {
    "HASH_JOIN": "JOIN", "LOOKUP_JOIN": "JOIN", "DB_JOIN": "JOIN",
    "HTTPCONNECTOR": "HTTP_CONNECTOR", "HTTP_CONNECTOR": "HTTP_CONNECTOR",
}
# Wording review_judge.infer_component_type_from_prompt does not cover.
_EXTRA_PROMPT_COMPONENTS = (
    (re.compile(r"\bhttp\s*connector\b", re.IGNORECASE), "HTTP_CONNECTOR"),
    (re.compile(r"\b(?:a|the|this|my|in)\s+map\b|\bmap\s+(?:component|transform)\b", re.IGNORECASE), "REFORMAT"),
    (re.compile(r"\bMAP\b"), "REFORMAT"),  # upper-case only: "MAP/REFORMAT"
    # Upper-case component ids ("a DATA_GENERATOR with output ports ..."): the
    # prompt patterns expect "data generator" with a space.
    (re.compile(r"\bDATA_?GENERATOR\b"), "DATA_GENERATOR"),
    (re.compile(r"\b(?:EXT_)?(?:HASH|MERGE)_JOIN\b"), "JOIN"),
    (re.compile(r"\bEXT_FILTER\b"), "FILTER"),
)
_SEMANTIC_RE = re.compile(
    r"\b(null|nullable|runtime|requirement|specification|spec|lifecycle|boundary|inclusive|"
    r"exclusive|overflow|precision|rounding|group|counter|emits?|routes?|port|semantic|"
    r"wrong\s+result|business)\b",
    re.IGNORECASE,
)
_SYNTAX_RE = re.compile(
    r"\b(typo|semicolon|misspell\w*|undeclared|syntax|brace|parenthes\w*|keyword|"
    r"missing\s+return|case-sensitive)\b",
    re.IGNORECASE,
)


def _split_record(rec: dict) -> Optional[tuple[str, str]]:
    """(user, reference answer) for single-exchange records, else None
    (the multi-turn filter of mut_validate._parse_input_record)."""
    msgs = rec.get("messages") or []
    users = [m for m in msgs if m.get("role") == "user"]
    assistants = [m for m in msgs if m.get("role") == "assistant"]
    if len(users) != 1 or len(assistants) != 1:
        return None
    user = users[0].get("content") or ""
    ref = assistants[0].get("content") or ""
    if not user.strip() or not ref.strip():
        return None
    return user, ref


# Appended to a validate prompt that does not say how to lay out the answer.
# At inference this is always added automatically, so the teacher samples and
# the trained records must carry it too. The layout wording follows the
# corpus's own format-specifying prompts (CTL_LoRAT_multibug_validate_thinking.json);
# the severity sentence states the project rule: a data-dependent runtime risk
# is a WARNING, never an ERROR on its own.
VALIDATE_FORMAT_INSTRUCTION = """\
Report independent findings in code order using ISSUES, SUGGESTIONS, and VERDICT, in this layout:

ISSUES:
  [ERROR] <location> — <what is wrong and why>
  [WARNING] <location> — <what is wrong and why>

SUGGESTIONS:
  - <a concrete repair for each finding>

VERDICT: PASS or FAIL

Classify as ERROR code that does not compile, a runtime failure that is certain, and output that violates a stated requirement (for example adding where the specification says subtract). Classify as WARNING a runtime risk that depends on the data (a nullable field that may be null, a lookup that may miss, input that may be malformed) and a suspicious choice that still produces the specified output. If the code has no issues, write `[INFO] No issues found.` under ISSUES, omit SUGGESTIONS, and give VERDICT: PASS."""

_FORMAT_SPEC_RE = (re.compile(r"\bISSUES\b"), re.compile(r"\bVERDICT\b"))


def has_output_format_spec(user: str) -> bool:
    """True if the prompt already names the ISSUES / VERDICT layout."""
    return all(r.search(user or "") for r in _FORMAT_SPEC_RE)


def with_validate_format(user: str) -> tuple[str, bool]:
    """(prompt, added): the prompt with the format instruction appended when
    it does not already specify the layout."""
    if has_output_format_spec(user):
        return user, False
    return user.rstrip() + "\n\n" + VALIDATE_FORMAT_INSTRUCTION, True


def classify_task(user: str, ref: str, tags: list) -> str:
    """validate | fix | generate | other, decided from the record itself."""
    if parse_validate_answer(ref) is not None:
        return "validate"
    ref_has_code = bool(ctl_blocks(ref))
    if not ref_has_code:
        return "other"
    if user_has_ctl_program(user):
        fix_signal = (
            "fix_code" in (tags or [])
            or "PROBLEMS FIXED" in ref
            or bool(_FIX_VERB_RE.search(strip_fences(user)))
        )
        return "fix" if fix_signal else "other"
    return "generate"


def resolve_component(rec: dict, user: str) -> tuple[str, str]:
    """(component, source). The component must be named by the record's
    `component` field or by the prompt; "" means unnamed (record dropped)."""
    raw = rec.get("component")
    if raw:
        key = re.sub(r"[\s/\-]+", "_", str(raw).strip().upper())
        comp = normalize_component_type(raw) or _EXTRA_COMPONENT_ALIASES.get(key, "")
        if comp:
            return comp, "field"
    comp = infer_component_type_from_prompt(user)
    if comp:
        return comp, "prompt"
    for pattern, bucket in _EXTRA_PROMPT_COMPONENTS:
        if pattern.search(user):
            return bucket, "prompt_extra"
    return "", ""


# Components the ctl_validate tool cannot model: HTTPConnector mappings read
# virtual request/response ports that no <Record> in the prompt describes.
COMPILE_UNSUPPORTED = frozenset({"HTTP_CONNECTOR"})


def compile_bucket_for(component: str, code: str) -> str:
    """Bucket handed to ctl_validate. Entry-point signatures in the code
    decide it when they are distinctive — a Reformat prompt that says
    "filter out" must not be compiled as a Filter expression."""
    if component in COMPILE_UNSUPPORTED:
        return component
    from_code = normalize_component_type(infer_component_type_from_code(code or ""))
    if from_code and from_code != "REFORMAT":
        return from_code
    return component or from_code


def fix_score(ref: str) -> int:
    prose = strip_fences(ref)
    return len(_SEMANTIC_RE.findall(prose)) - 2 * len(_SYNTAX_RE.findall(prose))


def load_exclusion_set() -> tuple[set[str], dict[str, int]]:
    excluded: set[str] = set()
    counts: dict[str, int] = {}
    for path in EXCLUDE_FILES:
        if not path.exists():
            print(f"  [warn] exclusion file missing: {rel(path)}")
            continue
        n = 0
        for rec in read_records(path):
            user = None
            if isinstance(rec.get("messages"), list):
                user = next((m.get("content") for m in rec["messages"] if m.get("role") == "user"), None)
            if user is None:
                user = rec.get("prompt")
            if user:
                excluded.add(norm_ws(user))
                n += 1
        counts[rel(path)] = n
    for path in SUITE_FILES:
        if not path.exists():
            continue
        tests = json.loads(path.read_text(encoding="utf-8")).get("tests", [])
        for t in tests:
            if t.get("user_message"):
                excluded.add(norm_ws(t["user_message"]))
        counts[rel(path)] = len(tests)
    return excluded, counts


def build_pool(excluded: set[str]) -> tuple[list[dict], dict]:
    """Every eligible prompt, with its task type, component and selection
    features, plus a report of what was dropped and why."""
    # A self-distilled file copied into the corpus must never become a prompt
    # source: its "reference" would be the teacher's own answer.
    sources = [(p, "think") for p in sorted(TRAIN_DIR.glob(SOURCE_GLOB)) if "selfdistill" not in p.name.lower()]
    sources += [(TRAIN_DIR / f, "fix_topup") for f in FIX_TOPUP_FILES]
    pool: list[dict] = []
    seen: set[str] = set()
    dropped: Counter = Counter()
    by_file: dict[str, Counter] = defaultdict(Counter)
    for path, origin in sources:
        for idx, rec in enumerate(read_records(path)):
            split = _split_record(rec)
            fname = path.name
            if split is None:
                dropped["not_single_exchange"] += 1
                by_file[fname]["dropped:not_single_exchange"] += 1
                continue
            user, ref = split
            if rec.get("id") in KNOWN_WRONG_REFERENCES:
                dropped["known_wrong_reference"] += 1
                by_file[fname]["dropped:known_wrong_reference"] += 1
                continue
            task = classify_task(user, ref, rec.get("tags") or [])
            if origin == "fix_topup" and task != "fix":
                continue  # top-up files contribute fix prompts only
            if task == "other":
                dropped["other_task"] += 1
                by_file[fname]["dropped:other_task"] += 1
                continue
            component, comp_src = resolve_component(rec, user)
            if not component:
                dropped["no_component"] += 1
                by_file[fname][f"dropped:no_component:{task}"] += 1
                continue
            key = norm_ws(user)
            if key in excluded:
                dropped["in_eval_or_suite"] += 1
                by_file[fname][f"dropped:in_eval_or_suite:{task}"] += 1
                continue
            if key in seen:
                dropped["duplicate_prompt"] += 1
                by_file[fname][f"dropped:duplicate:{task}"] += 1
                continue
            seen.add(key)
            code_for_bucket = main_ctl_block(ref) or main_ctl_block(user)
            # Identity, exclusion and dedup use the record's own prompt; the
            # teacher, judge and training record see the prompt as sent.
            user_original = user
            format_added = False
            if task == "validate":
                user, format_added = with_validate_format(user)
            entry = {
                "prompt_id": make_prompt_id(user_original),
                "task_type": task,
                "component": component,
                "component_source": comp_src,
                "compile_bucket": compile_bucket_for(component, code_for_bucket),
                "source_file": fname,
                "source_origin": origin,
                "source_index": idx,
                "record_id": rec.get("id"),
                "source_id": rec.get("source_id") or rec.get("id"),
                "tags": rec.get("tags") or [],
                "user": user,
                "user_original": user_original,
                "format_instruction_added": format_added,
                "reference": ref,
            }
            if task == "validate":
                parsed = parse_validate_answer(ref)
                entry["ref_findings"] = parsed["findings"]
                entry["ref_verdict"] = parsed["verdict"]
            elif task == "fix":
                entry["fix_to_spec"] = "fix_code" in entry["tags"]
                entry["fix_score"] = fix_score(ref)
            pool.append(entry)
            by_file[fname][f"eligible:{task}:{component}"] += 1
    report = {"dropped": dict(dropped), "by_file": {k: dict(sorted(v.items())) for k, v in by_file.items()}}
    return pool, report


def full_group(p: dict) -> str:
    """The FULL_PLAN group of a pool entry: pilot groups, with the lifecycle
    generate components merged."""
    group = pilot_group(p)
    if group.startswith("generate_") and group != "generate_other":
        return "generate_lifecycle"
    return group


def select_prompts(pool: list[dict], seed: int, plan: tuple = FULL_PLAN,
                   prefer: frozenset = frozenset()) -> tuple[list[dict], dict]:
    """Full-run selection by plan. Fix groups rank semantic defects above
    syntax typos (fix_score); every other group is spread across components
    so no single component dominates it. Prompt ids in `prefer` (ones whose
    samples can be reused) are taken first within a group, as a tie-break:
    the pilots that drew them used the same stratified picker."""
    rng = random.Random(seed)
    by_group: dict[str, list[dict]] = defaultdict(list)
    for p in pool:
        by_group[full_group(p)].append(p)
    chosen: list[dict] = []
    shortfall: dict[str, int] = {}
    quotas: Counter = Counter()
    for task, group, n in plan:
        items = by_group[group]
        want = len(items) if n is None else n
        if task == "fix":
            ranked = list(items)
            rng.shuffle(ranked)
            picked = sorted(ranked, key=lambda p: (-p["fix_score"], p["prompt_id"] not in prefer))[:want]
        else:
            first = round_robin([p for p in items if p["prompt_id"] in prefer], want, lambda p: p["component"], rng)
            picked = first + round_robin([p for p in items if p["prompt_id"] not in prefer],
                                         want - len(first), lambda p: p["component"], rng)
        if len(picked) < want:
            shortfall[group] = want - len(picked)
        chosen.extend({**p, "selection_group": group} for p in picked)
        quotas[task] += want
    notes = {
        "available_per_group": {g: len(v) for g, v in sorted(by_group.items())},
        "excluded_groups": {g: {"available": len(by_group[g]), "why": why}
                            for g, why in FULL_EXCLUDED_GROUPS.items()},
    }
    return chosen, summarize_selection(chosen, pool, dict(quotas), shortfall, notes)


def summarize_selection(chosen: list[dict], pool: list[dict], quotas: dict, shortfall: dict,
                        notes: dict) -> dict:
    summary = {
        "quotas": quotas,
        "selected": Counter(p["task_type"] for p in chosen),
        "shortfall": shortfall,
        "by_group": Counter(p["selection_group"] for p in chosen),
        "by_task_component": Counter(f"{p['task_type']}:{p['component']}" for p in chosen),
        "by_source_file": Counter(f"{p['task_type']}:{p['source_file']}" for p in chosen),
        "format_instruction_added": Counter(
            f"{p['task_type']}:{p.get('format_instruction_added', False)}" for p in chosen
            if p["task_type"] == "validate"),
        "eligible": Counter(p["task_type"] for p in pool),
        **notes,
    }
    return {k: dict(v) if isinstance(v, Counter) else v for k, v in summary.items()}


def pilot_group(p: dict) -> str:
    """The PILOT_PLAN group a pool entry belongs to."""
    task = p["task_type"]
    if task == "fix":
        if p["fix_to_spec"]:
            return "fix_tier0"
        return "fix_tier1" if p["source_origin"] == "think" else "fix_tier2"
    if task == "validate":
        if p["ref_verdict"] == "PASS" and p["ref_findings"] == 0:
            return "validate_pass_clean"
        if p["ref_findings"] >= 3:
            return "validate_multi3"
        if p["ref_verdict"] == "PASS":
            return "validate_pass_warn"
        return f"validate_{p['ref_findings']}"
    if p["component"] in LIFECYCLE_COMPONENTS:
        return f"generate_{p['component']}"
    return "generate_other"


def round_robin(items: list[dict], n: int, key, rng: random.Random) -> list[dict]:
    """Up to n items, taking one from each key value in turn, so a group
    spreads over source files (or components) instead of the largest one."""
    buckets: dict[Any, list[dict]] = defaultdict(list)
    for item in items:
        buckets[key(item)].append(item)
    keys = sorted(buckets, key=str)
    rng.shuffle(keys)
    for k in keys:
        rng.shuffle(buckets[k])
    picked: list[dict] = []
    while len(picked) < n and any(buckets[k] for k in keys):
        for k in keys:
            if buckets[k] and len(picked) < n:
                picked.append(buckets[k].pop())
    return picked


def parse_plan(spec: str) -> tuple:
    """'validate_pass_warn:15,fix_tier1:5' -> a PILOT_PLAN-shaped plan."""
    plan = []
    for item in spec.split(","):
        group, _, count = item.strip().partition(":")
        task = group.split("_", 1)[0]
        if task not in TASK_TYPES or not count.isdigit():
            raise SystemExit(f"ERROR: --plan entries are <group>:<count>, e.g. validate_pass_warn:15; got {item!r}")
        plan.append((task, group, int(count)))
    return tuple(plan)


def select_pilot(pool: list[dict], seed: int, plan: tuple = PILOT_PLAN) -> tuple[list[dict], dict]:
    """Stratified pilot: the plan's count from every group, each spread
    across source files (generate_other: across components)."""
    rng = random.Random(seed)
    by_group: dict[str, list[dict]] = defaultdict(list)
    for p in pool:
        by_group[pilot_group(p)].append(p)
    chosen: list[dict] = []
    shortfall: dict[str, int] = {}
    quotas: Counter = Counter()
    for task, group, n in plan:
        key = (lambda p: p["component"]) if group == "generate_other" else (lambda p: p["source_file"])
        picked = round_robin(by_group[group], n, key, rng)
        if len(picked) < n:
            shortfall[group] = n - len(picked)
        chosen.extend({**p, "selection_group": group} for p in picked)
        quotas[task] += n
    notes = {"available_per_group": {g: len(v) for g, v in sorted(by_group.items())}}
    return chosen, summarize_selection(chosen, pool, dict(quotas), shortfall, notes)


def prompts_of_runs(runs: list[str], runs_dir: Path) -> dict[str, set[str]]:
    """{run: prompt ids in its prompts.jsonl}. A run without one is an error, so
    a mistyped name cannot silently exclude nothing."""
    found: dict[str, set[str]] = {}
    for run in runs:
        path = runs_dir / run / "prompts.jsonl"
        if not path.exists():
            raise SystemExit(f"ERROR: --exclude-runs run {run!r} has no prompts.jsonl under {rel(runs_dir)}")
        found[run] = {p["prompt_id"] for p in read_jsonl(path)}
    return found


def cmd_select(args) -> int:
    out = run_dir(args)
    prompts_path = out / "prompts.jsonl"
    if prompts_path.exists() and not args.overwrite:
        print(f"ERROR: {rel(prompts_path)} exists; pass --overwrite to reselect "
              f"(this orphans any samples already drawn for this run)")
        return 1
    excluded, excl_counts = load_exclusion_set()
    pool, pool_report = build_pool(excluded)
    excluded_runs: dict[str, set[str]] = {}
    if args.exclude_runs:
        # Prompts an earlier run already drew: a second-generation teacher is
        # sent only to prompts no run has sampled.
        excluded_runs = prompts_of_runs([r.strip() for r in args.exclude_runs.split(",") if r.strip()],
                                        Path(args.runs_dir))
        drawn = set().union(*excluded_runs.values())
        before = len(pool)
        pool = [p for p in pool if p["prompt_id"] not in drawn]
        print(f"  --exclude-runs: {before - len(pool)} of {before} pool prompts already drawn by "
              f"{', '.join(excluded_runs)}; {len(pool)} remain")
    reusable: dict[str, tuple[str, list[dict]]] = {}
    mut_cfg = None
    if args.reuse_from:
        cfg, _raw = load_eval_config(args.eval_config)
        mut_cfg = resolve_mut_config(cfg, args.eval_config)
        reusable = find_reusable_samples([r.strip() for r in args.reuse_from.split(",")], pool, mut_cfg,
                                         args.seed, args.k, Path(args.runs_dir), exclude_run=args.run)
    if args.plan:
        chosen, summary = select_pilot(pool, args.seed, parse_plan(args.plan))
    elif args.pilot:
        chosen, summary = select_pilot(pool, args.seed)
    else:
        chosen, summary = select_prompts(pool, args.seed, prefer=frozenset(reusable))

    # Independent overlap recheck against the exclusion set.
    overlap = [p["prompt_id"] for p in chosen if norm_ws(p["user_original"]) in excluded]
    if overlap:
        print(f"ERROR: {len(overlap)} selected prompts overlap eval/suite sets: {overlap[:5]}")
        return 1

    prompts_path.write_text("".join(json.dumps(p, ensure_ascii=False) + "\n" for p in chosen), encoding="utf-8")
    report = {
        "created": now_iso(),
        "pilot": args.pilot,
        "plan": args.plan,
        "seed": args.seed,
        "exclusion_sources": excl_counts,
        "exclusion_prompts": len(excluded),
        "pool": pool_report,
        "excluded_runs": {run: len(ids) for run, ids in excluded_runs.items()},
        "pool_after_run_exclusion": len(pool),
        "selection": summary,
        "compile_bucket_differs_from_component": sum(
            1 for p in chosen if p["compile_bucket"] != p["component"]),
    }
    if args.reuse_from:
        report["reused"] = import_samples(out, chosen, reusable, Path(args.runs_dir),
                                          [r.strip() for r in args.reuse_from.split(",") if r.strip() != args.run])
    write_json(out / "select_report.json", report)
    print(f"Selected {len(chosen)} prompts -> {rel(prompts_path)}")
    if args.reuse_from:
        r = report["reused"]
        print(f"  reused samples for {r['prompts']} prompts ({r['by_task']}) from {r['by_run']}; "
              f"{r['metadata_conversions']} metadata conversions copied")
    print(f"  per task: {summary['selected']}   eligible: {summary['eligible']}")
    if summary["shortfall"]:
        print(f"  SHORTFALL: {summary['shortfall']}")
    print(f"  groups: {summary['by_group']}")
    print(f"  report: {rel(out / 'select_report.json')}")
    return 0


def load_prompts(out: Path) -> list[dict]:
    path = out / "prompts.jsonl"
    if not path.exists():
        raise SystemExit(f"ERROR: {rel(path)} not found — run `select` first")
    return read_jsonl(path)


# ---------------------------------------------------------------------------
# Checks shared by check-refs and filter
# ---------------------------------------------------------------------------


def format_check(prompt: dict, answer: str) -> Optional[str]:
    """None when the answer's format is acceptable, else the reason."""
    if not (answer or "").strip():
        return "empty_answer"
    task = prompt["task_type"]
    if task == "validate":
        parsed = parse_validate_answer(answer)
        if parsed is None:
            return "validate_format_missing"
        # "ISSUES: none" is a well-formed PASS; a FAIL must say what failed.
        if parsed["verdict"] == "FAIL" and not parsed["findings"]:
            return "validate_fail_without_findings"
        if parsed["verdict_count"] > 1:
            return "validate_multiple_verdicts"
        # The severity rule: any ERROR makes the verdict FAIL, WARNING/INFO alone
        # leave it PASS. Every corpus reference is consistent with this.
        if (parsed["verdict"] == "FAIL") != bool(parsed["errors"]):
            return "validate_verdict_inconsistent"
        return None
    block = main_ctl_block(answer)
    if not block:
        return "no_ctl_block"
    ref_block = main_ctl_block(prompt["reference"])
    if (not ref_block or has_ctl2_header(ref_block)) and not has_ctl2_header(block):
        return "missing_ctl2_header"
    return None


def library_check(prompt: dict, answer: str) -> tuple[Optional[str], list[str]]:
    if prompt["task_type"] == "validate":
        parsed = parse_validate_answer(answer) or {}
        spans = " ; ".join(_BACKTICK_RE.findall(parsed.get("suggestions", "")))
        names = called_functions(spans)
        # A suggestion may name the task's own (possibly invalid) call while
        # telling the user to replace it.
        ignore = called_functions(prompt["user"])
    else:
        names = called_functions(main_ctl_block(answer))
        ignore = set()
    unknown = unknown_functions(names, ignore)
    return ("unknown_function" if unknown else None), unknown


_SEQUENCE_OR_LOOKUP_RE = re.compile(r"\b(?:lookup|sequence)\s*\(", re.IGNORECASE)


class McpUnavailable(RuntimeError):
    pass


def _skip_status(log: str) -> str:
    """Why validate_ctl returned None, from its log. Raises McpUnavailable
    when the server could not be reached."""
    if "ERROR calling MCP tool" in log:
        # The tool answered but refused the request (e.g. "Component type 'rollup'
        # requires at least one output metadata"): an input problem, not an outage.
        if "isError=True" in log:
            return "skipped_tool_rejected_input"
        raise McpUnavailable(log.strip())
    if "lookup table" in log:
        return "skipped_lookup_sequence"
    if "no <Record> metadata" in log:
        return "skipped_no_metadata"
    if "accumulator" in log:
        return "skipped_rollup_accumulator"
    if "metadata-stage" in log:
        return "skipped_metadata_stage"
    return "skipped_unknown"


# Skips that synthesized XML metadata can remove: the prompt describes its
# ports (or the Rollup accumulator) in prose the rule-based parser could not read.
SYNTH_RECOVERABLE = frozenset({"skipped_no_metadata", "skipped_rollup_accumulator"})


def compile_check(prompt: dict, answer: str, mcp_cfg: dict, synth: Optional["MetadataSynth"] = None) -> dict:
    """{'status': ..., 'problems': [...], 'metadata_source': ...} — status is
    one of pass, fail, skipped_<reason>. With `synth`, a prompt whose metadata
    is prose is compiled against LLM-converted XML metadata, once that
    metadata has been verified on the reference answer. Raises McpUnavailable
    when the server could not be reached, so nothing is recorded for a sample
    that was never actually compiled."""
    from dpo_forge.ctl_validate_mcp import validate_ctl

    code = main_ctl_block(answer)
    if not code:
        return {"status": "skipped_no_code", "problems": []}
    if prompt["component"] in COMPILE_UNSUPPORTED:
        return {"status": "skipped_unsupported_component", "problems": []}
    if _SEQUENCE_OR_LOOKUP_RE.search(code):
        return {"status": "skipped_lookup_sequence", "problems": []}
    logs: list[str] = []
    result = validate_ctl(mcp_cfg, prompt["compile_bucket"], prompt["user"], code, log_fn=logs.append)
    source = "prompt"
    if result is None:
        status = _skip_status(" ".join(logs))
        if status not in SYNTH_RECOVERABLE or synth is None:
            return {"status": status, "problems": [], "log": " ".join(logs).strip()}
        meta = synth.get(prompt)
        if meta["status"] != "ok":
            return {"status": f"skipped_synth_{meta['status']}", "problems": [], "prose_skip": status}
        logs = []
        result = validate_ctl(mcp_cfg, prompt["compile_bucket"], meta["compile_prompt"], code, log_fn=logs.append)
        if result is None:
            return {"status": "skipped_synth_" + _skip_status(" ".join(logs)).removeprefix("skipped_"),
                    "problems": [], "log": " ".join(logs).strip()}
        source = "synthesized"
    problems = [f"[{i.severity}] {i.description}" for i in result.issues]
    return {"status": "fail" if result.has_error else "pass", "problems": problems, "metadata_source": source}


# ---------------------------------------------------------------------------
# Prose metadata -> XML, via the judge LLM
# ---------------------------------------------------------------------------
#
# ctl_validate needs <Record> XML per port. When a prompt describes its ports
# in prose that ctl_validate_mcp's rule-based parser cannot read, the judge LLM
# rewrites that description into structured ports; the XML itself is emitted
# here (ctl_validate_mcp._emit_record), so every name and type is checked
# rather than trusted. Converted metadata is used only after the prompt's
# REFERENCE answer compiles cleanly against it: a wrong conversion would
# otherwise reject correct samples.

_METADATA_SYSTEM = """\
# Role
You convert CloverDX port metadata that a task describes in prose into a
structured list of records. This is a faithful rewrite, never an invention.

# Rules
- Output every record the task describes: each input port, each output port, and
  the Rollup group accumulator if the task describes one.
- role is "input", "output" or "accumulator". port is the port number the task
  states; an unnumbered single input or output is port 0; the accumulator's port
  is null.
- record_name is the record name the task gives ("Input TicketIn has ..." ->
  "TicketIn"). If the task gives none, use the type name the task's own code uses
  for that record (for an accumulator, the parameter type in `initGroup(XAcc acc)`).
  Otherwise null.
- fields: exactly the fields the task lists for that record, in the listed order,
  with each name spelled exactly as written. Never add a field the task does not
  list, and never take fields from the code.
- type is one of: string, integer, long, number, decimal, boolean, date, byte,
  cbyte, variant ("double" is number). For a list field give the element type and
  container "list"; for a map field give the value type and container "map".
- nullable is true when the task says nullable, false when it says non-null / not
  null / required, and null when it says nothing.
- A record described relative to another ("same fields as the input plus x") may be
  expanded only when every resulting field and type is explicit.
- If any record's fields or types cannot be determined with certainty, set
  "complete" to false.

# Required output
A single raw JSON object, no fences or prose:
{
  "records": [
    {"role": "input" | "output" | "accumulator", "port": 0 | null, "record_name": "..." | null,
     "fields": [{"name": "...", "type": "...", "container": null | "list" | "map", "nullable": true | false | null}]}
  ],
  "complete": true | false,
  "notes": "anything uncertain"
}
"""

_CTL_FIELD_TYPES = frozenset({"string", "integer", "long", "number", "decimal", "boolean",
                              "date", "byte", "cbyte", "variant"})


def metadata_from_llm(data: dict, task_text: str) -> tuple[str, Optional[str], list[str]]:
    """(status, compile_prompt, problems) from the LLM's structured ports.
    status 'ok' only when every record, field name and type checks out; the
    compile prompt then labels each <Record> the way ctl_validate_mcp's
    extract_ports_metadata reads them."""
    from dpo_forge.ctl_validate_mcp import _emit_record

    problems: list[str] = []
    if not isinstance(data, dict) or not isinstance(data.get("records"), list) or not data["records"]:
        return "invalid", None, ["no records"]
    if data.get("complete") is not True:
        return "incomplete", None, [str(data.get("notes") or "LLM marked the conversion incomplete")]
    words = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", task_text or ""))
    by_role: dict[str, list[tuple[Optional[int], str]]] = defaultdict(list)
    for rec in data["records"]:
        role = rec.get("role")
        if role not in ("input", "output", "accumulator"):
            problems.append(f"bad role {role!r}")
            continue
        name = rec.get("record_name")
        if name is not None and name not in words:
            problems.append(f"record name {name!r} is not in the task")
        fields = []
        for f in rec.get("fields") or []:
            fname, ftype = f.get("name"), str(f.get("type") or "").lower()
            if fname not in words:
                problems.append(f"field {fname!r} is not in the task")
            if ftype not in _CTL_FIELD_TYPES:
                problems.append(f"field {fname!r} has unknown type {ftype!r}")
            container = f.get("container")
            if container not in (None, "list", "map"):
                problems.append(f"field {fname!r} has unknown container {container!r}")
            nullable = f.get("nullable")
            fields.append((fname, ftype, container, None if nullable is None else str(bool(nullable)).lower()))
        if not fields:
            problems.append(f"{role} record {name!r} has no fields")
        port = rec.get("port")
        rec_name = name or f"Synth{role.capitalize()}{port if port is not None else ''}"
        by_role[role].append((port, _emit_record(rec_name, fields)))
    if len(by_role["accumulator"]) > 1:
        problems.append("more than one accumulator")
    for role in ("input", "output"):
        ports = [p for p, _ in by_role[role]]
        if sorted(ports) != list(range(len(ports))):
            problems.append(f"{role} ports {ports} are not 0..n-1")
    if problems:
        return "invalid", None, problems
    parts = []
    for role, label in (("input", "Input"), ("output", "Output")):
        for port, xml in sorted(by_role[role], key=lambda t: t[0]):
            parts.append(f'{label} metadata (port {port}):\n<Metadata id="Synth{label}{port}">{xml}</Metadata>')
    for _port, xml in by_role["accumulator"]:
        parts.append(f'Accumulator metadata:\n<Metadata id="SynthAccumulator">{xml}</Metadata>')
    return "ok", "\n\n".join(parts) + "\n", []


class MetadataSynth:
    """Per-prompt LLM metadata conversion, verified on the reference answer and
    cached in <run>/metadata_synth.jsonl (one conversion per prompt, however
    many samples and threads ask). API errors are not cached, so a resume
    retries them."""

    def __init__(self, out_dir: Path, judge: "Judge", mcp_cfg: dict):
        self._path = out_dir / "metadata_synth.jsonl"
        self._judge = judge
        self._mcp_cfg = mcp_cfg
        self._cache = {r["prompt_id"]: r for r in read_jsonl(self._path)}
        self._locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
        self._guard = threading.Lock()

    def get(self, prompt: dict) -> dict:
        pid = prompt["prompt_id"]
        with self._guard:
            lock = self._locks[pid]
        with lock:
            if pid not in self._cache:
                entry = self._build(prompt)
                if entry["status"] != "llm_error":
                    append_jsonl(self._path, [entry])
                self._cache[pid] = entry
            return self._cache[pid]

    def _build(self, prompt: dict) -> dict:
        from dpo_forge.ctl_validate_mcp import validate_ctl

        entry: dict[str, Any] = {"prompt_id": prompt["prompt_id"], "created": now_iso()}
        asked = self._judge._ask(_METADATA_SYSTEM,
                                 f"## TASK\n<task>\n{prompt['user']}\n</task>\n\nOutput the JSON object only.",
                                 "selfdistill_metadata")
        if not asked["ok"]:
            return {**entry, "status": "llm_error", "error": asked["error"]}
        entry["llm"] = asked["verdict"]
        status, compile_prompt, problems = metadata_from_llm(asked["verdict"], prompt["user"])
        entry.update(status=status, problems=problems, compile_prompt=compile_prompt)
        if status != "ok":
            return entry
        ref_code = main_ctl_block(prompt["reference"])
        if not ref_code:
            return {**entry, "status": "unverified", "problems": ["reference has no CTL block"]}
        logs: list[str] = []
        result = validate_ctl(self._mcp_cfg, prompt["compile_bucket"], compile_prompt, ref_code, log_fn=logs.append)
        if result is None:
            skip = _skip_status(" ".join(logs))  # raises McpUnavailable -> nothing cached
            return {**entry, "status": "unverified", "problems": [f"reference compile {skip}"]}
        entry["reference_compile"] = [f"[{i.severity}] {i.description}" for i in result.issues]
        if result.has_error:
            # The conversion (or the reference itself) is wrong; never compile samples against it.
            return {**entry, "status": "unverified"}
        return entry


_PROBE_PROMPT = (
    "Input metadata (port 0):\n"
    '<Record name="ProbeIn" type="delimited" fieldDelimiter="|" recordDelimiter="\\n">'
    '<Field name="id" type="long"/></Record>\n\n'
    "Output metadata (port 0):\n"
    '<Record name="ProbeOut" type="delimited" fieldDelimiter="|" recordDelimiter="\\n">'
    '<Field name="id" type="long"/></Record>\n'
)
_PROBE_GOOD = "//#CTL2\nfunction integer transform() {\n    $out.0.id = $in.0.id;\n    return ALL;\n}\n"
_PROBE_BAD = "//#CTL2\nfunction integer transform() {\n    $out.0.id = ;\n    return ALL;\n}\n"


def probe_mcp(mcp_cfg: dict) -> None:
    """Fail loudly unless the compile check demonstrably works: a valid
    program must PASS and a syntax error must FAIL. validate_ctl returns None
    both for a skip and for an unreachable server, so without this a dead
    server would silently turn every compile check into a skip."""
    from dpo_forge.ctl_validate_mcp import validate_ctl

    logs: list[str] = []
    good = validate_ctl(mcp_cfg, "REFORMAT", _PROBE_PROMPT, _PROBE_GOOD, log_fn=logs.append)
    bad = validate_ctl(mcp_cfg, "REFORMAT", _PROBE_PROMPT, _PROBE_BAD, log_fn=logs.append)
    if good is None or bad is None or good.has_error or not bad.has_error:
        raise SystemExit(
            f"ERROR: ctl_validate MCP probe failed at {mcp_cfg['url']} "
            f"(valid program -> {getattr(good, 'verdict', None)}, syntax error -> "
            f"{getattr(bad, 'verdict', None)}; log: {' '.join(logs).strip() or '-'}).\n"
            f"  Start the CloverDX MCP server, or pass --no-compile to run without the compile check."
        )
    print(f"  ctl_validate MCP OK at {mcp_cfg['url']}")


def mcp_config(args) -> dict:
    return {**MCP_DEFAULTS, "url": args.mcp_url or MCP_DEFAULTS["url"]}


def compile_label(result: dict) -> str:
    """Compile status, marked when the metadata came from the LLM conversion."""
    status = result.get("status", "?")
    return f"{status}/synth" if result.get("metadata_source") == "synthesized" else status


def cmd_check_refs(args) -> int:
    """Checker sanity: the reference answers should pass format, library and
    compile checks. A failure is either a checker bug or a bad reference."""
    out = run_dir(args)
    prompts = load_prompts(out)
    mcp_cfg = None
    synth = None
    if not args.no_compile:
        mcp_cfg = mcp_config(args)
        probe_mcp(mcp_cfg)
        _cfg, raw = load_eval_config(args.eval_config)
        synth = MetadataSynth(out, Judge(judge_config(raw)), mcp_cfg)

    def check(p: dict) -> dict:
        answer = p["reference"]
        row = {"prompt_id": p["prompt_id"], "task_type": p["task_type"], "source_file": p["source_file"],
               "record_id": p["record_id"]}
        row["format"] = format_check(p, answer) or "ok"
        lib_reason, unknown = library_check(p, answer)
        row["library"] = lib_reason or "ok"
        row["unknown_functions"] = unknown
        if mcp_cfg and p["task_type"] != "validate":
            # With synth, prose-metadata prompts get their conversion built and
            # verified here, so `filter` starts with a warm cache.
            row["compile"] = compile_check(p, answer, mcp_cfg, synth)
        return row

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        rows = list(pool.map(check, prompts))
    stats: dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        s = stats[row["task_type"]]
        s[f"format:{row['format']}"] += 1
        s[f"library:{row['library']}"] += 1
        if "compile" in row:
            s[f"compile:{compile_label(row['compile'])}"] += 1
    (out / "refcheck.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                                        encoding="utf-8")
    report = {k: dict(sorted(v.items())) for k, v in stats.items()}
    write_json(out / "refcheck_report.json", report)
    for task, s in report.items():
        print(f"  {task}: {s}")
    bad = [r for r in rows if r["format"] != "ok" or r["library"] != "ok"
           or r.get("compile", {}).get("status") == "fail"]
    print(f"{len(bad)} of {len(rows)} references fail a check -> {rel(out / 'refcheck.jsonl')}")
    return 0


# ---------------------------------------------------------------------------
# Stage: sample
# ---------------------------------------------------------------------------


def load_eval_config(path: Path) -> tuple[dict, dict]:
    """(merged cfg, raw yaml). The mut section is resolved exactly as test.py
    does it: model path, then the template name from the training config."""
    path = Path(path).resolve()
    raw = eval_harness.load_config(path)
    cfg = eval_harness._deep_merge(eval_harness.DEFAULT_CONFIG, raw)
    return cfg, raw


def resolve_mut_config(cfg: dict, config_path: Path) -> dict:
    config_dir = Path(config_path).resolve().parent
    model_path, _run_name, _base = eval_harness.resolve_mut_model_path(cfg, config_dir)
    mut_cfg = dict(cfg.get("mut", {}))
    mut_cfg["model_path"] = model_path
    template_name = eval_harness.resolve_template_name(cfg, config_dir)
    if template_name and not mut_cfg.get("chat_template_name"):
        mut_cfg["chat_template_name"] = template_name
    return mut_cfg


def sampling_for(mut_cfg: dict, task_type: str) -> dict:
    """Per-task sampling, as test._resolve_mut_overrides resolves it: fix
    uses the validate block when the config has no fix block."""
    block = mut_cfg.get(task_type) or (mut_cfg.get("validate") if task_type == "fix" else None) or {}
    if not block.get("system_prompt"):
        raise SystemExit(f"ERROR: eval config has no mut.{task_type}.system_prompt "
                         f"(or mut.validate for fix) — the suite's system prompt is required")
    return {
        "system_prompt": block["system_prompt"],
        "temperature": float(block.get("temperature", 0.4)),
        "top_p": float(block.get("top_p", 1.0)),
        "top_k": int(block.get("top_k", 50)),
        "repetition_penalty": float(block.get("repetition_penalty", 1.0)),
    }


class SamplingClient(eval_harness.LocalMUTClient):
    """LocalMUTClient plus batched k-sample generation. The k samples share
    one prompt, so one generate() with num_return_sequences=k needs no
    padding and reuses the prompt prefill."""

    def sample_k(self, system: str, user: str, k: int, temperature: float, top_p: float,
                 top_k: int, repetition_penalty: float, max_new_tokens: int, seed: int) -> list[dict]:
        import torch

        self._load()
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        tokenized = self._tokenize_messages(messages)
        input_ids = (tokenized.input_ids if hasattr(tokenized, "input_ids") else tokenized).to(self._model.device)

        stop_ids: list[int] = []
        if self._tok.eos_token_id is not None:
            stop_ids.append(self._tok.eos_token_id)
        im_end_id = self._tok.convert_tokens_to_ids("<|im_end|>")
        if im_end_id is not None and im_end_id != self._tok.unk_token_id and im_end_id not in stop_ids:
            stop_ids.append(im_end_id)
        stop_set = set(stop_ids)

        torch.manual_seed(seed)
        t0 = time.monotonic()
        with torch.inference_mode():
            output = self._model.generate(
                input_ids,
                attention_mask=torch.ones_like(input_ids),
                max_new_tokens=max_new_tokens,
                do_sample=True,
                temperature=temperature,
                top_p=top_p,
                top_k=top_k,
                repetition_penalty=repetition_penalty,
                num_return_sequences=k,
                eos_token_id=stop_ids or None,
                pad_token_id=self._tok.eos_token_id,
            )
        elapsed = time.monotonic() - t0
        prompt_len = int(input_ids.shape[1])
        results = []
        for row in output:
            n_new, hit_cap = generated_length(row[prompt_len:].tolist(), stop_set)
            raw = self._tok.decode(row[prompt_len:prompt_len + n_new].tolist(), skip_special_tokens=True)
            results.append({"raw": raw, "new_tokens": n_new, "hit_cap": hit_cap})
        return [{**r, "prompt_tokens": prompt_len, "batch_elapsed_s": round(elapsed, 2)} for r in results]


def generated_length(gen: list[int], stop_set: set[int]) -> tuple[int, bool]:
    """(tokens generated including the stop token, hit_cap) for one row of a
    batched generate(). Finished rows are right-padded with EOS up to the
    longest row, so the first stop token ends the sequence; a row with no
    stop token at all ran into max_new_tokens."""
    stop_pos = next((i for i, t in enumerate(gen) if t in stop_set), None)
    if stop_pos is None:
        return len(gen), True
    return stop_pos + 1, False


def parse_shard(spec: str) -> tuple[int, int]:
    m = re.fullmatch(r"(\d+)/(\d+)", spec or "0/1")
    if not m or int(m.group(1)) >= int(m.group(2)):
        raise SystemExit(f"ERROR: --shard must be i/n with 0 <= i < n, got {spec!r}")
    return int(m.group(1)), int(m.group(2))


def load_samples(out: Path) -> dict[tuple[str, int], dict]:
    """All shards, deduplicated by (prompt_id, sample_idx); last write wins
    (a prompt re-sampled after a partial write replaces the partial rows)."""
    samples: dict[tuple[str, int], dict] = {}
    for path in sorted(out.glob("samples.shard*.jsonl")):
        for row in read_jsonl(path):
            samples[(row["prompt_id"], row["sample_idx"])] = row
    return samples


def sample_matches(sample: dict, target: dict, teacher: str, max_new_tokens: int, seed: int) -> Optional[str]:
    """None if `sample` is exactly what `sample` would draw now, else why not."""
    smp = sample.get("sampling") or {}
    checks = (
        ("teacher", sample.get("teacher_model") == teacher),
        ("system_prompt", sample.get("system_prompt") == target["system_prompt"]),
        ("temperature", smp.get("temperature") == target["temperature"]),
        ("top_p", smp.get("top_p") == target["top_p"]),
        ("top_k", smp.get("top_k") == target["top_k"]),
        ("repetition_penalty", smp.get("repetition_penalty") == target["repetition_penalty"]),
        ("max_new_tokens", smp.get("max_new_tokens") == max_new_tokens),
        ("reasoning_effort", smp.get("reasoning_effort") == target["reasoning_effort"]),
        ("chat_template", smp.get("chat_template_name") == target["chat_template_name"]),
        ("seed", sample.get("seed") == seed),
    )
    bad = [name for name, ok in checks if not ok]
    return ",".join(bad) if bad else None


def find_reusable_samples(runs: list[str], pool: list[dict], mut_cfg: dict, seed: int, k: int,
                          runs_dir: Path, exclude_run: Optional[str] = None) -> dict[str, tuple[str, list[dict]]]:
    """{prompt_id: (run, k sample rows)} for pool prompts whose samples in an
    earlier run match the current configuration exactly — the prompt text as
    sent (so validate prompts sampled before the format instruction, or under
    an older wording, never match), the teacher, and every sampling setting.
    The seed is derived from the prompt id, so a match is the same draw."""
    teacher = str(mut_cfg["model_path"])
    max_new_tokens = int(mut_cfg.get("max_new_tokens", 16384))
    by_id = {p["prompt_id"]: p for p in pool}
    found: dict[str, tuple[str, list[dict]]] = {}
    for run in runs:
        if run == exclude_run:
            continue
        src = runs_dir / run
        if not (src / "prompts.jsonl").exists():
            raise SystemExit(f"ERROR: --reuse-from run {run!r} not found under {rel(runs_dir)}")
        src_prompts = {p["prompt_id"]: p for p in read_jsonl(src / "prompts.jsonl")}
        grouped: dict[str, list[dict]] = defaultdict(list)
        for (pid, _j), row in load_samples(src).items():
            grouped[pid].append(row)
        for pid, rows in grouped.items():
            target_prompt = by_id.get(pid)
            if pid in found or target_prompt is None or src_prompts.get(pid, {}).get("user") != target_prompt["user"]:
                continue
            rows = sorted(rows, key=lambda r: r["sample_idx"])
            if [r["sample_idx"] for r in rows] != list(range(k)):
                continue
            target = {**sampling_for(mut_cfg, target_prompt["task_type"]),
                      "reasoning_effort": mut_cfg.get("reasoning_effort"),
                      "chat_template_name": mut_cfg.get("chat_template_name")}
            want_seed = seed + int(pid[:8], 16) % 1_000_000
            if all(sample_matches(r, target, teacher, max_new_tokens, want_seed) is None for r in rows):
                found[pid] = (run, rows)
    return found


def import_samples(out: Path, chosen: list[dict], reusable: dict[str, tuple[str, list[dict]]],
                   runs_dir: Path, runs: list[str]) -> dict:
    """Copy reusable samples (and verified metadata conversions) of the chosen
    prompts into this run. Rewrites samples.shard_reused.jsonl, so reselecting
    never leaves stale copies behind."""
    chosen_ids = {p["prompt_id"] for p in chosen}
    rows, by_task, by_run = [], Counter(), Counter()
    for pid in sorted(chosen_ids & set(reusable)):
        run, samples = reusable[pid]
        rows.extend({**r, "reused_from": run} for r in samples)
        by_task[samples[0]["task_type"]] += 1
        by_run[run] += 1
    path = out / "samples.shard_reused.jsonl"
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    # Metadata conversions depend only on the prompt, so any verified one carries over.
    have = {r["prompt_id"] for r in read_jsonl(out / "metadata_synth.jsonl")}
    copied = []
    for run in runs:
        for entry in read_jsonl(runs_dir / run / "metadata_synth.jsonl"):
            if entry["prompt_id"] in chosen_ids and entry["prompt_id"] not in have:
                copied.append({**entry, "copied_from": run})
                have.add(entry["prompt_id"])
    if copied:
        append_jsonl(out / "metadata_synth.jsonl", copied)
    return {"prompts": sum(by_run.values()), "by_task": dict(by_task),
            "by_run": dict(by_run), "metadata_conversions": len(copied)}


def cmd_sample(args) -> int:
    out = run_dir(args)
    prompts = load_prompts(out)
    shard_i, shard_n = parse_shard(args.shard)
    mine = [p for i, p in enumerate(prompts) if i % shard_n == shard_i]
    if args.limit:
        mine = mine[:args.limit]
    k = args.k

    existing = load_samples(out)
    done = {pid for pid in {key[0] for key in existing}
            if sum(1 for j in range(k) if (pid, j) in existing) == k}
    todo = [p for p in mine if p["prompt_id"] not in done]
    print(f"Shard {shard_i}/{shard_n}: {len(mine)} prompts, {len(mine) - len(todo)} already sampled, "
          f"{len(todo)} to go (k={k})")
    if not todo:
        return 0

    cfg, _raw = load_eval_config(args.eval_config)
    mut_cfg = resolve_mut_config(cfg, args.eval_config)
    if not mut_cfg.get("enable_thinking"):
        raise SystemExit("ERROR: eval config has enable_thinking false — self-distillation samples traces")
    max_new_tokens = int(args.max_new_tokens or mut_cfg.get("max_new_tokens", 16384))
    mut_cfg["max_new_tokens"] = max_new_tokens
    client = SamplingClient(mut_cfg)
    client.warm_up()
    teacher = str(mut_cfg["model_path"])
    samples_path = out / f"samples.shard{shard_i}.jsonl"
    stats_path = out / f"sample_stats.shard{shard_i}.json"
    stats = json.loads(stats_path.read_text()) if stats_path.exists() else {"by_task": {}}

    for n, p in enumerate(todo, 1):
        s = sampling_for(mut_cfg, p["task_type"])
        seed = args.seed + int(p["prompt_id"][:8], 16) % 1_000_000
        results = client.sample_k(s["system_prompt"], p["user"], k, s["temperature"], s["top_p"],
                                  s["top_k"], s["repetition_penalty"], max_new_tokens, seed)
        rows = []
        for j, r in enumerate(results):
            closed = bool(re.search(r"</think\s*>", r["raw"], re.IGNORECASE))
            thinking, answer = split_thinking(r["raw"], True)
            rows.append({
                "prompt_id": p["prompt_id"],
                "sample_idx": j,
                "task_type": p["task_type"],
                "thinking": thinking,
                "answer": answer,
                "think_closed": closed,
                "hit_cap": r["hit_cap"],
                "new_tokens": r["new_tokens"],
                "prompt_tokens": r["prompt_tokens"],
                "batch_elapsed_s": r["batch_elapsed_s"],
                "seed": seed,
                "system_prompt": s["system_prompt"],
                "sampling": {
                    "k": k,
                    "temperature": s["temperature"], "top_p": s["top_p"], "top_k": s["top_k"],
                    "repetition_penalty": s["repetition_penalty"], "max_new_tokens": max_new_tokens,
                    "enable_thinking": True, "reasoning_effort": mut_cfg.get("reasoning_effort"),
                    "chat_template_name": mut_cfg.get("chat_template_name"),
                },
                "teacher_model": teacher,
                "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
                "sampled_at": now_iso(),
            })
        append_jsonl(samples_path, rows)

        t = stats["by_task"].setdefault(p["task_type"], {"prompts": 0, "seconds": 0.0, "new_tokens": 0,
                                                          "max_new_tokens_in_batch": 0, "hit_cap": 0})
        t["prompts"] += 1
        t["seconds"] += results[0]["batch_elapsed_s"]
        t["new_tokens"] += sum(r["new_tokens"] for r in results)
        t["max_new_tokens_in_batch"] += max(r["new_tokens"] for r in results)
        t["hit_cap"] += sum(1 for r in results if r["hit_cap"])
        write_json(stats_path, stats)
        caps = sum(1 for r in results if r["hit_cap"])
        print(f"  [{n}/{len(todo)}] {p['task_type']:8s} {p['prompt_id']} "
              f"{results[0]['batch_elapsed_s']:7.1f}s  tokens={[r['new_tokens'] for r in results]}"
              + (f"  HIT CAP x{caps}" if caps else ""))
    return 0


# ---------------------------------------------------------------------------
# Judge
# ---------------------------------------------------------------------------

_JUDGE_ROLE = """\
# Role
You grade candidate answers for a self-distillation data pipeline. A CloverDX CTL2
model answered a TASK; you compare its CANDIDATE answer with a trusted, reviewed
REFERENCE answer to the same task. Every candidate you accept becomes a training
target that the model will be trained on with full confidence. Accepting a wrong
candidate is the worst outcome this pipeline can produce; rejecting a correct one
costs almost nothing. When you are unsure, reject.

# General rules
- Wording, ordering, formatting, variable names, comments and explanation style
  never matter. Conclusions and facts do.
- The REFERENCE is trusted. Where the candidate contradicts it, the candidate is
  wrong.
- Right but incomplete is REJECT.
- Every statement the candidate makes must be true — about CTL2, about the
  component contract and about the task. A false statement anywhere in the
  candidate's answer, including its explanations and suggestions, is REJECT.
- You see only the candidate's final answer, not its reasoning; judge that answer.
- Severity calibration (CTL2 reviews): ERROR for code that does not compile, a runtime
  failure that is certain, or output that violates a stated requirement of the task
  (adding where the specification says subtract). A runtime risk that depends on the
  data — a nullable field that may be null, a lookup that may miss, input that may be
  malformed — is WARNING, never ERROR on its own; so is a suspicious choice that still
  produces the specified output. INFO lines are notes, not findings.
"""

_RUBRICS = {
    "validate": """\
# Rubric — validate (an ISSUES / SUGGESTIONS / VERDICT review)
1. Take each ERROR and WARNING line in the REFERENCE as one finding. For each, find
   the candidate finding that describes the same defect (same code location, same
   root cause). If there is none, add it to `missing`. INFO lines in the reference
   are notes, not findings: a candidate that omits one is not incomplete (though a
   candidate that contradicts one is making a false claim).
2. For every matched pair whose severity differs, add an entry to
   `severity_mismatches`.
3. Take each candidate ERROR / WARNING line that matches no reference finding.
   Unless you are CERTAIN it is a real defect the reference overlooked — provable from
   the code and metadata alone — add it to `extra_findings`. Only a provable real
   defect goes to `extra_real_findings`, with the proof.
4. `verdict_match` is true only if the candidate's VERDICT equals the reference's.
5. A finding whose description is factually wrong (even if it points at the right
   line), or a suggested repair that would not compile or would not fix the problem,
   goes to `false_claims`.
""",
    "fix": """\
# Rubric — fix (the task gives code to repair)
1. Identify every defect the REFERENCE fixes: its list of problems, and every
   behavioural difference between the task's code and the reference's corrected code.
   Each must be fixed in the candidate's final code — any correct fix counts, it need
   not be the reference's fix. Each defect left unfixed goes to `missing`.
2. Check the candidate's final code against every requirement stated in the task.
   Each requirement it breaks goes to `broken_requirements`.
3. If the candidate changes behaviour that was already correct, or calls correct code
   a defect, add it to `wrong_fixes`.
4. The candidate's final code must compile on inspection: correct syntax, types,
   function signatures and the component's entry-point contract. Each problem goes to
   `compile_problems`.
5. Each false statement in the candidate's problem list or explanation goes to
   `false_claims`.
Set `verdict_match` to null.
""",
    "generate": """\
# Rubric — generate (write CTL2 for the task)
1. For every requirement in the task, the candidate's code must behave the same as the
   reference: the same outputs, null handling, edge cases, port routing, record counts
   and return values. Each requirement where it differs goes to
   `broken_requirements`. Each requirement it does not implement at all goes to
   `missing`.
2. The code must compile on inspection: correct syntax, types, function signatures and
   the component's entry-point contract. Each problem goes to `compile_problems`.
3. Each false statement in the candidate's explanation goes to `false_claims`.
Set `verdict_match` to null.
""",
}

_JUDGE_SCHEMA = """\
# Required output
Respond with a single raw JSON object (no markdown fences, no prose around it):
{
  "accept": true | false,
  "verdict_match": true | false | null,
  "missing": [string],
  "false_claims": [string],
  "extra_findings": [string],
  "extra_real_findings": [string],
  "severity_mismatches": [string],
  "broken_requirements": [string],
  "wrong_fixes": [string],
  "compile_problems": [string],
  "reason": "one or two sentences"
}
"accept" is true only if every list except extra_real_findings is empty and, for
validate, verdict_match is true.
"""

REJECT_LISTS = ("missing", "false_claims", "extra_findings", "severity_mismatches",
                "broken_requirements", "wrong_fixes", "compile_problems")

_ctl2_reference_text: Optional[str] = None


def _ctl2_reference() -> str:
    global _ctl2_reference_text
    if _ctl2_reference_text is None:
        _ctl2_reference_text = CTL2_REFERENCE_FILE.read_text(encoding="utf-8") if CTL2_REFERENCE_FILE.exists() else ""
    return _ctl2_reference_text


def build_judge_system(task_type: str, function_lookup: bool) -> str:
    parts = []
    ref = _ctl2_reference()
    if ref:
        parts += ["# CTL2 Language Reference", "", ref, "", "---"]
    parts += [_JUDGE_ROLE, _RUBRICS[task_type]]
    if function_lookup:
        parts.append(_FUNCTION_LOOKUP_NOTE)
    parts.append(_JUDGE_SCHEMA)
    return "\n\n".join(parts)


def build_judge_user(prompt: dict, candidate: str, reference_first: bool = True) -> str:
    head = (f"## Task type: {prompt['task_type']}\n"
            f"## Component: {prompt['component']}\n\n"
            f"## TASK (the user's request, verbatim)\n<task>\n{prompt['user']}\n</task>\n\n")
    ref = f"## REFERENCE ANSWER (trusted)\n<reference>\n{prompt['reference']}\n</reference>\n\n"
    cand = f"## CANDIDATE ANSWER (to grade)\n<candidate>\n{candidate}\n</candidate>\n\n"
    body = ref + cand if reference_first else cand + ref
    return head + body + "Grade the CANDIDATE against the REFERENCE with the rubric. Output the JSON object only."


def decide_accept(task_type: str, verdict: dict) -> bool:
    """The script decides, not the judge's own flag alone: any non-empty
    rejection list, or a validate verdict mismatch, rejects."""
    if verdict.get("accept") is not True:
        return False
    for key in REJECT_LISTS:
        value = verdict.get(key)
        if value:  # non-empty list (or any truthy non-list the judge put there)
            return False
    if task_type == "validate" and verdict.get("verdict_match") is not True:
        return False
    return True


# --- second pass: false-claim check over the trace and the answer ----------
#
# The reference judge compares conclusions; it can accept an answer that
# reaches them through a false belief ("byte2hex takes exactly one argument"),
# and self-distillation would then train that belief with full confidence.
# This pass runs on every judge-accepted sample and reads the thinking too.

_CLAIMS_ROLE = """\
# Role
You audit a CloverDX CTL2 model's REASONING TRACE and FINAL ANSWER for false
statements before the pair is used as a training target. The answer has already
been judged to reach the right conclusions; your only job is to find false claims.
Training on a false claim teaches it with full confidence, so be thorough.

# What counts
A claim is any statement of fact about CTL2 (syntax, types, conversions, null
semantics, operators, built-in functions and their overloads, arities, return
types and runtime errors), about a component's contract and lifecycle, or about
the task's own code, metadata or requirements.

- FINAL ANSWER: every false claim counts, however minor, including in explanations
  and suggestions.
- REASONING TRACE: a false claim counts unless the trace itself explicitly corrects
  it later ("wait, that's wrong — ..."). A tentative belief the trace acts on without
  verifying ("I believe X returns null") counts when X is false.
- Not a claim: questions, plans, hypotheses the trace checks and rejects, and
  statements about what the user wants that the task supports.
- Do not flag a statement because it is imprecise or incomplete; flag it only if it
  is false. Do not flag anything you cannot show is false.

Use the CTL2 reference and, where available, the `ctl_function_info` tool to settle
any claim about a built-in function before you flag it — or before you accept it.
"""

_CLAIMS_SCHEMA = """\
# Required output
Respond with a single raw JSON object (no markdown fences, no prose around it):
{
  "answer_false_claims": [{"claim": "quoted or paraphrased", "why_false": "..."}],
  "uncorrected_trace_false_claims": [{"claim": "...", "why_false": "..."}],
  "corrected_trace_false_claims": [{"claim": "...", "corrected_by": "..."}],
  "clean": true | false,
  "reason": "one sentence"
}
"clean" is true only if answer_false_claims and uncorrected_trace_false_claims are
both empty.
"""

CLAIM_REJECT_LISTS = ("answer_false_claims", "uncorrected_trace_false_claims")


def build_claims_system(function_lookup: bool) -> str:
    parts = []
    ref = _ctl2_reference()
    if ref:
        parts += ["# CTL2 Language Reference", "", ref, "", "---"]
    parts.append(_CLAIMS_ROLE)
    if function_lookup:
        parts.append(_FUNCTION_LOOKUP_NOTE)
    parts.append(_CLAIMS_SCHEMA)
    return "\n\n".join(parts)


def build_claims_user(prompt: dict, thinking: str, answer: str) -> str:
    return (f"## Task type: {prompt['task_type']}\n"
            f"## Component: {prompt['component']}\n\n"
            f"## TASK (the user's request, verbatim)\n<task>\n{prompt['user']}\n</task>\n\n"
            f"## REASONING TRACE\n<trace>\n{thinking}\n</trace>\n\n"
            f"## FINAL ANSWER\n<answer>\n{answer}\n</answer>\n\n"
            "Audit the trace and the answer for false claims. Output the JSON object only.")


def decide_claims_clean(verdict: dict) -> bool:
    """Clean only if the auditor says so AND both rejection lists are empty."""
    if verdict.get("clean") is not True:
        return False
    return not any(verdict.get(key) for key in CLAIM_REJECT_LISTS)


def judge_config(raw_eval_cfg: dict) -> dict:
    cfg = eval_harness._deep_merge(JUDGE_DEFAULTS, raw_eval_cfg.get("judge") or {})
    # The eval block is sized for the suite judge; keep this pipeline's purposes
    # on the function-lookup tool whatever the eval config says.
    lookup = dict(cfg.get("function_lookup") or {})
    lookup["purposes"] = sorted(set(lookup.get("purposes") or []) | set(JUDGE_PURPOSES) | {"selfdistill_rejudge"})
    cfg["function_lookup"] = lookup
    return cfg


class Judge:
    """One ReviewJudgeClient per worker thread (the client is synchronous and
    keeps per-instance API-capability flags)."""

    def __init__(self, cfg: dict, log_path: Optional[Path] = None):
        self._cfg = cfg
        self._local = threading.local()
        self._log_path = log_path
        self._clients: list = []
        self._lock = threading.Lock()

    def _client(self):
        client = getattr(self._local, "client", None)
        if client is None:
            from dpo_forge.review_judge import ReviewJudgeClient
            client = ReviewJudgeClient(self._cfg)
            self._local.client = client
            with self._lock:
                self._clients.append(client)
        return client

    def total_tokens(self) -> int:
        return sum(c.total_tokens for c in self._clients)

    def grade(self, prompt: dict, candidate: str, purpose: Optional[str] = None,
              reference_first: bool = True) -> dict:
        """Reference-comparison judge. {'ok', 'verdict', 'accept'} or {'ok': False, 'error'}."""
        purpose = purpose or f"selfdistill_{prompt['task_type']}"
        client = self._client()
        system = build_judge_system(prompt["task_type"], client.lookup_enabled_for(purpose))
        result = self._ask(system, build_judge_user(prompt, candidate, reference_first), purpose)
        if result["ok"]:
            result["accept"] = decide_accept(prompt["task_type"], result["verdict"])
        else:
            result["accept"] = False
        return result

    def check_claims(self, prompt: dict, thinking: str, answer: str) -> dict:
        """False-claim audit of trace + answer. {'ok', 'verdict', 'clean'} or {'ok': False, 'error'}."""
        purpose = "selfdistill_claims"
        client = self._client()
        system = build_claims_system(client.lookup_enabled_for(purpose))
        result = self._ask(system, build_claims_user(prompt, thinking, answer), purpose)
        result["clean"] = bool(result["ok"] and decide_claims_clean(result["verdict"]))
        return result

    def _ask(self, system: str, user: str, purpose: str) -> dict:
        client = self._client()
        attempts = 1 + int(self._cfg.get("max_retries", 2))
        last_err = ""
        for attempt in range(attempts):
            msg = user if attempt == 0 else user + "\n\nYour previous reply was not valid JSON. Reply with the raw JSON object only."
            try:
                raw = client._call(system, msg, purpose=purpose)
            except Exception as exc:  # noqa: BLE001 — network / API errors are retried, then recorded
                last_err = f"{type(exc).__name__}: {exc}"
                time.sleep(min(30, 5 * (attempt + 1)))
                continue
            verdict = eval_harness.parse_judge_json(raw)
            if isinstance(verdict, dict):
                return {"ok": True, "verdict": verdict, "attempts": attempt + 1}
            last_err = f"unparseable: {raw[:300]!r}"
        return {"ok": False, "error": last_err, "attempts": attempts}


# ---------------------------------------------------------------------------
# Stage: filter
# ---------------------------------------------------------------------------


# Known false CTL2 beliefs the teacher has stated (spec/validate_multifinding_
# coverage_spec.md, the belief table; the full1 audit). A deterministic
# backstop behind the claims pass, applied to the ANSWER only: a trace may state
# a belief and correct it later, which is allowed. Each pattern was checked
# against the 214 full1 records — one hit, the false claim the audit found.
# Between two keywords of a positive claim: any text without a sentence end or
# a negation ("dateAdd never mutates" is a true statement).
_GAP = r"(?:(?!\b(?:not|never|no|doesn't|does not|don't|isn't|is not|without)\b)[^\n.]){0,60}"
_CALL = r"(?:\([^()\n]*\))?`?"   # an optional argument list, so `dateAdd($in.0.d, 1L, day)` still matches
KNOWN_FALSE_BELIEFS: dict[str, re.Pattern] = {
    "dateAdd mutates its argument": re.compile(r"dateAdd" + _CALL + _GAP + r"\bmutat", re.I),
    "byte2hex takes one argument": re.compile(
        r"byte2hex" + _CALL + _GAP + r"\b(?:only|exactly) one\b|byte2hex\(byte\)`? only\b", re.I),
    "isNull() does not exist": re.compile(
        r"isNull\(?\)?`?[^\n.]{0,30}(?:does not exist|doesn't exist|is not a (?:CTL2 )?function)", re.I),
    "getWeek() is a function": re.compile(r"\bgetWeek\s*\("),
    "list/map assignment aliases": re.compile(
        r"\b(?:list|map|array)s?\b" + _GAP + r"\balias(?:es|ing|ed)?\b", re.I),
    "map appendAll does not exist": re.compile(
        r"appendAll[^\n.]{0,60}(?:does not exist|doesn't exist|unsupported|not supported|lists only)", re.I),
    "writing an unconnected port is harmless": re.compile(
        r"(?:unconnected|not connected)[^\n.]{0,80}(?:harmless|dead code|no effect|is ignored)", re.I),
    # Membership is in(x, list) or x.in(list); `x in [...]` and `x !in [...]` are
    # syntax errors (checked with the compiler). Both models keep the infix form in
    # "corrected" code (suite T41.B1, 6/6 runs). The operand shapes exclude prose
    # and interval notation ("in [0, 96]"): no false hit in the answers or traces
    # of all runs so far.
    "infix `in` operator": re.compile(
        r"\$(?:in|out)\.\w+\.\w+\s+!?in\s+(?:\[|\w+\s*\))|\b\w+\s+!?in\s+\[\s*\""),
    # A declared variable starts at its type default (a list empty, a date the
    # epoch, a number 0), never null. Both models claim otherwise in 40/40 runs of
    # suite T40 (trap T40.FP1). The contexts where null IS right are excluded below.
    "declared variables start null": re.compile(
        r"\b(?:module-level|global|declared|uninitiali[sz]ed|(?:has )?no initiali[sz]er|without an? (?:initiali[sz]er|initial value))\b"
        + _GAP + r"\b(?:defaults? to|starts?(?: out)? (?:as|at)|initiali[sz]es? to|(?:is|are) initiali[sz]ed to|begins? as)\s*`?null\b"
        r"|\b(?:CTL2 )?`?(?:date|string|integer|long|decimal|number|boolean|list|map)(?:\[\])?`? (?:variables?|lists?|maps?|globals?)"
        r" (?:defaults? to|starts? as|(?:is|are) initiali[sz]ed to) `?null\b"
        r"|\bno initiali[sz]er\b[^\n.]{0,12}(?:→|->|so|, so|means)\s*`?null\b"
        r"|`[^`\n]*;` (?:defaults? to|starts? as) `?null\b"
        r"|\b(?:is|are) `?null`? by default\b"
        r"|\bdefaults? to `?null`?(?: by default)?\b(?=[^\n]{0,40}(?:declar|initiali[sz]er|module|global))", re.I),
    # Owner rulings 2026-10-02/03 (spec/corpus_ruling_corrections_spec.md, _round2_spec.md).
    # STOP aborts the component; DataGenerator generate() must return OK or ALL.
    "STOP is a normal termination": re.compile(
        r"`?STOP`?[^\n.]{0,60}(?:normal(?:ly)? (?:termination|end|completion)|cleanly|gracefully"
        r"|(?:to )?(?:end|stop|finish)s? (?:the )?generation)", re.I),
    "generation runs until STOP": re.compile(
        r"(?:runs?|keeps? (?:going|generating)|continues?) until[^\n.]{0,40}returns? `?STOP\b", re.I),
    # Denormalizer transform() sees the group's last input record; Rollup transform()
    # and updateTransform() may read $in.0 too.
    "transform() cannot read $in.0": re.compile(
        r"\$in\.0`?[^\n.]{0,60}(?:is not (?:accessible|available|readable)|isn't (?:accessible|available)"
        r"|inaccessible|cannot be (?:read|accessed)|must not be read|(?:is )?stale)[^\n.]{0,40}\btransform\b"
        r"|\btransform\(\)`?[^\n.]{0,60}\b(?:cannot|can't|must not|MUST NOT|should not|never)\s+(?:read|access)[^\n.]{0,25}\$in\.0"
        r"|\$in\.0`?\)?[^\n.]{0,20}\b(?:(?:is|are) (?:only )?(?:accessible|available|readable) only|(?:is|are) only (?:accessible|available|readable))"
        r" (?:in|inside|within) `?(?:append|updateGroup)\(", re.I),
    # A never-assigned non-nullable output field carries its type's zero value.
    "unset output fields are null": re.compile(
        r"\b(?:unset|never[- ]assigned|unassigned|not assigned)\b[^\n.]{0,50}\bfields?\b[^\n.]{0,50}"
        r"\b(?:are|is|will be|remains?|stays?|defaults? to|come out(?: as)?)\s+`?null\b"
        r"|\bnon-?null(?:able)? (?:output )?fields?\b[^\n.]{0,60}\bwill be `?null\b", re.I),
    # Writing $out.0 in Denormalizer append() is benign (no effect), not a failure.
    "$out.0 in append() fails": re.compile(
        r"\$out\.0(?:(?!\bnot\b|n't\b|\bno\b)[^\n.]){0,80}\bappend\(\)(?:(?!\bnot\b|n't\b|\bno\b)[^\n.]){0,80}(?:NPE|NullPointer|throws|runtime (?:error|failure|exception))"
        r"|\bappend\(\)(?:(?!\bnot\b|n't\b|\bno\b)[^\n.]){0,80}\$out\.0(?:(?!\bnot\b|n't\b|\bno\b)[^\n.]){0,80}(?:NPE|NullPointer|throws|runtime (?:error|failure|exception))", re.I),
    # *OnError callbacks are valid but must not report the failed record as processed
    # without at least logging it (a silent SKIP is tolerated).
    "OnError returns OK without logging": re.compile(
        r"function\s+integer\s+\w+OnError\s*\([^)]*\)\s*\{(?:(?!printLog|printErr|raiseError)[^}])*?\breturn\s+OK\s*;", re.S),
}
# Around a match, words that make the claim a true one: a Rollup accumulator field
# unassigned in initGroup IS null, and so are declared variant/byte/cbyte values.
# A quoted `x in [...]` followed by "is not valid CTL2 syntax" is a correct finding
# that flags the construct, not a use of it.
_BELIEF_TRUE_CONTEXT: dict[str, re.Pattern] = {
    "declared variables start null": re.compile(
        r"accumulator|\bacc\.\w|\bgroup\.\w|variant|\bc?byte\b|lookup|map key|missing key", re.I),
    "infix `in` operator": re.compile(
        r"not (?:valid|allowed|supported|a CTL2)|invalid|no infix|not an? (?:infix )?operator|"
        r"(?:does not|doesn't|won't|will not) (?:compile|parse)|syntax error|parser error", re.I),
    "STOP is a normal termination": re.compile(
        r"(?i:\babort|\bnot (?:a )?normal|not (?:allowed|valid)|do not use it|don't use it)|\bERROR\b"),
    "OnError returns OK without logging": re.compile(r"without logging|silently|suppress|no log", re.I),
    # Unassigned Rollup accumulator fields and nullable output fields ARE null.
    "unset output fields are null": re.compile(r"accumulator|initGroup|\bacc\.\w|(?<!non-)(?<!non )\bnullable\b", re.I),
}
# A negation just before the match, in the same clause: "`=` does not alias the
# list" is a correct statement. Punctuation ends the clause, so a heading such as
# "not initialised** - a module-level date defaults to null" is still a claim.
_NEGATION_RE = re.compile(r"\b(?:not|no|never|doesn't|does not|don't|isn't|is not|without|rather than)\b[^\n.*:;–—-]{0,25}$", re.I)


def belief_hits(text: str) -> list[str]:
    """Names of the known false beliefs `text` states. A match right after a
    negation ("`=` does not alias the list"), or in a context where the claim is
    true (_BELIEF_TRUE_CONTEXT), is skipped."""
    hits = []
    text = text or ""
    for name, pattern in KNOWN_FALSE_BELIEFS.items():
        true_context = _BELIEF_TRUE_CONTEXT.get(name)
        for m in pattern.finditer(text):
            if _NEGATION_RE.search(text[max(0, m.start() - 40):m.start()]):
                continue
            if true_context and true_context.search(text[max(0, m.start() - 200):m.end() + 60]):
                continue
            hits.append(name)
            break
    return hits


def evaluate_sample(prompt: dict, sample: dict, mcp_cfg: Optional[dict], judge: Judge,
                    synth: Optional[MetadataSynth] = None) -> dict:
    """Checks cheapest first; the first failing check is recorded as the
    rejection stage."""
    row = {"prompt_id": sample["prompt_id"], "sample_idx": sample["sample_idx"], "task_type": prompt["task_type"],
           "thinking_words": len((sample.get("thinking") or "").split())}

    def reject(stage: str, reason: str, **extra) -> dict:
        return {**row, "accepted": False, "rejected_at": stage, "reason": reason, **extra}

    if sample.get("hit_cap"):
        return reject("format", "hit_cap")
    if not sample.get("think_closed"):
        return reject("format", "think_not_closed")
    fmt = format_check(prompt, sample.get("answer", ""))
    if fmt:
        return reject("format", fmt)
    lib_reason, unknown = library_check(prompt, sample["answer"])
    if lib_reason:
        return reject("library", lib_reason, unknown_functions=unknown)
    compile_result = None
    if mcp_cfg and prompt["task_type"] != "validate":
        compile_result = compile_check(prompt, sample["answer"], mcp_cfg, synth)
        if compile_result["status"] == "fail":
            return reject("compile", "compile_error", compile=compile_result)
    row["compile"] = compile_result or {"status": "not_run"}
    graded = judge.grade(prompt, sample["answer"])
    if not graded["ok"]:
        return reject("judge", "judge_error", judge_error=graded["error"], compile=row["compile"])
    row["judge"] = graded["verdict"]
    if not graded["accept"]:
        return reject("judge", "judge_rejected", judge=graded["verdict"], compile=row["compile"])
    # Second pass: only a judge-accepted sample can become training data.
    claims = judge.check_claims(prompt, sample.get("thinking", ""), sample["answer"])
    if not claims["ok"]:
        return reject("claims", "claims_error", claims_error=claims["error"], judge=row["judge"],
                      compile=row["compile"])
    row["claims"] = claims["verdict"]
    if not claims["clean"]:
        return reject("claims", "false_claim", claims=claims["verdict"], judge=row["judge"],
                      compile=row["compile"])
    beliefs = belief_hits(sample["answer"])
    if beliefs:
        return reject("beliefs", "known_false_belief", beliefs=beliefs, judge=row["judge"],
                      claims=row["claims"], compile=row["compile"])
    return {**row, "accepted": True, "rejected_at": None, "reason": None}


# Rows with these reasons were never really decided and are retried on resume.
RETRYABLE_REASONS = ("judge_error", "claims_error")


def load_judged(out: Path) -> dict[tuple[str, int], dict]:
    """judged.jsonl keyed by (prompt_id, sample_idx); last write wins."""
    return {(r["prompt_id"], r["sample_idx"]): r for r in read_jsonl(out / "judged.jsonl")}


def cmd_filter(args) -> int:
    out = run_dir(args)
    prompts = {p["prompt_id"]: p for p in load_prompts(out)}
    samples = load_samples(out)
    judged_path = out / "judged.jsonl"
    # A judge/claims API error is retried on resume; every other verdict is final.
    done = {key for key, r in load_judged(out).items() if r.get("reason") not in RETRYABLE_REASONS}
    todo = [s for key, s in sorted(samples.items()) if key not in done and s["prompt_id"] in prompts]
    if args.limit:
        todo = todo[:args.limit]
    print(f"{len(samples)} samples, {len(done)} already judged, {len(todo)} to go")
    if not todo:
        return 0

    mcp_cfg = None
    if args.no_compile:
        print("  --no-compile: compile check disabled for this run")
    else:
        mcp_cfg = mcp_config(args)
        probe_mcp(mcp_cfg)
    _cfg, raw = load_eval_config(args.eval_config)
    judge = Judge(judge_config(raw))
    synth = MetadataSynth(out, judge, mcp_cfg) if mcp_cfg else None
    print(f"  judge: {judge._cfg.get('model')} (effort {judge._cfg.get('reasoning_effort')}), "
          f"{args.judge_workers} workers")

    counts: Counter = Counter()
    mcp_failure: Optional[str] = None
    with ThreadPoolExecutor(max_workers=args.judge_workers) as pool:
        futures = {pool.submit(evaluate_sample, prompts[s["prompt_id"]], s, mcp_cfg, judge, synth): s for s in todo}
        for n, fut in enumerate(as_completed(futures), 1):
            s = futures[fut]
            try:
                row = fut.result()
            except McpUnavailable as exc:
                mcp_failure = str(exc)
                pool.shutdown(wait=False, cancel_futures=True)
                break
            row["judged_at"] = now_iso()
            append_jsonl(judged_path, [row])
            counts["accepted" if row["accepted"] else f"rejected:{row['rejected_at']}:{row['reason']}"] += 1
            print(f"  [{n}/{len(todo)}] {s['task_type']:8s} {s['prompt_id']}#{s['sample_idx']} "
                  f"{'ACCEPT' if row['accepted'] else 'reject ' + row['rejected_at'] + ':' + row['reason']}")
    print(f"  results: {dict(counts)}   judge tokens: {judge.total_tokens():,}")
    if mcp_failure:
        print(f"ERROR: ctl_validate MCP failed mid-run ({mcp_failure}). Nothing was recorded for the "
              f"affected samples; restart the server and rerun `filter` to resume.")
        return 2
    return 0


# ---------------------------------------------------------------------------
# Stage: rejudge
# ---------------------------------------------------------------------------


def cmd_rejudge(args) -> int:
    """Independent second judge pass on a random subset, balanced between
    accepted and judge-rejected samples, with reference and candidate in
    swapped order. Measures judge reliability (pilot question 3)."""
    out = run_dir(args)
    prompts = {p["prompt_id"]: p for p in load_prompts(out)}
    samples = load_samples(out)
    # Measures the reference judge alone: a sample the claims pass rejected
    # was still a reference-judge accept.
    judged = [r for r in load_judged(out).values() if r.get("rejected_at") in (None, "judge", "claims")
              and r.get("reason") != "judge_error"]
    for r in judged:
        r["judge_accept"] = r["accepted"] or r["rejected_at"] == "claims"
    rng = random.Random(args.seed)
    acc = [r for r in judged if r["judge_accept"]]
    rej = [r for r in judged if not r["judge_accept"]]
    rng.shuffle(acc)
    rng.shuffle(rej)
    half = args.n // 2
    pick = acc[:half] + rej[:args.n - half]
    if len(pick) < args.n:  # backfill from whichever side has more
        rest = acc[half:] + rej[args.n - half:]
        pick += rest[:args.n - len(pick)]
    _cfg, raw = load_eval_config(args.eval_config)
    judge = Judge(judge_config(raw))
    rows = []
    for r in pick:
        s = samples[(r["prompt_id"], r["sample_idx"])]
        g = judge.grade(prompts[r["prompt_id"]], s["answer"], purpose="selfdistill_rejudge", reference_first=False)
        rows.append({"prompt_id": r["prompt_id"], "sample_idx": r["sample_idx"], "task_type": r["task_type"],
                     "first_accept": r["judge_accept"], "second_accept": g["accept"], "second_ok": g["ok"],
                     "second_verdict": g.get("verdict"), "second_error": g.get("error"),
                     "first_verdict": r.get("judge")})
        print(f"  {r['task_type']:8s} {r['prompt_id']}#{r['sample_idx']}: first={r['judge_accept']} second={g['accept']}")
    (out / "rejudge.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows),
                                       encoding="utf-8")
    ok = [x for x in rows if x["second_ok"]]
    agree = sum(1 for x in ok if x["first_accept"] == x["second_accept"])
    by_task: dict[str, Counter] = defaultdict(Counter)
    for x in ok:
        by_task[x["task_type"]]["agree" if x["first_accept"] == x["second_accept"] else "disagree"] += 1
    report = {
        "n": len(rows),
        "judged_ok": len(ok),
        "agreement": round(agree / len(ok), 3) if ok else None,
        "accept_then_reject": sum(1 for x in ok if x["first_accept"] and not x["second_accept"]),
        "reject_then_accept": sum(1 for x in ok if not x["first_accept"] and x["second_accept"]),
        "by_task": {k: dict(v) for k, v in by_task.items()},
    }
    write_json(out / "rejudge_report.json", report)
    print(f"Agreement {report['agreement']} on {len(ok)} decisions; accept->reject "
          f"{report['accept_then_reject']}, reject->accept {report['reject_then_accept']}")
    return 0


# ---------------------------------------------------------------------------
# Stage: assemble
# ---------------------------------------------------------------------------

_WAIT_RE = re.compile(r"\bwait\b", re.IGNORECASE)
_LET_ME_RE = re.compile(r"\blet me\b", re.IGNORECASE)
_CHECK_RE = re.compile(r"\b(?:double[- ]check|check|verify|verif(?:y|ied|ication))\b", re.IGNORECASE)


def trace_stats(traces: list[str]) -> dict:
    if not traces:
        return {"n": 0}
    words = [len(t.split()) for t in traces]
    return {
        "n": len(traces),
        "median_words": statistics.median(words),
        "p10_words": sorted(words)[max(0, math.floor(0.1 * (len(words) - 1)))],
        "p90_words": sorted(words)[math.ceil(0.9 * (len(words) - 1))],
        "wait_rate": round(sum(1 for t in traces if _WAIT_RE.search(t)) / len(traces), 3),
        "let_me_rate": round(sum(1 for t in traces if _LET_ME_RE.search(t)) / len(traces), 3),
        "check_verify_rate": round(sum(1 for t in traces if _CHECK_RE.search(t)) / len(traces), 3),
    }


def pick_accepted(accepted: list[dict], rng: random.Random) -> dict:
    """Uniform random choice. Never the shortest: preferring short traces is a
    length-compression pressure (findings §3.13)."""
    return rng.choice(sorted(accepted, key=lambda s: s["sample_idx"]))


def split_label(accepted: int, k: int) -> str:
    if accepted == 0:
        return "0/k"
    return "k/k" if accepted == k else "1..k-1/k"


def cmd_assemble(args) -> int:
    out = run_dir(args)
    prompts = load_prompts(out)
    samples = load_samples(out)
    judged = load_judged(out)
    # Samples rejected after filtering: a manual audit (audit_rejects.json) and
    # the known-false-belief backstop, for runs filtered before it existed.
    # They leave the accepted set, so another accepted sample of the same
    # prompt can be picked instead.
    audit_rejects = {(r["prompt_id"], r["sample_idx"]): r["reason"]
                     for r in (json.loads((out / "audit_rejects.json").read_text())
                               if (out / "audit_rejects.json").exists() else [])}
    samples_for_scan = load_samples(out)
    post_rejects: dict[tuple[str, int], str] = {}
    for key, r in judged.items():
        if not r["accepted"]:
            continue
        if key in audit_rejects:
            post_rejects[key] = "audit:" + audit_rejects[key]
        elif key in samples_for_scan and belief_hits(samples_for_scan[key]["answer"]):
            post_rejects[key] = "beliefs:" + ",".join(belief_hits(samples_for_scan[key]["answer"]))
    judged = {k: ({**r, "accepted": False, "rejected_at": "post_filter", "reason": post_rejects[k]}
                  if k in post_rejects else r) for k, r in judged.items()}
    by_prompt_samples: dict[str, list[dict]] = defaultdict(list)
    for (pid, _j), s in samples.items():
        by_prompt_samples[pid].append(s)

    pending = [p["prompt_id"] for p in prompts
               if not by_prompt_samples.get(p["prompt_id"])
               or any((s["prompt_id"], s["sample_idx"]) not in judged for s in by_prompt_samples[p["prompt_id"]])]
    if pending and not args.allow_incomplete:
        print(f"ERROR: {len(pending)} prompts are not fully sampled and judged "
              f"(e.g. {pending[:3]}); finish `sample`/`filter` or pass --allow-incomplete")
        return 1

    kept: list[dict] = []
    gaps: list[dict] = []
    over_cutoff: list[dict] = []
    splits: dict[str, Counter] = defaultdict(Counter)
    accept_rates: dict[str, Counter] = defaultdict(Counter)
    reject_reasons: dict[str, Counter] = defaultdict(Counter)
    compile_status: dict[str, Counter] = defaultdict(Counter)
    kept_traces: dict[str, list[str]] = defaultdict(list)
    valid_traces: dict[str, list[str]] = defaultdict(list)

    for p in prompts:
        pid, task = p["prompt_id"], p["task_type"]
        ss = sorted(by_prompt_samples.get(pid, []), key=lambda s: s["sample_idx"])
        rows = [judged.get((pid, s["sample_idx"])) for s in ss]
        if not ss or any(r is None for r in rows):
            continue
        k = len(ss)
        accepted = [s for s, r in zip(ss, rows) if r["accepted"]]
        for s, r in zip(ss, rows):
            accept_rates[task]["accepted" if r["accepted"] else "rejected"] += 1
            if not r["accepted"]:
                reject_reasons[task][f"{r['rejected_at']}:{r['reason']}"] += 1
            if r["rejected_at"] != "format":
                valid_traces[task].append(s["thinking"])
            if (r.get("compile") or {}).get("status"):
                compile_status[task][compile_label(r["compile"])] += 1
        splits[task][split_label(len(accepted), k)] += 1
        if not accepted:
            gaps.append({
                "prompt_id": pid, "task_type": task, "component": p["component"],
                "source_file": p["source_file"], "record_id": p["record_id"],
                "reject_reasons": Counter(f"{r['rejected_at']}:{r['reason']}" for r in rows),
                "user": p["user"],
            })
            continue
        rng = random.Random(f"{args.seed}:{pid}")
        choice = pick_accepted(accepted, rng)
        total_tokens = choice["prompt_tokens"] + choice["new_tokens"] + CUTOFF_MARGIN_TOKENS
        if total_tokens > args.cutoff:
            over_cutoff.append({"prompt_id": pid, "task_type": task, "tokens": total_tokens})
            continue
        verdict = judged[(pid, choice["sample_idx"])]
        kept_traces[task].append(choice["thinking"])
        kept.append({
            "id": f"selfdistill_{pid}_{choice['sample_idx']}",
            "prompt_id": pid,
            "messages": [
                {"role": "system", "content": choice["system_prompt"]},
                {"role": "user", "content": p["user"]},
                {"role": "assistant", "content": choice["answer"], "reasoning_content": choice["thinking"]},
            ],
            "task_type": task,
            "component": p["component"],
            "source_file": p["source_file"],
            "source_index": p["source_index"],
            "source_id": p["source_id"],
            "teacher_model": choice["teacher_model"],
            "sample_idx": choice["sample_idx"],
            "sampling": {**choice["sampling"], "seed": choice["seed"]},
            "accepted_of_k": f"{len(accepted)}/{k}",
            "judge_verdict": verdict.get("judge"),
            "claims_verdict": verdict.get("claims"),
            "compile": verdict.get("compile"),
            "tokens": total_tokens,
            "reused_from": choice.get("reused_from"),
            "created": now_iso(),
        })

    records_path, train_path = output_paths(out, args.run)
    write_json(records_path, kept)
    # The tagged file goes through convert_think's own transform — the path
    # that produces LlamaFactory's exact thought_words spelling. <think> tags
    # are never written here.
    import convert_think
    tagged, n_reasoning = convert_think.transform_records(copy.deepcopy(kept), only_reasoning=True)
    write_json(train_path, tagged, ensure_ascii=True)
    write_json(out / "gaps.json", gaps)

    audit_rng = random.Random(f"{args.seed}:audit")
    audit = audit_rng.sample(kept, math.ceil(0.1 * len(kept))) if kept else []
    ref_by_id = {p["prompt_id"]: p["reference"] for p in prompts}
    audit_path = out / "audit_sample.jsonl"
    # A completed audit is a record of what was read; re-assembling (say, after
    # an audit reject) must not replace it with a fresh, unaudited sample.
    if any(r.get("audited") for r in read_jsonl(audit_path)):
        audit = read_jsonl(audit_path)
        print(f"  keeping the audited {rel(audit_path)} ({len(audit)} records)")
    else:
        audit_path.write_text("".join(json.dumps({
            "id": r["id"], "task_type": r["task_type"], "component": r["component"],
            "user": r["messages"][1]["content"], "thinking": r["messages"][2]["reasoning_content"],
            "answer": r["messages"][2]["content"], "reference": ref_by_id[r["prompt_id"]],
            "audit_false_claim": None, "audit_note": "",
        }, ensure_ascii=False) + "\n" for r in audit), encoding="utf-8")

    stats = {}
    for path in sorted(out.glob("sample_stats.shard*.json")):
        for task, t in json.loads(path.read_text()).get("by_task", {}).items():
            agg = stats.setdefault(task, Counter())
            agg.update(t)
    throughput = {task: {
        "prompts": t["prompts"],
        "mean_s_per_prompt": round(t["seconds"] / t["prompts"], 1) if t["prompts"] else None,
        "tokens_per_s": round(t["new_tokens"] / t["seconds"], 1) if t["seconds"] else None,
        "hit_cap": t["hit_cap"],
    } for task, t in stats.items()}

    report = {
        "created": now_iso(),
        "prompts": len(prompts),
        "pending_prompts": len(pending),
        "kept": len(kept),
        "kept_by_task": dict(Counter(r["task_type"] for r in kept)),
        "kept_from_reused_samples": sum(1 for r in kept if r.get("reused_from")),
        "post_filter_rejects": {f"{k[0]}#{k[1]}": v for k, v in sorted(post_rejects.items())},
        "tagged_records": len(tagged),
        "tagged_with_reasoning": n_reasoning,
        "dropped_over_cutoff": over_cutoff,
        "cutoff": args.cutoff,
        "gaps_by_task": dict(Counter(g["task_type"] for g in gaps)),
        "split_by_task": {k: dict(v) for k, v in splits.items()},
        "sample_accept_rate_by_task": {
            k: round(v["accepted"] / (v["accepted"] + v["rejected"]), 3) for k, v in accept_rates.items()},
        "reject_reasons_by_task": {k: dict(v.most_common()) for k, v in reject_reasons.items()},
        "compile_status_by_task": {k: dict(v) for k, v in compile_status.items()},
        "throughput_by_task": throughput,
        "trace_stats_kept": {k: trace_stats(v) for k, v in kept_traces.items()},
        "trace_stats_format_valid": {k: trace_stats(v) for k, v in valid_traces.items()},
        "teacher_reference_3_13": {"fix_median_words": 1480, "wait_rate": 0.44, "let_me_rate": 0.89},
        "audit_sample": len(audit),
        # Kept traces whose false claims the trace itself corrected (allowed, but worth watching).
        "kept_with_corrected_trace_claims": sum(
            1 for r in kept if (r.get("claims_verdict") or {}).get("corrected_trace_false_claims")),
        "format_instruction_added": dict(Counter(
            str(p.get("format_instruction_added", False)) for p in prompts if p["task_type"] == "validate")),
    }
    rejudge_report = out / "rejudge_report.json"
    if rejudge_report.exists():
        report["rejudge"] = json.loads(rejudge_report.read_text())
    write_json(out / "report.json", report)
    (out / "report.md").write_text(render_report_md(args.run, report), encoding="utf-8")
    print(f"Kept {len(kept)} records")
    print(f"  training file (register this): {rel(train_path)}")
    print(f"  records with provenance:       {rel(records_path)}")
    print(f"  split: {report['split_by_task']}")
    print(f"  gaps: {report['gaps_by_task']}  over cutoff: {len(over_cutoff)}  audit: {len(audit)}")
    print(f"  report: {rel(out / 'report.md')}")
    return 0


def output_paths(out: Path, run: str) -> tuple[Path, Path]:
    """(records file, training file) — the two final products of a run."""
    return out / f"selfdistill_{run}_records.json", out / f"selfdistill_{run}_train.json"


def render_report_md(run: str, r: dict) -> str:
    lines = [f"# Self-distillation run `{run}`", "", f"Created {r['created']}.", "",
             f"**Training file:** `selfdistill_{run}_train.json` — register this one as the phase-3 dataset.",
             f"**Records with provenance:** `selfdistill_{run}_records.json` — the same records before tagging.", ""]
    lines += [f"- Prompts: {r['prompts']} (pending: {r['pending_prompts']})",
              f"- Kept: {r['kept']} {r['kept_by_task']}; tagged records: {r['tagged_records']}",
              f"- Gaps (0/k): {r['gaps_by_task']}",
              f"- Dropped over cutoff {r['cutoff']}: {len(r['dropped_over_cutoff'])}",
              f"- Audit sample: {r['audit_sample']} records in `audit_sample.jsonl`",
              f"- Kept traces with self-corrected false claims: {r['kept_with_corrected_trace_claims']}",
              f"- Validate prompts with the format instruction appended: {r['format_instruction_added']}", ""]
    lines += ["## Acceptance", "", "| task | sample accept rate | k/k | 1..k-1/k | 0/k |", "|---|---|---|---|---|"]
    for task in TASK_TYPES:
        s = r["split_by_task"].get(task, {})
        lines.append(f"| {task} | {r['sample_accept_rate_by_task'].get(task, '-')} | {s.get('k/k', 0)} | "
                     f"{s.get('1..k-1/k', 0)} | {s.get('0/k', 0)} |")
    lines += ["", "## Rejection reasons", ""]
    for task, reasons in r["reject_reasons_by_task"].items():
        lines.append(f"- **{task}**: " + ", ".join(f"{k} {v}" for k, v in reasons.items()))
    lines += ["", "## Compile status", ""]
    for task, st in r["compile_status_by_task"].items():
        lines.append(f"- **{task}**: " + ", ".join(f"{k} {v}" for k, v in st.items()))
    lines += ["", "## Throughput", "", "| task | prompts | s / prompt (k batched) | tokens/s | hit cap |",
              "|---|---|---|---|---|"]
    for task, t in r["throughput_by_task"].items():
        lines.append(f"| {task} | {t['prompts']} | {t['mean_s_per_prompt']} | {t['tokens_per_s']} | {t['hit_cap']} |")
    lines += ["", "## Thinking distribution (kept vs all format-valid samples)", "",
              "| task | set | n | median words | p10 | p90 | wait | let me | check/verify |",
              "|---|---|---|---|---|---|---|---|---|"]
    for task in TASK_TYPES:
        for label, key in (("kept", "trace_stats_kept"), ("format-valid", "trace_stats_format_valid")):
            s = r[key].get(task)
            if s and s.get("n"):
                lines.append(f"| {task} | {label} | {s['n']} | {s['median_words']} | {s['p10_words']} | "
                             f"{s['p90_words']} | {s['wait_rate']} | {s['let_me_rate']} | {s['check_verify_rate']} |")
    t = r["teacher_reference_3_13"]
    lines += ["", f"Teacher eval-time reference (§3.13): fix median ~{t['fix_median_words']} words, "
                  f"\"wait\" ~{t['wait_rate']:.0%}, \"let me\" ~{t['let_me_rate']:.0%}.", ""]
    if "rejudge" in r:
        rj = r["rejudge"]
        lines += ["## Judge reliability (rejudge)", "",
                  f"Agreement {rj['agreement']} on {rj['judged_ok']} decisions; accept→reject "
                  f"{rj['accept_then_reject']}, reject→accept {rj['reject_then_accept']}.", ""]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--run", required=True, help="run name; files go to <runs-dir>/<run>/")
    common.add_argument("--runs-dir", default=str(RUNS_DIR))
    common.add_argument("--eval-config", type=Path, default=DEFAULT_EVAL_CONFIG,
                        help="eval config giving the teacher, template, system prompts, sampling and judge")
    common.add_argument("--seed", type=int, default=0)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("select", parents=[common], help="choose prompts")
    p.add_argument("--pilot", action="store_true",
                   help="stratified pilot (PILOT_PLAN): every fix tier, validate group and generate component")
    p.add_argument("--reuse-from", default=None,
                   help="comma-separated earlier runs whose samples to reuse where teacher, prompt text, "
                        "system prompt, sampling and seed all match (full selection prefers those prompts)")
    p.add_argument("--exclude-runs", default=None,
                   help="comma-separated earlier runs whose prompts are removed from the pool before selection "
                        "(to send a new teacher only to prompts no run has sampled)")
    p.add_argument("--k", type=int, default=DEFAULT_K, help="samples per prompt the reused prompts must have")
    p.add_argument("--plan", default=None,
                   help="targeted pilot: <group>:<count>,... using pilot groups (e.g. validate_pass_warn:15)")
    p.add_argument("--overwrite", action="store_true")
    p.set_defaults(func=cmd_select)

    compile_args = argparse.ArgumentParser(add_help=False)
    compile_args.add_argument("--no-compile", action="store_true",
                              help="skip the ctl_validate MCP compile check (on by default)")
    compile_args.add_argument("--mcp-url", default=None, help=f"default {MCP_DEFAULTS['url']}")

    p = sub.add_parser("check-refs", parents=[common, compile_args], help="run the cheap checks on reference answers")
    p.add_argument("--workers", type=int, default=6, help="parallel metadata conversions")
    p.set_defaults(func=cmd_check_refs)

    p = sub.add_parser("sample", parents=[common], help="sample k completions per prompt")
    p.add_argument("--shard", default="0/1", help="i/n: this process takes prompts with index %% n == i")
    p.add_argument("--k", type=int, default=DEFAULT_K)
    p.add_argument("--max-new-tokens", type=int, default=None, help="override (smoke tests only)")
    p.add_argument("--limit", type=int, default=None, help="first N prompts of this shard")
    p.set_defaults(func=cmd_sample)

    p = sub.add_parser("filter", parents=[common, compile_args], help="format / library / compile / judge")
    p.add_argument("--judge-workers", type=int, default=4)
    p.add_argument("--limit", type=int, default=None)
    p.set_defaults(func=cmd_filter)

    p = sub.add_parser("rejudge", parents=[common], help="independent second judge pass")
    p.add_argument("--n", type=int, default=20)
    p.set_defaults(func=cmd_rejudge)

    p = sub.add_parser("assemble", parents=[common], help="build the kept set, tagged file and report")
    p.add_argument("--cutoff", type=int, default=DEFAULT_CUTOFF)
    p.add_argument("--allow-incomplete", action="store_true")
    p.set_defaults(func=cmd_assemble)
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
