# Targeted training examples — three CTL2 defect patterns

**~85 records total, not a bulk expansion.** Everything below this line, up to the
"Internal tracking" section at the end, is a self-contained brief for generating CTL2
training examples. It assumes CTL2 knowledge (the language, the ETL component model, and
the `ISSUES:` / `SUGGESTIONS:` / `VERDICT:` review format below) but no other context.

## Priority, and why

The ranking criterion for a validate review is **precision over recall**: a correct-but-
incomplete review is preferred over a complete one containing a misclassification. A wrong
finding sends a developer to fix something that is not broken, or downgrades something that
will fail in production; a missing finding merely leaves them where they started.

So a record that teaches "do not claim X is a defect when it is not" is worth at least as
much as one that teaches "find defect Y."

| group | topic | records |
|---|---|---|
| A | ERROR vs WARNING severity calibration | ~50 |
| B | Rollup vs Denormalizer `$in.0` read access | ~20 |
| C | Outer-join null guards must test the join key | ~15 |

---

## A — severity: ERROR vs WARNING (~50 records)

**The rule to teach:**

> **ERROR** — the code cannot compile, or will certainly fail at runtime, or provably emits
> wrong data for some input the prompt describes. **WARNING** — syntactically valid, it will
> run to completion, but it probably does not do what was intended. A WARNING alone does not
> make the verdict FAIL.

The test to apply, stated precisely: **before writing an ISSUE, try to name the concrete
failure it causes** — a compile error, a specific runtime exception, or a specific input row
whose emitted output would be wrong. If you can name that failure, the finding is ERROR. If
the code runs correctly on every input the prompt describes but the choice looks like a
mistake, the finding is WARNING and the verdict stays PASS.

Generate examples that require calibrating this distinction in **both directions** — a model
trained on only one direction will simply move its bias rather than correct it.

**Write ~50 records, balanced roughly 25/25 between the two sides below.**

**WARNING side — valid code, runs correctly, looks suspicious.** Generate CTL2 Reformat /
Filter / Joiner validate examples built around constructs like these, each one syntactically
valid and semantically consistent with the surrounding metadata, so there is no failure to
name:

- Date/time format-pattern strings that are valid but likely mean something other than what
  the field name or comment implies — e.g. `"DD/MM/YYYY"` where `DD` is day-of-year (1–366)
  rather than day-of-month (`dd`), `"YYYY-ww"` mixing a week-based year token with a
  calendar-year token, or `"hh:mm"` where `mm` is minutes but the field is named
  `formatted_month`.
- A literal value that is technically valid for its type and passes any declared constraints,
  but is implausible for the described domain (e.g. an `age` field assigned `250`, a
  percentage assigned `140`).
- Defensive code that goes beyond what the prompt's failure scenario requires — an extra null
  check, an extra divide-by-zero guard, or a redundant bounds check that can never be
  triggered by the described inputs. This is **never** a defect by itself: flag it, if at
  all, as an `[INFO]` style-only note, never `[WARNING]` or `[ERROR]`, and never let it change
  the verdict.
- A dead store: a local variable or field assigned a value that is unconditionally
  overwritten before it is read, where the final result is unaffected. This is a code-quality
  observation (`[WARNING]`), not a correctness defect, because the output is unchanged.
- Naming or formatting that is inconsistent with an established convention visible elsewhere
  in the same file (e.g. every other output field is `snake_case` and one is `camelCase`),
  where the value itself is still computed and typed correctly.

Each of these gets `[WARNING]` in `ISSUES:` (or is omitted entirely if minor), and
`VERDICT: PASS` unless an unrelated genuine ERROR is also present (see below).

**ERROR side — certain failure.** Generate examples built around constructs like these,
each one provably broken:

- A call to a function that does not exist in the CTL2 standard library, or a real function
  called with the wrong number of arguments or an argument type it does not accept.
- Unreachable code: statements following an unconditional `return`, `break`, `continue`, or
  `raise`/`error()` at the same block level, so they can never execute.
- A relational comparison (`<`, `>`, `<=`, `>=`) against a value that is `null` on some input
  path the prompt describes — CTL2 comparisons against null do not behave like normal
  ordering and this yields a wrong result rather than an exception, so name the input row
  that is misclassified.
- An integer literal above `2147483647` (2³¹−1) written without the `L` suffix, which
  overflows the `int` type it is assigned to or compared against.
- Dereferencing a field or map/list lookup result that is provably `null` on some input the
  metadata or prompt describes (e.g. reading `.unit_price` off the result of a `lookup()`
  call whose key is not guaranteed to match, with no null check first).
- Writing to `$out.*` inside a component lifecycle function where the component's contract
  forbids writing output at that stage (see Group B for the Rollup/Denormalizer specifics).
- An unconditional division or modulo where the divisor can be zero for some input the
  prompt describes, with no guard.

Each of these gets `[ERROR]` in `ISSUES:`, names the specific failure (the input row, the
exception, or the wrong emitted value), and `VERDICT: FAIL`.

**Combine the two sides in roughly a third of the WARNING-side records:** put one genuine
ERROR-side construct alongside a WARNING-side construct in the same snippet, so a single
review must assign two different severities rather than picking one mode for the whole
answer. The reasoning trace must address each construct separately and state, for each,
whether a concrete failure can be named.

---

## B — Rollup and Denormalizer have *opposite* `$in.0` rules (~20 records)

Two CTL2 ETL components — Rollup and Denormalizer — have contradictory rules about reading
`$in.0` (the current input record) inside their transform-stage functions, and a review must
apply the rule for the specific component in front of it, never the other one's rule.

**Rollup**, from its component contract: reading `$in.0.*` inside `transform()` or
`updateTransform()` (and their `OnError` counterparts) is legitimate and expected —
`$in.0` there refers to the current record contributing to the group, and this **must never
be flagged as an ERROR or WARNING**. Rollup's actual restriction runs the other direction:
`$out.*` may only be **written** inside `updateTransform()`, `transform()`, and their
`OnError` forms. Writing to `$out.*` inside `initGroup()`, `updateGroup()`, or
`finishGroup()` is an ERROR, because those stages run before or between group members and
have no current output record context.

**Denormalizer**, from its component contract: do **not** read `$in.0` inside `transform()`.
By the point `transform()` runs, the record being built has already been accumulated across
multiple `append()` calls, and `$in.0` inside `transform()` refers to unrelated, stale
state — reading it there is an ERROR. The correct pattern is to capture any value needed from
the input during `append()` (storing it in a global or accumulator variable) and to reset that
state in `clean()` between groups.

**Write ~20 records as contrast pairs** — matched code shapes across the two components,
with opposite verdicts, so the reasoning must identify which component it is looking at
before applying either rule:

- **10 Rollup records** where `transform()` or `updateTransform()` reads `$in.0.<field>` —
  this is correct and must not be flagged. Verdict PASS, unless an unrelated genuine defect
  is seeded elsewhere in the same snippet — in that case the `$in.0` read must be explicitly
  *absent* from the ISSUES list, not merely unaddressed. Include some records where the
  Rollup is grouping by a field (e.g. `department_id`) and also reads that same field via
  `$in.0.department_id` inside `transform()`, since that specific shape is the one most
  likely to be miscategorized as suspicious.
- **5 Denormalizer records** where `transform()` reads `$in.0.<field>` — this is an ERROR.
  The suggested fix captures the value in `append()` into an accumulator/global variable and
  clears it in `clean()`.
- **5 Rollup records** where `$out.*` is written inside `initGroup()`, `updateGroup()`, or
  `finishGroup()` — this is an ERROR, teaching the restriction that does apply to Rollup, so
  the model does not conclude "Rollup has no `$in`/`$out` restrictions at all."

Every reasoning trace in this group must **name the component before applying a rule** —
state explicitly "this is a Rollup `transform()`" or "this is a Denormalizer `transform()`"
before citing which access is or is not allowed.

---

## C — outer-join null guards must test the join key (~15 records)

When code checks whether an outer join (`LEFT OUTER` or `FULL OUTER`, via `ExtHashJoin` or
`ExtMergeJoin`) produced a match versus a padding record for the unmatched side, the guard
must test the **join key field** — the field the join condition is actually performed on,
which is guaranteed non-null on every genuinely matched record and null (or the join's
configured null value) on every unmatched/padding record.

Testing a different field from the joined side instead — a nullable payload field that
merely happens to usually be populated — is wrong: any matched record whose payload field is
legitimately null gets misclassified as unmatched, silently producing the wrong branch's
logic with no exception raised. This is a provable-wrong-output defect (ERROR), not a style
issue, because a specific input row (a matched record with that payload field null) can be
named as producing the wrong result.

**Write ~15 records**, mixed between generate tasks (write the join-handling CTL2) and
validate tasks (review CTL2 that already contains this mistake), spread across
`ExtHashJoin` and `ExtMergeJoin`, and across `LEFT OUTER` and `FULL OUTER` join types.

- For generate tasks: the prompt's input metadata should mark the join key field as
  `nullable="false"` and at least one payload field on the joined side as `nullable="true"`,
  so the correct answer must choose the key field for the guard and the reasoning can cite
  the metadata to justify why.
- For at least 5 records, make them validate tasks where the candidate code tests the
  nullable payload field instead of the key, and the correct answer flags this as `[ERROR]`,
  naming the specific scenario: a matched record whose payload field is null but whose join
  key is populated, which the guard would incorrectly treat as unmatched.

---

## Format — must match exactly

Records go into the reasoning corpus, so every record carries a reasoning trace.

**Emit the reasoning as a separate `reasoning_content` field — do not write `<think>` tags
by hand.** Each assistant message has two fields: `content` holds the answer alone,
`reasoning_content` holds the thinking. Nothing else about the message format changes.

```json
{
  "id": "severity_ck_001",
  "messages": [
    {"role": "user", "content": "Validate this Reformat CTL2 …"},
    {"role": "assistant",
     "reasoning_content": "The output metadata declares formatted_date as … so DD is day of year, which compiles and runs. I cannot name a row that fails, so this is WARNING, not ERROR.",
     "content": "ISSUES:\n  [WARNING] `DD` in \"DD/MM/YYYY\" is day-of-year …\nSUGGESTIONS:\n  - Use `dd` for day of month.\nVERDICT: PASS"}
  ]
}
```

A separate script, `convert_think.py`, later merges the two fields into the tagged form the
trainer needs:

```bash
python3 convert_think.py CTL_LoRAT_reasoning_v2.json -o CTL_LoRA_training_data_think.json
```

**Leave the tagging to that script — never hand-write `<think>` tags in authored records.**
The merge step needs an exact literal spelling (`"<think>\n"` … `"\n</think>\n\n"`) to be
stripped correctly by the training pipeline; a hand-typed variant that is off by even one
character fails silently and trains the reasoning text *with* loss where it should have
none. The script is idempotent and will also normalize any tags that slip in, but there is
no upside to hand-tagging and one silent-failure mode to hand-typing it.

A record with no `reasoning_content` still converts — it just gets an empty reasoning
block — so a missing trace is not caught by the merge step itself. Check for it explicitly
(see Verification below).

**Validate answers** use this exact structure, with no prose outside it:

```
ISSUES:
  [ERROR] <what fails, and the failure it causes>
  [WARNING] <what is suspicious, and why it still runs>
SUGGESTIONS:
  - <the fix>
VERDICT: FAIL
```

Use `ISSUES:\n  [INFO] No issues found.` with `VERDICT: PASS` for a clean review with
nothing to flag.

**Reasoning length: target a median of ~240 tokens, p10 ≥ 200, p90 ≤ 300.** Length must come
from *grounding*, never from padding: quote the relevant metadata before relying on it, cite
the specific rule before applying it, and for an ERROR finding, trace the specific input row
that fails. A trace that only restates the answer or announces a conclusion without
justifying it is not acceptable regardless of token count. For Group A especially, the trace
must state explicitly whether a concrete failure can be named — that determination *is* the
severity decision.

Every record needs `id`, `messages`, and the `source_file` / `source_index` / `source_id`
fields if it was generated by modifying an existing record.

---

## Verification

Run this on the authored file, **before** `convert_think.py`:

```python
import json, re, statistics as st, collections
R = json.load(open('CTL_LoRAT_reasoning_v2.json'))
A   = lambda e: [m for m in e['messages'] if m['role'] == 'assistant']
ans = lambda e: "".join(m.get('content', '') for m in A(e))
rea = lambda e: "".join(m.get('reasoning_content', '') for m in A(e))
u   = lambda e: next(m['content'] for m in e['messages'] if m['role'] == 'user')

print('records:', len(R))
print('assistant msgs with no reasoning_content (want 0):',
      sum(1 for e in R for m in A(e) if not m.get('reasoning_content', '').strip()))
print('hand-written <think> tags (want 0 - convert_think.py adds them):',
      sum(1 for e in R if '<think>' in ans(e) or '<think>' in rea(e)))
print('validate answers with no VERDICT (want 0):',
      sum(1 for e in R if 'ISSUES:' in ans(e) and 'VERDICT:' not in ans(e)))

tok = [len(re.findall(r'\S+', rea(e))) * 4 // 3 for e in R]
print('reasoning tokens: median %d  p10 %d  p90 %d   (target 240 / >=200 / <=300)' % (
    st.median(tok), sorted(tok)[len(tok)//10], sorted(tok)[9*len(tok)//10]))

sev = collections.Counter()
for e in R:
    for s in ('[ERROR]', '[WARNING]', '[INFO]'):
        sev[s] += ans(e).count(s)
print('severity mix:', dict(sev),
      '| ERROR:WARNING = %.2f' % (sev['[ERROR]'] / max(1, sev['[WARNING]'])))
print('verdicts:', dict(collections.Counter(
    re.findall(r'VERDICT:\s*(\w+)', ans(e))[-1] for e in R if 'VERDICT:' in ans(e))))
dup = [k for k, n in collections.Counter(u(e).strip() for e in R).items() if n > 1]
print('duplicate prompts (want 0):', len(dup))
```

Then convert, and confirm the tagging came out right. This is the check that catches a
spelling mistake before it costs a multi-hour training run:

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

**Severity balance target.** Measured against the 752-record reasoning corpus before this
work, `[ERROR]` outnumbers `[WARNING]` 1.8:1 (218 vs 124), which is the likely source of an
over-eager ERROR bias. Group A's ~25 WARNING-side records should bring that ratio down
toward roughly 1.3:1. Check the mix before and after adding new records; if `[ERROR]` share
is still climbing, the new set is unbalanced and will reinforce rather than correct the
bias.

**Reasoning length target.** New records should sit at a median of roughly 240 tokens, not
the pre-existing corpus median of ~124 — shorter traces correlate with lower usefulness in
prior measurements on this corpus.

After authoring, run `dedup_reasoning.py` against the SFT source files, since new records
built from existing ones supersede their originals, and rebuild both corpus files.

---

## Internal tracking (not part of the generation brief above)

This section is for people tracking this project's evaluation results. It is not an
instruction to the generating agent and assumes context the sections above do not.

Current suite: `resources/ctl2_test_suite_v4.json`, evaluated at `--runs 3`, T=0.4, against
model `qwen38_fix1`. The three groups above map to specific suite tests that currently score
low or trigger false-positive traps:

| group | maps to suite test | current score / behavior |
|---|---|---|
| A | severity calibration test in the validate suite | 0.50; over-escalation triggered 4 of 8 false-positive trap triggers |
| B | Rollup/Denormalizer `$in.0` test | 0.75, 3 trap triggers |
| C | outer-join key-guard test | 0.88, wrong guard field reproduced in all 3 runs |

**Sequencing note.** `spec/data_fix_spec_round3.md` adds 12 Denormalizer records reinforcing
"never read `$in.0` in `transform()`." Those fixes are correct on their own, but landing them
without Group B above will deepen the over-generalization to Rollup. Apply B and round-3
together, or B first.

Retrain and evaluate at `--runs 3`, T=0.4 once the new records are merged in. The measurement
is **not** the suite score, which weights a missed finding the same as a wrong one — split
the validate findings instead:

| | fix1 baseline | target |
|---|---|---|
| WRONG findings | 6% | ↓ |
| triggered false-positive traps | 8 | ↓ — the headline number |
| severity-calibration test | 0.50 | ≥ 0.85 |
| Rollup/Denormalizer trap triggers | 3 | 0 |
| outer-join key-guard test | 0.88 | ≥ 0.96 |
| CAUGHT rate | 74% | hold — do not trade precision away for it |
