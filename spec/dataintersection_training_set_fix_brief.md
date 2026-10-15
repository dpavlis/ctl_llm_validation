# DataIntersection training set, round 2: remove the `$out.0` hints, add whole-component prompts, add DPO against per-port CTL

**Revise `CTL_LoRA_dataintersection_sft.json` (60) and `CTL_LoRA_DPO_dataintersection.jsonl` (40)** in
`ctl_lora_training/sft_training_data/`. Keep the counts, the format and the validation standard of round 1
(`logs/CTL_LoRA_dataintersection_validation.json`). This brief does for the DataIntersection set what
`spec/scd2_training_set_fix_brief.md` did for the SCD-2 set.

DPO pairs are referred to by their **line number in the file, counting from 1**.

## Why

The audit found **no wrong code or claim**:
- no SFT answer and no DPO chosen answer uses `$out.1`, `$out.2`, `getOutputPort()` or a callback other than
  `transform()`;
- di_sft_052 (a fix task) correctly removes a `$out.1` reference.

Keep all of that. The problem is that **the set never makes the model decide anything about the output record**, so
it doesn't help on real prompts. OPCD run c11 trained on these prompts and still fails suite v5 T53 in every sample:
- all 10 thinking-off answers write `$out.1` / `$out.2`;
- c10 routed with `getOutputPort()`;
- c11 now invents per-port callbacks (`transformMatched()`, `transformUnmatched()`, `transformRightOnly()` …) that
  the component never calls, and puts the reconciliation logic in them. T53 thinking-off fell from 0.48 to 0.14.

T53 and T54 ask for "the complete CTL2 for this component only, including its required entry functions", with three
connected consumers. That is how users ask, and the set has no prompt like it.

### 1. Every code prompt gives the answer away

All 28 code prompts state the mechanism in the user turn:
- "For CTL, physical output1 is represented by the single local `$out.0` record";
- "The middle-output transform has one local output record (`$out.0`)";
- "Write the result into local transform record `$out.0`, which feeds physical1";
- "the transform output schema shown below belongs to `$out.0` and physical port1";
- "The CTL transform exposes the middle record as `$out.0`".

The teacher saw the same prompts, so neither SFT nor OPCD ever produced a signal for an unhinted prompt.

**Remove the hint** from these prompts:
- **SFT code prompts (28):** di_sft_012, 019, 024, 031–043, 045–053, 055–057;
- **SFT prose prompts (12):** di_sft_007, 014, 018, 022, 023, 025, 026, 044, 054, 058, 059, 060 (check each one:
  keep the wording where the question itself is about the local record, as in a validate or fix task whose code
  is wrong);
- **DPO prompts (17):** lines 2, 6, 12, 14, 16, 17, 18, 22, 23, 24, 25, 26, 27, 30, 35, 39, 40.

**What may stay in a prompt:** the graph wiring in business terms ("removals read output 0, matched reconciliation
output 1, additions output 2"), the metadata of each port, and the join key.

**What must go:**
- `$out.0`, "local output record", "middle record";
- "matched transform" / "middle-output transform" when it tells the model that the CTL handles only the matched
  stream. Replace it with the business requirement ("emit one reconciliation row per matched pair");
- "side outputs preserve their inputs" / "unmatched outputs retain their input metadata" when it tells the model that
  ports 0 and 2 need no CTL.

The answer carries the knowledge instead. Every code answer whose prompt mentions the side outputs adds one sentence:
- the transform runs only for matched pairs and writes `$out.0`;
- DataIntersection sends that record to output 1;
- outputs 0 and 2 pass the one-sided records through unchanged, with no CTL.

### 2. No prompt asks for the whole component

**Add 10 SFT generate tasks** in the T53/T54 framing:
- "Write the complete CTL for this DataIntersection" (or "… including its entry functions");
- all three outputs connected to named consumers, with the removal/addition consumers described as needing the
  one-sided records unchanged;
- the matched-pair logic is a realistic reconciliation (null-safe comparison, a change list, a status code, `SKIP`
  for unchanged pairs where the spec says to drop them).

The answer is a single `transform()` that writes `$out.0` and returns an emitting value, plus the sentence from
section 1.

Vary the scenarios:
- 3 with `Allow key duplicates` (Cartesian pairs, state reset per call);
- 3 where the business wording makes per-port handling tempting ("additions must be flagged NEW", "removals need a
  reason code"). The answer says this cannot be done inside DataIntersection and names the downstream Reformat or
  Map;
- 4 plain reconciliations.

**Make room** by rewriting 10 of the 32 prose examples into these tasks. Pick the prose examples that repeat a point
another example already makes. The SFT then has 38 code tasks and 22 prose tasks.

### 3. DPO pairs hardly ever reject the per-port mistake

Only 3 of the 40 rejected answers target it:
- line 22 (`$out.1.id`);
- line 23 (`getOutputPort()`);
- line 24 (prose about the output index).

**Rewrite 8 of the 30 prose pairs** (your choice; keep the ones testing join-key, duplicate and null-key facts) into
code pairs on whole-component prompts from section 2. Each rejected answer differs from the chosen one in one point:
- 2 × the matched logic writes `$out.1` instead of `$out.0`;
- 1 × the A-only / B-only records are written to `$out.0` / `$out.2` in `transform()`;
- 2 × an invented callback (`transformMatched()`, `transformUnmatched()`, `transformLeft()` …) carries the logic and
  `transform()` is left trivial or missing;
- 1 × `getOutputPort()` or a returned port number is used to route records;
- 1 × the A-only records are flagged inside DataIntersection (the right answer moves this to a downstream
  Reformat);
- 1 × `$in.2` or a third-input assumption.

Use the same prompts in the SFT-generate style: no hints (section 1), and the scenarios differ from the 10 new SFT
tasks.

### 4. Run-together words

Put the spaces back, as for the SCD-2 set. These are mostly `physical1`, `output0`, `output2`, `on0`, `on2`,
`input0`, `input1`, `port1` and `ports0/1/2`. Affected SFT prompts (34):
- di_sft_005, 020, 023, 030;
- di_sft_031–060.

The DPO prompts have none. Use a regex pass, then re-read.

## Form

- **Answers stay short and answer-only:** code plus 1–3 sentences; explanations of a few sentences.
- **Each DPO pair still differs in one point only.**
- **No overlap:**
  - don't reuse the scenarios of suite v5 T53 (contract snapshot reconciliation with duplicate pairs) and T54
    (loyalty membership notices), or of `llama_train/data/opcd/generate_gaps.jsonl` and the hard cases;
  - check with 5-gram Jaccard < 0.30 against them, and within the set with field names masked.

## Validation

Same as round 1, for every new or changed example:
- `ctl_validate` for every CTL block;
- a real graph run in `MiscExamples/dataintersection/` (never `DPOForge`) for every new generate answer, with all
  three outputs connected and the record counts on each output checked, plus runIds;
- for the rejected DPO answers in section 3: compile or run them and record how they fail (initialization error,
  missing records, …), so each pair's "wrong" is evidence, not opinion;
- update `logs/CTL_LoRA_dataintersection_validation.json` (counts, task mix, compiler and runtime results, the hint
  check, diversity).

---

## Internal tracking (not part of the brief)

- Evidence: c11 (2026-10-15) T53 off 0.48 → 0.14, T53 on 0.50 → 0.58, T54 ≈ flat; c11 holdouts DI +0.04/+0.05.
- The SCD-2 set passed the same audit (no hints, no run-together words, correct component contracts).
- After the revision: re-run the c11 teacher check on T53/T54 with the unhinted prompts, then rebuild the DI group.
