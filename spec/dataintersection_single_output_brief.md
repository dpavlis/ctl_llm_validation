# DataIntersection training set, round 4: the request names three outputs, the answer says the CTL sees one

**Revise the DataIntersection rows of four files** in `ctl_lora_training/sft_training_data/`:
`CTL_LoRA_dataintersection_sft.json` (60), `CTL_LoRA_DPO_dataintersection.jsonl` (40), and the DataIntersection
rows of `CTL_LoRA_scd2_sft.json` (31 of 60) and `CTL_LoRA_DPO_scd2.jsonl` (20 of 40), which round 3
(`spec/dataintersection_join_framing_brief.md`) did not touch. Keep the counts, the ids, the format and the
validation standard of rounds 1–3. DPO pairs are referred to by line number in the file, from 1.

CTL2 facts come from the reference §8.9 (`ctl_lora_training/references/CTL2_Reference_for_LLM_compact.md`, same text
in `cloverdx-llm-reference.md`) or from `ctl_validate` / a graph run (`CLAUDE.md`, correctness rules).

## Why

Owner ruling, 2026-11-02: `return ALL` in a DataIntersection transform is not wrong and works, as long as the CTL
does not write `$out.1` or `$out.2`. The defect the model keeps producing is the belief that the three physical
outputs are three CTL outputs: as a generator it writes `$out.1` for the matched record, as a reviewer it flags
`return ALL` on correct code with "`ALL` sends the matched record to all three output ports".

The 2026-11-02 audit of the corpus found where that belief is taught:

1. **The requests describe three outputs, the answers never say the CTL sees one.** About a third of the
   DataIntersection prompts say "All outputs are connected: 0=A-only, 1=both, 2=B-only", "Physical output 1 metadata:
   …", "physical 0/1/2 are A-only/matched/B-only" (DI SFT 12 of 35, DI DPO 11 of 37, SCD2 SFT 6, SCD2 DPO 7). The
   model knows from Reformat that `ALL` means every output port and that `$out.N` is port N; the prompt tells it there
   are three ports; no answer in the rb1009 corpus told it that the transform has a single output record (DI SFT
   answers: 0 such sentences; the compact reference had no DataIntersection section until 2026-11-01). Round 3 fixed
   the answers' prose but left the prompt wording and added nothing that resolves it.
2. **Round 3 §3 put the false-alarm sentence into the training text.** Five DPO rejected answers (lines 12, 14, 16,
   17, 35) have correct code and a rationale that states the belief: "`return ALL` sends the matched record to all
   three output ports", "should write matched records to `$out.1`, the both port", "`$out.0` is the A-only port",
   "`return ALL` broadcasts … to every connected consumer". DPO lowers the probability of that text, but it is the one
   place in the corpus where the three-port claim is written out in full, and the pairs teach "`ALL` is the mistake",
   which is not the ruling.
3. **The SCD2 sets still teach the old framing.** 18 SCD2 SFT answers and 16 SCD2 DPO chosen answers `return ALL`
   from a DataIntersection transform, and their explanations say "physical output 1 carries the version decisions",
   "its B-only physical output 2 feeds …". Round 3 did not cover them.

The join-framing prompt paragraph, which says exactly "one output record, the component forwards one-sided records
itself", took the DataIntersection harness tasks from 76/102 to 98/102 first-attempt passes with no validate false
alarms; the corpus should say the same thing in the answers to the prompts that mention the outputs.

## What to change

### 1. Answers to port-describing prompts state the single output record once

For every SFT answer and DPO chosen answer whose **prompt** names the component's outputs (numbers, "physical
output", "A-only/B-only" consumers, "all outputs are connected"), the explanation contains one sentence, in varied
wording, that says:

- the transform fills a single output record, `$out.0`, once per matched pair, and returns `OK` to emit it
  (`SKIP` drops the pair);
- the records whose key is on one side only are forwarded by the component itself and never reach the CTL; which
  consumer receives them is wiring, not code.

Examples of acceptable wording (do not reuse any of them more than 5 times; write your own variants):

- "The CTL has one output record. It fills `$out.0` for each matched pair and returns `OK`; the one-sided records are
  routed by the component without any code."
- "Only matched pairs reach `transform()`, and it emits one record, `$out.0`. The component delivers the unmatched A
  and B records to their consumers by itself."
- "There is nothing to route here: `$out.0` is the only record the transform fills, and `return OK` emits it. The
  component takes care of the records that exist on one side only."

Allowed: the prompt's own words for the consumers ("the retirement writer", "the audit stream"), without numbers.
Not allowed in explanations, as in round 3: "output 0/1/2", "port 0/1/2", "A-only port", "B-only port", "both port",
"the return value does not select a port", "`ALL` sends to all three", "`$out.0` maps to physical output 1".

Prompts that do not mention the outputs keep their short explanation; nothing is added to them.

### 2. Prompts stay as they are

Do not add port language to prompts, and do not remove it. The model must answer users who describe three connected
consumers, so the prompt mix of round 3 stays (DI SFT 12 of 35, DI DPO 11 of 37 name the outputs). The fix is in the
answer, not in the request. The two prompts that explicitly ask for an explanation of the outputs or their metadata
(for example "Specify the metadata needed on DataIntersection's three physical output ports …") are answered in
component terms: the matched record's metadata is the transform's output metadata, the one-sided outputs carry the
input metadata of their side, and the CTL writes only the matched record.

### 3. DPO: the rejected side is wrong code, never a wrong sentence about `ALL` or the ports

Replace the five explanation-only pairs of round 3 §3 (DI DPO lines 12, 14, 16, 17, 35) with code contrasts, same
prompt, chosen unchanged:

- rejected writes the matched record to `$out.1` (or `$out.2`) with otherwise identical code and a neutral,
  one-sentence rationale that does not mention ports ("Fills the matched record and emits it.");
- or rejected reads the wrong side (`$in.0` for the B value), drops a null guard the prompt requires, or returns
  `SKIP` for a pair the prompt says to keep;

at least three of the five are `$out.1` writes. No rejected answer in either DPO file carries a statement about what
`ALL` does, about "the both port", or about `$out.0` being a port. Rejected answers whose defect is `return STOP`,
`getOutputPort()` or a per-port callback stay as they are.

Where a rejected answer in the DI DPO file still returns `ALL` with code that is wrong for another reason (round 3
left `return ALL` in 6 rejected answers), change it to `return OK` so the pair does not contrast the return value.

### 4. SCD2 DataIntersection rows: apply round 3 §1–2

In `CTL_LoRA_scd2_sft.json` and `CTL_LoRA_DPO_scd2.jsonl`, for every row whose CTL is a DataIntersection transform:

- `return ALL` → `return OK` in SFT answers and DPO chosen answers (also in rejected answers whose defect is
  something else, as in round 3 §1);
- explanations in the join framing, no port numbers (round 3 §2), plus the single-output sentence of §1 above when
  the prompt names the outputs.

Rows whose CTL is a Reformat downstream of the DataIntersection (two-output "CLOSE on 0, OPEN on 1" expanders,
`$out.1.*` writes, `return 1`) are correct Reformat code and are not changed. Prompt text that describes the graph
("physical output 2 feeds a retirement Reformat") stays, per §2.

### 5. Validation log

Update `logs/CTL_LoRA_dataintersection_validation.json` and `logs/CTL_LoRA_scd2_validation.json`: `reviewed_date`,
what was changed in rounds 3 and 4 (the round-3 revision was not recorded), the list of changed SFT indices and DPO
lines, and the compile results of the changed CTL answers. Every answer whose code changed (round 4 changes code only
in the SCD2 rows and the replaced rejected answers) is compile-checked with `ctl_validate` with the row's input and
matched-output metadata; rejected `$out.1` answers must fail the check, chosen answers must pass.

## Acceptance checks (we run these on the delivered files)

- For every SFT answer and DPO chosen answer whose prompt matches `output [012]|port [012]|physical output|A-only|
  B-only|all outputs are connected` (case-insensitive): the explanation contains `$out.0` and one of `single|one
  output record|only (record|output)|the only record` and one of `forward|route|deliver|pass|take care`; no sentence
  used more than 5 times across the four files.
- No SFT answer or DPO chosen explanation, in any of the four files, contains `output 0`, `output 1`, `output 2`,
  `port 0`, `port 1`, `port 2`, `A-only port`, `B-only port`, `both port`, `all three`, `three ports`.
- No DPO rejected answer, in either DPO file, contains `all three`, `three output ports`, `every connected`,
  `broadcast`, `both port`, `A-only port`, `B-only port`, or "`$out.1`" inside prose (a `$out.1` write in the code
  block is the intended defect).
- `return ALL` appears in no SFT answer and no DPO chosen answer of the four files; every emitting DataIntersection
  answer returns `OK`. Reformat answers in the SCD2 files are unchanged (diff).
- Counts 60 / 40 / 60 / 40, same ids and order, `reviewed_date` updated, DPO files keep their `CTL_LoRA_DPO_*.jsonl`
  names; prompts unchanged except where §2 allows nothing (diff of the prompt fields is empty).
- The validation logs record rounds 3 and 4 and the compile results.

## What we do with it

The sets enter the next rebuild together with the rewritten §8.9. On the current candidate the same sentence is
carried by the deployment prompt (`data/sysprompt/di_frame_v2.txt`); no further OPCD lane is planned on this topic
(difr1–3, WORKLOG 2026-11-02). The evaluation prompts (pool_tweak_di, di_frame_prompts, the validate controls) keep
their three-output wording on purpose: they measure whether the model holds up when the user talks that way.
