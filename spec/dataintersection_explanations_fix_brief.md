# DataIntersection training set, round 2b: vary the repeated explanation sentence

**A prose-only revision of `CTL_LoRA_dataintersection_sft.json` and `CTL_LoRA_DPO_dataintersection.jsonl`** (commit
`ef089f2`). No CTL changes, so no new compiler or graph runs. Keep the counts (60 / 40), the format and everything else
from round 2 (`spec/dataintersection_training_set_fix_brief.md`).

DPO pairs are referred to by their **line number in the file, counting from 1**.

## Why

Round 2 did what the brief asked:
- the hints are gone;
- the whole-component prompts are in;
- the DPO pairs target the per-port mistake;
- the validation passes.

One thing came out too uniform. This sentence appears **word for word in 38 SFT answers, 17 DPO chosen answers and 16
rejected answers**:

> The transform runs only for matched pairs and writes $out.0, which DataIntersection sends to output 1; outputs 0 and
> 2 pass one-sided records through unchanged without CTL.

The wording came from the brief, which was meant as the content, not the text. 38 copies in one narrow topic teach the
model to recite a template, and to attach it to answers where it doesn't belong. In 26 of the 38 SFT prompts the side
outputs aren't mentioned at all.

## What to change

### 1. SFT: keep the fact where the prompt calls for it, in varied words

**Keep a sentence, rewritten**, in the 12 answers whose prompt names the side outputs or their consumers, or asks for
the complete component:
- di_sft_001, 002, 003, 004, 006, 013;
- di_sft_018, 019, 021, 025, 028, 053.

For these:
- Use at least 5 different phrasings across the 12, none used more than 3 times.
- Tie it to the scenario where possible. For example: "Only matched pairs reach this code; the review rows go to
  output 1 through `$out.0`, while withdrawn and discovered lots pass through unchanged."
- One sentence. Each must still state all three facts:
  - `transform()` runs only for matched pairs;
  - it writes `$out.0`, which goes to output 1;
  - outputs 0 and 2 pass records through with no CTL.

**Remove the sentence** from the other 26 answers, whose prompts don't involve the side outputs:
- di_sft_012, 024, 031–043, 045–052, 055–057.

Some of these answers are then code only. Answers that must keep at least one sentence:
- di_sft_024, 031, 032, 033, 035, 036, 037, 038, 039, 040, 042, 046, 048, 050, 051, 055, 056;
- or any other answer left with code only.

For those, write one sentence about **the decision in that task**, not the component contract. For example:
- "Unchanged pairs return SKIP, so only moved seats reach the review."
- "null and "" compare as different values, so a cleared label counts as a change."

Where the task really is about the local record (di_sft_052, a fix task), say it in that answer's own words.

### 2. DPO: the same variation, still one point of difference

- **Lines 1, 3, 4, 6, 12, 14, 15, 16, 17, 18, 19, 22, 23, 26, 35, 36:**
  - rewrite the sentence in varied words as in section 1;
  - **identically in the chosen and rejected answer**, so the pair still differs only in the targeted point;
  - drop it where the prompt doesn't involve the side outputs.
- **Line 27:** the sentence is the chosen side of the contrast. Keep the fact; just vary the wording.

### 3. di_sft_052: remove the giveaway

The prompt says "This CTL refers to physical output numbering", which names the bug. Replace it with the symptom only,
for example "The component fails to initialize with this CTL. Fix it so every matched policy gets its proposed limit."

## Checks

- **No sentence of 12 or more words appears in more than 3 answers** across both files. Report the most repeated
  sentences.
- **The three facts survive** in every answer that keeps a sentence. List each rewritten sentence with its id.
- **No CTL changed.** Fenced code blocks are byte-identical to `ef089f2`. Show the diff limited to code blocks; it
  should be empty.
- **Update `logs/CTL_LoRA_dataintersection_validation.json`:** file hashes, the hint check, the diversity numbers, and
  a short `round2b` entry listing what changed.
