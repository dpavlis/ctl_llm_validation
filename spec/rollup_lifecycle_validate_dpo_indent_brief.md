# Rollup lifecycle validate set, round 3: indent the code in nine DPO prompts

**One small change to `CTL_LoRA_DPO_rollup_lifecycle_validate.jsonl`** (`ctl_lora_training` `79a1430`). Round 2 indented the
SFT code; the DPO prompts were not in that brief.

## What to change

In DPO lines 1–9 (`lifecycle_dpo_001`–`009`), the CTL code in the **user turn** (`prompt`) has no indentation inside
function bodies. Indent it like every other record in the set: 4 spaces per block level.
- Change only whitespace at the start of lines. Keep every line and its order, so the code and the runtime outcome stay
  the same.
- The chosen and rejected answers need no change. Both are already formatted, and none cites line numbers.

## Validation

- **Whitespace-only check:** for each of the 9 records, the prompt with leading whitespace stripped from every line
  must equal the round-2 prompt stripped the same way. Record the check in the log.
- **Rerun:** compile and run the 9 graphs again, with the indented code, and confirm the expected outcomes are unchanged.
- **Log:** update the file hash and add a `round3` list of the 9 ids to
  `logs/CTL_LoRA_rollup_lifecycle_validate_validation.json`.
- **Commit:** commit the data, the log and the updated graphs together.
