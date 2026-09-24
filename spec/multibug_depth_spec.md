# Deep multi-defect reviews — 10 additional records at 5 and 6 findings

**10 new records. Nothing existing is edited.** Everything above the "Internal tracking"
section at the end is a self-contained brief. It assumes CTL2 knowledge (the language, the
ETL component model, and the `ISSUES:` / `SUGGESTIONS:` / `VERDICT:` review format below)
but no other context.

Write them to a new source file, `CTL_LoRAT_multibug_deep_thinking.json`, so the existing
multi-defect records are left untouched.

## What to produce

| records | findings each | defect slots |
|---|---|---|
| 5 | **5** | 25 |
| 5 | **6** | 30 |

Each record is a `validate` example: a CTL2 snippet plus its input/output metadata, and a
review that reports every defect. Nothing above six findings — six is the realistic ceiling
for a reviewable transform.

## These must be genuinely new examples

The corpus already contains 35 multi-defect reviews. The 10 new ones exist to add **depth**
(more defects per review) without repeating what is there. Concretely:

- **New scenarios.** A new record is not an existing one with the field names changed, the
  business domain swapped, or one extra defect bolted on. The transform should do a
  different job, over different metadata.
- **New explanations.** No sentence should be reusable verbatim from another record, in the
  review or in the reasoning. If two of your own new records could share a sentence, rewrite
  one of them.
- **New defect constructs.** See the exclusion list below. Reusing one or two unavoidable
  fundamentals (a null dereference, an overflowing literal) is fine; building five records
  out of the same six constructs is not.

A quick self-test: if someone read three of your ten records, the fourth should still teach
them something.

## Construct families already used — prefer something else

These appear in the existing 35 multi-defect records. Avoid them where you can, and where a
fundamental is genuinely worth repeating, put it in a different component and a different
failure story:

```
length  substring  left  right  charAt  trim  upperCase  lowerCase  removeBlankSpace
split  join  find  replace  contains  binarySearch  append  appendAll  pop  clear  getKeys
str2date  date2str  date2num  dateDiff  dateAdd  getMonth  getDayOfWeek  getWeekNumber
str2integer  str2byte  byte2hex  byte2base64  num2str  toNumber  decimal2integer
decimal2double  cast  getType  typeof  round  sha1  isnull  isNull  nvl  lookup
codePointLength  getUrlHost  getFileExtension  generate  transform  foreach  catch  finally
```

Plus these patterns: unsuffixed literals above 2³¹−1, string concatenation with a nullable
field, unguarded division, ordered comparison against null, `if(...)` used as a ternary,
assignment into an undeclared output field, decimal→integer narrowing, `return SKIP`/`STOP`
misuse, unreachable `return`.

Richer ground that is barely touched: component lifecycle contracts (which function may read
`$in.0` or write `$out.*`, and when), multi-port routing, accumulator state that is never
reset between groups, lookup table declaration and misuse, map/list membership and default
values, sequence and sorting assumptions, `//#CTL2:COMPILE` mode restrictions, and metadata
attributes that contradict the code (a field declared `nullable="false"` that the code tests
for null, wrong declared length or scale, a delimiter mismatch).

## Spread the records across components

29 of the existing 30 deep records are Reformat transforms. **At most 2 of your 10 may be
Reformat.** Cover the rest across: Rollup, Denormalizer, Normalizer, ExtHashJoin or
ExtMergeJoin, Filter, Partition, DataGenerator, and a Reformat-with-Lookup ("Map"). Component
lifecycle gives you defect material that a plain Reformat cannot.

## Construction rules

- **The defects must be independent** — different lines, different mechanisms. Do not seed
  the same mistake five times.
- **Mix severities, and roughly 2:1 ERROR to WARNING across the set** (about 37 ERROR and
  18 WARNING across the 55 slots). Every record carries at least one of each.
  - `[ERROR]` when you can name the concrete failure: a compile error, a runtime exception,
    or a specific input row whose emitted output would be wrong.
  - `[WARNING]` when the code runs correctly on every input described but the choice looks
    unintended. A `[WARNING]` alone does not make the verdict FAIL.
  - `[INFO]` for a remark that is not a defect at all — including explicitly noting that a
    construct which *looks* wrong is correct here.
- **Order the `ISSUES:` lines to match the order the constructs appear in the code**, not by
  severity. A reader is diffing the review against the file.
- **Do not always put the warning last.** In the existing records the warning-worthy
  construct is the final statement almost every time, which is a pattern worth breaking.
  Place it first or in the middle in at least half of your records.
- **Include a trap in at least 3 records**: a construct that looks wrong but is correct in
  context, which the review must leave unflagged, or flag at `[INFO]` while saying plainly
  that it is fine. Defensive code beyond what the prompt requires is never a defect.

## Per-finding word floor

**Every `[SEVERITY]` line gets at least 35 words.** A six-finding review therefore runs to
roughly 210–280 words in its `ISSUES:` block. Length scales with defect count; it does not
get divided among them. (The existing deep records land at a median of 46 words per line —
match that.)

Each line states three things, in this order:

1. **The construct** — quote the offending expression verbatim, in backticks.
2. **The mechanism, with its qualifier** — what the language actually does here, including
   the condition that makes it wrong. This is the part that must never be dropped: prefer
   "requires two arguments, a record and a field name" over "is wrong", and "not available in
   `//#CTL2:COMPILE` mode" over "is not valid". Dropping the qualifier turns a true statement
   into a false one — "`isNull()` takes a record and a field" becomes "`isNull()` is not a
   CTL2 function", which is simply untrue.
3. **The consequence** — the compile error, the runtime exception, or the specific input row
   whose emitted value would be wrong.

Words must come from **grounding, never padding**: naming the mechanism, quoting the metadata
that proves a field is nullable, tracing the row that fails. Restating the severity or
rephrasing the fix a second time does not count. A 40-word line that says nothing a 15-word
line would not have said fails this spec rather than satisfying it.

**`SUGGESTIONS:` does not substitute.** A reader who stops at `ISSUES:` must not come away
with a false belief.

## Reasoning traces

One segment per defect, in the same order as the findings, then a one-line verdict
justification. Observed working length in the existing deep records is **45–55 tokens per
defect** — so roughly 250–300 tokens for a five-finding record and 300–350 for a six-finding
one. Do not pad beyond that.

Two requirements:

- **Name the field and the function.** Write "invoice_no is non-null by metadata, so the nvl
  fallback can never be taken" rather than "the key field is non-null by metadata". Generic
  referring expressions make segments interchangeable between records, which is how
  boilerplate creeps back in.
- **Reach the qualifier before stating the conclusion**, so the qualifier is the reason for
  the finding and not an afterthought.

## Examples to learn from — read these before writing

Pre-selected from the existing corpus. Each is cited for one specific quality; none should be
copied.

| source_file | source_id | read it for |
|---|---|---|
| `CTL_LoRAT_multibug_validate_thinking.json` | `multibug_026` | the explanation standard. Its findings anticipate the naive fix and say why it also fails — *"Merely changing this call to `cast(parsed, integer)` would fail at runtime for the permitted JSON value 2.5."* That is what a 46-word line buys. |
| `CTL_LoRAT_multibug_validate_thinking.json` | `multibug_004` | a clean 4-finding baseline, and reasoning that names its fields (`tracking`, `weight_text`, `comment`) instead of referring to them generically. |
| `CTL_LoRAT_multibug_validate_thinking.json` | `multibug_030` | the only non-Reformat record in that file (Normalizer). Shows the format carrying over to a component with lifecycle functions. |
| `CTL_LoRAT_validate_thinking.json` | `nullcmp_partition_tv_02` | **the structural model for this spec**: 5 findings, Partition, and it closes with an `[INFO]` stating that the `==` comparisons need *no* null guard because equality is null-safe. That is the trap case done well. Its lines are shorter than this spec's floor — copy the structure, not the length. |
| `CTL_LoRAT_validate_thinking.json` | `tvalidat22_31`, `tvalidat22_35` | severity interleaving — `WEWW` and `EWWW`, warnings not clustered at the end. Also DataGenerator, a component the deep records do not cover. |

## Format — must match exactly

**Emit the reasoning as a separate `reasoning_content` field — do not write `<think>` tags by
hand.** Each assistant message has two fields: `content` holds the answer alone,
`reasoning_content` holds the thinking.

```json
{
  "id": "multibug_deep_001",
  "messages": [
    {"role": "user", "content": "Validate the following CTL2 code. …metadata…"},
    {"role": "assistant",
     "reasoning_content": "Rollup writes output only from updateTransform and transform, so the $out assignment inside initGroup has no output record to target and fails at compile time. …",
     "content": "ISSUES:\n  [ERROR] `$out.0.total = 0` — …\nSUGGESTIONS:\n  - …\nVERDICT: FAIL"}
  ]
}
```

A separate script merges the two fields into the tagged form the trainer needs:

```bash
python3 convert_think.py CTL_LoRAT_multibug_deep_thinking.json -o <merged output>
```

**Leave the tagging to that script.** The merge needs an exact literal spelling
(`"<think>\n"` … `"\n</think>\n\n"`); a hand-typed variant that is off by one character fails
silently and trains the reasoning text *with* loss where it should have none.

**Answer structure**, with no prose outside it:

```
ISSUES:
  [ERROR] <construct, mechanism with its qualifier, concrete consequence>
  [WARNING] <construct, why it is suspicious, why it still runs correctly>
SUGGESTIONS:
  - <the fix>
VERDICT: FAIL
```

Every record needs `id`, `messages`, and `source_file` / `source_index` / `source_id`.

## Verification

Run on the new file, before `convert_think.py`:

```python
import json, re, collections, statistics as st
R = json.load(open('CTL_LoRAT_multibug_deep_thinking.json'))
ans = lambda e: ''.join(m.get('content','') for m in e['messages'] if m['role']=='assistant')
rea = lambda e: ''.join(m.get('reasoning_content','') for m in e['messages'] if m['role']=='assistant')

def lines(a):
    b = a.split('ISSUES:',1)[1].split('SUGGESTIONS:')[0].split('VERDICT:')[0]
    return [' '.join(l.split()) for l in b.splitlines() if re.match(r'\s*\[(ERROR|WARNING|INFO)\]', l)]

L = [lines(ans(e)) for e in R]
print('records:', len(R), '(want 10)')
print('findings distribution:', dict(collections.Counter(len(x) for x in L)), '(want {5:5, 6:5})')

short = [(e.get('id'), l[:60]) for e, ls in zip(R, L) for l in ls if len(l.split()) < 35]
print('issue lines under the 35-word floor (want 0):', len(short), short[:3])
w = [len(l.split()) for ls in L for l in ls]
print('words/line: median %.0f  min %d   (existing deep records: 46)' % (st.median(w), min(w)))

sev = collections.Counter(re.match(r'\[(\w+)\]', l).group(1) for ls in L for l in ls)
print('severities:', dict(sev), '| ERROR:WARNING = %.2f (want ~2.0)' % (sev['ERROR']/max(1,sev['WARNING'])))
print('records with no WARNING or no ERROR (want 0):',
      sum(1 for ls in L if not any('[WARNING]' in l for l in ls) or not any('[ERROR]' in l for l in ls)))
print('records where the warning is last (want <=5):',
      sum(1 for ls in L if ls and ls[-1].startswith('[WARNING]')))

S = collections.Counter()
for e in R:
    for s in re.split(r'(?<=[.])\s+', rea(e)):
        s = ' '.join(s.split())
        if len(s.split()) >= 6: S[s] += 1
print('reasoning sentences repeated across records (want 0):', sum(n for n in S.values() if n > 1))
IL = collections.Counter(l for ls in L for l in ls)
print('issue lines repeated (want 0):', sum(n for n in IL.values() if n > 1))

tok = [(len(rea(e).split())*4//3, len(ls)) for e, ls in zip(R, L)]
print('reasoning tokens per defect: %s   (want 45-55)' %
      [round(t/n) for t, n in tok])
```

Then check it against the corpus it is joining — no prompt may already exist there:

```python
import json
new = json.load(open('CTL_LoRAT_multibug_deep_thinking.json'))
old = json.load(open('CTL_LoRA_training_data_think.json'))
u = lambda e: next(m['content'] for m in e['messages'] if m['role']=='user').strip()
seen = {u(e) for e in old}
print('new prompts that already exist in the corpus (want 0):', sum(1 for e in new if u(e) in seen))
```

After merging, rebuild both corpus files and re-run the standard pre-flight: no duplicate
prompts, no conflicting answers, every think prompt present in the phase-1 corpus with the
same answer, and no train/eval overlap.

---

## Internal tracking (not part of the generation brief above)

Context is in `spec/ctl2_training_findings.md` §3.8 and `spec/explanation_budget_spec.md`.

The 2026-09-24 regeneration of `CTL_LoRAT_multibug_validate_thinking.json` fixed the
templating completely — distinct defect kinds 23 → 113, verbatim reasoning-sentence reuse
91% → 0%, issue-line reuse 48% → 0%, in-file ERROR:WARNING 3.83 → 2.00, words per issue line
39 → 46. Corpus hygiene is clean.

It also flattened the depth distribution to a uniform 4 findings per record, which is what
this spec restores:

| findings | before regeneration | after | after this spec |
|---|---|---|---|
| 4 | 17 | 34 | 34 |
| 5 | 11 | 1 | 6 |
| 6 | 6 | 0 | 5 |
| 7 | 1 | 0 | 0 |

Depth is the point: T5 in `resources/ctl2_test_suite_v4.json` seeds **six** defects, and the
measured failure was specifically at that depth — at 6 reported findings the model spent ~20
words each and 100% of runs contained a WRONG finding, against 3% at 35+ words per finding.
Training currently has no 6-finding example at all. Seven-finding reviews were dropped as
unrealistic.

These 10 records also lift the share of validate records with ≥4 findings from 10.3% to
about 12.8%, meeting the 12% target in `explanation_budget_spec.md`.

Note for whoever updates `explanation_budget_spec.md`: its reasoning budget of
"240 tokens + 120 per defect beyond the first" is wrong and is superseded here by the
measured 45–55 tokens per defect. The formula was written before any multi-defect trace
existed; the traces that work cover every defect at roughly a fifth of that budget.
