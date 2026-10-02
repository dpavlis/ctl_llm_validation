# Targeted DPO repairs — round 2

**Fix the 59 repaired pairs that failed acceptance, and bring three reference documents in line
with three rulings.** This continues `dpo_targeted_repairs_spec.md` (round 1). Every rule of
round 1 still applies, unless a ruling below changes it. Everything above "Internal tracking" is
the brief.

You are working in the `ctl_lora_training` repository:

| path | what it is |
|---|---|
| `sft_training_data/CTL_LoRAT_DPO_targeted_repairs.jsonl` | your 113 round-1 pairs |
| `sft_training_data/CTL_LoRAT_DPO_targeted_repairs_round2_feedback.jsonl` | **the input**: one line per pair that needs attention |
| `sft_training_data/CTL_LoRAT_DPO_repair_candidates.jsonl` | the original candidates, unchanged |
| `references/CTL2_Reference_for_LLM_compact.md`, `references/ctl-function-library.json`, `sft_training_data/componet_contracts.md` | the references |

## What happened in acceptance

Each round-1 chosen side went through:
- the format, function-library and known-false-belief checks;
- a reference judge (gpt-6-sol, comparing against the corpus reference answer);
- a claims audit of the chosen trace and answer.

**53 of the 113 pairs passed and are final. Don't touch them.** The other 60 are in the feedback
file:
- 59 have `status: needs_round2`;
- one has `status: accepted_by_ruling` (no action needed).

Each feedback line lists `items`. Each item has a `source`:
- `judge`;
- `claims_audit`;
- `belief_scan`;
- `manual_review`: a human-checked finding, which is always correct.

And each item has a `status`:
- `verify_and_fix`: check it. If it is right, fix it.
- `overruled`: a ruling below makes the item wrong. Ignore it, provided the field read in
  `transform()` really is the group key. If it isn't, treat the item as `verify_and_fix`.

The judge and the audit are still fallible. Single judgements flip on about 15% of boundary
cases. As in round 1:
- verify every `verify_and_fix` item against the references;
- if an item is wrong, keep the text and record the item under `judge_items_rejected`, with
  evidence;
- an item you find wrong is not a reason to skip the pair.

## Rulings (the user's, final)

These override any reference document that disagrees, and any grader note.

1. **`return STOP;` aborts the component.** It is not a normal termination.
   - DataGenerator `generate()` must return `OK` or `ALL`. Returning `STOP` there is an
     **ERROR**, even behind a guard that the configured record count makes unreachable.
   - The component configuration sets the record count.
   - Line 386 of `CTL2_Reference_for_LLM_compact.md` ("DataGenerator: normal termination") is
     wrong.
2. **Denormalizer `transform()` may read `$in.0`, which holds the last input record of the
   group.**
   - Reading a group key there is valid.
   - A value that varies within the group must still be saved during `append()`, for example
     when the task asks for the first record's value.
   - The "Read $in.0 only in append()" and "Do not read $in.0 in transform()" rules in
     `componet_contracts.md` are wrong. Your round-1 analysis was right.
3. **A never-assigned non-nullable output field is never null at emission.** It carries its
   type's zero value (`string` `""`, `integer`/`long`/`decimal` `0`, `number` `0.0`).
   - A never-assigned nullable field is null.
   - Rollup accumulator fields are different: one not assigned in `initGroup()` is null.
   - "Unset record fields are null" (compact reference, lines 628 and 1042) is wrong for
     non-nullable output fields.

Some round-1 pairs are now wrong because of ruling 1. Some chosen sides call `STOP` a clean or
normal way to end generation, or keep a `STOP` guard as a WARNING. Fix these wherever the
feedback flags them. Also check every other pair that is not final for the same error.

## Part A — repair the 59 pairs

For each `needs_round2` line:

1. **Start from your round-1 chosen side.** Apply the round-1 rules: minimal edits, the
   model's own voice, no mentions of the reference or judge, and the ratio thresholds
   (trace ≥ 0.85, answer ≥ 0.75), measured **against the original rejected text**.
2. **Resolve every item:**
   - **Fix it** if it is right.
   - **Reject it with evidence** in `judge_items_rejected` if it is wrong.
   - **Drop the pair** if the fix would break the thresholds. Log it as `too_far`.
3. **Re-check the pair as a whole.** Make sure the trace and the answer still agree, and that no
   new false statement crept in. One round-1 repair introduced an error of its own: it declared
   the valid `list[variant]` invalid.
4. **If a different candidate for the same prompt is a better start, you may replace the pair
   with it.** Use the round-1 procedure, and put the old pair id in `replaces`.

Write the results to **`sft_training_data/CTL_LoRAT_DPO_targeted_repairs_round2.jsonl`**:
- Use the same schema as round 1, plus:
  - `"round": 2`;
  - `"replaces"`, when a pair was replaced;
  - `"feedback_resolution"`: for each feedback item, `{"text": <first 120 characters>,
    "resolution": "fixed" | "rejected" | "overruled", "note": ...}`.
- Keep the same `id` for repaired pairs.
- Write **only** the pairs you touched. The 53 final pairs stay in the round-1 file. Don't
  rewrite that file.
- Write the `edits` list as real sentence- or phrase-level changes. Round 1's list was a
  character-level diff, with entries like `"igh" -> "p"`, which documents nothing. One entry per
  meaningful change is enough.

Add a **"Round 2"** section to `CTL_LoRAT_DPO_targeted_repairs_log.md`:
- counts of fixed, dropped and replaced pairs;
- the feedback items you rejected, grouped by theme, with evidence;
- anything new in the reference conflicts.

## Part B — apply the rulings to the reference documents

Make the smallest edits that state the three rulings correctly:

- `references/CTL2_Reference_for_LLM_compact.md`:
  - line 386 (`STOP`), per ruling 1;
  - lines 628 and 1042 (unset record fields), per ruling 3.
- `sft_training_data/componet_contracts.md`:
  - the Denormalizer port model and access rules (section (c), around line 325; section (f),
    around line 365), per ruling 2;
  - check the DataGenerator section stays consistent with ruling 1 (it already says
    "STOP means ABORT").
- Search both documents for other statements of the three old beliefs, and fix them the same
  way.
- Don't edit corpus records. List the corpus records that now contradict the rulings, with ids,
  in the log's "Round 2" section. Round 1's "Reference answers that need correction" list is a
  starting point; the Denormalizer entries there are confirmed by ruling 2.

Commit Part A and Part B as two separate commits, and push.

---

## Internal tracking

Not part of the brief.

- **Acceptance artifacts:**
  - `llama_train/data/self_distill/dporep/acceptance_pass1_oldref.jsonl`: pass 1, run against
    `resources/ctl2-basics.md` before the rulings;
  - `acceptance.jsonl`: pass 2, run after `ctl2-basics.md` was corrected for rulings 1–3;
  - pass agreement: 45 pairs passed both and 55 failed both; 13 flipped.
- **Feedback** built from pass 2, plus one manual finding. Five judge items were marked
  `overruled` by ruling 2 (Denormalizer group-key reads).
- **On return:**
  - run acceptance again on the round-2 pairs, with two passes;
  - final set = the 53 final round-1 pairs + 1 accepted by ruling + the round-2 pairs that pass
    both judgements;
  - then convert, NLL check, train (single-GPU DPO on base, `dpo_logps_chunk_size: 1024`) and
    evaluate, as in round 1's Internal tracking.
