# Explanation budget — multi-defect reviews and the per-finding word floor

**~40 new records plus a length rule that applies to every validate record written from
now on.** Everything above the "Internal tracking" section at the end is a self-contained
brief. It assumes CTL2 knowledge (the language, the ETL component model, and the
`ISSUES:` / `SUGGESTIONS:` / `VERDICT:` review format below) but no other context.

## The problem this fixes

A code review that reports several defects has to spend words on each one. When the
explanation of a defect gets compressed past a certain point, the qualifier is the first
thing to go — and for a large class of CTL2 facts, **dropping the qualifier turns a true
statement into a false one**:

| correct, qualified | what it becomes when truncated | now false because |
|---|---|---|
| `isNull()` requires two arguments, a record and a field index or name; the one-argument call is an arity error | "`isNull()` is not a CTL2 function" | `isNull` exists; only this call is wrong |
| The conditional-fail expression (` : `) is not available in `//#CTL2:COMPILE` mode | "conditional-fail is not valid CTL2" | it is valid, in interpreted mode |
| `dd` is day-of-month; `DD` is day-of-year, so this pattern is probably not what was meant | "`DD` is invalid" | `DD` is a valid pattern letter |

The reviewer that writes the short version gives the *right fix* for the *wrong reason*.
That is worse than it looks: a developer who reads "isNull is not a CTL2 function" learns
something false and will misapply it the next time.

**So every finding needs enough room to carry its qualifier.** That is the entire point of
this document.

---

## Part 1 — multi-defect reviews (~40 records)

Most validate examples in the corpus review code with one or two defects. Reviews of code
with **four or more** defects are almost absent, and that is exactly where explanations get
squeezed. Write ~40 records whose candidate code contains several independent defects at
once.

**Distribution:**

- **15 records with 4 defects**
- **15 records with 5 defects**
- **10 records with 6 or 7 defects**

**Construction rules:**

- The defects must be **independent** — different lines, different mechanisms. Do not seed
  five instances of the same mistake; the point is to practise switching between unrelated
  explanations inside one answer.
- **Mix severities within a single record.** A realistic multi-defect review contains both
  certain failures and valid-but-suspicious constructs. At least two thirds of these records
  should carry both `[ERROR]` and `[WARNING]` lines. (For which is which: `[ERROR]` when you
  can name the concrete failure — a compile error, a runtime exception, or a specific input
  row whose output would be wrong; `[WARNING]` when the code runs correctly on every input
  described but the choice looks unintended. A `[WARNING]` alone does not make the verdict
  FAIL.)
- **Order the `ISSUES:` lines to match the order the constructs appear in the code**, not by
  severity. A reader is diffing the review against the file.
- Draw the defects from across CTL2: wrong function arity or a nonexistent overload, integer
  literals above 2³¹−1 without the `L` suffix, null dereference on a provable path,
  unreachable statements, assignment to an output field absent from the output metadata,
  string concatenation with a nullable field, whole-string versus substring matching
  operators, unguarded division, a construct valid in interpreted mode but not in
  `//#CTL2:COMPILE`, and metadata/type mismatches.
- Include a few records where one of the several defects is a **trap**: a construct that
  looks wrong but is correct in context, which the review must leave unflagged while
  correctly reporting the genuine defects around it.

---

## Part 2 — the per-finding word floor

**Every `[SEVERITY]` line gets at least ~35 words, regardless of how many lines the review
has.** A review reporting six defects therefore runs to roughly 210 words in its `ISSUES:`
block. Length scales with defect count; it does not get divided among them.

This applies to **all** validate records written from now on, not only the multi-defect ones
in Part 1.

**Anatomy of an issue line.** Each one states three things, in this order:

1. **The construct** — quote the offending expression verbatim, in backticks.
2. **The mechanism, with its qualifier** — what the language actually does here, including
   the condition that makes it wrong. This is the part that must never be dropped: prefer
   "requires two arguments, a record and a field name" over "is wrong", and "not available
   in `//#CTL2:COMPILE` mode" over "is not valid".
3. **The consequence** — the compile error, the runtime exception, or the specific input row
   whose emitted value would be wrong.

```
  [ERROR] `isNull($in.0.amount)` — `isNull()` (camelCase) takes two arguments, a record and
    a field index or name, as in `isNull($in.0, "amount")`. The single-argument form does not
    resolve to any overload, so the transform fails to compile. The one-argument null test is
    the lowercase `isnull($in.0.amount)`.
```

**Where the words must come from.** Grounding, never padding. Naming the mechanism, quoting
the metadata that proves a field is nullable, and tracing the input row that fails all count.
Restating the severity, announcing that an issue exists, or rephrasing the fix a second time
do not. A 40-word line that says nothing a 15-word line would not have said is a failure of
this spec, not a satisfaction of it.

**Suggestions do not substitute.** The `SUGGESTIONS:` block carries the fix; the `ISSUES:`
line still has to carry the mechanism on its own. A reader who stops at `ISSUES:` must not
come away with a false belief.

---

## Part 3 — qualifier-sensitive facts

When a record's explanation involves a fact of the form *"X is wrong **in situation C**"* or
*"X requires **form F**"*, the reasoning trace must state the qualifier explicitly, and the
answer line must keep it. Treat these as the shape to watch for:

- **Arity and case distinctions between similarly named built-ins.** Two functions differing
  only in capitalisation or argument count both exist; the call is wrong, the function is not
  imaginary. Say which overload was expected.
- **Constructs whose validity depends on the compilation mode.** A construct available in
  interpreted `//#CTL2` but not `//#CTL2:COMPILE` is not "invalid CTL2" — name the mode.
- **Format-pattern letters.** A pattern letter with the wrong case usually denotes a real but
  different field (day-of-year rather than day-of-month, week-based year rather than calendar
  year, minutes rather than month). It is a misuse, not a syntax error — say what it actually
  means.
- **Type rules that hold only in one direction.** Widening that is automatic one way and an
  error the other; assignments legal for one type pair and not its reverse.

In each case the trace should reach the qualifier *before* the answer states the conclusion,
so the qualifier is the reason for the finding rather than an afterthought that compression
can strip.

---

## Format — must match exactly

Records go into the reasoning corpus, so every record carries a reasoning trace.

**Emit the reasoning as a separate `reasoning_content` field — do not write `<think>` tags
by hand.** Each assistant message has two fields: `content` holds the answer alone,
`reasoning_content` holds the thinking.

```json
{
  "id": "multibug_001",
  "messages": [
    {"role": "user", "content": "Validate the following CTL2 code. …"},
    {"role": "assistant",
     "reasoning_content": "Six things to check. The output metadata declares result, provider and amount only, so the assignment to date_start has no target field and will not compile. isNull is called with one argument; the camelCase form takes a record plus a field name, so this is an arity error rather than an unknown function …",
     "content": "ISSUES:\n  [ERROR] `isNull($in.0.amount)` — `isNull()` (camelCase) takes two arguments …\nSUGGESTIONS:\n  - Use `isnull($in.0.amount)` for the single-value null test.\nVERDICT: FAIL"}
  ]
}
```

A separate script, `convert_think.py`, merges the two fields into the tagged form the trainer
needs:

```bash
python3 convert_think.py CTL_LoRAT_reasoning_v2.json -o CTL_LoRA_training_data_think.json
```

**Leave the tagging to that script — never hand-write `<think>` tags in authored records.**
The merge step needs an exact literal spelling (`"<think>\n"` … `"\n</think>\n\n"`) to be
stripped correctly by the training pipeline; a hand-typed variant that is off by one
character fails silently and trains the reasoning text *with* loss where it should have none.

**Validate answers** use this exact structure, with no prose outside it:

```
ISSUES:
  [ERROR] <construct, mechanism with its qualifier, concrete consequence>
  [WARNING] <construct, why it is suspicious, why it still runs correctly>
SUGGESTIONS:
  - <the fix>
VERDICT: FAIL
```

**Reasoning length scales with defect count.** The existing single-defect target is a median
of ~240 tokens. For these records, budget roughly **240 tokens plus ~120 per defect beyond
the first** — a six-defect review reasons in about 800 tokens. The trace must address every
defect it will report; a trace that reasons about two defects and then lists six is the exact
failure this spec exists to prevent.

Every record needs `id`, `messages`, and the `source_file` / `source_index` / `source_id`
fields if it was generated by modifying an existing record.

---

## Verification

**Run this on the file of newly authored records, not on the merged corpus.** The word floor
is a rule for new records; the 300 validate records already in the reasoning corpus average
21 words per line, so 391 of their 422 issue lines fail it. Rewriting them is a separate
decision — see Internal tracking — and pointing this script at the merged file will bury the
new records' results under that backlog.

```python
import json, re, statistics as st, collections
R = json.load(open('CTL_LoRAT_reasoning_v2.json'))
A   = lambda e: [m for m in e['messages'] if m['role'] == 'assistant']
ans = lambda e: "".join(m.get('content', '') for m in A(e))
rea = lambda e: "".join(m.get('reasoning_content', '') for m in A(e))

def issue_lines(a):
    if 'ISSUES:' not in a:
        return []
    body = a.split('ISSUES:', 1)[1].split('SUGGESTIONS:')[0].split('VERDICT:')[0]
    return [l.strip() for l in body.splitlines()
            if re.match(r'\s*\[(ERROR|WARNING|INFO)\]', l) and 'No issues found' not in l]

recs = [(e, issue_lines(ans(e))) for e in R]
recs = [(e, L) for e, L in recs if L]
print('validate-format records:', len(recs))

short = [(e.get('id'), len(l.split()), l[:70])
         for e, L in recs for l in L if len(l.split()) < 35]
print('issue lines under 35 words (want 0):', len(short))
for s in short[:5]:
    print('   ', s)

by_n = collections.defaultdict(list)
for e, L in recs:
    by_n[len(L)].append(st.mean([len(l.split()) for l in L]))
print('mean words/finding by finding count (all should be >=35, and must NOT decline):')
for n in sorted(by_n):
    print(f'    {n} findings: {len(by_n[n]):4d} records, {st.mean(by_n[n]):.1f} w/finding')

multi = sum(1 for _, L in recs if len(L) >= 4)
print(f'records with >=4 findings: {multi} ({100*multi/len(recs):.1f}%)  -- target >=12%')

tok = [(len(re.findall(r'\S+', rea(e))) * 4 // 3, len(L)) for e, L in recs]
under = [(t, n) for t, n in tok if t < 240 + 120 * (n - 1) * 0.7]
print('traces below ~70% of the scaled reasoning budget (want few):', len(under))
```

Then convert and confirm the tagging:

```bash
python3 convert_think.py CTL_LoRAT_reasoning_v2.json -o CTL_LoRA_training_data_think.json
python3 -c "
import json
B = json.load(open('CTL_LoRA_training_data_think.json'))
a = lambda e: ''.join(m['content'] for m in e['messages'] if m['role']=='assistant')
bad = [e.get('id') for e in B if not ('<think>\n' in a(e) and '\n</think>\n\n' in a(e))]
print('records:', len(B), '| wrong thought-word spelling (want 0):', len(bad), bad[:5])
print('reasoning_content left over (want 0):',
      sum(1 for e in B for m in e['messages'] if 'reasoning_content' in m))
"
```

After authoring, run `dedup_reasoning.py` against the SFT source files, since new records
built from existing ones supersede their originals, and rebuild both corpus files.

### Measured baseline, 2026-09-23

Before this amendment, across 1094 validate-format records in the phase-1 corpus and 300 in
the reasoning corpus:

```
words per issue line: median 19  (p10 10, p90 33)
mean words/finding by finding count:  1 -> 22.9   2 -> 19.1   3 -> 18.7   4 -> 18.4   5 -> 17.4
records with >=4 findings:  phase-1 48/1094 (4.4%)   reasoning 6/300 (2.0%)
```

Two things to move: the floor (19 → ≥35) and the slope, which currently runs the wrong way —
explanations get *shorter* as the review gets harder. After the amendment the w/finding row
should be flat or rising.

In the reasoning corpus specifically, **391 of 422 issue lines are under 35 words**. The ~40
new records will not by themselves outweigh 213 single-finding records averaging 21 words, so
expect this to be a two-step job: add the multi-defect records first, measure, and only widen
to a corpus-wide revision if the multi-defect records alone do not move the per-finding word
count at inference.

---

## Internal tracking (not part of the generation brief above)

This section is for people tracking this project's evaluation results. It is not an
instruction to the generating agent.

Motivation and evidence are in `spec/ctl2_training_findings.md` §3.8. Summary: pooled across
`qwen38_fix1` and `qwen38_fix2` validate runs, the share of runs containing a WRONG finding is
45% below 20 words per reported finding and 3% at or above 35 — a 15× swing, holding within
each model separately. The false claims the models produce appear **zero** times in the
corpus while the correct qualified statements appear 22 and 45 times, so this is truncation,
not learned misinformation.

This amendment is the follow-up to `spec/targeted_examples_spec.md`, whose ~91 records
produced `qwen38_fix2`: validate 0.7885 → 0.8462 (best measured, beating the 0917 baseline's
0.8034), CAUGHT 74.2% → 81.7%, false-positive traps 8 → 4, but WRONG 6.5% → 10.8% as a direct
consequence of reporting more findings inside a fixed answer budget.

**Scope decision still open: revise the existing 300?** This spec as written only governs new
records. The existing reasoning corpus has 391 of 422 issue lines under the floor, and the
model's inference-time behaviour is not a pure copy of corpus line length (it produces ~38
words per finding on single-finding reviews against the corpus's 21.3), so the multi-defect
records in Part 1 may be sufficient on their own. Measure after this amendment lands; a
corpus-wide rewrite is ~300 records and should not be started on a hunch.

**Sequencing.** Land this before writing more severity examples. Group A's ERROR-side records
in the targeted spec had no measurable effect on under-escalation (T16, T18 unchanged), and
one plausible reason is that those records are single-finding and short — they teach the label
without room for the reasoning that justifies it. Re-test under-escalation after this
amendment before concluding the ERROR-side approach itself failed.

**Success criteria** on the next retrain, at `--runs 3`, T=0.4, counting **validate tests
only** (see findings §4.3):

| | fix2 | target |
|---|---|---|
| WRONG rate | 10.8% | ≤ 6.5% — back to fix1's level *without* losing recall |
| CAUGHT rate | 81.7% | hold ≥ 80% |
| false-positive traps | 4/61 | ≤ 4 |
| median words per reported finding | ~20 on multi-bug runs | ≥ 30 |
| validate score | 0.8462 | ≥ 0.85 |
