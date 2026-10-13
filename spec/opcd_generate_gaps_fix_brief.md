# OPCD generate gaps, round 2: fix the generator, not the prompts

**Rebuild `data/opcd/generate_gaps.jsonl` (120 prompts, 20 per gap G1–G6).** `spec/opcd_generate_gaps_brief.md`
still applies in full: gaps, counts, components, realism, rubric rules, run requirement, output format. This file lists
what round 1 got wrong and the checks that must now catch it.

## Why

Round 1 has real strengths, and they must be kept:
- 120 prompts with 2+ interacting traps each;
- every reference compiled and ran FINISHED_OK;
- no scenario overlap with the suites;
- rubrics far better than before (33 of 1,166 items copied from a clause).

But the prompts come from shared clause templates, and the templates show through. In a review of 12 prompts (2 per
gap), 6 were must-fix and 6 minor; none was clean. The defects come from the generator, so **fix the generator and
regenerate**. Don't hand-edit 120 prompts.

## Defects to remove

### 1. Templated scenarios

With field names masked, prompts within a gap share most of their text: masked 5-gram Jaccard averages 0.41 (G4) and
0.46 (G5), up to 0.64. Field names are a domain prefix plus a fixed role (`reef_lot`, `reef_text`, `reef_ready` /
`organ_lot`, `organ_text`, `organ_ready`), which is how the set passed the 0.30 check.

**Required:**
- Each prompt is its own scenario: its own business rules, its own field names in the domain's vocabulary
  (`cask_fill_dt`, `bottling_lot_no`, not `<prefix>_text`), its own clause structure.
- Within a gap, vary which traps combine and what the output looks like (one record per input, a summary, multiple
  rows per input, two ports), not only the nouns.

### 2. Garbled splices and leftovers from other templates

Examples:
- "apply The parsed quantity may not exceed the exact ceiling" (16 G5 prompts);
- "apply One decimal unit above the ceiling is permitted" (G5_09, also ambiguous between 1.00 and 0.01);
- "the threshold itself is deliberately ignored" (G4_19);
- "unless if that does not apply specified" (G6_06);
- missing spaces ("are2026-03-30", "with06:00");
- doubled words ("submitted submitted readings").

Leftover clauses also refer to things the prompt doesn't have:
- "order=asc for Denormalizer" in a non-Denormalizer;
- WEIGHT, never defined;
- "specialized admission rule", "duplicate-ID rule", "non-reserved";
- holidays listed but never used;
- UTC-clock or name/timestamp formatting clauses in prompts with no such fields (G3_04, G3_15);
- grouped-processing and closing-row text in a Reformat (G6_13).

**Required:** every sentence is grammatical and refers only to fields, codes and rules that exist in that prompt.
Read every prompt once as a developer would before accepting it.

### 3. Trap giveaways

These state the very traps the prompts are meant to test:
- "missing history differs from initial zero" (19);
- "Zero remains real" / "remains legitimate" / "genuine observations, including at the beginning" (60+);
- "Zero is eligible, not missing";
- "a first zero … must be remembered as a real observation";
- "Reset lot-local state";
- "never a graph failure".

**Required:**
- State only business facts.
- "Readings of 0 are valid" is fine when the domain needs it (a model must know 0 is a value), but say it once,
  plainly, as a business fact.
- Never mention initial values, history, resets, sentinels, flags, graph failure or how state starts.

### 4. Undefined outputs

A model can't produce what the prompt never names. Examples:
- the kind of a valid row (DETAIL in G2_05, VALID in G6_13);
- "immediately append CROSSING" (a separate row, or a suffix on the kind?);
- the quarter label (`2025/3` or `2025/Q3`?);
- the week bucket (the Monday, as `yyyy-MM-dd`?);
- "Info diagnostics carry the complete reason string" in a Partition, which has no reason field;
- LIMIT rules that mention "a negative correction" when the grammar is unsigned (G5_17).

**Required:**
- Every output field, code, label and format the rubric checks is defined in the prompt, with one example value where
  the format is not obvious.
- No rule contradicts another, and no rule can never fire (G1_03: a four-admission LIMIT that printing at four makes
  unreachable).

### 5. Rubric defects

- **Items that fail correct code:**
  - G3 .6 requires normalising a field that feeds no decision (`sprig_shape`, `lapis_stone`);
  - G1_14 .5 rejects the valid "compare with the initial `""`" solution;
  - G4 .2 can mark a correct solution with no sentinel as missing.

  Check every item against at least one alternative correct solution, not only the reference.
- **Items pasted from the prompt** (G4 .5/.6, G5 .6/.10) or citing internal labels the judge can't map
  (`last_global`, `same_day`): rewrite them as atomic checks of observable code behaviour.
- **Forbidden items are the same generic pair in every prompt** (writing an input field; `cast()`). Replace them with 2–3
  that target the gap's real defect in this prompt:
  - **G1:** changing a dictionary entry on a refused row; testing a dictionary entry with `== null` when it has a
    typed default.
  - **G2:** an emit function that never returns `SKIP` (endless loop) or emits the group summary per record; global
    state not reset per group.
  - **G3:** a declared variable tested with `== null` / `isnull()` as the first-record sentinel; 0 used as "no
    previous".
  - **G4:** taking a sequence value for rows that are not openings; carrying state across keys.
  - **G5:** an unguarded `str2decimal` / strict `str2date` on text that can be blank or invalid; stopping at the first
    failed check.
  - **G6:** a date function without `"UTC"` on a UTC business calendar; integer division in a ratio.

  F1 in G4_08 names Rollup functions in a Normalizer rubric; forbidden items must fit the component.
- **The trap the prompt is built around must have a required item.** Missing ones: G3_15 has no item for saving the
  first row's memo in `append()`; G2_05 has no item for the DETAIL delta; G5_09 has none for the logged diagnostics.
- Use one id scheme: `<prompt id>.<k>` and `<prompt id>.F<k>`.

### 6. Run evidence

`artifacts.comparison` pointed to missing files for every prompt, and `data/opcd/generate_gaps_runs/` was then removed
(14 Oct, 00:15), so the runs can't be checked.

**Required:**
- Deliver `generate_gaps_runs/cases/<id>/` for every prompt: graph, inputs, expected and actual outputs,
  `comparison.json`.
- Every path in `artifacts` must exist.

## Checks to add to `generate_gaps_check.py`

- **Template similarity:** mask every field name (any token with `_`), every number and the XML metadata, then
  require masked 5-gram Jaccard < 0.30 for every pair within a gap and < 0.25 on average within a gap.
- **Repeated sentences:** no sentence of 8+ words may appear in more than 3 prompts (the closing "Write the complete
  CTL2…" sentence excepted).
- **Giveaway scan:** fail on the phrases in §3 and their variants (initial, history, reset, sentinel, flag, missing
  vs zero, graph failure).
- **Text hygiene:** fail on a capital letter after a lowercase verb mid-sentence ("apply The"), digits glued to words,
  and doubled words.
- **Rubric:**
  - no item's first 60 characters appear in the prompt;
  - no item cites an identifier that is neither a metadata field, an output code nor a CTL2 function;
  - forbidden items differ between prompts (no forbidden check text in more than 3 prompts).
- **Artifacts:** every path in `artifacts` exists.
- **Defined outputs:** every output code or label the rubric names appears in the prompt.

## Before delivering

Have an independent reviewer (a fresh subagent with no access to your generator) read 3 prompts per gap as a developer
would, write their own solution, and grade it with your rubric. Fix whatever fails a correct solution or confuses the
reviewer, then report what the review found.

---

## Internal tracking (not part of the brief)

- On delivery, rerun the masked-similarity and giveaway scans here, and spot-review 12 prompts again (2 per gap) before
  the teacher check (`spec/opcd_generate_gaps_brief.md` internal tracking).
