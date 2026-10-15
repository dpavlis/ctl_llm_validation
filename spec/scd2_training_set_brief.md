# SCD type 2 training set: 60 SFT examples and 40 DPO pairs

**Write a run-verified training set for slowly changing dimension type 2 (SCD-2) versioning in CTL2:**
- 60 SFT examples;
- 40 DPO pairs.

It mirrors the DataIntersection set (`ctl_lora_training/sft_training_data/CTL_LoRA_dataintersection_sft.json`,
`CTL_LoRA_DPO_dataintersection.jsonl` after its rename, `logs/CTL_LoRA_dataintersection_validation.json`) in format, size and validation standard.

## Why

The CTL2 corpus has no SCD-2 examples. Every model variant scores lowest on these tasks:
- suite v5 T60, an SCD Normalizer: 0.45–0.59 with thinking off;
- T61, versioning carried across consecutive records: 0.53–0.69.

OPCD run c9 improved them with thinking off, but its thinking-on SCD answers got worse. A teacher with the component
guide in context reached only 0.68. The knowledge is missing from the corpus.

What models get wrong (judge notes, suite v5 and the OPCD gap prompts):
- **Change detection:**
  - inverted logic (`!(a || b)` where "any attribute differs" was meant);
  - null-unsafe comparison;
  - "null → empty string" or "null → 0" not counted as a change when the spec says it is.
- **Row order and content:**
  - CLOSE must come before OPEN;
  - the closing row must carry the *previous* version's values and `valid_from`, not the new ones;
  - a brand-new key must emit OPEN only.
- **Keys:**
  - take the surrogate key from the sequence exactly once per opening, never for CLOSE or audit rows;
  - `sequence(Name, long).next()` when the key is long;
  - never call `current()` before `next()`.
- **Dates:**
  - `valid_to` as "the day before the effective date" must be computed in UTC;
  - `dateAdd(d, -1, day)` uses the host calendar and shifts by an hour across DST on a CET host; fixed milliseconds or
    a UTC rebuild don't (`ctl2-basics.md` §13.3).
- **State across records (Reformat over consecutive rows of the same key):**
  - detect the first row of a key with a flag or a key change, not by testing a declared variable for null (it starts
    at `""` / 0 / epoch);
  - reset the carried version when the key changes.
- **Component contract:**
  - Normalizer emits several rows per input through `count()` + `transform(integer idx)`, and has exactly one output;
  - a two-output Reformat routes by returning the port index, with `ALL` only when both ports should get the row;
  - writing Normalizer-style `transform(idx)` inside a Reformat is wrong.
- **Unchanged rows:** dropped with `SKIP`, or emitted as an audit row, exactly as the spec says.

## Content

**SFT (60):** about 10 explanations, 25 generate, 13 validate and 12 fix tasks. Spread them over:

| topic | examples |
|---|---|
| change detection (null-safe, which attributes count, null vs empty) | 10 |
| CLOSE / OPEN / audit row content and order | 10 |
| surrogate keys from a sequence (once per opening, long) | 8 |
| `valid_from` / `valid_to` / `is_current`, UTC day boundaries, DST | 8 |
| state across consecutive records of a key (Reformat), first record, key change | 10 |
| component choice and contract: Normalizer multi-row vs two-output Reformat vs Rollup | 8 |
| unchanged and deleted (retired) keys, reopen after retirement | 6 |

**DPO (40):** one plausible wrong answer per pair, each targeting one bullet from "Why":
- inverted change logic;
- a sequence value taken for CLOSE rows;
- `dateAdd(…, day)` in place of a UTC day;
- a closing row with the new values;
- a declared-variable `== null` first-row test;
- `transform(idx)` in a Reformat;
- `ALL` sending a closing row to both ports;
- and so on.

The chosen and rejected answers differ only in that one point.

**Form**, as in the DataIntersection set:
- Answer-only, with no thinking traces. Answers are short: code plus 1–3 sentences, or for explanations a direct
  answer of a few sentences.
- Realistic business scenarios with metadata where the task needs it.
- **No hints in the user turn:** state the requirement, not the mechanism.
- The same system prompt as the DataIntersection DPO file.

**No overlap:**
- Don't reuse the scenarios of suite v5 T59–T61 (account dimension, tariff versions, service regions), the OPCD gap
  prompts `llama_train/data/opcd/generate_gaps.jsonl` (G4), or the hard cases.
- Check with 5-gram Jaccard < 0.30 against them, and within the set with field names masked (no templated
  skeletons).

## Validation

- **Compiler:** every CTL block passes `ctl_validate` (or compiles inside its graph when it uses a sequence).
- **Runtime:** every generate and fix answer runs in a real graph on the CloverDX server, in sandbox `MiscExamples`,
  folder `scd2/` (never `DPOForge`). Use 8–15 input records covering the example's edge cases, and compare the output
  with the expected output derived from the spec by hand. Include at least one case that crosses a DST change for
  every example that computes `valid_to`.
- **Explanations and DPO pairs:** every factual claim is either in `ctl2-basics.md` or backed by a probe run recorded
  with its runId.
- **Independent review:** a fresh reviewer re-derives 10 answers from the user turn alone.

## Deliverables

In `ctl_lora_training/sft_training_data/`:
- `CTL_LoRA_scd2_sft.json`: a list of `{"id": "scd2_sft_001", "messages": [{"role": "user", …}, {"role": "assistant", …}], "reviewed_date": "…"}`.
- `CTL_LoRA_DPO_scd2.jsonl`: one `{"prompt", "chosen", "rejected", "system", "reviewed_date"}` per line. The
  `CTL_LoRA_DPO_` prefix is required: the base-rebuild script reads DPO pairs only from `CTL_LoRA_DPO_*.jsonl`.
- `logs/CTL_LoRA_scd2_validation.json`, with the same fields as the DataIntersection log: counts, coverage per topic
  and task kind, compiler results, runtime results with runIds, diversity, semantic review.
- Graphs and fixtures under `logs/scd2_runtime/`.
- If a runtime fact is new, a short note added to `componet_contracts.md`.

---

## Internal tracking (not part of the brief)

- **c11** = c10's recipe plus two new gap groups:
  - DataIntersection: prompts from the 60 DI SFT user turns;
  - SCD-2: prompts from these 60 SFT user turns.
- Hold out about 10 per group for measurement.
- Teacher: rb1006 + rulev3 + the component guide (DataIntersection, Normalizer or Reformat) + §8.9 / §13.3. The
  verified SFT answer could also go in as a worked example, SDFT-style; teacher-check both variants.
- Gates as for c9, plus T53/T54 and T60/T61 at n10 in both modes.
- The SFT/DPO files also go into the next base rebuild automatically (`data/build_sft_rebuild.py` reads every
  `sft_training_data/*.json` and `CTL_LoRA_DPO_*.jsonl`). The DataIntersection DPO file is being renamed by the owner to
  match that pattern.
