# Suite v5: real-world generate tests

**Write 30 new generate tests for the evaluation suite, modelled on the tasks a DEVELOPER agent
will send in production: one ETL component inside a real graph, with realistic metadata, business
language, graph context (parameters, lookups, sequences, error ports) and the edge cases real data
has.** They extend `ctl2_test_suite_v4.json` to v5. Everything above "Internal tracking" is the brief.

This is **not** the 600-task benchmark pool (`spec/generate_bench_brief.md`). That pool is calibrated
by difficulty and refreshed; the suite is the fixed regression instrument with per-test history, run on
every model in both thinking modes. The two must not share scenarios.

House style, owner rulings and compiler checks are as in the earlier briefs;
`spec/ctl2_training_findings.md` §7 lists the rulings. Verify with `ctl_validate` any built-in or
construct you rely on beyond those facts.

## Why

The 25 generate tests in v4 are solved at 0.97–0.98 by every model since September. They were written
as unit tests of one CTL2 feature each, in tidy language, with 2–5 fields per port. Production tasks
look different:
- metadata with 15–40 fields, most of them copied through unchanged;
- specifications written in business terms ("late deliveries", "active contracts") that the model has
  to map onto field conditions;
- graph context: parameters, lookup tables, sequences, a reject / error port with a reason field;
- edge cases: empty strings vs nulls, dates with and without time, decimals from strings, duplicate
  keys, the first and last record;
- implicit requirements: copy every unmapped field through, keep the input order, do not drop records
  silently.

A model can pass v4 and still fail these. The suite needs tests where it does.

## Scenario archetypes (2–3 tests each, 30 in total)

| # | archetype | typical component(s) | what makes it real |
|---|---|---|---|
| 1 | **CSV onboarding: validate and route** | Reformat with 2 output ports, or Partition + Reformat | 20+ string fields in, typed fields out; rows that fail any rule go to a reject port with `reject_reason` listing every failed rule; rules in business language |
| 2 | **Legacy mapping / migration** | Reformat | wide input (30 fields), wide output (25), renames, code translations via a small inline map, defaults for missing values, copy-through of the rest |
| 3 | **Enrichment with reference data** | Reformat + lookup | composite key, miss handling with a default *and* a flag field, case / whitespace normalisation of the key before lookup |
| 4 | **Change detection (CDC) against a previous snapshot** | **DataIntersection** (see the component note below); one test may use ExtMergeJoin full outer for contrast | the matched pairs go through the transform, which emits UPDATE / UNCHANGED with a change-set string naming the changed fields; null-safe comparison; A-only and B-only records leave on ports 0 and 2 without CTL |
| 5 | **Deduplication with a winner rule** | Rollup or Denormalizer on a sorted stream | keep the most recent complete record per key; completeness defined over several nullable fields; tie-break |
| 6 | **Slowly changing dimension (type 2)** | Rollup / Reformat with state | close the previous version (`valid_to`), open the new one, surrogate key from a sequence |
| 7 | **Report aggregation with business buckets** | Rollup, summary per group | date bucketing (week / month / fiscal quarter), several conditional sums, averages with the zero-count case, percentages rounded half-up to 2 places |
| 8 | **Hierarchy flattening / un-flattening** | Normalizer (variant / JSON array in, rows out) or Denormalizer (rows in, list out) | nested structures, optional elements, ordinal numbering, a parent key copied onto each child |
| 9 | **Routing by rule priority with an error port** | Partition with `getOutputPortOnError` | 4–6 ports, rules in a stated order, a catch-all, records that throw go to the error port |
| 10 | **Reusable function library** | standalone functions (the suite's "Standalone / pure function" category) | 3–4 functions with precise contracts (null in → null out, rounding, formats), used from a small `transform()` |
| 11 | **Synthetic data for a test fixture** | DataGenerator | deterministic sequences, a parameter for the row count, referential consistency between generated fields, correct termination |
| 12 | **Audit and run metadata** | Reformat | run id and timestamp from graph parameters, a record hash or checksum over selected fields, a sequence number, a source-file name |

Every test uses one component's CTL only (the DEVELOPER tasks the model per component), but the
prompt may describe the surrounding graph in one or two sentences where it matters (what feeds the
port, what consumes it, which parameters exist).

### Component note: DataIntersection (archetype 4)

Use it for CDC rather than a joiner: it is the CloverDX component built for it, and the training
corpus has few examples of it, so these tests probe a component the model has rarely seen. The
prompt gives only what a developer would (the join key, which output ports are connected, the
metadata); the rubric checks that the model knows the contract. Port layout (owner-confirmed, 2026-10-12): input 0 = stream A, input 1 = stream B; output 0 = records only in A, output 1 = records in both A and B, output 2 = records only in B. From the component reference:
- two **sorted** inputs: port 0 (flow A, e.g. the previous snapshot) and port 1 (flow B, the new
  data); the **Join key** pairs fields across them (`$key_a=$key_b;…`);
- records whose key is on **both** inputs go through the CTL transform and out on **output port 1**
  (its own metadata); records only on input 0 go **unchanged** to output port 0 (input-0 metadata);
  records only on input 1 go unchanged to output port 2 (input-1 metadata);
- so the transform sees matched pairs only (`$in.0` from A, `$in.1` from B) and never the A-only or
  B-only records: INSERT and DELETE need no CTL, the transform decides UPDATE vs UNCHANGED;
- the transform uses the joiner CTL template (`function integer transform()`, same as Map and the
  joiners) and writes the matched-pair result to **`$out.1`**: CTL port numbering follows the
  component's output port numbers, so `$out.0` and `$out.2` are the pass-through ports and are not
  written by the transform (owner-confirmed, 2026-10-12);
- *Equal NULL* is true by default (null key values match each other); *Allow key duplicates* is true
  by default (duplicate keys produce a Cartesian product of pairs). State both in the prompt when the
  spec depends on them.

Write at least one test where the spec requires a change-set string (the names of fields whose
values differ, null-safe, in metadata order) and one where UNCHANGED pairs must be dropped
(`SKIP`) rather than emitted.

## Realism rules for every test

1. **Metadata:** 12–40 fields per record, real-looking names (`cust_ref_no`, `dlvry_promised_dt`),
   mixed nullability, decimals with `length` / `scale`, at least one date and one field the task
   never uses. Output metadata lists every output field; the spec says "copy all other fields
   unchanged" where that is meant, and the rubric checks it.
2. **Specification language:** business terms first, then precise definitions ("A delivery is *late*
   when `delivered_at` is after `promised_at` by more than 2 calendar days, or when `delivered_at` is
   null and `promised_at` is more than 30 days ago."). 5–10 numbered clauses. Every clause testable.
3. **Edge cases stated, not implied:** what null means for each nullable field the task touches; empty
   string vs null; the first record / group; duplicates; a date without a time part; a string that does
   not parse. Each test must have at least two such clauses.
4. **Graph context where the archetype calls for it:** parameters (`${...}` read from CTL), a named
   lookup table with its own metadata, a sequence, dictionary entries, an error / reject port with a
   `reason` field. Verify the CTL mechanism with the compiler before writing the rubric.
5. **Length:** prompts of 300–900 words. If it does not fit in that, split the task.

## Rubric

Same format as v4's generate tests (T33 is the model):
- `required`: 6–12 items, `{id, check, rationale}`; every spec clause covered; alternatives listed
  wherever CTL2 allows several correct forms; copy-through, ordering and null handling get their own
  items.
- `forbidden`: 2–5 items for the plausible wrong solutions: dropping records silently, a null guard on
  a never-null field, integer division for a decimal percentage, lookup without miss handling,
  `isnull()` on a bare declaration, state not reset per group.
- `scoring`: `{"method": "required_fraction", "forbidden_penalty": 0.2}`.
- `temperature`: 0.4 (the project's standard; §4.2 of the findings).
- The judge sees `ctl2-basics.md` from the snapshot. If a rubric relies on a CTL2 fact not in that
  file (sequences, parameters, dictionary, a date pattern letter), list the fact in the validation
  report with how you verified it, so it can be added to the reference before the snapshot is cut.

## Record schema

The suite's test object, plus a `group` field:

```json
{"test_id": "T44", "type": "generate", "group": "rw",
 "component": "Reformat (CSV onboarding, reject port)",
 "archetype": 1, "temperature": 0.4,
 "system_prompt": "<v4's generate system prompt, verbatim>",
 "user_message": "…",
 "rubric": {"description": "…", "required": [...], "forbidden": [...],
            "scoring": {"method": "required_fraction", "forbidden_penalty": 0.2}},
 "reference": "<complete, compiled CTL2 solution>", "reference_compiles": true,
 "compile_result": "<ctl_validate output>"}
```

`test_id` continues v4's numbering (T44–T73). `reference` is for review and the judge's aid only;
mark anything you are unsure of.

## Checks

- Compile every reference with `ctl_validate` in the stated header mode; no diagnostics.
- A `check_suite_rw.py`: schema, id sequence, archetype coverage (2–3 each), field-count and
  prompt-length rules, every spec clause referenced by a rubric item, metadata XML well-formed, every
  field named in the spec or rubric present in the metadata.
- Dedup against the v4 suite, the training corpus (`ctl_lora_training/sft_training_data/CTL_LoRAT_*.json`),
  `data/opcd/hard_cases*.jsonl` and `data/genbench/tasks.jsonl` (exact and 5-gram Jaccard; rewrite above 0.5).
- Subagent review per 10 tests: decidability of each rubric item from the prompt; the reference
  re-derived from the spec; CTL2 facts against §7 and the compiler.
- Deliver `data/suite_v5/generate_rw.json` (an array of the 30 test objects), the checker, compile
  results, dedup report and a validation report.

---

## Internal tracking and rollout (not part of the brief)

- **Assemble v5:** `resources/ctl2_test_suite_v5.json` = v4's tests + the 30, same
  `judge_system_prompt` / `judge_instructions`; snapshot to `results/eval_snapshot_<date>/` with
  the updated `ctl2-basics.md` once the new facts are confirmed by the owner.
- **Scoring continuity:** `test.py` summary should report `generate` as before *and* `generate_rw`
  (the `group: rw` tests) separately, so v4 history stays comparable; the like-for-like column stays
  on v4's test ids. Small change in `run_suite` / `print_summary_table`.
- **Baselines:** run rb1006, c4 and c7 on v5 at n=5 in both modes (vLLM, ~12 min each) before any
  model is trained with v5 as a gate. Expect `generate_rw` well below 0.97; that gap is the point.
- **Exclusion:** add v5 to `self_distill.SUITE_FILES` immediately so nothing trains on it.
- **Refresh policy:** when real DEVELOPER traffic exists, replace up to 10 of the 30 per version with
  anonymised real tasks (same checks), keeping ids stable for retired tests by marking them
  `retired: true` rather than deleting.
