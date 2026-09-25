# Rollup per-record output loop — rebalancing an under-taught pattern

**~20 new records plus ~21 conversions.** Everything above the "Internal tracking"
section at the end is a self-contained brief. It assumes CTL2 knowledge (the language
and the CloverDX component model) but no other context.

## The pattern to teach

A CloverDX **Rollup** groups input records and can emit output at two different moments.
Which lifecycle functions do the emitting is the whole subject here.

**Summary-only Rollup** — one output row per group:

- `updateGroup()` returns **`false`**, so the per-record loop never starts.
- `updateTransform()` is a stub; it writes nothing.
- `finishGroup()` returns `true`, `transform()` writes `$out.0` and emits the summary.

**Per-record output loop** — one output row per *input record*, usually alongside a
per-group summary on a second port:

- `updateGroup()` returns **`true`**. This is what starts the `updateTransform()` loop
  for that input record. Returning `false` here means the per-record port silently
  receives nothing — the single most common way this pattern is written wrong.
- `updateTransform(integer counter, Acc acc)` has a **real body**: it writes the
  per-record output fields and returns the **port number** (`return 1;`), not `ALL`,
  not `OK`.
- Both emitting functions are **bounded by a counter guard** — `if (counter > 0) return
  SKIP;` — because returning a port number emits a row and calls the function again with
  an incremented `counter`. Without the guard the same row repeats forever.
- `transform()` likewise guards on `counter` and returns its own port number
  (`return 0;`).
- Per-record values come from the accumulator **after** `updateGroup()` has folded the
  current record in, so a running total includes the current record.
- Output fields may be written **only** in `updateTransform()` and `transform()` (and
  their `OnError` forms). Writing `$out.*` in `initGroup()`, `updateGroup()` or
  `finishGroup()` is an error.

This is the pattern the corpus under-teaches, and the reason for this document.

## What to produce

### A. ~20 new generate records

Each asks for a Rollup and expects the per-record loop. Cover these shapes — the corpus
currently has almost nothing outside the first:

| shape | count | note |
|---|---|---|
| Two output ports: per-record on port 1, summary on port 0 | 6 | the common case |
| **Three output ports**: per-record, summary, plus a conditional third (e.g. an alert row only for records meeting a condition) | 4 | absent from the corpus |
| **Single output port**, per-record and summary rows distinguished by a `record_type` field | 4 | one existing example only |
| **Per-record only, no summary at all** — `finishGroup()` returns `false` deliberately | 3 | one existing example only |
| Per-record loop where the accumulator has **no metadata configured** (`VoidMetadata` placeholder) | 3 | tests that the pattern survives without a typed accumulator |

Vary the domain, field names and metadata across all of them. Each must include all five
lifecycle functions, typed with the named accumulator where one is supplied.

### B. ~6 new validate records

Review CTL2 that gets the pattern wrong, and say why. The existing validate-side records
cover three failure modes well; write new ones for cases they miss:

- `updateGroup()` returns `false` while the task requires per-record output → the port
  receives nothing.
- `updateTransform()` returns the port number with **no counter guard** → the same row
  repeats instead of one row per input record.
- `$out.*` written in `updateGroup()` or `initGroup()` → invalid, output is writable only
  in the transform functions.
- `updateTransform()` returns `ALL` or `OK` instead of the port number.
- Running values read from the accumulator **before** `updateGroup()` folds in the current
  record, so the per-record row is off by one.
- A per-record loop present where the task needs only a summary and the second port is not
  connected → dead code, flag as `[WARNING]` not `[ERROR]` (it compiles and runs).

### C. ~21 conversions (see the list below)

Rewrite near-duplicate summary-only records into per-record ones. **A conversion is not
an answer edit.** The prompt is what decides which pattern is correct — a prompt asking
for one summary row per group correctly gets a summary-only answer. So converting means
rewriting the prompt to require per-record output (add a second port, or a `record_type`
discriminator on one port) and then writing the matching answer. What you reuse is the
domain, the metadata and the field names; the CTL2 is new.

These are safe to convert because each is a near-duplicate of another record that stays
summary-only, so no coverage is lost. Keep the first of each pair as-is, convert the
second:

| keep as summary-only | convert to per-record |
|---|---|
| `treasoniae_37` | `componen9c_220` |
| `treasoniae_49` | `componen9c_221` |
| `treasoniae_50` | `componen9c_237` |
| `treasoniae_51` | `componen9c_239` |
| `treasoniae_52` | `componen9c_241` |
| `treasoniae_53` | `componen9c_259` |
| `treasoniae_54` | `componen9c_291` |
| `treasoniae_55` | `componen9c_310` |
| `treasoniae_58` | `treasoniae_62` |
| `treasoniae_63` | `componen9c_64` |
| `treasoniae_68` | `componen9c_236` |
| `treasoniae_69` | `componen9c_238` |

(12 pairs listed; the full set of 21 is reproducible with the script in Verification.)
The `componen9c_*` records live in `CTL_LoRA_components_contracts.json`, the
`treasoniae_*` in `CTL_LoRAT_reasoning_v2.json`.

## Examples to read first

Pre-selected from the corpus. Cited for one quality each; none should be copied.

| source_file | source_id | read it for |
|---|---|---|
| `CTL_LoRAT_rollup_update_transform_examples.json` | `trollupu62_0` | **the gold standard.** Two ports, `updateGroup` returns true, `updateTransform` guards on `counter` and returns 1, `transform` guards and returns 0, running totals taken post-update, `nvl()` on the nullable surcharge. Match this shape. |
| same | `trollupu62_2` | single output port, DETAIL and SUMMARY rows distinguished by `record_type` |
| same | `trollupu62_4` | per-record output with **no** summary — `finishGroup()` deliberately returns false |
| same | `trollupu62_15` | validate side: `updateTransform()` returns port 1 with no counter guard, so the row repeats |
| same | `trollupu62_17` | validate side: `$out.1` written inside `updateGroup()`, which is invalid |
| same | `trollupu62_contrast_02` | the reverse case — a per-record loop where none is needed, correctly `[WARNING]` and not `[ERROR]` |

Two records in that file, `trollupu62_16` and `trollupu62_18`, answer correct code with a
bare `ISSUES: none / VERDICT: PASS` in four words. Do not imitate those — a validate answer
on correct code should still say briefly why the pattern is right.

## Format

Records follow the corpus conventions.

**Generate answers** are a `//#CTL2` fenced block containing all five lifecycle functions,
with no prose outside the fence unless the prompt asks for explanation.

**Validate answers** use:

```
ISSUES:
  [ERROR] <construct, mechanism with its qualifier, concrete consequence>
SUGGESTIONS:
  - <the fix>
VERDICT: FAIL
```

Use `ISSUES:\n  [INFO] No issues found.` with `VERDICT: PASS` for clean code.

### Every record must carry `reasoning_content` — this is not optional

**Write a `reasoning_content` field on every new record in A and B, and on every conversion
in C.** A record without it trains in one phase; a record with it trains in two, and the
second phase is the one that matters most here (see below). Never hand-write `<think>`
tags: `content` holds the answer, `reasoning_content` holds the thinking, and
`convert_think.py` merges them. The merge needs an exact literal spelling and a hand-typed
variant fails silently, training the reasoning with loss where it should have none.

**Why it is mandatory here.** The pipeline builds two datasets. Phase 1 trains on every
record, answers only. Phase 3 trains *only* on records that have reasoning, runs last, and
is short and gentle. The Rollup imbalance exists in both, and it is worse where it counts:

| | per-record : summary-only | ratio | summary-only as share of corpus |
|---|---|---|---|
| phase 1 | 25 : 342 | 1:13.7 | 3.0% |
| phase 3 | 19 : 95 | 1:5.0 | **10.0%** |

Phase 3 is over three times denser in summary-only Rollup content and it is the last thing
the model sees, which is why this failure is dose-sensitive. Records written without
`reasoning_content` would land in phase 1 only and leave phase 3 untouched at 1:5.0 —
fixing the phase that is not driving the problem. With reasoning on all ~20 new records,
phase 3 moves to roughly 1:2.4.

Note that conversions do not help phase 3 much on their own: of the listed conversion
targets, all but `treasoniae_62` currently live outside the reasoning corpus. Giving them
`reasoning_content` as part of the rewrite is what pulls them into phase 3.

**What the reasoning should say.** For a generate record, walk the decision the pattern
turns on rather than narrating the code: why this task needs the per-record loop at all,
therefore why `updateGroup()` returns true, why `updateTransform()` needs the `counter`
guard (a port return re-invokes it), why it returns the port number rather than `ALL`, and
why the running value is read after the accumulator has folded in the current record. For
a validate record, reach the rule before stating the verdict. Name the fields and functions
of that specific record rather than referring to them generically. Around 200-300 tokens
is right; length must come from grounding, not restatement.

Every record needs `id`, `messages`, and `source_file` / `source_index` / `source_id`.

## Verification

```python
import json, re, collections
R = json.load(open('<new or edited file>.json'))
asst = lambda e: ''.join(m.get('content','') or '' for m in e['messages'] if m['role']=='assistant')
HAS = re.compile(r'function\s+integer\s+updateTransform\s*\(', re.I)
def body(s):
    m = HAS.search(s)
    if not m: return ''
    rest = s[m.end():]; nxt = re.search(r'\nfunction\s', rest)
    return rest[:nxt.start()] if nxt else rest[:800]

rea = lambda e: ''.join(m.get('reasoning_content','') or '' for m in e['messages'] if m['role']=='assistant')
missing = [e.get('id') for e in R if not rea(e).strip()]
print('records with NO reasoning_content (want 0):', len(missing), missing[:5])
print('records with hand-written <think> tags (want 0):',
      sum(1 for e in R if '<think>' in asst(e) or '<think>' in rea(e)))
import statistics as st
tok = sorted(len(rea(e).split()) * 4 // 3 for e in R if rea(e).strip())
if tok: print('reasoning tokens: median %d  p10 %d  p90 %d  (target ~200-300)' % (
    st.median(tok), tok[len(tok)//10], tok[9*len(tok)//10]))

gen = [e for e in R if 'ISSUES:' not in asst(e)]
per = [e for e in gen if re.search(r'\$out\.\d+\.', body(asst(e)))]
print('generate records:', len(gen), '| with a real updateTransform body:', len(per), '(want all)')
print('updateGroup returns true (want all):',
      sum(1 for e in per if re.search(r'updateGroup[^}]{0,400}?return\s+true', asst(e), re.S)))
print('counter guard in updateTransform (want all):',
      sum(1 for e in per if re.search(r'counter\s*[><=]+\s*0', body(asst(e)))))
print('returns a port number not ALL/OK (want all):',
      sum(1 for e in per if re.search(r'return\s+\d+\s*;', body(asst(e)))))
print('all five lifecycle functions (want all):',
      sum(1 for e in per if all(f in asst(e) for f in
          ('initGroup','updateGroup','finishGroup','updateTransform','transform'))))
print('writes $out in initGroup/updateGroup/finishGroup (want 0):',
      sum(1 for e in per if re.search(
          r'function\s+(?:void|boolean)\s+(?:init|update|finish)Group[^}]{0,600}?\$out\.', asst(e), re.S)))
```

Then re-measure the corpus-wide ratio, which is the point of the exercise:

```python
import json, re
R = json.load(open('CTL_LoRA_training_data.json'))
THINK = re.compile(r'^<think>\n.*?\n</think>\n\n', re.S)
a = lambda e: THINK.sub('', ''.join(m.get('content','') or '' for m in e['messages'] if m['role']=='assistant'))
HAS = re.compile(r'function\s+integer\s+updateTransform\s*\(', re.I)
def body(s):
    m = HAS.search(s)
    if not m: return ''
    rest = s[m.end():]; nxt = re.search(r'\nfunction\s', rest)
    return rest[:nxt.start()] if nxt else rest[:800]
roll = [e for e in R if HAS.search(a(e))]
per  = [e for e in roll if re.search(r'\$out\.\d+\.', body(a(e)))]
print(f'per-record {len(per)} : summary-only {len(roll)-len(per)}  = 1:{(len(roll)-len(per))/max(1,len(per)):.1f}')
print('  baseline was 1:13.7 (25 : 342); target after this work is about 1:5 (66 : 321)')
```

**Run the same ratio check on `CTL_LoRA_training_data_think.json`** — that is the phase-3
dataset and the one this work most needs to move:

```python
# identical to the block above, but opening CTL_LoRA_training_data_think.json
#   baseline 1:5.0 (19 : 95); target about 1:2.4 or better
# If this number has not moved, the new records are missing reasoning_content
# and the intervention has not touched the phase that drives the failure.
```

Then rebuild both corpus files and run the standard pre-flight (findings §5.1): no
duplicate prompts, no conflicting answers, every think prompt present in the phase-1
corpus with the same answer, no train/eval overlap.

---

## Internal tracking (not part of the generation brief above)

Motivation: T37 (`Rollup, per-record output loop, two output ports`) is the only suite
test with a monotonic decline across every model — 0917 0.97, fix1 0.87, fix2 0.77,
fix3 ckpt-250 0.57 — and it is the largest single generate regression. Generate is the
primary objective.

Pooling all 79 T37 runs across 15 models (51 good, 28 bad), the failure is always the
same: the model writes the summary-only pattern. Failing rubric items are T37.6 (counter
guard) 16x, T37.7 (`return 1`) 19x, T37.9 (transform port/guard) 15x, T37.5 (real body) 9x.

Corpus counts behind it, measured 2026-09-25:

| | per-record | summary-only | ratio |
|---|---|---|---|
| phase-1 corpus | 25 | 342 | 1:13.7 |
| phase-3 (reasoning) corpus | 19 | 95 | 1:5.0 |

Summary-only Rollups are **3.3× denser in phase 3** (10.0% of records) than in phase 1
(3.0%), and phase 3 runs last — which is why T37 is phase-3-dose-sensitive: 0.97 at
ckpt-100 (1.2 ep), 0.87 at ckpt-150, 0.57 at ckpt-250 (2.9 ep). Two knobs, one cause.

**Why convert as well as add.** Conversion moves both sides of the ratio:
adding N gives (25+N)/342, converting N gives (25+N)/(342−N):

| | per-record : summary-only | ratio |
|---|---|---|
| now | 25 : 342 | 1:13.7 |
| +20 new only | 45 : 342 | 1:7.6 |
| 21 conversions only | 46 : 321 | 1:7.0 |
| **both** | **66 : 321** | **1:4.9** |

Conversion alone beats adding alone despite being one record more, because it moves the
denominator too. The stronger argument is corpus discipline: generate has fallen at every
round as the corpus grew, so a rebalance that does not add net records is preferable. The
21 conversion targets are genuine near-duplicates (>85% prompt similarity to a record that
stays summary-only), so nothing is lost. The pool is otherwise not very redundant — only
21 of 316 generate-type summary-only records cluster — so conversion beyond these 21 would
start costing real coverage. Hence: convert 21, add ~20, landing near 1:5.

**On the "6 records with no updateTransform".** An earlier note said 9 of the 22 records in
`CTL_LoRAT_rollup_update_transform_examples.json` "don't demonstrate the pattern". That was
wrong on two counts. Six of them are *validate*-side records teaching the same pattern from
the review angle, and they are good. Three others (`trollupu62_2`, `_4`, `contrast_02`) do
demonstrate it — the detector that flagged them required `$out.1` specifically and so missed
single-output-port per-record loops. The only weak records in the file are `trollupu62_16`
and `trollupu62_18`, whose answers are four words. Correcting that detector also moved the
headline ratio from a reported 1:27 to the true 1:13.7.

**Cheap validation.** The ratio is a grep, so the corpus side can be checked before any
training. The prediction is that T37 rises and stops being phase-3-dose-sensitive. T37 is
bimodal (runs score ~1.0 or ~0.3–0.6), so a before/after on it needs `--runs 5` or more;
at n=3 the difference between 0.57 and 0.97 is two bad runs versus none.
