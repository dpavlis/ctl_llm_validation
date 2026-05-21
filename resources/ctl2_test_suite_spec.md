# CTL2 Model Evaluation — Test Suite Specification

## Purpose

This document specifies how to execute the CTL2 model evaluation test suite and how to interpret results. The suite evaluates a CTL2 fine-tuned LLM across 8 standard tests covering code generation and code validation. A second LLM acts as a judge, scoring each response against a structured rubric.

The test definitions live in `ctl2_test_suite.json`.

---

## Architecture

```
ctl2_test_suite.json
        │
        ▼
┌───────────────────┐     user_message + system_prompt     ┌─────────────────┐
│   Test Runner     │ ──────────────────────────────────►  │  Model Under    │
│   (Python script) │                                       │  Test (MUT)     │
│                   │ ◄──────────────────────────────────  │  Ollama/OpenAI  │
└───────────────────┘         model response                └─────────────────┘
        │
        │  test definition + model response
        ▼
┌───────────────────┐                                       ┌─────────────────┐
│   Judge Caller    │ ──────────────────────────────────►  │  Judge LLM      │
│                   │                                       │  (Claude/GPT)   │
│                   │ ◄──────────────────────────────────  │                 │
└───────────────────┘      structured score JSON            └─────────────────┘
        │
        ▼
  results_<model>_<timestamp>.json
  summary_<model>_<timestamp>.md
```

---

## Test Suite File Structure

`ctl2_test_suite.json` contains:

```
{
  "version": "1.0",
  "description": "...",
  "judge_system_prompt": "...",     # System prompt for the judge LLM
  "judge_instructions": "...",      # Evaluation protocol text
  "tests": [ ... ]                  # Array of 8 test objects
}
```

Each test object:

```
{
  "test_id":       "T1",
  "type":          "generate" | "validate",
  "component":     "Reformat" | "Denormalizer" | "Rollup" | "",
  "temperature":   0.1 | 0.05,
  "system_prompt": "...",           # Exact system prompt for the MUT
  "user_message":  "...",           # Complete user message (description + XML metadata)

  # For generate tests:
  "rubric": {
    "required":  [ { "id", "check", "rationale" }, ... ],
    "forbidden": [ { "id", "check", "rationale" }, ... ],
    "optional":  [ { "id", "check", "rationale" }, ... ],
    "scoring":   { "PASS": "...", "PARTIAL": "...", "FAIL": "..." }
  },

  # For validate tests:
  "bugs": [ { "id", "code", "description", "correct_fix", "severity" }, ... ],
  "rubric": {
    "required_findings":      ["T4.B1", ...],
    "fix_quality":            { "T4.B1": "...", ... },   # present in T4 only
    "false_positive_traps":   [ { "id", "trap", "reality" }, ... ],  # T7 only
    "verdict_expected":       "PASS" | "FAIL",
    "scoring":                { "PASS": "...", "PARTIAL": "...", "FAIL": "..." }
  }
}
```

---

## Tests Overview

| ID | Type | Component | Temp | Key challenge |
|----|------|-----------|------|---------------|
| T1 | generate | Reformat | 0.1 | Wildcard copy, `nvl()` on nullable, `today()` |
| T2 | generate | Denormalizer | 0.1 | Module-level vars only; `$out.0` forbidden in `append()`/`clean()` |
| T3 | generate | Reformat (variant) | 0.1 | `cast()` on variant fields; no `parseJson()` wrapper |
| T4 | validate | — | 0.05 | 4 deliberate bugs; fix for `cast()` must be direct assignment, not `double2decimal()` |
| T5 | validate | — | 0.05 | 5 subtle bugs; `string+null` and `~=` semantics are the hardest |
| T6 | generate | Rollup | 0.1 | Full lifecycle: `initGroup`/`updateGroup`/`finishGroup`/`transform(counter, acc)` |
| T7 | validate | — | 0.05 | Correct code — must return PASS; `isBlank()` and `split("\\|")` must not be false-flagged |
| T8 | generate | Reformat | 0.1 | Date literals `2020-01-01` inline — `str2date()` and `createDate()` forbidden |

---

## Execution Protocol

### Step 1 — Call the Model Under Test (MUT)

For each test:

1. Read `test["system_prompt"]` and `test["user_message"]` from the JSON.
2. Send as a standard chat completion:
   - `messages[0]`: `role=system`, `content=test["system_prompt"]`
   - `messages[1]`: `role=user`, `content=test["user_message"]`
3. Use `temperature=test["temperature"]` (0.1 for generate, 0.05 for validate).
4. Record the raw response text.

**MUT endpoint:** Configurable — Ollama-compatible (`/v1/chat/completions`) or OpenAI API.

**Timeout:** 240 seconds per call. Retry once on timeout before marking as ERROR.

**Repetitions:** Run each test `N` times (configurable, default `N=1`). For statistical scoring use `N=3`.

---

### Step 2 — Call the Judge LLM

For each MUT response, call the judge with:

- **System prompt:** `suite["judge_system_prompt"]`
- **User message:** Build from the template below

```
## Test Definition

Test ID: {test_id}
Type: {type}
Component: {component}

### System prompt sent to model:
{system_prompt}

### User message sent to model:
{user_message}

### Rubric:
{rubric_as_yaml_or_json}

---

## Model Response to Evaluate:

{mut_response}

---

## Instructions:

{suite["judge_instructions"]}

Respond with a JSON object exactly matching this schema:
{
  "test_id": "...",
  "verdict": "PASS" | "PARTIAL" | "FAIL" | "ERROR",
  "score": "N/M",
  "findings": [
    { "id": "T1.1", "status": "PRESENT" | "MISSING" | "WRONG", "note": "..." }
  ],
  "false_positives_triggered": [
    { "id": "T7.FP1", "triggered": true | false, "note": "..." }
  ],
  "forbidden_present": [
    { "id": "T1.F1", "present": true | false, "note": "..." }
  ],
  "notes": "brief overall justification"
}
```

**Judge model:** Configurable. Recommended: `claude-opus-4` or `gpt-4o`. Must be a strong reasoning model.

**Judge temperature:** 0.0 — deterministic scoring.

---

### Step 3 — Parse and Store Results

The judge response must be valid JSON matching the schema above. If parsing fails:
- Retry the judge call once with an explicit "respond with valid JSON only" reminder.
- If still invalid, mark the result as `"verdict": "ERROR"`.

Store each result in a results array. Write to `results_<model_name>_<timestamp>.json`.

---

## Scoring

### Per-test scoring

| Verdict | Meaning |
|---------|---------|
| `PASS` | All required items present/caught, no forbidden items, correct fixes |
| `PARTIAL` | Most requirements met but with gaps (missing items, wrong fixes) |
| `FAIL` | Critical failures: wrong lifecycle, forbidden functions used, wrong verdict on validate test |
| `ERROR` | MUT timeout, MUT API error, or judge JSON parse failure after retry |

### Numeric score per test

Compute from judge findings:

```
score = (items with status PRESENT or CAUGHT) / (total required items)
```

Subtract penalties:
- Each forbidden item present: `-0.2`
- Each false-positive trap triggered (T7): `-0.25`
- Wrong fix quality on critical items (T4.B2 `cast()` fix): `-0.1`

Clamp to `[0.0, 1.0]`.

### Suite-level scoring

```
suite_score = mean(per_test_scores)

generate_score = mean(T1, T2, T3, T6, T8)
validate_score = mean(T4, T5, T7)
```

### Critical failures (automatic FAIL regardless of score)

These override the numeric score:

| Test | Critical failure condition |
|------|---------------------------|
| T2 | `$out.0` accessed in `append()` or `clean()` |
| T4 | Suggests `double2decimal()` or `convert()` as fix (hallucinated functions) |
| T5 | Inverts `~=` and `?=` definitions (says `~=` is contains match) |
| T6 | Generates single `transform()` with no accumulator parameter (Reformat pattern) |
| T7 | Returns FAIL verdict on correct code |
| T8 | Uses `str2date()` or `createDate()` for both date boundaries |

---

## Configuration

The script should accept a config file or CLI arguments:

```yaml
# config.yaml

# Model under test
mut:
  base_url: "http://localhost:11434/v1"   # Ollama or OpenAI-compatible
  model: "qwen3.5-9b-ctl3"
  api_key: "ollama"                       # "ollama" for local, real key for OpenAI

# Judge LLM
judge:
  provider: "anthropic"                   # "anthropic" | "openai"
  model: "claude-opus-4-20250514"
  api_key: "${ANTHROPIC_API_KEY}"

# Execution
runs_per_test: 1                          # Repeat each test N times
timeout_seconds: 240
output_dir: "./results"

# Test selection (optional — omit to run all)
test_ids: ["T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8"]
```

---

## Output Files

### `results_<model>_<timestamp>.json`

```json
{
  "model": "qwen3.5-9b-ctl3",
  "timestamp": "2025-05-16T14:30:00Z",
  "suite_score": 0.82,
  "generate_score": 0.88,
  "validate_score": 0.73,
  "tests": [
    {
      "test_id": "T1",
      "run": 1,
      "mut_response": "...",
      "judge_result": {
        "verdict": "PASS",
        "score": "5/5",
        "findings": [ ... ],
        "notes": "..."
      },
      "numeric_score": 1.0,
      "critical_failure": false,
      "duration_seconds": 12.4
    },
    ...
  ]
}
```

### `summary_<model>_<timestamp>.md`

Human-readable summary table:

```
Model: qwen3.5-9b-ctl3
Run:   2025-05-16 14:30

| Test | Type     | Component   | Verdict | Score | Critical |
|------|----------|-------------|---------|-------|----------|
| T1   | generate | Reformat    | PASS    | 5/5   |          |
| T2   | generate | Denormalizer| PASS    | 5/5   |          |
| T3   | generate | Reformat    | PARTIAL | 3/4   |          |
| T4   | validate | —           | PASS    | 4/4   |          |
| T5   | validate | —           | PARTIAL | 3/5   |          |
| T6   | generate | Rollup      | PASS    | 6/6   |          |
| T7   | validate | —           | PASS    | 0FP   |          |
| T8   | generate | Reformat    | PASS    | 5/5   |          |

Suite score:    0.82
Generate score: 0.88
Validate score: 0.73
```

---

## Key Domain Rules for the Judge Prompt

Include these in the rubric sections passed to the judge to ensure correct evaluation:

### Functions that do NOT exist in CTL2
- `toInteger()` → use `str2integer()`
- `toBoolean()` → use `str2bool()`
- `toDouble()` → use `str2double()`
- `toLong()` → use `str2long()`
- `toDecimal()` → use `str2decimal()`
- `addDays()` → use `dateAdd(date, long, day)`
- `now()` → use `today()`
- `double2decimal()` → **does not exist**; `number → decimal` is automatic upcast
- `convert()` → **does not exist**
- `size()` on lists → use `length(list)`
- `toUpperCase()` → use `upperCase()`

### Valid CTL2 behaviours that models frequently false-flag
- `isBlank(string)` — **valid** built-in; returns true for null/empty/whitespace
- `cast(variant, decimal)` — **valid**; `decimal` is a supported cast target type
- `split(s, "\\|")` — **correct** escaping for literal pipe in regex
- `append(list, item)` — **returns** the modified list (not void); assigning the return value is valid but redundant
- `switch` on `number`, `decimal`, `date` — **valid** in CTL2 (unlike many other languages)
- `number → decimal` assignment — **automatic upcast**; no conversion function needed
- Function overloading (same name, different parameter types) — **valid** in CTL2

### Operator semantics
- `~=` — **whole-string** regex match (full string must equal pattern)
- `?=` — **contains** regex match (pattern found anywhere in string)
- `null + "string"` → produces `"nullstring"` (literal "null" concatenated), not empty string
- `string += value` where string is null → treats null as `""` (null-safe)
- `isnull(expr)` — lowercase, 1 argument, correct for named field null check
- `isNull(record, fieldName)` — camelCase, 2 arguments, for dynamic field access

### Denormalizer lifecycle access rules
| Function | `$in.0` accessible | `$out.0` accessible |
|---|---|---|
| `append()` | ✓ | ✗ (NPE) |
| `transform()` | ✗ | ✓ |
| `clean()` | ✗ | ✗ (NPE) |

### Rollup required lifecycle
- `initGroup(Acc acc)` — initialise accumulator fields
- `updateGroup(Acc acc)` — accumulate from `$in.0` per record
- `finishGroup(Acc acc)` — optional post-group computation
- `updateTransform(integer counter, Acc acc)` — optional per-record output (return SKIP to suppress)
- `transform(integer counter, Acc acc)` — group output; **must** have `if (counter > 0) return SKIP`

---

## Comparing Multiple Models

To compare models, run the suite for each and load all results files:

```python
results = {
    "CTL3":  load("results_ctl3_20250516.json"),
    "CTLv4": load("results_ctlv4_20250516.json"),
}
```

Suggested comparison table format:

```
| Test | CTL3  | CTLv4 | Delta |
|------|-------|-------|-------|
| T1   | PASS  | PASS  |   =   |
| T2   | PASS  | PASS  |   =   |
| T3   | PASS  | PASS  |   =   |
| T4   | 4/4✓  | 4/4✓  |   =   |
| T5   | 4/5   | 3/5   |  -1   |
| T6   | PASS  | PASS  |   =   |
| T7   | PASS  | PASS  |   =   |
| T8   | PASS  | PASS  |   =   |
|------|-------|-------|-------|
| Gen  | 0.95  | 0.97  | +0.02 |
| Val  | 0.78  | 0.72  | -0.06 |
| All  | 0.88  | 0.86  | -0.02 |
```

---

## Implementation Checklist for Claude Code

The Python script should implement:

- [ ] Load `ctl2_test_suite.json`
- [ ] Parse CLI args / config file (MUT endpoint, judge endpoint, runs per test)
- [ ] For each test (or selected subset):
  - [ ] Call MUT with correct system prompt, user message, temperature
  - [ ] Handle timeout (240s) with single retry
  - [ ] Call judge with structured prompt including test definition + MUT response
  - [ ] Parse judge JSON response; retry once on parse failure
  - [ ] Compute numeric score from findings
  - [ ] Detect critical failures
- [ ] Write `results_<model>_<timestamp>.json`
- [ ] Write `summary_<model>_<timestamp>.md`
- [ ] Optional: `--compare results_a.json results_b.json` flag for side-by-side diff
- [ ] Optional: `--tests T4,T5,T7` flag for running subset

### Suggested Python libraries
- `httpx` or `requests` — HTTP calls to MUT (Ollama/OpenAI-compatible)
- `anthropic` — for judge calls via Anthropic API
- `openai` — alternative for both MUT and judge
- `pydantic` — validate judge JSON response schema
- `rich` — progress display and summary table rendering
- `yaml` — config file parsing
- `argparse` — CLI interface
