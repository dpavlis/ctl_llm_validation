# OPCD generate gaps: run-verified generate prompts for the component behaviours every model misses

**Write 120 new generate prompts**, each with a short rubric and a reference solution that you **run in a real
graph**, covering six gaps that suite v5 found in every model variant. They are training prompts for on-policy context
distillation (OPCD): the model writes its own answer, and a teacher (the same model with the official component
guide and verified runtime facts in its prompt) scores it token by token. **Your prompts and rubrics are the
training data; your references are not shown to the model.** They prove that each prompt is solvable and let us
measure the teacher and the result.

Follow the realism rules, prompt style and checks of `spec/suite_generate_rw_brief.md` and
`spec/suite_generate_rw2_brief.md`, and the rubric rules in `data/suite_v5/round2/rubric_rewrite_rules.md`. Graph
work uses the same harness and sandbox as round 2 (`MiscExamples`, a new folder `opcd_gaps/`; never touch
`DPOForge`). CTL2 facts: `resources/ctl2-basics.md` (now with §8.9 DataIntersection and §13.3 run-verified runtime
behaviour) and `spec/ctl2_training_findings.md` §7. This file says only what is different.

## Why

Suite v5 (findings §3.20) ran 30 real-world generate tests on rb1006 and two OPCD-trained variants (c4, c7) at
n=15. The variants tie within ±0.025, and they all fail the same things (score range over the three models, thinking
off / on):

| gap | suite test | off | on | what a typical answer gets wrong |
|---|---|---|---|---|
| G1 dictionary state | T73 | 0.52–0.59 | 0.67–0.71 | dictionary entries as typed run state; updating them only for accepted rows; reading a flag that gates other work |
| G2 Rollup per-record + group emit | T57 | 0.74–0.85 | 0.59–0.77 | `updateTransform` and `transform` both used; the emit functions are called with counter 0, 1, … until `SKIP`; global state reset per group |
| G3 stateful routing | T67 | 0.70–0.74 | 0.69–0.79 | Partition or Reformat that compares with the previous valid record; first record per key; zero as a real value, not "missing" |
| G4 multi-row versioning (SCD 2) | T60, T61 | 0.45–0.68 | 0.63–0.90 | Normalizer emitting CLOSE / OPEN / audit rows; sequence keys taken once per opening; carried state across consecutive records |
| G5 multi-check validation, two ports | T44, T46 | 0.39–0.63 | 0.81–0.96 | every check evaluated independently, all reasons listed in order; no parse exception (`str2decimal("")` throws, strict `str2date` throws on bad dates); exact shape checks |
| G6 UTC business calendars | T63, T62 | 0.54–0.84 | 0.93–0.97 | week / month / fiscal-quarter buckets computed in UTC on a non-UTC host (`getMonth(d,"UTC")`, `date2str(…,"UTC")`); half-away-from-zero rounding |

DataIntersection (T53/T54) is out of scope: it already has dedicated SFT and DPO training files.

## The prompts

**20 per gap, 120 in total.** For each gap:
- **Components:** at least 3 different ones where the gap allows. Examples:
  - G1: Reformat, Partition and DataGenerator using dictionary entries.
  - G2: Rollup only, but vary which emit carries what (per-record detail plus a group summary; per-record only with a
    group-level decision; a group emit that needs the first and the last record).
  - G3: Partition, Reformat with two outputs, Denormalizer.
  - G4: Normalizer and Reformat; one Rollup variant.
  - G5: Reformat with a reject port, Partition with an error port, Normalizer with per-child rejects.
  - G6: Rollup, Denormalizer, Reformat bucketing.
- **Scenarios:** new domains. No scenario may share business content with suite v5 (T44–T73), the v4 suite or
  `data/opcd/hard_cases*.jsonl`. Check with the 5-gram Jaccard script: < 0.30 against every suite prompt and
  between any two of your prompts.
- **Difficulty:** each prompt needs at least **two** interacting traps from its gap, plus one edge-case clause from
  another gap where it fits naturally (e.g. a G2 Rollup whose group key date must be bucketed in UTC). A prompt a
  quick answer solves fully is not useful for training.
- **Length:** 250–600 words (shorter than the suite: these are sampled many times). Metadata 8–25 fields per record,
  still realistic (mixed nullability, decimals with scale, at least one date, one unused field).
- **No hints.** State the business need, not the mechanism: don't name the entry functions, don't say "use a flag",
  "don't use STOP", "reset in clean()", "pass UTC", and don't give expected output values. Keep the closing sentence
  "Write the complete CTL2 for this component only, including its required entry functions."
- **Thinking traps that must appear across the set** (each in at least 15 prompts): a first-record / previous-record
  test where the natural sentinel is a declared variable (which starts at 0 / "" / epoch / empty, never null);
  blank or malformed text that would throw if converted unguarded; a date without a time part; a nullable field the
  spec reads.

## Rubric, reference and run

- **Rubric:** 6–10 required items and 2–3 forbidden items per prompt, following `rubric_rewrite_rules.md`: atomic,
  decidable from the code, valid alternatives listed, item-specific rationale, the runtime fact written into the item
  when the judge would not otherwise know it.
- **Reference:** a complete CTL2 solution, compiled with `ctl_validate` (standalone where possible) and **run** in a
  graph on 8–15 input records that exercise every edge-case clause, with the expected output derived from the spec by
  hand. `reference_runs: true` only when every output record matches.
- Run at least one probe per gap for any runtime behaviour your rubric relies on that is not yet in `ctl2-basics.md`
  §13.3, and record it with its runId.

## Output

`/home/pavlisd/llama_train/data/opcd/generate_gaps.jsonl`, one object per line:

```json
{"id": "opcd_gen_G2_07", "gap": "G2", "task_type": "generate", "component": "ROLLUP",
 "user": "<full prompt>",
 "traps": ["per-record emit loop", "group state reset", "UTC month bucket"],
 "rubric": {"required": [{"id": "G2_07.1", "check": "...", "rationale": "...", "clauses": [1]}],
            "forbidden": [{"id": "G2_07.F1", "check": "...", "rationale": "..."}]},
 "reference": "<CTL2>", "reference_compiles": true, "reference_runs": true,
 "graph_file": "opcd_gaps/graph/G2_07.grf", "run_ids": [18123]}
```

Also deliver:
- `data/opcd/generate_gaps_runs/`: graphs, inputs, expected and actual outputs;
- `generate_gaps_check.py`: schema, counts per gap and component, the Jaccard checks against the suites and within the set, word counts, `reference_runs` for all, and the trap coverage counts;
- `generate_gaps_report.json`: probes with runIds, and anything you could not make run.

---

## Internal tracking (not part of the brief)

- **Holdout:** 3 prompts per gap (18) for measurement, never trained on. Gate set: suite v5 T57, T60, T61, T62, T63,
  T67, T73, T44, T46 at n10 in both modes (`scripts/suite_v5_rw_run.sh`), plus the usual c4 gates (§5 step 4:
  T40/T42 n20, thinking-off validate 9 reps, fix n20, full generate).
- **Teacher:** c4 with a system-prompt block per prompt: the CloverDX component guide for that prompt's component
  (`component_get_guide`, trimmed to the contract and CTL sections) + `ctl2-basics.md` §13.3. **Teacher check first**
  (k=4, thinking on and off, judged with the brief's rubrics on the holdout plus 20 training prompts): the teacher
  must beat c4 by ≥ 0.10 per gap, or that gap is dropped — distillation cannot transfer what the teacher does not do.
  Also check thinking-off priming as in §3.19: if the guide in the prompt hurts thinking-off answers, score
  thinking-off samples against plain c4 (replay) as before.
- **Run c9:** continue from the c4 adapter (`init_adapter`), these prompts ×2 plus replay of v4 generate/validate and
  hard-case sets 1–3 ×1 so the declaration belief and validate do not regress; 16 rounds as c4.
- **Gates:** each gap's suite tests +0.10 in the weaker mode; T40/T42 not worse than c4; thinking-off validate WRONG
  ≤ c4 + 1 sd (8.2% + 1.3%); fix not below c4 − 0.03; v4 generate not below 0.96.
