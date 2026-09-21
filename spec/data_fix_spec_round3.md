# Fix spec round 3 — Denormalizer contract violations and two Rollup defects

Scope: **14 records, all in `CTL_LoRA_components_contracts.json`.**

Found while authoring reasoning traces for `CTL_LoRA_reasoning_v2.json`: writing grounded
reasoning forces the answer to be verified, which surfaced defects the original review
missed. That is how these were caught, and it is worth noting as a method.

**Where to apply.** The original per-dataset source file on the authoring machine, then
re-combine and re-upload. `source_index` is the zero-based array position within that file,
which is how to address each record directly. The combined corpus on the training host is a
derived artifact.

---

## BUG-6 — Denormalizer `transform()` reading `$in.0` is never flagged (12 records)

`resources/componet_contracts.md` is explicit, three times over:

> line 412 — Read `$in.0` only in `append()`.
> line 415 — **Do not read `$in.0` in `transform()`.**
> line 540 — Never read `$in.0` in `transform()`.

`append()` is the accumulation phase; by the time `transform()` runs, the group is consumed
and there is no current input record. The group key must be captured into module-level state
during `append()` and emitted from there.

Twelve validate examples put exactly this defect in the prompt code and **never mention it**
in the answer. Split by how damaging that is:

### 6a — verdict PASS: actively teaches the violation as correct (5 records) — HIGH priority

| `source_index` | `source_id` | field read in `transform()` |
|---|---|---|
| 124 | `componen9c_124` | `$in.0.customer_id` |
| 133 | `componen9c_133` | `$in.0.customer_id` |
| 135 | `componen9c_135` | `$in.0.category` |
| 136 | `componen9c_136` | `$in.0.product_id` |
| 137 | `componen9c_137` | `$in.0.project_id` |

These are worse than a missed finding. Several carry an `[INFO]` praising the code — e.g.
`componen9c_137`: *"This is valid Denormalizer CTL for the stated requirement."* The model is
being taught that a contract violation is exemplary.

**Fix:** add the finding as an `[ERROR]` and change the verdict to `FAIL`. Suggested text,
adapting the field name per record:

```
  [ERROR] Denormalizer `transform()` reads `$in.0.customer_id`. The input record is not
  available in `transform()` — the group has already been consumed by `append()`. Capture
  the group key in module-level state during `append()` and emit the saved value here.

SUGGESTIONS:
  - Add a module-level `customerId`, set it from `$in.0.customer_id` in `append()`, and
    reset it in `clean()` alongside the other group state.
```

Keep any other findings already present in the answer.

### 6b — verdict already FAIL: the finding is simply missing (7 records) — lower priority

| `source_index` | `source_id` | field |
|---|---|---|
| 120 | `componen9c_120` | `$in.0.product_id` |
| 127 | `componen9c_127` | `$in.0.category` |
| 128 | `componen9c_128` | `$in.0.account_id` |
| 129 | `componen9c_129` | `$in.0.category` |
| 130 | `componen9c_130` | `$in.0.customer_id` |
| 131 | `componen9c_131` | `$in.0.invoice_id` |
| 308 | `componen9c_308` | `$in.0.receipt_no` |

These reach `FAIL` for other reasons, so they do not teach the violation as acceptable — but
they do teach an incomplete review. Add the same `[ERROR]` finding; leave the verdict at
`FAIL`.

**Verified not a problem:** no record anywhere in the corpus has assistant-authored code that
reads `$in.0` in a Denormalizer `transform()`. The generated code is uniformly correct; only
the reviews are incomplete.

---

## BUG-7 — Rollup with four missing lifecycle functions marked PASS (1 record)

| | |
|---|---|
| `source_index` | 82 |
| `source_id` | `componen9c_82` |

The prompt defines only `transform(integer counter, SensorAcc acc)`. The answer is
`ISSUES: none` / `VERDICT: PASS`.

The Rollup contract requires all five — `initGroup`, `updateGroup`, `finishGroup`,
`updateTransform`, `transform` — regardless of runtime control flow. Without `finishGroup`
returning true, `transform()` is never invoked and the group emits nothing.

**Fix:** flag each missing function by name as its own `[ERROR]`, verdict `FAIL`. Naming them
individually matters — the eval rubric scores each separately and a generic "the lifecycle is
incomplete" earns credit for none.

---

## BUG-8 — output port mismatch marked WARNING/PASS (1 record)

| | |
|---|---|
| `source_index` | 84 |
| `source_id` | `componen9c_84` |

```ctl
$out.1.region = $in.0.region;      // populates port 1
...
return 0;                          // routes to port 0
```

The answer calls this a `[WARNING]` and returns `PASS`. The populated record is not the one
emitted, so the summary is silently dropped. The suite treats this class as critical —
`T37.F3`'s rationale is *"silently dropping half the requested output"*.

**Fix:** `[ERROR]`, verdict `FAIL`.

---

## Do NOT change these

`CTL_LoRA_reasoning_v2.json` also rewrote two answers where **the corpus was right**. If that
file is used as a source for corpus corrections, exclude these:

| `source_index` | `source_id` | v2 change | why v2 is wrong |
|---|---|---|---|
| 287 | `componen9c_287` | WARNING→ERROR, PASS→FAIL | `nvl($in.0.room_revenue, 0)` flagged as an integer fallback on a decimal. `ctl2-basics.md:231` — `integer → decimal` is automatic widening, so this compiles and works. The corpus's WARNING about clarity was correct. Escalating it is the T24 failure mode. |
| 281 | `componen9c_281` | ERROR+WARNING→WARNING, FAIL→PASS | `acc.count` is never incremented, so `acc.total / acc.count` divides by zero on **every** group — unconditional, and `ctl2-basics.md:228` says ÷0 throws for decimal. Downgrading to PASS is a regression. |

## Undecided — needs a ruling before either is changed

| `source_index` | `source_id` | question |
|---|---|---|
| 77 | `componen9c_77` | Divide-by-zero on a *conditional* counter (`answered_count`), reachable only when an entire group is null. Corpus says ERROR/FAIL; v2 says WARNING/PASS. Data-dependent, so both are defensible — the project's convention is WARNING for unprovable runtime risk, which favours v2. |
| 167 | `componen9c_167` | Normalizer without `clean()`. Corpus says ERROR/FAIL; v2 argues `clean()` is optional because `count()` overwrites all module state on every record. The reasoning looks sound but should be checked against the Normalizer contract before the corpus is changed. |

---

## Verification

```python
import json, re, sys
D = [e for f in sys.argv[1:] for e in json.load(open(f))]
def asst(e):
    c = "\n".join(m.get("content","") for m in e["messages"] if m["role"] == "assistant")
    return c.split("\n</think>\n\n", 1)[1] if "\n</think>\n\n" in c else c
def usr(e):  return "\n".join(m.get("content","") for m in e["messages"] if m["role"] == "user")
def tbody(code):
    m = re.search(r"function\s+\w+\s+transform\s*\(\s*\)\s*\{", code)
    if not m: return None
    i, d = m.end(), 1
    while i < len(code) and d:
        d += 1 if code[i] == "{" else -1 if code[i] == "}" else 0
        i += 1
    return code[m.end():i]
def viol(t):
    for b in re.findall(r"```ctl\n(.*?)```", t, re.S):
        if "function integer append()" not in b: continue
        tb = tbody(b)
        if tb and re.search(r"\$in\.0\.", tb): return True
    return False
bad = [e.get("source_id") for e in D
       if viol(usr(e)) and "VERDICT:" in asst(e)
       and not re.search(r"\$in\.0[^\n]*transform|transform\(\)[^\n]*\$in\.0", asst(e))]
print("Denormalizer $in.0-in-transform() defects still unflagged:", len(bad), "(want 0)", bad)
```

Run against the source file, or post-combine against the corpus. It currently reports 12.
