# Rollup validate set: missing lifecycle functions and accumulator initialisation

> **Correction, 2026-10-23 (findings §3.30):** the premise below is wrong for the plain rebuilds. rb1011 catches T22's
> missing functions thinking off in 43/40 of 45 samples, and rb1009s2 in 45/19. The miss is specific to rb1009 and the
> OPCD line built on it. Trained into rb1012 (two seeds), the set did not raise catching (29–34/45), and both seeds
> regressed on the accumulator explanation, cause not found. The set is delivered but not in the default recipe.

**Write one new set in `ctl_lora_training/sft_training_data/`,** in the format and to the validation standard of the
Rollup accumulator set (round 2):

| file | records |
|---|---|
| `CTL_LoRA_rollup_lifecycle_validate_sft.json` | 50 SFT |
| `CTL_LoRA_DPO_rollup_lifecycle_validate.jsonl` | 25 DPO pairs |

## Why

Every model we have trained misses missing Rollup lifecycle functions when it reviews code without thinking. In the suite
test that measures this (a Rollup with three of the five functions, plus an accumulator field that is never initialised):
- **Thinking off:** all 9 recent models miss both absent functions in 20 of 20 samples.
- **Thinking on:** the absent functions are usually found, but the uninitialised accumulator field is explained wrongly
  in nearly every sample ("an integer field starts at 0").

**The corpus covers this thinly.** Of its 70 Rollup validate examples:
- 16 omit only `updateTransform`, and 8 omit `finishGroup` (7 of them together with `updateTransform`);
- none omits `initGroup`, `updateGroup` or `transform`;
- an absent function combined with another real defect appears about 7 times.

The model has learned to look for `updateTransform` sometimes, not to check all five.

## The facts

All of these were run-verified on the CloverDX server; cite the run ids in the log.
- **All five functions are mandatory:** `initGroup`, `updateGroup`, `finishGroup`, `updateTransform`, `transform`.
  - If any is missing, the component **fails at initialization**: `Component initialization failed. Required
    function(s) finishGroup(), updateTransform() are missing!` (runs 21965–21968, 2026-10-22).
  - The graph fails before any record is processed. It does **not** run and silently emit nothing.
- **Return values control invocation, not definition.**
  - `updateGroup()` returning false means `updateTransform()` is not called for that record; it must still be defined.
  - `finishGroup()` returning false means the group emits nothing; it must still be defined.
- **Accumulator reset** (`ctl2-basics.md` §8.7, corrected 2026-10-22; live probe run 5465): before each group, every field
  is reset from the accumulator metadata.
  - nullable without a default → null;
  - nullable **with** a default → still null;
  - non-nullable without a default → its type's zero value;
  - non-nullable with a default → that default.

  Omitted nullability, including an accumulator described in prose ("count (integer), total (decimal)"), means nullable.
- **Declared CTL variables** (global or local) start at their type default, never null. Keep this rule apart from
  accumulator fields.
- **Every Rollup group has at least one record.** A plain per-group count incremented in `updateGroup()` is at least 1
  in `transform()`. A divide-by-zero guard on it is not a required fix; only a conditional count can be 0.
- **`transform()` may read `$in.0`**, e.g. the group key.

## Content

### SFT (50)

| task | count | shape |
|---|---|---|
| validate | ~40 | `ISSUES:` / `SUGGESTIONS:` / `VERDICT:`, answer-only (no thinking) |
| fix-to-spec | ~10 | "Fix … so that it compiles and does what the specification says. List every problem you fix with the reason, then give the complete corrected code." |

**Coverage across the set:**
- **Each function missing:** each of the five lifecycle functions is absent in at least 6 examples. Include `initGroup`,
  `updateGroup` and `transform`, which the corpus never omits.
- **How many are missing:** 1, 2 and 3 functions in about equal shares.
- **Absence plus another defect:** about half the examples with an absent function also contain a different real defect,
  for example:
  - a nullable accumulator field never initialised and then used in arithmetic (the T22 shape; the field may be described
    in metadata or in prose);
  - a wrong output field;
  - a conditional count used as a divisor without a guard.
- **Complete code:** about 15 examples define all five functions.
  - About half are PASS. Their tempting non-bugs: `updateGroup` returning false with an `updateTransform` that returns
    `SKIP`, the plain count divisor, `$in.0` in `transform()`, a non-nullable accumulator field used without
    initialisation.
  - The rest have a different real defect.

  These keep the model from reporting a function as missing when it is present.
- **Misnamed functions:** 4 examples where a function is present but misnamed (`finishgroup`, `updateTranform`) or written
  in Java style. Run them and state in the answer what the server reports.
- **Order and length:**
  - Vary the function order. Some put `transform` first.
  - Vary the length: about a third should be 60–120 lines, where an absent function is easy to overlook.

**Answer pattern (validate):**
- Report each absent function as its own `[ERROR]` line naming it, never as "the lifecycle is incomplete".
- State the consequence correctly: the component fails at initialization ("Required function(s) X are missing!").
- Give the missing function's correct signature in `SUGGESTIONS`.
- Explain accumulator findings with the reset rule above and name the field's nullability.
- Keep each finding at 25 words or more. Shorter findings truncate true facts into false ones.

**Answer pattern (fix-to-spec):** list each added function with its reason, then give the complete code with all five
functions.

### DPO (25)

Each rejected answer differs from the chosen one in one point:

| rejected answer | pairs |
|---|---|
| names only one of two absent functions | 6 |
| reports the absent function as "the group emits nothing" / "transform() is unreachable", instead of the init failure | 3 |
| explains a nullable accumulator field as starting at 0 (findings otherwise identical) | 5 |
| flags `updateGroup` returning false as a bug | 3 |
| demands a divide-by-zero guard on a plain per-group count | 3 |
| reports a present function as missing, on complete code | 5 |

## Form

- **No hints in the user turn.** Write "Validate this Rollup transform …" with the metadata and the code. Never write
  "check the lifecycle functions" or "all five functions are required".
- **Metadata:**
  - realistic and varied: tables, field lists, CloverDX XML, short prose;
  - nullability stated on some accumulator fields and omitted on others;
  - grouping keys with domain names, of varied types, and two-field keys in at least 8 examples.
- **Diversity:**
  - no opening phrase (first five words) in more than 5 prompts;
  - no explanation sentence of 12 or more words in more than 3 answers;
  - code similarity (identifiers, numbers and strings masked; `difflib` ratio ≥ 0.90): at most 40 pairs. Report it as in
    the accumulator set's log.

## No overlap

**Do not reuse these scenarios:**
- suite v4 T6 (order Rollup), T22 (department salary Rollup), T36, T37, T41 (warehouse stock);
- suite v5 T57 (receipt Rollup);
- `llama_train/data/opcd/hard_cases3.jsonl`;
- the Rollup accumulator set and the Rollup update-transform set.

**Check:** 5-gram Jaccard below 0.30 against all of them, with field names masked.

## Validation

- **Compiler:** every CTL block passes `ctl_validate`, except the intended missing- or misnamed-function cases. For those,
  record the server's initialization error.
- **Runtime:** sandbox `MiscExamples`, folder `rollup_lifecycle/`, never `DPOForge`; 8–15 input records with at least
  one single-record group and one group with nulls in the accumulated field.
  - Every complete example and every corrected fix-to-spec answer runs.
  - Every absent-function example runs and records its init failure.
- **Rejected DPO answers:** record how each is wrong.
- **Claims:** every factual claim is in `ctl2-basics.md` or backed by a probe run id.
- **Independent review:** a reviewer re-derives 10 answers from the user turn alone and lists, for each, the five
  functions and which are absent.

## Deliverables

In `ctl_lora_training/sft_training_data/`:
- the two data files above;
- `logs/CTL_LoRA_rollup_lifecycle_validate_validation.json`, with:
  - counts and task mix;
  - the per-function absence counts and the combination table;
  - compiler and runtime results with run ids;
  - the hint check, diversity, the overlap check and the review;
- graphs and fixtures under `logs/rollup_lifecycle_runtime/`.

The `CTL_LoRA_DPO_` prefix is required: the rebuild script reads DPO pairs only from `CTL_LoRA_DPO_*.jsonl`.

---

## Internal tracking (not part of the brief)

- **Evidence:** findings §3.27 (review correction) and §3.28.
  - T22 thinking off: B4/B5 missed 20/20 for every model.
  - T22 thinking on: c13c 0.442, c14 0.300 (n20); B1 WRONG in 20/20 and 17/20.
  - Live lifecycle probe, 2026-10-22: runs 21964 (reference passes) and 21965–21968 (init failures). The T6.7 and T22.B5
    rubric text ("the group emits nothing") was corrected to the init failure the same day; scoring is unchanged.
- **Use:** the next rebuild, or as OPCD prompts. The rebuild corpus is answer-only, so thinking-off validate WRONG should not
  rise (watch it, §3.26).
- **Gates:**
  - T22 at n20 in both modes; success is B4/B5 caught in at least half of thinking-off samples;
  - thinking-off validate ×9, with WRONG reported excluding T18/T22;
  - T6, T36 and T37 at n10, to check for false "missing function" findings.
