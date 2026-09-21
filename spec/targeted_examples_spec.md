# Targeted training examples — three named defects

**~85 records, not a bulk expansion.** The corpus is no longer volume-limited. As of
`qwen38_fix1` (2026-09-21) the model scores **0.9715 on generate with 17 of 25 tests
perfect**, and its validate losses trace to three specific rules it has not learned. This
spec targets those three. Adding more general reasoning traces will not move them.

## Priority, and why

The ranking criterion is **precision over recall**: a correct-but-incomplete review is
preferred over a complete one containing a misclassification. A wrong finding sends a
developer to fix something that is not broken, or downgrades something that will fail in
production; a missing finding merely leaves them where they started.

So a record that teaches the model to *stop making a wrong claim* is worth more than one
that teaches it to find an extra bug.

| # | defect | records | tests affected | current |
|---|---|---|---|---|
| A | ERROR vs WARNING severity | ~50 | T24, T16, T18 | T24 **0.50** |
| B | Rollup vs Denormalizer `$in.0` port access | ~20 | T22 | T22 0.75, 3 FP traps |
| C | Outer-join null guard on the key field | ~15 | T34 | T34 0.88 |

---

## A — severity: ERROR vs WARNING (~50 records)

**The rule the model must learn:**

> **ERROR** — the code cannot compile, or will certainly fail at runtime, or provably emits
> wrong data. **WARNING** — syntactically valid and it will run, but probably not what was
> meant. A WARNING does not by itself make the verdict FAIL.

The model is wrong in **both directions**, so this is miscalibration, not a bias that a
single nudge fixes. Measured on `qwen38_fix1`:

| test | the code | model said | required |
|---|---|---|---|
| T24 | `date2str(d, "DD/MM/YYYY")` — valid, runs, means day-of-year | ERROR → FAIL | **WARNING → PASS** |
| T16 | `return 2;` after an unconditional return — unreachable | WARNING | **ERROR** |
| T18 | `lookup(X).get(k).unit_price` with no null guard | WARNING | **ERROR** |

T24's over-escalation alone triggered **4 of fix1's 8** false-positive traps.

The distinction is not "how bad does it look" but **"can you name the failure?"** — the
suite's own wording:

> *"Before … listing an ISSUE, state the concrete failure it causes: a compile error, a
> runtime CTLException, or a specific input row whose emitted output would be wrong. If you
> cannot name that failure, it is NOT an issue."*

Apply that test one step further: if you can name a failure, it is ERROR. If the code runs
to completion on every input the prompt describes but the *intent* looks wrong, it is
WARNING and the verdict stays PASS.

**Write ~50 records, balanced across both directions — roughly 25 each.** An unbalanced set
will simply move the bias.

**WARNING side (valid, runs, suspicious).** Draw on: date/time pattern letters (`DD`, `YYYY`,
`mm`, `hh` vs `HH`); a literal that is valid but implausible; defensive code beyond the
prompt (an extra null check or divide-by-zero guard is **never** a defect — see the suite's
addendum C); a dead store that a later unconditional assignment overwrites; naming or
formatting that contradicts an apparent convention. Verdict **PASS**.

**ERROR side (certain failure).** Draw on: an invented or misspelled function; wrong arity or
a nonexistent overload; unreachable code; an ordered comparison against null; an integer
literal above 2^31−1 without the `L` suffix; dereferencing a value that is null on a
provable path; writing `$out` in a function where the contract forbids it; an unconditional
divide-by-zero. Verdict **FAIL**.

Make roughly a third of the WARNING records contain **one genuine ERROR alongside** a
suspicious-but-valid construct, so the model must assign two different severities in one
answer rather than picking a mode for the whole review. The reasoning must say, for each,
which failure it can or cannot name.

---

## B — Rollup and Denormalizer have *opposite* `$in.0` rules (~20 records)

The model has learned the Denormalizer rule and applies it to Rollup, where it is
explicitly wrong. This produced 3 of fix1's 8 trap triggers, and it is a **wrong finding**,
the costliest kind.

The two contracts, verbatim:

| component | rule | source |
|---|---|---|
| **Rollup** | *"reading `$in.0` inside `updateTransform()` or `transform()` is legitimate and **must never be flagged as an ERROR**"* | `componet_contracts.md:55` |
| **Denormalizer** | *"Do not read `$in.0` in `transform()`."* | `componet_contracts.md:415` |

Rollup's contract is broader still: `$in.0.*` is readable in **all** of `initGroup`,
`updateGroup`, `finishGroup`, `updateTransform`, `transform` and their `OnError`
counterparts. What Rollup *does* restrict is the other direction — `$out.*` is writable
**only** in `updateTransform`, `transform`, and their `OnError` forms; writing `$out` in
`initGroup`/`updateGroup`/`finishGroup` is an ERROR.

**Write ~20 records as contrast pairs** — same shape of code, two components, opposite
verdicts:

- **10 Rollup** reading `$in.0` in `transform()` / `updateTransform()` → **not an issue**.
  Verdict PASS (or FAIL for an unrelated seeded bug, with the `$in.0` read explicitly
  *not* listed). Several should be grouped by the very field being read, since that is the
  case fix1 got wrong: grouping by `department_id` and then reading `$in.0.department_id`.
- **5 Denormalizer** reading `$in.0` in `transform()` → **ERROR**, with the fix being to
  capture the value during `append()` and reset it in `clean()`.
- **5 Rollup** writing `$out` in `initGroup`/`updateGroup`/`finishGroup` → **ERROR**, so the
  model learns Rollup's actual restriction rather than concluding "Rollup has no rules".

Each reasoning trace must **name the component before applying a rule**. The failure mode is
pattern-matching `$in.0` inside `transform()` without checking which component's
`transform()` it is.

> **Sequencing note.** `spec/data_fix_spec_round3.md` adds 12 Denormalizer records that
> reinforce "never read `$in.0` in `transform()`". Those fixes are correct, but landing them
> without this group will deepen exactly this over-generalisation. Apply B and round-3
> together, or B first.

---

## C — outer-join guards test the key, not a payload field (~15 records)

In all three runs of T34, the model guarded a LEFT OUTER join with
`isnull($in.1.account_name)` instead of `isnull($in.1.account_id)`. A matched record whose
nullable `account_name` happens to be null is then misclassified as unmatched — wrong
output, no error raised. Systematic across runs, so it is a learned habit, not sampling.

> **Rule:** detect a join miss by testing the **join key** — the field the join is performed
> on, which is non-null in every matched record. Never test a nullable payload field.

**Write ~15 records**, mixed generate and validate, across `ExtHashJoin` and `ExtMergeJoin`,
LEFT OUTER and FULL OUTER. Include metadata in the prompt where the payload field is
explicitly `nullable="true"` and the key is `nullable="false"`, so the reasoning can cite it.
At least 5 should be validate records where the *candidate code* makes the mistake and the
answer flags it as ERROR, naming the input row that would be misclassified.

---

## Format — must match exactly

Records go in the reasoning corpus (`CTL_LoRAT_reasoning_v2.json` or a sibling merged into
it), so every record carries a `<think>` block.

**Thought-word spelling is load-bearing.** LlamaFactory matches the literal strings
`"<think>\n"` and `"\n</think>\n\n"`. Any other spelling and `remove_thought()` silently
fails to strip the block, which then trains **with loss** in phase 1 — the opposite of what
the pipeline intends. The assistant content must be exactly:

```
<think>
{reasoning}
</think>

{answer}
```

**Validate answers** use the corpus format, with no prose outside it:

```
ISSUES:
  [ERROR] <what fails, and the failure it causes>
  [WARNING] <what is suspicious, and why it still runs>
SUGGESTIONS:
  - <the fix>
VERDICT: FAIL
```

Use `ISSUES:\n  [INFO] No issues found.` with `VERDICT: PASS` for a clean review.

**Reasoning length: target a median of ~240 tokens, p10 ≥ 200, p90 ≤ 300.** Length must come
from *grounding*, never from padding: quote the metadata before relying on it, cite the
contract line before applying it, trace the specific input row that fails. A trace that
restates the answer or announces conclusions is rejected regardless of token count. For
group A especially, the trace must state which concrete failure it can name — that reasoning
*is* the severity decision.

Every record needs `id`, `messages`, and the `source_file` / `source_index` / `source_id`
fields if generated from an existing record.

---

## Verification

```bash
python3 - <<'PY'
import json, re, statistics as st, collections
R = json.load(open('CTL_LoRAT_reasoning_v2.json'))
a = lambda e: "".join(m['content'] for m in e['messages'] if m['role'] == 'assistant')
u = lambda e: next(m['content'] for m in e['messages'] if m['role'] == 'user')
bad = [e['id'] for e in R if not ('<think>\n' in a(e) and '\n</think>\n\n' in a(e))]
print('wrong thought-word spelling (want 0):', len(bad), bad[:5])
tok = [len(re.findall(r'\S+', a(e).split('</think>')[0])) * 4 // 3 for e in R]
print('reasoning tokens: median %d  p10 %d  p90 %d' % (
    st.median(tok), sorted(tok)[len(tok)//10], sorted(tok)[9*len(tok)//10]))
sev = collections.Counter()
for e in R:
    ans = a(e).split('</think>')[-1]
    for s in ('[ERROR]', '[WARNING]', '[INFO]'):
        sev[s] += ans.count(s)
print('severity mix:', dict(sev))
v = collections.Counter(re.findall(r'VERDICT:\s*(\w+)', a(e))[-1]
                        for e in R if 'VERDICT:' in a(e))
print('verdicts:', dict(v))
dup = [p for p, n in collections.Counter(u(e).strip() for e in R).items() if n > 1]
print('duplicate prompts (want 0):', len(dup))
PY
```

**Measured baseline**, run against the 752-record reasoning corpus on 2026-09-21:

```
reasoning tokens: median 124  p10 61  p90 260     <- the 452 older traces pull this down;
                                                     the 300 v2 traces sit at median ~244
severity mix: [ERROR] 218  [WARNING] 124  [INFO] 49
verdicts:     FAIL 162  PASS 132
```

**ERROR outnumbers WARNING 1.8 : 1.** That is the likeliest source of the T24
over-escalation, and it is the number this work has to move. Group A's ~25 WARNING-side
records should bring the ratio close to 1.3 : 1 and the verdicts near even. Check the mix
before and after; if ERROR is still climbing, the set is unbalanced and will make T24 worse
rather than better.

New records should sit at the v2 length (median ~240), not the corpus median of 124 — the
older short traces are the ones the dose curve found least useful.

Then run `dedup_reasoning.py` against the SFT sources, since new records built from existing
ones supersede their originals, and rebuild both corpus files.

## How to tell whether it worked

Retrain and evaluate at `--runs 3`, T=0.4. The measurement is **not** the suite score, which
weights a missed finding the same as a wrong one. Split the validate findings:

| | fix1 baseline | target |
|---|---|---|
| WRONG findings | 6% | ↓ |
| triggered FP traps | 8 | **↓ — the headline number** |
| T24 | 0.50 | ≥ 0.85 |
| T22 trap triggers | 3 | 0 |
| T34 | 0.88 | ≥ 0.96 |
| CAUGHT | 74% | hold — do not trade precision away for it |
