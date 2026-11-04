# Corpus corrections — four CTL2 rulings

**Bring the training corpus into line with four rulings by the corpus owner.** About 90
candidate records are listed below. Some are confirmed contradictions and some are
scan hits that may be false positives. Verify each one, correct the ones that really contradict
a ruling, and log the outcome for every record. Everything above "Internal tracking" is the
brief.

You are working in the `ctl_lora_training` repository:

| path | what it is |
|---|---|
| `sft_training_data/*.json`, `*.jsonl` | the training corpus: SFT records (`messages`, with the assistant's `content` and sometimes `orig_reasoning_content`) and DPO pairs (`prompt` / `chosen` / `rejected`) |
| `sft_eval_data/*` | evaluation data: **list only, don't edit** (see Part D) |
| `references/CTL2_Reference_for_LLM_compact.md`, `sft_training_data/componet_contracts.md` | already updated for rulings 1–3 (commit `62ea4ab`) |
| `references/ctl-function-library.json` | the built-in function catalog |
| `sft_training_data/CTL_LoRAT_DPO_targeted_repairs_log.md` | the repair-round log: "Corpus records contradicting the rulings" and "Reference answers that need correction" give per-record notes for Part A |

## The four rulings (final)

1. **`return STOP;` aborts the component.** It is not a normal termination. DataGenerator
   `generate()` must return `OK` or `ALL`. Returning `STOP` (or `SKIP`, or a port index used as a
   stop signal) there is an **ERROR**, even behind a guard that the configured record count makes
   unreachable. The component configuration sets the record count.
2. **Denormalizer `transform()` may read `$in.0`, which holds the last input record of the
   group.**
   - Reading an invariant group key there is valid.
   - A value that varies within the group must still be saved during `append()` when the task
     needs a different record's value, for example the first one. That remains a real
     requirement ERROR. It is just not a blanket "input is unavailable" rule.
   - This ruling is about **Denormalizer only.** Don't extend it to Rollup or other components.
3. **A never-assigned non-nullable output field is never null at emission.** It carries its
   type's zero value (`string` `""`, `integer`/`long`/`decimal` `0`, `number` `0.0`).
   - A never-assigned nullable output field is null.
   - Rollup accumulator fields are different: one not assigned in `initGroup()` is null.
   - Missing assignments are an ERROR only when they violate a stated output requirement, never
     because "the field will be null".
4. **`*OnError` callbacks are valid optional hooks, and they should log the error.**
   - Returning `SKIP` (or `0` from `countOnError`) without logging is tolerated: the failing
     record isn't processed.
   - A callback that **silently returns `OK`** is a defect: it reports the failed record as
     processed.
   - A fix should add logging and/or `SKIP`. It must not claim the callback is invalid, and it
     need not delete it.

The severity rule still holds:
- **ERROR:** the code does not compile; a runtime failure is certain; or a stated requirement is
  violated.
- **WARNING:** a runtime risk that depends on the data, or a suspicious but specified behaviour.
- **VERDICT:** FAIL if there is any ERROR.

## How to correct a record

- **Minimal edits.** Change only the false statement, the wrong finding, severity or verdict,
  or the wrong code, plus whatever directly depends on it. Keep the record's voice, structure,
  ordering and formatting.
- **Keep the trace and the answer consistent.** If a record has `orig_reasoning_content`,
  correct the trace too, so it reaches the corrected conclusion itself.
- **Validate answers:** after removing or changing a finding, re-derive the verdict (any ERROR
  means FAIL). Never leave a finding that now has no basis.
- **Code:** corrected code must compile. Use the CloverDX compiler if you have it; otherwise
  check every call against `ctl-function-library.json` and every callback against
  `componet_contracts.md`. For ruling 4, the standard fix is
  `printLog(error, "<callback> failed: " + errorMessage);` before the return, with `SKIP` instead
  of `OK` where the record should not be processed.
- **DPO pairs:**
  - Correct the `chosen` side.
  - If the `rejected` side is actually the correct behaviour under a ruling, the pair teaches the
    opposite. Rewrite `chosen`, or drop the pair and log it.
  - Don't touch `rejected` otherwise.
- **Keep ids.** Set or refresh `reviewed_date` to the edit date on every record you change.
- **Don't fix things you merely dislike.** Only contradictions with the rulings, plus the
  verified conflicts in Part C.

## Part A — confirmed by the repair rounds (verify, then correct)

The repair agent found these by reading each record. Its per-record notes are in the repair log.
Re-verify each one before editing; for ruling 2 in particular, keep any real first-record
requirement.

Ruling 1:

| file | records | ids |
|---|---:|---|
| `CTL_LoRAT_reasoning_v2.json` | 1 | `treasoniae_185` |

Ruling 2:

| file | records | ids |
|---|---:|---|
| `CTL_LoRAT_reasoning_v2.json` | 23 | `treasoniae_245`, `treasoniae_247`, `treasoniae_248`, `treasoniae_249`, `treasoniae_250`, `treasoniae_251`, `treasoniae_252`, `treasoniae_253`, `treasoniae_263`, `treasoniae_265`, `treasoniae_268`, `treasoniae_269`, `treasoniae_270`, `treasoniae_272`, `treasoniae_282`, `treasoniae_283`, `treasoniae_284`, `treasoniae_285`, `treasoniae_365`, `treasoniae_366`, `treasoniae_367`, `treasoniae_368`, `treasoniae_369` |
| `CTL_LoRA_validate_examples.json` | 19 | `validateb8_221`, `validateb8_222`, `validateb8_239`, `validateb8_265`, `validateb8_318`, `validateb8_319`, `validateb8_382`, `validateb8_410`, `validateb8_455`, `validateb8_509`, `validateb8_532`, `validateb8_533`, `validateb8_541`, `validateb8_558`, `validateb8_560`, `validateb8_600`, `validateb8_648`, `validateb8_727`, `validateb8_955` |

Ruling 3:

| file | records | ids |
|---|---:|---|
| `CTL_LoRAT_reasoning_v2.json` | 2 | `treasoniae_264`, `treasoniae_282` |
| `CTL_LoRA_validate_examples.json` | 2 | `validateb8_191`, `validateb8_809` |

## Part B — scan hits (verify each; expect false positives)

A regex scan of the assistant answers, traces and DPO `chosen` sides produced these. Many will
be fine, for example where the text discusses the wrong belief in order to reject it, or where
the component is a Rollup and not a Denormalizer. Correct only real contradictions, and log
every hit as `corrected` or `false_positive`, with one line of evidence.

Ruling 1 — `STOP` described as a normal or clean termination:

| file | records | ids |
|---|---:|---|
| `CTL_LoRAT_validate_thinking.json` | 1 | `tvalidat22_47` |
| `CTL_LoRA_examples_reversed.json` | 1 | `examples4a_219` |
| `CTL_LoRA_validate_examples.json` | 1 | `validateb8_56` |

Ruling 2 — Denormalizer `transform()` described as unable to read `$in.0` (not already in Part A):

| file | records | ids |
|---|---:|---|
| `CTL_LoRA_DPO_components.jsonl` | 6 | `dpocompo2d_84`, `dpocompo2d_85`, `dpocompo2d_87`, `dpocompo2d_88`, `dpocompo2d_90`, `dpocompo2d_rollupin_02` |
| `CTL_LoRA_DPO_data.jsonl` | 3 | `dpodata3c_450`, `dpodata3c_576`, `dpodata3c_674` |
| `CTL_LoRA_DPO_misc_new.jsonl` | 1 | `acxee-33` |
| `CTL_LoRA_component_suggest_1.json` | 1 | `componene2_84` |
| `CTL_LoRA_components_contracts.json` | 1 | `componen9c_rollupin_02` |
| `CTL_LoRA_conversations.json` | 1 | `conversa78_457` |
| `CTL_LoRA_llm_augmented_functions_examples.json` | 6 | `llmaugme92_1228`, `llmaugme92_1367`, `llmaugme92_1449`, `llmaugme92_1487`, `llmaugme92_426`, `llmaugme92_819` |
| `CTL_LoRA_sft_misc_new.json` | 1 | `unreachval_sft_007_denormalizer_input_in_transform_and_dead_tail` |
| `CTL_LoRA_with_metadata_set_1.json` | 2 | `withmeta5c_110`, `withmeta5c_167` |

Ruling 3 — unset output fields described as null:

| file | records | ids |
|---|---:|---|
| `CTL_LoRA_llm_augmented_simple.json` | 1 | `llmaugmec4_260` |
| `CTL_LoRA_validate_examples.json` | 1 | `validateb8_798` |

Ruling 4 — an `*OnError` callback in taught code that returns `OK` without logging:

| file | records | ids |
|---|---:|---|
| `CTL_LoRAT_reasoning_v2.json` | 2 | `examples51_35`, `treasoniae_420` |
| `CTL_LoRAT_thinking.json` | 5 | `tthinkinac_162`, `tthinkinac_170`, `tthinkinac_35`, `tthinkinac_66`, `tthinkinac_95` |
| `CTL_LoRA_DPO_complex.jsonl` | 4 | `dpocomplcb_2`, `dpocomplcb_44`, `dpocomplcb_5`, `dpocomplcb_51` |
| `CTL_LoRA_DPO_eval.jsonl` | 1 | `dpo-eval-001` |
| `CTL_LoRA_component_suggest_1.json` | 3 | `componene2_85`, `componene2_86`, `componene2_93` |
| `CTL_LoRA_eval_data.json` | 1 | `eval-thinking-refresh-003` |
| `CTL_LoRA_eval_data_think.json` | 1 | `eval-thinking-refresh-003` |
| `CTL_LoRA_eval_data_think_src.json` | 1 | `eval-thinking-refresh-003` |
| `CTL_LoRA_fix_this_code.json` | 1 | `fixthiscc4_5` |
| `CTL_LoRA_llm_augmented_short.json` | 5 | `llmaugme77_100`, `llmaugme77_143`, `llmaugme77_42`, `llmaugme77_68`, `llmaugme77_77` |
| `CTL_LoRA_with_metadata_set_1.json` | 1 | `withmeta5c_157` |

The scan is not exhaustive. While you work through these files, also fix any other passage you
come across that contradicts a ruling, and log it.

## Part C — other reference conflicts found during the repair rounds

These came from the repair agent's analysis, not from the rulings. Fix one **only if the
evidence is conclusive**: the prompt's own explicit wording, the function catalog, the compiler,
or the severity rule. Otherwise log it as `needs_owner_decision`, with the evidence for both
sides.

| record | file | claimed problem |
|---|---|---|
| `fixthiscc4_69` | `CTL_LoRA_fix_this_code.json` | The prompt's ordered `else if` rules put the qualifying MED rule (rule 2) before the IR/KP country rule (rule 3); the reference checks country first. |
| `tvalidat22_52` | `CTL_LoRAT_validate_thinking.json` | Repeating `items[0]` violates the explicit one-row-per-element requirement: ERROR, not WARNING. |
| `tvalidat22_7` | `CTL_LoRAT_validate_thinking.json` | `lpad` pads with spaces, but the prompt requires five digits: ERROR, not WARNING. (STOP is already ERROR there; keep it.) |
| `tvalidat22_35` | `CTL_LoRAT_validate_thinking.json` | The quota/allocation and reversed-probability defects violate explicit requirements (ERROR, not WARNING). The June 30 post-midnight warning is unreachable when MAX_DATE is midnight. |
| `treasoniae_18` | `CTL_LoRAT_reasoning_v2.json` | Nullable input propagated into non-nullable output is a data-dependent risk (WARNING), not ERROR. |
| `validate_source_ndlbi-12` | `CTL_LoRAT_validate_thinking.json` | The null `zone_prefix` finding is unreachable (exact-key lookup on a non-null key). |
| `validate_source_ndlbi-19` | `CTL_LoRAT_validate_thinking.json` | Missing data-dependent WARNINGs for nullable `maximum_damage_score` and `required_seal_prefix`. |
| `validateb8_962` | `CTL_LoRAT_validate_examples_think.json` | `clear(queues)` on a declared typed list is safe (declared lists start empty): remove that warning. |
| `fixthiscc4_118` | `CTL_LoRA_fix_this_code.json` | Calendar-window wording ("next seven days including today") versus a timestamp window. **Disputed:** the judge read the 7-day bound as correct, so log it unless the prompt text is unambiguous. |
| `fixthiscc4_27` | `CTL_LoRA_fix_this_code.json` | Reading group keys from `$in.0` in **Rollup** `transform()`. Not covered by ruling 2 (Denormalizer only): log as `needs_owner_decision`. |
| `tmultibucd_38` | `CTL_LoRAT_multibug_validate_thinking.json` | WARNINGs about preview ordering and the optional note, both of which the prompt explicitly allows. |
| `rollupcontract_tv_06` | `CTL_LoRAT_validate_thinking.json` | A missing `initGroup` prevents initialization before any null arithmetic can occur, so describe the null arithmetic as a consequence, not as the observed behaviour. |
| `treasoniae_16` | `CTL_LoRAT_reasoning_v2.json` | Add an ERROR for the four absent mandatory Rollup callbacks; don't add a null-constraint ERROR for unassigned aggregates (ruling 3). |

## Part D — evaluation data (list only)

`sft_eval_data/` scores the models, and changing it breaks comparability with earlier results.
**Don't edit it.** List every eval record that contradicts a ruling, using the same checks:
- the Part B hits in `CTL_LoRA_DPO_eval.jsonl` and `CTL_LoRA_eval_data*.json`;
- anything else you notice.

For each, give the proposed correction. The corpus owner will decide.

## Output

1. **The corrected corpus files,** edited in place.
2. **`sft_training_data/CTL_ruling_corrections_log.md`**, with one row per listed record:
   file, id, ruling or Part C, outcome (`corrected`, `false_positive`, `dropped_pair` or
   `needs_owner_decision`), and a one-line description of the change or evidence. It also
   contains:
   - any extra records you corrected beyond the lists;
   - the Part D eval-data list;
   - counts per outcome.
3. **Validation:** every edited file still parses. Every edited validate answer still has
   `ISSUES:` / `VERDICT:` with a verdict consistent with its severities. Every edited code block
   still compiles (or, without a compiler, passes the library check).

Commit corpus edits and the log together, and push.

---

## Internal tracking

Not part of the brief.

- **Sources:**
  - Part A: the repair agent's round-2 log table ("Corpus records contradicting the rulings").
  - Part B: a regex scan of the corpus (scratchpad `scan_rulings.py`, 2026-10-03). It covers the
    assistant answers, `orig_reasoning_content` and DPO `chosen` sides, and skips the repair-round
    files and the agent-authored few-shot file.
  - Part C: the repair agent's round-1 and round-2 conflict lists. Of these, only the
    severity-rule cases and the prompt-order case (`fixthiscc4_69`) were checked in llama_train.
- **Eval suite:** v4 has no rubric that contradicts the four rulings (checked on 2026-10-03). T29
  penalises STOP, T40.FP1 and T32 encode the declaration defaults, and no rubric forbids the
  Denormalizer `$in.0` read.
- **After the corrections land:**
  - `self_distill.KNOWN_WRONG_REFERENCES` and the gaps lists may be stale;
  - add the new beliefs to `KNOWN_FALSE_BELIEFS` (STOP as normal termination; Denormalizer
    input unavailable in `transform()`; unset non-nullable output fields are null);
  - an SFT retrain on the corrected corpus is the next experiment
    (the targeted-repair DPO round showed no measurable effect; see llama_train commit 7b4c3e2).
