# Corpus corrections, round 2: two new rulings, owner decisions and two restorations

**This follows up `corpus_ruling_corrections_spec.md`, which you implemented in commit `0728a10`.**
Everything from round 1 still applies: minimal edits, the trace and answer kept consistent, ids
kept, `reviewed_date` refreshed on changed records, and every record logged. Everything above
"Internal tracking" is the brief.

You are working in the `ctl_lora_training` repository. The round-1 log is
`sft_training_data/CTL_ruling_corrections_log.md`; this round adds a "Round 2" section to it.

## New owner rulings (final)

5. **Rollup `transform()` may read `$in.0`.**
   - Reading the group key there is valid. It doesn't need to be saved in `updateGroup()` first.
   - Values that vary within the group still belong in the accumulator.
   - Suite test T38 already treats `$in.0` reads in `updateTransform()` and `transform()` as legal.
6. **In a Denormalizer, `append()` accumulates into module-level variables and `transform()`
   builds the output.**
   - Writing `$out.0` in `append()` is **benign but has no effect** on the emitted record. It is
     not a runtime error, not an NPE, and not a compile error.
   - It is a defect only because the value is lost. If the task needs that output and
     `transform()` never sets it, that's a requirement ERROR. Under ruling 3, the field then comes
     out as its type's zero value.

Rulings 1–4 from round 1 stand unchanged.

## Owner decisions on round-1 open items

- **`fixthiscc4_27`:** resolved by ruling 5. Apply it.
- **`fixthiscc4_118`:** the window is **7 elapsed days**: `target_start_date` from today through
  today + 7, inclusive (`0 ≤ dateDiff(target_start_date, today(), day) ≤ 7`). The current
  reference already implements this. **Rewrite the user request so it is unambiguous**; see Part B.
- **`treasoniae_264`:** resolved by ruling 6. Apply it.
- **Evaluation data:** `sft_eval_data/` is used only for training-loss evaluation (the final
  checkpoint is used, not the best-eval-loss one), so it may now be edited. Implement the five
  Part D proposals from round 1; see Part C.

## Part A — reference documents

- **`sft_training_data/componet_contracts.md`:**
  - Rollup section (c): "Read $in.0 only in updateGroup" (around line 148) contradicts ruling 5.
    Restate it as: `$in.0` is read in `updateGroup()` for accumulation and may also be read in
    `updateTransform()` / `transform()`, for example the group key.
  - Denormalizer section: "Wrong: using $out.0 in append()" and "Never write $out.0 in append()"
    (around lines 441 and 455). Keep the advice, but state the reason from ruling 6: the write has
    no effect and the output is built in `transform()`. It is not a failure.
  - Search the whole file for other statements of either old belief.
- **`references/CTL2_Reference_for_LLM_compact.md`:** search for the same two beliefs and fix any
  you find.
- **Skill copies:** apply the same changes to the tracked validator rubric snapshot
  (`sft_eval_data/.codex_skill_edit/…/validation-rubric.md`), and extend
  `references/CTL2_round2_skill_updates.patch` (or add a new patch file) for the installed
  skills.

## Part B — specific training records

| record | file | correction |
|---|---|---|
| `fixthiscc4_27` | `CTL_LoRA_fix_this_code.json` | Ruling 5. Remove the claim that group keys *must* be saved in `updateGroup()` instead of being read from `$in.0` in `transform()`. Either reading `$in.0` there or saved state is acceptable. Keep the code unless it is otherwise wrong, and keep the unrelated summary-only-pattern fix. |
| `fixthiscc4_118` | `CTL_LoRA_fix_this_code.json` | Owner decision. In the **user request**, replace "within the next 7 calendar days including today" with unambiguous wording that matches the reference: from today through 7 days after today, inclusive (0–7 days ahead). Check that the reference code and explanation match the new wording exactly (`dateDiff(...) >= 0 && dateDiff(...) <= 7`), and that the other bands (14/21/28-day lead times) are untouched. |
| `treasoniae_264` | `CTL_LoRAT_reasoning_v2.json` | Ruling 6. The current finding says output fields "may be written only in `transform()`", as a contract violation. Restate it: the `$out.0.invoice_id` write in `append()` has no effect on the emitted record. If `transform()` never sets `invoice_id`, the emitted value is `""` (ruling 3), which is the real defect; keep it as ERROR when the output needs `invoice_id`. The repair stays: assign it in `transform()` (reading `$in.0.invoice_id` there is valid by ruling 2). Align the trace. |
| `validateb8_191` | `CTL_LoRA_validate_examples.json` | **Restore an over-correction.** Round 1 removed the `group_key` finding along with its false "remains null" reason. The output lists `group_key`, but the code never assigns it, so every group is emitted with `group_key` = `""` and the key is lost. Add back an `[ERROR]` saying exactly that (not "null"), with the suggestion `$out.0.group_key = $in.0.group_key;` in `transform()` (valid by ruling 2). Keep the other current findings; the verdict stays FAIL. |

While working through these files, fix any other passage that contradicts ruling 5 or 6, and log
it. A scan run on the llama_train side found no other explicit statements of either belief in the
training corpus, so few or none are expected.

## Part C — evaluation data (now editable)

Implement the five round-1 Part D proposals in `sft_eval_data/`, with the same minimal-edit
rules:

| record | file(s) | correction |
|---|---|---|
| `dpo-eval-001` | `CTL_LoRA_DPO_eval.jsonl` | Ruling 4. In the chosen side's `appendOnError`, add `printLog(error, "appendOnError failed: " + errorMessage);` and return `SKIP`. Leave `rejected` unchanged. |
| `eval-thinking-refresh-003` | `CTL_LoRA_eval_data.json`, `CTL_LoRA_eval_data_think.json`, `CTL_LoRA_eval_data_think_src.json` | Ruling 4. Add error logging in `transformOnError`, and keep `OK` and the required populated fallback row. Align the trace in the thinking variants. Keep all three copies consistent. |
| `validation_verdict_holdout_5_002` | `CTL_LoRA_eval_data.json` | Ruling 2. Remove the false ERROR about the invariant `account_id` read and the saved-key suggestion. Keep the `running_total` state-reset ERROR, and keep FAIL. The thinking variants already allow this read; make this copy match them. |

## Part D — `treasoniae_365`–`369` (restore ERROR)

Round 1 downgraded these five Denormalizer reviews from ERROR/FAIL to WARNING/PASS, on the grounds
that the prompt never explicitly requires the first record. The code saves `first_product` in
`append()` on the first row, but `transform()` emits `$in.0.product_name` (the **last** record,
by ruling 2) into an output field named **`first_value`**. The field name and the captured
variable make the intended behaviour clear, so the mismatch is wrong output: **ERROR, FAIL**.

- The reason must be the wrong value: the last record's product instead of the first. Not "the
  input is unavailable".
- Keep ruling 2's point that reading `order_id` (the group key) in `transform()` is valid.
- Suggestion: `$out.0.first_value = first_product;`.

Restore the ERROR and FAIL in all five records with that reasoning, and align the traces.

## Output

1. The corrected documents, training records and eval records, edited in place.
2. A **"Round 2"** section appended to `sft_training_data/CTL_ruling_corrections_log.md`, with
   one row per record or document touched (file, id, part, outcome, a one-line description), plus
   any extra records found.
3. Validation, as in round 1:
   - every edited file parses, with record counts and ids unchanged;
   - every edited validate answer has a verdict consistent with its severities;
   - every edited code block compiles, or passes the library check.

Commit and push. Make separate commits for the documents and for the records if that's
convenient.

---

## Internal tracking

Not part of the brief.

- **llama_train side, done on 2026-10-03 before this brief:**
  - `resources/ctl2-basics.md` (judge reference): §8.7 now says Rollup transform reads `$in.0`;
    §8.4 now says an `$out.0` write in `append()` has no effect.
  - Working `resources/ctl2_test_suite_v4.json`: T2's rationale no longer claims an NPE. The
    frozen `results/eval_snapshot_20261001/` copy is unchanged, so suite scores stay comparable.
  - Memories saved: rollup-transform-reads-input, denormalizer-append-out-no-effect,
    sft-eval-data-is-training-eval.
- **Scan on 2026-10-03:** no explicit ruling-5/6 contradictions in the training corpus outside
  the named records. The only hits were in `CTL_LoRAT_DPO_repair_candidates.jsonl`, the model's
  own rejected samples, which are not training data. The 88 dporep training pairs contain no
  "append() can populate $out.0" claims.
- **Part D** is my recommendation; the owner can delete it before handing this over.
