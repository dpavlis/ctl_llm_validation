# Rollup accumulator and Normalizer sets, round 2: less templating in the Rollup set, sequence keys in the Normalizer set

**Revise the four files delivered in `ctl_lora_training` `e12bc6c`:**
- `CTL_LoRA_rollup_accumulator_sft.json` (50) and `CTL_LoRA_DPO_rollup_accumulator.jsonl` (30);
- `CTL_LoRA_normalizer_multirow_sft.json` (40) and `CTL_LoRA_DPO_normalizer_multirow.jsonl` (20).

Keep the counts, the format, the facts and the validation standard. `spec/rollup_normalizer_corpus_brief.md` still
applies; this brief says what to change.

## What is good

- **Correctness:** the facts are right, every answer was compiled and run, and the DPO pairs differ in exactly the
  intended point.
- **Prompts and answers:** no prompt contains a mechanism hint, and every Rollup answer defines all five lifecycle
  functions.
- **Normalizer pattern:** every Normalizer answer follows the requested pattern: decide once in `count()`, a branch →
  rows table, state reset on every call.

Keep all of that.

## Set A (Rollup): reduce the templating

The set teaches the facts in too few shapes. In training that weights a handful of examples many times over.

1. **The grouping key is `group_code` in all 80 prompts.** Use domain names (`station_id`, `policy_no`, `batch_key`, …)
   and vary the type (string, integer, long). Give at least 10 examples a **two-field key**.
2. **Most accumulators carry a `rows` counter and most outputs a `record_count`.** Keep a record counter in at most half
   of the examples, and vary its name.
3. **Prompt openings repeat:**
   - 49 of 80 start with "The reporting job processes …";
   - 16 start with "For this CloverDX Rollup …".

   No opening phrase (first five words) may appear in more than 5 prompts. Vary the metadata layout too: tables, field
   lists, CloverDX XML and short prose.
4. **The code answers form one large cluster.** With identifiers, literals and strings masked, these answers are at
   least 90% alike, each with 7–14 others:
   - rollup_acc_sft_001–005, 008–010, 012–016;
   - rollup_acc_sft_036, 037, 041–045.

   **Rewrite about 12 of them** into different accumulation shapes:
   - a conditional count that can really be 0, used as a divisor;
   - a running min/max over dates with nulls;
   - a string join with a separator and a null rule;
   - a first/last value by arrival order;
   - several flags combined in `finishGroup()`;
   - a weighted sum with a separate weight total;
   - a Rollup that emits per record through `updateTransform()` and a group total.

   **Target:** at most 60 code-answer pairs at ≥ 0.90 similarity. That is the level of the existing Rollup sets in the
   corpus; the current set has 100. **Measure:** `difflib.SequenceMatcher` ratio on the code with identifiers, numbers
   and strings replaced by placeholders and CTL keywords kept; report it in the log.
5. **Repeated short sentences.** Vary each of these into its own wording:
   - "Read $in.0.group_code when writing the output key." (5 answers);
   - "The independent source-record counter still includes every record." (4);
   - "ISSUES: [ERROR] The complete Rollup omits mandatory finishGroup; …" (4).

Keep the DPO category counts. The DPO prompts follow the same rules (1–3).

## Set B (Normalizer): add sequence keys

**Only 1 of the 33 code answers uses `sequence(…, long).next()`.** The brief asked for it, and versioned outputs need
it. Rewrite these so the requirement includes a new surrogate key:
- **6 generate tasks:**
  - a key taken once per opened version;
  - at least 2 with two openings in one record;
  - at least 2 where some branches open nothing.
- **2 fix tasks:**
  - a key consumed for a non-opening row;
  - `next()` called in both `count()` and `transform()`.
- **1 validate task:** a correct key use that a reviewer might wrongly flag.

Take them from generate tasks that have no key now, so the total stays at 40. In the answers, take the key in `count()`
into a module variable, or at the matching `idx` in `transform()`, and never take it for CLOSE, audit or error rows.
Check the final sequence value in every run.

## Validation

For changed records only, as in round 1:
- compiler;
- a graph run with every branch exercised;
- runs of the rejected DPO answers;
- the overlap checks.

Update both validation logs:
- file hashes;
- the new similarity measure from A4, before and after;
- the opening-phrase count;
- the sentence-repetition count;
- a `round2` list of the changed ids.
