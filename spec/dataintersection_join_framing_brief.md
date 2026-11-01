# DataIntersection training set, round 3: the join framing and `return OK`

**Revise `CTL_LoRA_dataintersection_sft.json` (60) and `CTL_LoRA_DPO_dataintersection.jsonl` (40)** in
`ctl_lora_training/sft_training_data/`. Keep the counts, the format and the validation standard of rounds 1–2b
(`spec/dataintersection_training_set_fix_brief.md`, `spec/dataintersection_explanations_fix_brief.md`,
`logs/CTL_LoRA_dataintersection_validation.json`). DPO pairs are referred to by their line number in the file, from 1.

Follow the correctness rules in `CLAUDE.md`: CTL2 facts come from the reference §8.9 (rewritten 2026-11-01,
`ctl_lora_training/references/CTL2_Reference_for_LLM_compact.md` §8.9, same text in `cloverdx-llm-reference.md`) or
from `ctl_validate` / a graph run.

## Why

Owner rulings, 2026-11-01 (`spec/di_section_8_9_rewrite.md`, `spec/sysprompt_rules_findings.md`):

1. **DataIntersection is explained as a join-like transform**, not as three output ports plus a `$out.0` rule. The CTL
   sees one matched pair (`$in.0` the A record, `$in.1` the B record) and produces one output record, `$out.0`. Records
   whose key is on one side only never reach the CTL; the component passes them on by itself on its other outputs,
   and what is connected there is a graph matter, not the CTL's business.
2. **The idiom is `return OK`** (emit the pair's result) and `return SKIP` (drop the pair). `ALL`, `0` and `1` behave
   the same but new code does not use them.

The evidence: the model applies the Reformat/Partition model (the return value selects a port, `$out.N` is port N),
and every text that explains three ports feeds it. One system-prompt paragraph in the join framing, with no port
number in it, took valprec2's DataIntersection tasks from 76/102 to 98/102 first-attempt execution passes thinking on
(`$out.1` misses 21 → 2), while a rules prompt that explained the ports and named `ALL` made the same tasks worse and
produced "`return ALL` sends the matched record to all three ports" false alarms in code review. The current set
teaches the old framing: 48 of 60 SFT answers and 34 of 40 DPO chosen answers `return ALL`, none returns `OK`, and the
explanations say "`$out.0` … for output 1", "outputs 0 and 2 deliver one-sided rows".

What rounds 1–2b got right stays: no `$out.1`/`$out.2`, no `getOutputPort()`, no per-port callbacks in any SFT or
chosen answer; the whole-component prompts; the DPO pairs against per-port CTL; varied wording.

## What to change

### 1. Code: `return ALL` → `return OK`

In every SFT answer and every DPO chosen answer, the emit path returns `OK`. `SKIP` stays where a pair is dropped.
Nothing else in the code changes; the records were compiled and graph-run in round 1 and the return value is the
only edit, so re-run the compile check (`ctl_validate`) on each changed answer and the graph runs of the round-1
validation sample.

DPO rejected answers: where the rejected answer's defect is something else (`$out.1`, `getOutputPort()`, per-port
callbacks, wrong side read), change its `return ALL` to `return OK` too, so the pair does not accidentally teach
"ALL is the mistake". Where a pair is meant to target the return value (see 3), the rejected keeps `ALL` or a port
number.

### 2. Explanations: the join framing, no port numbers

Rewrite the prose of every SFT answer and every DPO chosen answer so that it describes the CTL in the join framing:

- the transform runs once per matched pair, `$in.0` from input 0 (A), `$in.1` from input 1 (B);
- it fills one output record, `$out.0`, and returns `OK` to emit it (or `SKIP` to drop the pair);
- one-sided records never reach the CTL; the component passes them on unchanged on its other outputs.

Not allowed in the explanations: "`$out.0` goes to output 1 / port 1", "outputs 0 and 2 …", "the both port", "A-only
port", "B-only port", "the return value does not select a port" and other sentences that name or number the
component's outputs. When the prompt itself names the consumers of the outputs (see 4), the explanation may say
"the one-sided records reach their consumers without CTL", without numbers.

Vary the wording as in round 2b: no sentence appears in more than 5 answers. Where the prompt does not mention the
side outputs, the explanation does not have to either; one sentence on what `transform()` emits is enough.

### 3. DPO: add the belief we saw in reviews

Keep the existing pairs (per-port CTL in the rejected). Re-target 6 of the 40 pairs (pick the ones with the weakest
contrast today) so that the rejected answer has correct code but the wrong explanation, in the words the model uses:

- "`return ALL` sends the matched record to all three output ports";
- "matched records must be written to `$out.1`, the both port";
- "`$out.0` is the A-only port";
- "the return value selects the output port";

with the chosen answer's code identical except `return OK`, and the chosen explanation in the join framing. These are
explanation-only contrasts; they need no new compile runs.

### 4. Prompts: keep the port talk in about half

Users describe their graph with three connected consumers ("A-only on 0, both on 1, B-only on 2"), as suite T53/T54
and 23 of the 51 pool_tweak prompts do. The model must stay robust to that, so the prompt mix stays roughly as it is
(about half the prompts name the three outputs or their consumers, half say nothing about outputs). Do not add port
language to prompts that do not have it, and do not remove it where it is. The answer to a port-describing prompt
still follows 2: one `$out.0`, `return OK`, and no port numbers in the explanation.

### 5. Validate-style records

There is no DataIntersection validate set in the corpus; do not add one in this round. Our own validate ground-truth
controls (B1, B1-tweak) are regenerated on our side from the new references.

## Acceptance checks (we run these on the delivered files)

- `return ALL` appears in no SFT answer and no DPO chosen answer; `return OK` appears in every emitting answer.
- No SFT answer, DPO chosen or rejected uses `$out.1`, `$out.2`, `getOutputPort()` or a callback other than
  `transform()` (rejected answers that deliberately show those mistakes excepted, as in round 2).
- The explanation strings of SFT answers and DPO chosen answers contain none of: `output 1`, `output 0`, `output 2`,
  `port 0`, `port 1`, `port 2`, `A-only port`, `B-only port`, `both port`.
- No explanation sentence occurs in more than 5 answers.
- Every changed CTL answer compiles (`ctl_validate`); the round-1 graph-run sample passes.
- Counts 60 / 40, same ids, `reviewed_date` updated; the DPO file keeps its `CTL_LoRA_DPO_*.jsonl` name.

## What we do with it

- The sets enter the next rebuild. Until then the framing is taught through OPCD on valprec2 with the rewritten
  §8.9 as the teacher's context (the route that moved beliefs before), gated on the DataIntersection harness subset
  (76/102 baseline), the DataIntersection validate controls (false alarm 0.08) and the standard full gates.
