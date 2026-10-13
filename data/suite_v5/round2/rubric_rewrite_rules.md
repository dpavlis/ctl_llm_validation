# Rubric rewrite rules (round 2b, 2026-10-13)

The round-2 rubrics in `data/suite_v5/generate_rw.json` copy the prompt clauses (161 of 259 required
items verbatim), bundle 3–5 edge cases per item, list no alternatives, and carry boilerplate
rationales. Rewrite the `rubric.required` and `rubric.forbidden` of each test. **Do not change the
prompt, the reference or anything else.**

## How the judge works

The judge (an LLM) sees: the system prompt and `user_message` sent to the model, the rubric, the
model's answer, and `resources/ctl2-basics.md`. It does **not** see `reference`. It marks each
required item PRESENT / PARTIAL / MISSING / WRONG and each forbidden item present / absent. Score =
fraction of required items met, minus 0.2 per forbidden item present.

## Required items (8–12 per test)

1. **Atomic.** One observable behaviour per item: one edge case, one decision, one output field
   rule. Missing one edge case must cost one item, not a bundle. Split clauses that carry several
   edge cases; merge nothing that a model could get half right.
2. **Decidable from the code.** Phrase each item as what the code must do, checkable by reading it
   ("trims `payment_term_txt` and upper-cases it before comparing with NET30/NET60"). No upstream
   guarantees, example values, cross-run behaviour, or documentation/comment requirements.
3. **Alternatives.** List every valid CTL2 form inline: "(either X, Y, or Z)". Common ones:
   - reset of per-parent / per-group state: in `count()`, `clean()`, `initGroup()`, at the end of
     `transform()`, or by fresh local declarations;
   - a parse guard: strict `isDate(...)` before `str2date`, a regex shape check, the conditional-fail
     form `str2date(...) : null` (valid in `//#CTL2`), or a try-style OnError path — whichever the
     spec allows to yield the required result;
   - lookup miss: `rec == null`, `isnull(rec)`, or `count(...) > 0` before `get`;
   - parameters: `getParamValue("P")` or `"${P}"`;
   - joining: `join(sep, list)` or concatenation with correct separators;
   - blank test: `isBlank(x)`, `trim(nvl(x,"")) == ""`, or `x == null || trim(x) == ""` — whichever
     matches the spec's null/empty distinction;
   - copy-through: `$out.0.* = $in.0.*;` (copies by field name, skips missing fields) or explicit
     per-field assignment;
   - emit return: for single-output components `OK`, `0` or `ALL`; for a multi-output Reformat the
     port index (or `ALL` only where the spec wants every port).
4. **Specific `.1`.** Item `.1` states the actual entry contract of this component (e.g. "Normalizer:
   `count()` returns the number of children and `transform(integer idx)` builds child idx" or
   "two-output Reformat: `transform()` returns 0 for accepted rows and 1 for rejected rows"), not a
   generic "uses the contract correctly". Don't spend more than one item on the contract.
5. **Every numbered clause** of the prompt is covered by at least one item (`clauses` lists them).
6. **Rationale:** one sentence specific to the item: the failure the item catches (e.g. "strict
   str2date throws on 2025-02-30, so parsing first loses the DATE reason"). No boilerplate.
7. **Weight the discriminators.** Spend items on the behaviours a quick solution gets wrong (the
   test's `difficulty_traps`, the round-1 failure modes, the reviewers' notes), not on things every
   answer does. Avoid free items ("emits rows", "uses CTL2").

## Forbidden items (2–4 per test)

Only defects that are wrong at runtime or against the spec, specific to this test: e.g. a bare
declared variable tested with `== null` / `isnull()` as a first-record sentinel (it starts at
0 / "" / epoch / empty, never null); returning `STOP` from DataGenerator `generate()`; writing the
Denormalizer winner to `$out.0` in `append()`; letting a parse exception escape where the spec
requires a defined result; integer division for a decimal ratio; state not reset per group. Never
penalise a style choice or a valid alternative listed in the required items. Do not make a
forbidden item the mirror of a required item (that double-penalises one mistake).

## CTL2 and runtime facts (verified; use them, and accept what they allow)

- Owner rulings: `spec/ctl2_training_findings.md` §7 and `resources/ctl2-basics.md`. Declared
  variables start at type defaults (integer/long 0, string "", boolean false, date epoch, list/map
  empty); only variant/byte/cbyte start null. Metadata fields are nullable unless
  `nullable="false"`. Rollup accumulator fields are reset from metadata each group (explicit reset
  optional; global variables still need a manual reset). All five Rollup functions required; a
  Rollup `transform`/`updateTransform` is called repeatedly (counter 0,1,…) until it returns SKIP.
  Denormalizer `transform()` reads `$in.0` = last record; writing `$out.0` in `append()` has no effect.
  `==` / `!=` are null-safe.
- Live runs (data/suite_v5/validation_report.json → facts_for_judge_reference):
  `str2decimal("")` throws; strict `isDate(s,"yyyy-MM-dd",...,true)` is false for 2025-02-30 and
  2025-1-1 and strict `str2date` throws on both (trailing characters unverified — keep an explicit
  shape check where the spec requires it); DataGenerator `recordsNumber=0` never calls `generate()`;
  **DataIntersection CTL writes the matched record to `$out.0` (emitted on physical port 1); writing
  `$out.1` fails at init; OK/0/1/ALL emit, SKIP drops, STOP → ERROR** (ctl2-basics §8.9 still says
  `$out.1` and is being corrected — follow the runs); Denormalizer reset at end of `transform()` ≡
  reset in `clean()`; simple-lookup duplicates need `keyDuplicates=true`, `get` returns null on a
  miss and `next()` iterates duplicates; date functions without a timezone use the host timezone
  (CET), so UTC business dates need the `"UTC"` arguments; full-outer ExtMergeJoin transforms
  matched and one-sided records on output 0 with the absent side's fields null; Normalizer has one
  output and `count()` = 0 emits nothing; `RUN_ID` is reserved (tests use `AUDIT_RUN_ID`);
  `length()` counts UTF-16 units; `round(decimal, n)` rounds half away from zero.
- If an item needs a fact the judge cannot know from ctl2-basics.md or the prompt, put the fact in
  the item text itself ("…(strict str2date throws on an impossible date)…").

## Output

Write `data/suite_v5/round2/rubric_rewrite_<first>_<last>.json`:

```json
{"T44": {"required": [{"id": "T44.1", "check": "...", "rationale": "...", "clauses": [1]}],
         "forbidden": [{"id": "T44.F1", "check": "...", "rationale": "..."}],
         "notes": "anything the owner should know (spec gaps you could not fix in the rubric)"}}
```

Ids `T<nn>.<k>` from 1 and `T<nn>.F<k>` from 1. Before writing, check every item against the
reference and the recorded run (`data/suite_v5/run_graphs/<TID>/`, `graph_run_results.json`): the
reference must pass every required item and trigger no forbidden item.
