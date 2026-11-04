# Complex-generation benchmark and training pool: 600 CTL2 generate tasks

**Write 600 new *generate* tasks, each with a checkable rubric and a compiled reference solution,
in the shape a DEVELOPER agent will send to the model in production: one task sentence, the port
metadata, a numbered specification.** No answers are shipped to the model; the rubric is for the
judge. The 50 hardest tasks become a held-out benchmark; the rest become the training pool for the
next method (reward-driven training). Everything above "Internal tracking" is the brief.

House style, owner rulings and compiler checks are as in the earlier briefs
(`spec/opcd_hard_cases_brief.md`, `_cases2_`, `_cases3_`), and `spec/ctl2_training_findings.md`
§7 lists the rulings that settle what counts as correct.

## Why

Generate is the model's primary job, and the current 25 generate tests sit at 0.97–0.98 for every
model since September: they no longer measure anything. They are also simpler than what the
DEVELOPER agent will ask for. We need tasks of production complexity, in production shape, with a
rubric that a judge can score item by item, and enough of them that a training method can learn from
them without ever seeing the benchmark.

## Task matrix: fill every cell

**Components (10): about 65 tasks each, DataIntersection about 30:**

| component | CTL contract the task must exercise |
|---|---|
| Reformat | `transform()`, one or more output ports |
| Rollup | all five lifecycle functions, custom accumulator, per-record or summary output |
| Denormalizer | `append()` / `transform()` / `clean()`, group state |
| Normalizer | `count()` / `transform(idx)` / `clean()` |
| Partition | `getOutputPort()`, routing only, optional `getOutputPortOnError` |
| ExtFilter | a bare boolean expression or `function boolean filter()` as the brief's earlier sets used |
| ExtHashJoin / ExtMergeJoin | `transform()` with `$in.0` driver and `$in.1`… slaves, inner / left outer, unmatched slaves null |
| DataGenerator | `generate()`, state across calls, `STOP` semantics |
| Reformat + lookup | `lookup(X).get(key)` with miss handling, or a map built in `init()` |
| DataIntersection | change detection between two sorted inputs: matched pairs through `transform()` to output 1, A-only / B-only records pass unchanged on ports 0 / 2; see the component note in `spec/suite_generate_rw_brief.md`. The transform writes `$out.1` (CTL numbering follows the output ports). Rarely seen in the corpus, so keep it to ~30 tasks |

**Logic features (10). Each task names 2–4 of them in its metadata; across the set every feature
appears at least 90 times:**

1. multi-clause conditionals where the order of rules matters (first match wins, priorities);
2. aggregation with per-group resets (sums, counts, min / max, distinct lists);
3. cross-record state: previous record, running totals, sequence breaks;
4. date arithmetic and formats: `dateDiff`, `dateAdd`, truncation, parsing with patterns, time zones;
5. string parsing and building: split, substring, regex, padding, joining with separators;
6. decimal precision and rounding, integer vs decimal division, overflow-safe `long`;
7. lookups and maps: key composition, misses, defaults, caching in `init()`;
8. nullable handling: inputs that may be null, unmatched slave fields, map misses, the spec saying
   what null means;
9. multi-port routing and partial output: which records go where, error ports;
10. typed conversions: `str2integer`, `num2str` with formats, `decimal` ↔ `number`, list / map
    containers, `variant`.

**Tiers:**

| tier | share | spec clauses | features | cross-record state |
|---|---|---|---|---|
| T1 | 20% | 2–3 | 1 | no |
| T2 | 40% | 4–6 | 2 | sometimes |
| T3 | 40% | 7–10 | 3–4 | yes |

**Domains:** vary widely (logistics, billing, telemetry, clinical, HR, retail, energy, public
records, finance, manufacturing). Do not reuse scenarios from the training corpus, the suite or the
hard-case sets; the dedup check below enforces this mechanically, so pick domains and field names
freely rather than defensively.

## Each task

**The prompt (`user_message`)** has three parts and nothing else:
1. One sentence naming the component and its purpose, as a developer would write it ("Write the
   complete CTL2 Rollup transform that …"). State the group key, sort order and port layout
   where the component needs them.
2. Port metadata as CloverDX XML, one `<Metadata>` block per port, every field with `type` and
   `nullable`, decimals with `length` / `scale`, lists with `containerType="list"`. Lookup tables
   get their own metadata block and the lookup name.
3. A numbered specification. Every clause must be testable: it names a field, a value, a condition
   or an ordering. Say what null means wherever a nullable field is involved. Say what happens on
   the first record or group when state is involved. Don't explain CTL2; the model is supposed to
   know it.

**The rubric** mirrors the suite's generate tests (`results/eval_snapshot_20261003/ctl2_test_suite_v4.json`,
see T33 for the style):
- `required`: 5–10 items, each `{id, check, rationale}`. Every spec clause maps to at least one item.
  The `check` says what to look for in the code, including the acceptable alternatives (the suite's
  T33.5 is the model: "any membership test that leaves the emitted order intact … all of these score
  PRESENT"). The `rationale` says why, with the CTL2 fact it rests on.
- `forbidden`: 1–4 items a plausible wrong solution would contain: the wrong port, a missing reset,
  `.contains()` on a list, `isnull()` on a bare declaration, integer division where decimal is
  specified, a null guard on a field the spec says is never null.
- `scoring`: `{"method": "required_fraction", "forbidden_penalty": 0.2}` as in the suite.
- Every `check` must be decidable from the prompt alone. If deciding it needs a fact the prompt
  does not state, state it in the spec or drop the item.

**The reference** is a complete solution you wrote and compiled with `ctl_validate`. It proves the
task is solvable in the header mode you chose, and the judge may see it as an aid. It is not ground
truth: mark it `"reference_confidence": "high" | "medium"` honestly, and never let the rubric depend
on a choice the reference made that the spec does not require.

## Record schema

One JSON object per line in `/home/pavlisd/llama_train/data/genbench/tasks.jsonl`. Keys match the
suite's test objects so `test.py` can load them unchanged:

```json
{"test_id": "G0001", "type": "generate",
 "component": "Rollup (summary-only, custom accumulator)",
 "temperature": 0.4,
 "system_prompt": "<the suite's generate system prompt, verbatim>",
 "user_message": "<task sentence>\n\n<metadata XML>\n\nSpecification:\n1. …",
 "rubric": {"description": "…", "required": [{"id": "G0001.1", "check": "…", "rationale": "…"}],
            "forbidden": [{"id": "G0001.F1", "check": "…", "rationale": "…"}],
            "scoring": {"method": "required_fraction", "forbidden_penalty": 0.2}},
 "bench": {"tier": "T3", "features": [2, 3, 8], "domain": "cold-chain logistics",
           "header": "//#CTL2", "reference": "<complete CTL2 code>",
           "reference_compiles": true, "reference_confidence": "high",
           "compile_result": "<ctl_validate output>"}}
```

`component` uses the suite's naming (`Rollup (summary-only, custom accumulator)`,
`Join (ExtHashJoin LEFT OUTER)`, `Map (Reformat + Lookup)`, …) so results group with the existing
tests. The `system_prompt` is the suite's generate prompt, copied verbatim from the snapshot.

## Production and checks

- Produce in 10 batches of 60 (one component per batch with a mixed tier profile; the tenth batch
  tops up whichever feature counts are short). Review each batch with subagents as before: one reads
  the spec against the rubric for decidability, one re-derives the expected behaviour from the spec
  and checks the reference does it, one checks CTL2 facts against §7.
- Compile every reference with `ctl_validate`. It must pass, with no diagnostics, in the stated
  header mode.
- Run `data/genbench/check_tasks.py` (write it as part of this work, like `check_hard_cases*.py`):
  schema, id sequence, component / tier / feature counts against the matrix, every spec clause
  referenced by a rubric item, rubric ids unique, metadata XML well-formed, every field named in the
  spec present in the metadata.
- Dedup: normalise whitespace and compare `user_message` against every prompt in
  `ctl_lora_training/sft_training_data/CTL_LoRAT_*.json`, the suite snapshots and
  `data/opcd/hard_cases*.jsonl` (exact), and report the 20 nearest by 5-gram Jaccard on the spec
  text (near). Rewrite anything over 0.5.
- Deliver `tasks.jsonl`, `check_tasks.py`, the compile results, the dedup report and a validation
  report in the style of `data/opcd/hard_cases3.validation_report.json`.

---

## Internal tracking (not part of the brief)

- **Calibration** (`data/genbench/calibrate.py`): sample rb1006 at k=4 on all 600 via the vLLM
  eval path (`scripts/vllm_eval_serve.sh`, `test.py` vllm mode), score with compile +
  `test.py`'s rubric judge, record pass@1 / pass@4 / compile rate per task. About 1.5 GPU-hours and
  2,400 judge calls.
- **Split:**
  - benchmark `ctl2_generate_bench_v1.json` (suite schema): 50 tasks with pass@4 > 0 and
    pass@1 ≤ 0.5, stratified by component and tier, plus 10 regression controls that rb1006 passes;
    add it to `self_distill.SUITE_FILES` and the exclusion set so no pipeline trains on it;
  - pool `pool.jsonl`: the rest, with pass@1 labels; GRPO samples preferentially from
    0 < pass@1 < 1;
  - review queue: pass@4 = 0 → agent decides unsolvable vs ambiguous, rewrites the ambiguous.
- Also measure c4 and c7 on the benchmark before any training on the pool, so the first GRPO
  run has two baselines.
- v2 later: input / expected-output fixtures for T3 tasks, executed on the CloverDX server, as a
  judge-free reward.
