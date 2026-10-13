# Suite v5, round 2: run the references in real graphs, replace the clones, and add hard tests

**Rework `data/suite_v5/generate_rw.json` (T44–T73) in two parts:**
- **Part A:** build real CloverDX graphs on the local server and **run** the references that need
  graph context (lookups, sequences, parameters), plus a few runtime questions the review left open.
- **Part B:** replace the renamed copies with distinct scenarios, and make the suite hard enough to
  separate model variants.

`spec/suite_generate_rw_brief.md` still applies: realism rules, rubric format, record schema, checks,
deliverables. This file says only what is different. Owner rulings are in
`spec/ctl2_training_findings.md` §7. `resources/ctl2-basics.md` now has §8.9 DataIntersection.

## Why

Round 1 was reviewed and run against three model variants:
- rb1006 (the current base);
- c4 and c7 (two OPCD-trained variants of it).

Each ran 5 times per test, with thinking off and on. Scores below are after the rubric fixes:

| scenario (archetype) | tests | off: rb1006 / c4 / c7 | on: rb1006 / c4 / c7 |
|---|---|---|---|
| 1 CSV onboarding | T44–46 | .67 / .67 / .72 | .97 / .95 / .93 |
| 2 legacy migration | T47–49 | 1.00 / 1.00 / 1.00 | .99 / .99 / 1.00 |
| 3 lookup enrichment | T50–52 | 1.00 / 1.00 / 1.00 | 1.00 / 1.00 / 1.00 |
| 4 DataIntersection CDC | T53–55 | .84 / .82 / .79 | .86 / .82 / .86 |
| 5 dedup winner | T56–58 | .89 / .86 / .79 | .97 / .97 / .99 |
| 6 SCD2 | T59–61 | .88 / .94 / .88 | .81 / .77 / .87 |
| 7 Rollup report | T62–63 | .97 / .99 / .97 | 1.00 / 1.00 / 1.00 |
| 8 Normalizer JSON | T64–65 | .97 / .97 / .97 | .96 / 1.00 / 1.00 |
| 9 Partition | T66–67 | 1.00 / 1.00 / 1.00 | .99 / 1.00 / 1.00 |
| 10 function library | T68–69 | 1.00 / 1.00 / 1.00 | .97 / 1.00 / 1.00 |
| 11 DataGenerator | T70–71 | 1.00 / 1.00 / 1.00 | 1.00 / .97 / 1.00 |
| 12 audit stamping | T72–73 | 1.00 / 1.00 / 1.00 | .96 / .96 / .99 |
| **total** | | **.925 / .926 / .915** | **.952 / .946 / .965** |

Three problems:

1. **The suite is 12 tests, not 30.** The 2–3 tests of each archetype are the same prompt with renamed
   fields (75–94% shared 5-grams). Their scores move together, so they add repeats, not information.
2. **Half of it is saturated.** Archetypes 2, 3, 7, 9, 10 and 11 score 0.97–1.00 for every model in
   both modes. They cannot separate variants. Total spread between models: 0.01–0.02, within noise.
3. **Eight references were never run.** T50–52 (lookup), T59–61 (sequence) and T72–73 (sequence,
   parameters) failed standalone `ctl_validate` because it has no graph context. The graph check
   then failed with "Sandbox not found: DWHExample": that sandbox does not exist on this server.

**What the models actually got wrong** (judge notes, all variants). Use these as the guide to what
"hard" means:
- **DataIntersection, thinking on (40 of 45 answers):** they invent `transformLeftOnly()` /
  `transformRightOnly()` functions for the pass-through ports. Thinking off, they write `!a == b`
  where `a != b` was meant, which does not compile.
- **Onboarding, thinking off:**
  - `str2date` on an impossible date (2025-02-30) throws, instead of giving a DATE rejection;
  - a regex cap on the integer digits is not enforced;
  - a date shape like `2025-1-1` is accepted because the shape was never checked.
- **Dedup, thinking off:**
  - the winner is written to `$out.0` in `append()`, where it has no effect;
  - a tie-break branch is never reached for null/null timestamps.
- **SCD2:**
  - inverted change logic (`!(a || b)` where `!(a && b)` was meant);
  - returning `ALL` where one port was required;
  - Normalizer-style `transform(idx)` written in a Reformat;
  - an `integer` sequence used where `long` was specified.

The common thread is a multi-branch decision with several interacting edge cases, an uncommon
component contract, or a runtime failure path the code must avoid. Single-mechanism tasks with
clean data are solved every time.

## Part A: build and run the graph-dependent tests

Use the CloverDX MCP server at `http://localhost:8083/clover/mcp/mcp`. If it doesn't respond, the
server must be started by the owner (`~/cloverserver/.../bin/startup.sh`); ask, don't start it yourself.

- **Sandbox:**
  - Work in sandbox **`MiscExamples`**, under a new folder `suite_v5/` (graphs in
    `suite_v5/graph/`, data in `suite_v5/data-in/` and `suite_v5/data-out/`), unless the owner has
    created a dedicated `SuiteV5` sandbox. Check with `sandbox_list`.
  - **Do not touch `DPOForge`.** Its skeletons are shared and read-only.
  - Don't write outside your folder.
- **Start each session** with `task_workflow_get`. Use:
  - `component_get_guide` for component contracts;
  - `sandbox_write_file` to write files;
  - `job_validate`, then `job_run` + `job_await`, then `job_get_tracking` / `job_get_log` /
    `sandbox_read_file` to run a graph and check its output.

  Known quirk: `job_validate` has no `params` argument. Parameter values for a run go to
  `job_run(params=…)`, or into the graph's `<GraphParameters>`.
- **For each graph-dependent test** (lookup, sequence, parameters, dictionary; currently T50–52,
  T59–61 and T72–73, plus any new test that uses them):
  1. Build a minimal graph: a reader on a small input file → the tested component with the
     **reference** CTL → a writer per output port. Include the real resource: a lookup table with its
     own metadata and data, a sequence, or graph parameters.
  2. Write **8–20 input records that exercise every edge-case clause** of the spec: the first and
     last record, nulls vs empty strings, a lookup miss, a date without time, duplicates, a value
     that does not parse.
  3. `job_validate` must pass cleanly, then `job_run` it and compare every output file with the
     expected output you derive from the spec by hand.

  Record the result per test in `graph_run_results.json`:
  - the graph path and the input and expected files;
  - the runId and the actual output;
  - pass/fail per record.

  Set `"reference_runs": true` only when every record matches. A mismatch is either a bug in the
  reference or a spec ambiguity: fix it, and say which it was.
- **Also run every other reference the same way.** It's cheap once the harness exists, and runtime
  errors (an exception on a bad date, a wrong port) are what compile checks miss. The standalone
  `ctl_validate` result stays as the compile gate. Add `reference_runs` to every test.
- **Settle these open runtime questions with a live run**, and list each answer in the validation
  report as a fact for `ctl2-basics.md` (with the runId):
  1. `str2decimal("")`: does it throw, or return null? (T64/65 clause 4 depends on it; if it
     returns null, the reference must raise explicitly.)
  2. `str2date` / `isDate` with the strict flag on `2025-02-30` and on `2025-1-1` with pattern
     `yyyy-MM-dd`.
  3. DataGenerator with `recordsNumber=0`: is `generate()` called at all?
  4. DataIntersection: is any function other than `transform()` (and its `OnError`) ever called,
     e.g. `transformLeftOnly`? Check `component_get_guide` and a run.
  5. A Denormalizer that resets its state at the end of `transform()` instead of `clean()`: same
     output on 3 groups?

## Part B: distinct scenarios, and more hard tests

**Keep 30 tests and ids T44–T73.** Round 1 has no history apart from the baseline above, so
replace in place.

- **One clone per archetype at most.** In each archetype keep the best-reviewed test (the
  representative: T44, T47, T50, T53, T56, T59, T62, T64, T66, T68, T70, T72), and replace every
  renamed sibling with a **different scenario**. The replacement must differ in at least two of:
  - the component;
  - the core mechanism (e.g. a Rollup per-record emit vs a Denormalizer, multi-port routing vs a
    reject field, list/map state vs scalar state);
  - the edge cases tested;
  - the business domain.

  Pairwise 5-gram Jaccard between any two suite prompts must be **< 0.30** (round 1: 0.75–0.94
  within an archetype). Add this check to `check_suite_rw.py`.
- **Harden or replace the saturated archetypes.** These are 2, 3, 7, 9, 10 and 11, and their kept
  representatives too. Make them hard by:
  - **Interacting rules:** several clauses that touch the same field or decision, so getting
    one right is not enough. For example:
    - priority routing where an earlier rule's condition can throw on a later rule's input;
    - a lookup miss combined with a stale-date check and a fallback chain.
  - **Runtime failure paths:** inputs that make the naive code throw (an unparseable date, an
    empty string into a number, a null into arithmetic, a missing map key, a list index past the
    end), where the spec requires a defined result instead.
  - **No API hints in the prompt.** Round 1 often named the functions to implement (T64: "Implement
    Normalizer count() and transform(integer idx)"). A developer states the business need; the model
    must know the component's entry points, its return-value contract and which ports it writes.
    Keep "Write the complete CTL2 for this component only, including its required entry functions."
  - **Uncommon components or features.** Use components and contracts the corpus has few
    examples of, and verify each contract with `component_get_guide` and a run:
    - DataIntersection;
    - Rollup with per-record emit (`updateTransform`) *and* a group emit;
    - Normalizer over a map or a variant;
    - a Partition whose error port carries the message;
    - ExtMergeJoin full outer, with null sides;
    - a Denormalizer with list state;
    - dictionary entries.
  - **State across records:**
    - first and previous record logic;
    - groups of one record;
    - state that must reset per group;
    - "seen yet" flags.

    Use declared variables of every type here. The models believe a bare declared variable
    starts null, but `long`/`integer` start at 0, `string` at `""`, `date` at the epoch, and lists
    and maps start empty (§7). A naive `== null` first-record test is the bug.
  - **Exact numerics:**
    - decimal vs double;
    - rounding half-up at a stated scale;
    - integer division traps;
    - a percentage with a zero denominator.
- **Target difficulty.** Write each test so that you expect a careful expert to need the whole spec,
  and a plausible quick solution to miss at least one required item. Aim for:
  - at least **12 tests** where you expect a typical model answer to fail 2 or more required items;
  - no test that is a single mechanism over clean data.

  We will run the variants on the result. Tests that score ≥ 0.97 for all six model/mode
  combinations go back to you for round 3.
- **Rubric:** 8–12 required items (round 1: 6–8) so scores have resolution. One item per
  edge-case clause. List every valid alternative form, including the ones the runtime answers in
  Part A allow:
  - a reset in `clean()` or at the end of `transform()`;
  - any non-SKIP return value in DataIntersection;
  - `isnull(rec)`, `rec == null` or `count() > 0` before `get`.

  Penalise in `forbidden` only what is wrong at runtime or against the spec, never a style choice.
- **Coverage.** Keep all 12 archetypes, at 2–3 tests each.
  - Components across the 30 tests: at least 8 distinct ones.
  - Thinking-relevant traps: at least 6 tests whose natural solution needs a first-record or
    previous-record sentinel, or per-group state.
  - Dedup: against v4, the training corpus, `data/opcd/hard_cases*.jsonl` and
    `data/genbench/tasks.jsonl` if present (report it as missing if not), as before.

## Deliverables

- **Updated `data/suite_v5/generate_rw.json`.** Same schema, plus:
  - `reference_runs`;
  - `graph_file`;
  - `run_ids`;
  - `retired_scenario`: the round-1 scenario the test replaced, if any.
- **The run harness and evidence:**
  - `graph_run_results.json`;
  - the graphs and data copied back into `data/suite_v5/run_graphs/`;
  - the script that builds them.
- **`check_suite_rw.py` extended:**
  - the cross-prompt Jaccard < 0.30 check;
  - `reference_runs` true for all 30;
  - at least 8 components.
- **The runtime facts (Part A)** with their runIds, in `validation_report.json` under
  `facts_for_judge_reference`.
- **A short change log:** for each test id, what was kept, hardened or replaced, and why.

---

## Internal tracking (not part of the brief)

- **After delivery:**
  - review it (subagents per 10 tests, as in round 1);
  - rebuild `resources/ctl2_test_suite_v5.json`;
  - add the confirmed runtime facts to `ctl2-basics.md`;
  - rerun rb1006 / c4 / c7 at n5 in both modes with `scripts/suite_v5_rw_run.sh`.
- **Gates:**
  - spread between the best and worst variant on `generate_rw` ≥ 0.05 in at least one mode;
  - fewer than 6 tests at ≥ 0.97 for all six combinations;
  - no test at ≤ 0.2 for all six (that is a broken test or a broken rubric, not a hard one).
- **Round-1 baselines** (`results/results_qwen38_v5rw_*_rejudged_resources.json`) were on round-1
  prompts. Rerun them after round 2; don't compare across rounds.
