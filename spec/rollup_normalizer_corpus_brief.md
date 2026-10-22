# Two run-verified training sets: Rollup accumulator lifecycle and multi-branch Normalizer counts

**Write two new sets in `ctl_lora_training/sft_training_data/`, in the format and to the validation standard of the
DataIntersection set (round 2b) and the SCD-2 set:**

| set | SFT | DPO |
|---|---|---|
| A. Rollup accumulator lifecycle | 50 | 30 |
| B. Multi-branch Normalizer: `count()` and `transform(idx)` in agreement | 40 | 20 |

## Why

Two weak spots remain after the latest training runs. Training on prompts alone, with a teacher that already answers
correctly, did not fix either of them. One run-verified SFT/DPO round did fix the last comparable gap (DataIntersection
output records), so these go to the corpus.

### A. Rollup accumulator lifecycle

Models fix Rollup code correctly but **explain the accumulator wrongly**:
- "the nullable field `total` starts at 0", when a nullable accumulator field without a metadata default starts null;
- "the accumulator keeps its value from the previous group";
- a divide-by-zero guard on a per-group count, presented as a bug fix;
- "`updateGroup()` returning false discards the record".

In a fix-to-spec task, a correct fix with a false explanation still fails. The suite tests that measure this are a
Rollup fix-to-spec task and a Rollup validate task; do not reuse their scenarios (see "No overlap").

**The facts.** All are in `ctl2-basics.md` §8.7 and §13.3 and were run-verified on the CloverDX server.
- **The accumulator is reset from its metadata before each group,** never carried over from the previous group.
  - A field without a metadata default starts **null when nullable**. Omitted nullability means nullable.
  - It starts at its **type's zero value when non-nullable**.
  - An explicit metadata **default** supplies the starting value of a **non-nullable** field. A **nullable** field starts
    null even when its metadata defines a default (live probe, run 5465; corrected 2026-10-22).
- **Declared CTL variables** (global or local, not record fields) start at their type default, never null. The
  accumulator is a record, so its fields follow the metadata rules above, not the declared-variable rule.
- **Every group has at least one record,** so a per-group count incremented in `updateGroup()` is at least 1 in
  `transform()`. Only a conditional count (for example "number of back-ordered lines") can be 0.
- **`updateGroup()` returning false** means `updateTransform()` is not called for that record. The accumulation in its
  body still runs.
- **All five lifecycle functions:** `initGroup`, `updateGroup`, `finishGroup`, `updateTransform`, `transform`.
  `finishGroup()` returning false means the group emits nothing.
- **`transform()` may read `$in.0`** (for example the group key, which is constant within the group).
- **`++` / `--` are valid** on accumulator fields.

### B. Multi-branch Normalizer counts

On specifications with many branches, models without thinking write a `Normalizer` whose entry functions are right but
whose `count()` disagrees with what `transform(idx)` emits:
- a branch that needs 2 rows returns 1;
- an audit row is counted but never built, or built but not counted;
- a silent branch returns 1 instead of 0;
- per-record state from the previous input record leaks into the next one.

The suite test that measures this is a tariff/rate SCD ledger Normalizer with about 12 rules: cancel, malformed rate,
unchanged with and without audit, new, replace, repriced audit. Its thinking-off answers miss the count rule in 9 of
10 samples.

## Content

### Set A: Rollup accumulator (50 SFT, 30 DPO)

**SFT task mix:**

| task | count | shape |
|---|---|---|
| fix-to-spec | ~20 | "Fix … so that it compiles and does what the specification says. List every problem you fix with the reason, then give the complete corrected code." Every listed fix carries a one-sentence reason that states the accumulator fact correctly. |
| validate | ~15 | In the `ISSUES:` / `SUGGESTIONS:` / `VERDICT:` format. About a third are PASS cases that contain a tempting non-bug: the count divisor, `updateGroup()` returning false, `$in.0` in `transform()`. |
| generate | ~10 | |
| explanation | ~5 | Short. |

**Cover, across the set:**
- nullable / non-nullable / metadata-default accumulator fields;
- string, decimal, integer, long, date and boolean accumulator fields;
- nulls coming from input fields as well as from the accumulator;
- conditional counts that really can be 0, next to plain counts that cannot.

**Distractors.** Include declared CTL variables (module-level or local) next to the accumulator in some examples, so
the answer has to keep the two rules apart.

**DPO pairs.** Each rejected answer differs in one point:

| rejected answer | pairs |
|---|---|
| explains a nullable accumulator field as starting at 0 (code otherwise identical) | 8 |
| claims carry-over from the previous group | 4 |
| guards a plain per-group count against zero, as a fix | 5 |
| "updateGroup false discards the record" | 4 |
| treats a declared CTL variable as null, next to a correctly handled accumulator | 4 |
| omits `finishGroup()`, or returns false from it | 5 |

### Set B: multi-branch Normalizer (40 SFT, 20 DPO)

**SFT:** about 25 generate, 8 fix and 7 validate tasks. Each specification has **6–12 branches**, and every branch fixes
the number of rows it emits (0, 1, 2 or 3). Vary the domains: SCD ledgers, order lines, inventory moves, policy
endorsements, subscription events, timesheet splits.

**Answer pattern:**
- `count()` computes the per-record decision once, stores it in module-level variables, and returns the row count.
- `transform(idx)` reads only those variables.
- A comment table in `count()` lists branch → rows. This is the habit we want: it makes count/transform agreement
  checkable.
- State is reset at the start of every `count()`.
- `sequence(…, long).next()` is called exactly once per new key, in `count()` or at the matching `idx`.

**DPO pairs.** Each rejected answer differs in one point:

| rejected answer | pairs |
|---|---|
| count off by one on one branch | 6 |
| an audit row built but not counted, or counted but not built | 4 |
| a silent branch returning 1 | 3 |
| state not reset between records | 4 |
| `sequence.next()` called in both `count()` and `transform()` | 3 |

## Form

As in the DataIntersection round-2b and SCD-2 sets:
- **Answer-only:** no thinking traces. Code plus 1–3 sentences; fix answers list each fix with its reason.
- **No mechanism hints in the user turn.** State the requirement and the metadata, not the CTL. Never write "the
  accumulator starts null", "count() must return 2" or "reset state in count()".
- **Vary the wording of explanations:** no sentence of 12 or more words in more than 3 answers.
- **Realistic metadata,** with nullability stated explicitly on some fields and omitted on others (omitted means
  nullable).

## No overlap

**Do not reuse these scenarios:**
- suite v4 T22 (department salary Rollup) and T41 (warehouse stock Rollup with back-orders);
- suite v5 T57 (receipt Rollup) and T60 (tariff ledger Normalizer);
- the OPCD prompt files `llama_train/data/opcd/hard_cases3.jsonl` and `generate_gaps.jsonl`;
- the SCD-2 set.

**Check** with 5-gram Jaccard < 0.30 against them, and within each set with field names masked.

## Validation

- **Compiler:** every CTL block passes `ctl_validate`.
- **Runtime:** every generate and fix answer runs in a real graph in sandbox `MiscExamples`, folders `rollup_acc/` and
  `normalizer_multi/` (never `DPOForge`), with 8–15 input records.
  - **Set A:** at least one group with nulls in the accumulated input field, and one group with a single record.
  - **Set B:** every branch exercised at least once, and the output row count per input record checked against the
    specification.
- **Rejected DPO answers:** run each one and record how it fails (wrong rows, a missing audit row, a compile error).
- **Claims:** every factual claim in an explanation is in `ctl2-basics.md` or backed by a probe run with its runId.
- **Independent review:** a reviewer re-derives 10 answers per set from the user turn alone.

## Deliverables

In `ctl_lora_training/sft_training_data/`:
- `CTL_LoRA_rollup_accumulator_sft.json`, `CTL_LoRA_DPO_rollup_accumulator.jsonl`;
- `CTL_LoRA_normalizer_multirow_sft.json`, `CTL_LoRA_DPO_normalizer_multirow.jsonl`;
- `logs/CTL_LoRA_rollup_accumulator_validation.json`, `logs/CTL_LoRA_normalizer_multirow_validation.json`:
  - counts and task mix;
  - compiler and runtime results with runIds;
  - the hint check;
  - diversity;
  - review;
- graphs and fixtures under `logs/rollup_acc_runtime/` and `logs/normalizer_multi_runtime/`.

The `CTL_LoRA_DPO_` prefix is required: the rebuild script reads DPO pairs only from `CTL_LoRA_DPO_*.jsonl`.

---

## Internal tracking (not part of the brief)

- **Evidence:** findings §3.25.
  - T41 at n20: rb1009 0.988, the rulev6 teacher 0.978, c13c 0.815, c13d 0.840 (OPCD with hard set 3 and the rulev7
    Rollup teacher).
  - T22 0.44 for both (teacher 0.72).
  - T60 thinking off: c10 0.71, c13c 0.38; T60.1 missed 9/10.
- **Use:** the next base rebuild (rb1010). It also carries the belief traces from `spec/belief_durability_plan.md` Part B
  and the harness-derived data.
- **Gates on rb1010:** T41/T22 at n20; T60 thinking off at n10; the existing rebuild gates (`scripts/rb1009_eval.sh`).
- **Watch:** thinking-off validate WRONG, which rose with every thinking-heavy corpus addition (rb1008). These sets are
  answer-only, so this is not expected.
