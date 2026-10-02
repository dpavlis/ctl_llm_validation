# Targeted DPO pairs — minimal repairs of the model's own failed answers

**Repair 150–200 of the model's rejected answers, so that each repair and its original form a DPO
pair.** The pairs cover two task types: *fix this code*, and validate reviews that have two or
more findings. Everything above the "Internal tracking" section at the end is a self-contained
brief. It assumes you know CTL2 (the language, the CloverDX component model, and the
`ISSUES:` / `SUGGESTIONS:` / `VERDICT:` review format), but no other context about this project.

You are working inside the `ctl_lora_training` repository:

| path | what it is |
|---|---|
| `sft_training_data/CTL_LoRAT_DPO_repair_candidates.jsonl` | **the input**: 414 answers the model got wrong, on 74 prompts, each with what a judge said was wrong (described below) |
| `sft_training_data/CTL_LoRA_fix_this_code.json` | the corpus the *fix* prompts come from |
| `sft_training_data/CTL_LoRAT_multibug_validate_thinking.json` | house style for multi-finding reviews |
| `sft_training_data/componet_contracts.md` | which functions each component must or may define, and what may be written where |
| `references/CTL2_Reference_for_LLM_compact.md` | the language reference |
| `references/ctl-function-library.json` | every built-in function, with each of its overloads |
| `references/CTL2_SFT_Validation_Playbook.md` | house style for validate answers |

## Why this exists

The model under training is a fine-tuned 27B model with a thinking mode. For every prompt it
writes a reasoning trace and then an answer. Two kinds of prompt fail almost always:

| group | prompt draws (4 samples each) | draws where no sample was correct | distinct prompts in the input |
|---|---|---|---|
| `fix_tier2`: fix this code (from `CTL_LoRA_fix_this_code.json`) | 37 | 32 | 29 |
| `validate_2`: reviews with 2 findings | 56 | 41 | 33 |
| `validate_multi3`: reviews with 3 or more findings | 17 | 16 | 12 |

(A prompt can be drawn more than once, by different checkpoints.)

The usual way to build DPO pairs is to pair one of the model's correct samples with one of its
wrong samples for the same prompt. That doesn't work when there are no correct samples, which is
why these groups were barely represented in the last DPO round. Pairing the corpus reference
answer against the model's sample doesn't work either. The reference is written in a voice the
model doesn't produce, so the pair mostly teaches style instead of the fact that was wrong.
(Measured on authored traces: a mean negative log-likelihood of 1.77 per token under the model,
against 0.13 for its own text.)

**The fix: start from the model's own wrong answer and correct only what is wrong.** The
corrected copy is the *chosen* side and the original is the *rejected* side. The two sides share
almost every token, so the training signal falls on the few tokens that carry the error.

The failures are mostly false statements about CTL2, not bad code:

| what the judge reported (judge-rejected samples) | fix_tier2 (177) | validate_2 (187) | validate_multi3 (32) |
|---|---|---|---|
| false claim about CTL2 | 155 | 130 | 21 |
| missed defect / missed finding | 124 | 80 | 19 |
| wrong fix | 103 | 47 | 8 |
| wrong severity (ERROR vs WARNING) | – | 67 | 8 |
| broken stated requirement | 40 | 24 | 6 |
| reported a problem that isn't one | 4 | 73 | 8 |

The same few claims recur many times. The topics are:
- `isNull` (≈60);
- lifecycle and contract functions, such as `getOutputPortOnError` on Partition, `countOnError` on Normalizer, `init()` (≈66);
- `OK` as a return value (≈45);
- defaults of declared variables and nullability of primitives (≈45);
- `clear()` on lists (≈18);
- decimal vs number (≈22).

**Don't trust the topic list or the judge's wording. Verify every claim yourself** (see "The
judge's notes are hints" below).

## The input file

One JSON object per line. Fields:

| field | meaning |
|---|---|
| `id` | candidate id, `dpocand_<prompt_id>_<hash>` |
| `prompt_id`, `group`, `task_type`, `component` | which prompt and group (`fix_tier2`, `validate_2`, `validate_multi3`) |
| `source_file`, `source_record_id` | where the prompt's corpus record lives |
| `system`, `prompt` | exactly what the model was shown |
| `reference_answer` | the corpus answer for the prompt; usually right, occasionally wrong |
| `model` | which checkpoint wrote the sample: `base` (prefer it, see below) or `sd1ep2` |
| `reasoning_content` | the model's reasoning trace |
| `answer` | the model's answer |
| `compile` | compiler result on the answer's code, if it was run |
| `rejected_at` | `judge` (the answer was graded wrong) or `claims` (the answer was right, but the trace or answer states something false) |
| `judge_model`, `judge_reason`, `claims_reason` | the grader's summary |
| `problems` | the grader's itemised findings: `false_claims`, `missing`, `wrong_fixes`, `severity_mismatches`, `broken_requirements`, `extra_findings`, `compile_problems`, `answer_false_claims`, `trace_false_claims` |
| `run` | internal bookkeeping |

Don't modify this file.

## What a repair is

For each candidate you choose, produce a *chosen* reasoning trace and answer by editing the
model's own text:

1. **Correct every real error, and nothing else.** That means:
   - every false CTL2 statement, in the answer and in the trace;
   - every defect the answer misses or fixes wrongly;
   - every wrong severity;
   - every finding that isn't a real problem (remove it).

   Leave everything that is correct byte-for-byte identical: wording, order, formatting,
   variable names, code style, the sentence before and after an edit.
2. **Edit the trace where the error happens.**
   - If the trace states a false belief, rewrite that sentence and whatever it immediately
     concludes from it, so the trace reaches the right conclusion by itself.
   - If the trace never noticed a defect the answer must report, add a short passage where the
     trace looks at that line of code.
   - Write in the trace's own voice: same person, same tense, same terseness. Don't make it
     more polished than the surrounding text.
3. **Keep the answer consistent with the trace.** Every finding or fix in the chosen answer is
   reasoned about in the chosen trace, and nothing the trace concludes is contradicted by the
   answer.
4. **Never mention the reference, the judge, the corpus or the editing.** The chosen side must
   read as if the model had written it.
5. **Keep the edit small.** Measure the edit with
   `difflib.SequenceMatcher(None, rejected, chosen).ratio()`, separately for the trace and the
   answer:
   - The trace must keep **ratio ≥ 0.85**.
   - The answer must keep **ratio ≥ 0.75**. Adding a missed finding to a short answer costs more,
     so its threshold is lower.

   If a correct answer needs more change than that, the model's approach was wrong rather than
   one fact. Skip the candidate and log it as `too_far`.

### The judge's notes are hints, not truth

The `problems` lists were written by an LLM grader and **contain mistakes**. For example, some
notes claim "`init()` is not a Normalizer lifecycle function". The reference (§8.8 *Optional
init()*) says `init()` is optional in every CTL2 transform, so that note is itself false.

For every item in `problems`:
- **Verify it** against `references/CTL2_Reference_for_LLM_compact.md`,
  `references/ctl-function-library.json`, `sft_training_data/componet_contracts.md`, and the
  compiler if you have one.
- **If it is wrong**, the model's statement stands. Don't edit it.
- **If every item is wrong** and the sample is actually correct, don't make a pair. Log it as
  `judge_wrong`, with the evidence.
- **Look beyond the list.** The grader also misses things. Fix any real error you find that it
  didn't list.
- **The `reference_answer` can be wrong too.** If it is, log the prompt as `reference_wrong`,
  with the evidence, and judge the sample on the facts.

### Severity rule (validate answers)

The question to ask of every finding is: **is the failure certain, or does it depend on the data?**

- **ERROR:**
  - the code does not compile;
  - it compiles, but a runtime failure is certain whatever the data;
  - it runs, but violates a requirement stated in the prompt.
- **WARNING:** a runtime risk that depends on the data (a nullable field that may be null, a
  lookup that may miss, malformed input), or a suspicious choice that still produces the
  specified output.
- **VERDICT:** FAIL if there is any ERROR. Otherwise PASS, even with warnings.

A *missing* finding is worse than an imperfect explanation. A *false* explanation is worse than a
missing one. Keep each finding at about 25 words or more: shorter findings tend to truncate a
true fact into a false one.

## Which candidates to repair

- **Coverage first.** Aim for at least one pair for every one of the 74 prompts that has a
  repairable candidate. Then add a second and a third pair per prompt where the extra samples fail
  differently (a different false claim, or a different missed defect). Don't repair three samples
  that all make the same mistake.
- **Prefer `model: base` samples.** That checkpoint is the one DPO will train. Use `sd1ep2`
  samples only for prompts without a repairable `base` sample.
- **Within a prompt, start with the candidate that has the fewest real errors.** It gives the
  smallest edit.
- **Target: 150–200 pairs.** Every group must have pairs, and `validate_multi3` takes whatever
  its 12 prompts allow.

## Checks before you write a pair

- [ ] Every code block in the chosen answer compiles. Use the CloverDX CTL2 compiler if you
      have it; otherwise check every call against `ctl-function-library.json` (name, arity,
      argument types) and every lifecycle function against `componet_contracts.md`. Set
      `compile_checked` to `compiler` or `library_only`.
- [ ] The chosen answer is fully correct: it would be accepted when compared with a correct
      reference.
- [ ] No sentence in the chosen trace or answer is false. Uncertain statements are fine only if
      the trace resolves them correctly before the answer.
- [ ] The rejected side is the input sample, byte-identical.
- [ ] Both ratios meet the thresholds in rule 5.
- [ ] The chosen answer keeps the output format the prompt asks for. For validate: `ISSUES:`,
      optional `SUGGESTIONS:`, then `VERDICT:`.

## Output

Write **`sft_training_data/CTL_LoRAT_DPO_targeted_repairs.jsonl`**, one pair per line:

```json
{
  "id": "dporep_<prompt_id>_<n>",
  "candidate_id": "dpocand_…",
  "prompt_id": "…",
  "group": "fix_tier2 | validate_2 | validate_multi3",
  "component": "…",
  "model": "base | sd1ep2",
  "system": "<copied from the candidate>",
  "prompt": "<copied from the candidate>",
  "chosen_reasoning_content": "<repaired trace>",
  "chosen_answer": "<repaired answer>",
  "rejected_reasoning_content": "<candidate reasoning_content, unchanged>",
  "rejected_answer": "<candidate answer, unchanged>",
  "edits": [
    {"where": "trace | answer", "kind": "false_claim | missed_defect | wrong_fix | severity | spurious_finding | requirement",
     "before": "<the original text, short>", "after": "<the new text, short>",
     "evidence": "<reference section, library overload or compiler message>"}
  ],
  "judge_items_rejected": ["<each problems item you found wrong, with why>"],
  "ratio_trace": 0.93,
  "ratio_answer": 0.88,
  "compile_checked": "compiler | library_only",
  "reviewed_date": "YYYY-MM-DD"
}
```

Also write **`sft_training_data/CTL_LoRAT_DPO_targeted_repairs_log.md`**. It contains:
- one table row per candidate you looked at and didn't repair, giving its id, the outcome
  (`too_far`, `judge_wrong`, `reference_wrong`, `duplicate_failure`) and one line of evidence;
- a short list of the false CTL2 beliefs you corrected, with counts;
- every `reference_wrong` prompt, with the fix you believe its corpus record needs. **Don't edit
  the corpus record.**

Commit both files to the repository. Don't change any other file.

---

## Internal tracking

Not part of the brief; for the `llama_train` side.

- **Input built by** `llama_train/export_dpo_targets.py`:
  - sources: runs pilot1, pilot2, full1, gen2pilot_fix6, gen2pilot_sd1ep2 and gen2full;
  - groups: fix_tier2, validate_2 and validate_multi3, rejected at the judge or claims stage;
  - excluded: `KNOWN_WRONG_REFERENCES`; 9 duplicate samples dropped;
  - teachers: 261 candidates from base (`qwen38_fix6_sftdpo`) and 153 from sd1ep2.
- **Acceptance on return** (this machine), before any training:
  1. format, library, compile (MCP) and the `KNOWN_FALSE_BELIEFS` scan on the chosen side;
  2. two agreeing gpt-6-sol judgements (reference judge and claims audit) on the chosen side,
     the same decision path as `self_distill.py filter`. This is needed because about 15% of
     single judgements flip on boundary prompts;
  3. mean token negative log-likelihood of the chosen side under base, which should be close to
     the rejected side's. A large gap means the edits are off-policy;
  4. `reference_wrong` entries go to the corpus owner;
  5. `judge_wrong` cases are checked and, if confirmed, added to the judge's known errors.
- **Training:**
  - convert with `convert_think` (`<think>` tags), the same spelling as `dpo1_train.jsonl`;
  - DPO on base for one GPU with `dpo_logps_chunk_size: 1024` and no length cap
    (LlamaFactory 83fda7c8);
  - start with the targeted pairs alone; the comparison arm is the targeted pairs plus the
    211-pair dpo1 set, which also runs the single-GPU infrastructure check.
- **Evaluation and success bar:**
  - fix-only, T39–T43 at n=20, against base's 0.7035;
  - full suite at n=5, run twice, because same-model noise is about ±0.01 on generate and
    ±0.025 on validate;
  - success means fix is up with a permutation p < 0.1, generate holds within noise, and the
    validate WRONG rate does not rise.
- **Caveat:** the suite's fix tests are fix-to-spec tasks (T39–T43), not fix-this-code. These
  pairs target the beliefs those tests trap (null defaults, contract functions), so expect the
  transfer to be partial.
