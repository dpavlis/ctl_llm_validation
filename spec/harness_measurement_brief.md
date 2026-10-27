# Brief: two measurements the harness is missing — a fresh-domain pool, and ground truth for validate

**For the executing agent.** Read `CLAUDE.md` and `WORKLOG.md` first, then findings §3.28 (execution scoring), §3.31 (the
agentic harness) and §3.34/§4.7 (the noise bands) in `spec/ctl2_training_findings.md`. No GPUs are needed except a vLLM
server for the model under test. Do not commit; list what should be committed.

## Why

Two things limit what we can claim today:
1. **The harness pool is corpus-shaped.** Pool 1 (`data/agent_harness/pool1.jsonl`, 137 tasks) is 30 suite-v5 tests plus
   107 prompts written by the corpus authors in their own scenarios. c13c passes 0.92 of it thinking on with feedback
   (§3.31). We do not know whether a prompt from a domain and phrasing nobody here wrote scores the same.
2. **Validate has no ground truth.** Every validate number is a judge score against a rubric, and §3.34 shows the
   thinking-off validate aggregate moves 0.04–0.13 between seeds of one recipe, the WRONG share by 1.6–3.3 points — the
   whole range we have been reading as model differences. Generate got an executor-grade measure in §3.28; validate
   needs one.

## Part A — the fresh-domain pool (`agent_harness.py pool --tweak`)

The harness already has the mechanism, unrun: `--tweak SFT_JSON N` rewrites corpus prompts into a new business domain
with new field names and a structurally different rule (mut_validate's tweak prompt, `dpo_forge/review_judge.py`), then
asks the same LLM (`configs/mut_validate_qwen38.yaml` → `tweak_llm`, gpt-6.1-sol at 127.0.0.1:9001) for a fixture and a
reference solution (`FIXTURE_SYSTEM` in `agent_harness.py`), and keeps the task only if the reference, run in the graph,
reproduces the LLM's own expected rows. Two independent derivations must agree, so an accepted fixture is trustworthy;
a rejected one costs nothing.

1. Run it on the generate records of the six corpus sets with runtime harnesses (SCD-2, syntax pitfalls, Rollup
   accumulator, Normalizer multi-row, DataIntersection, zeroDate) with `--seed` varied, until **≥ 120 accepted tasks**.
   Record the acceptance rate and why rejections happen (no JSON, reference fails to compile, reference disagrees with
   the expected rows); if the rate is below 30%, read 10 rejections and fix the fixture prompt once, then continue.
   Write `data/agent_harness/pool_tweak.jsonl` and its `.report.json`.
2. Read 15 accepted tasks by hand: is the prompt self-contained (metadata, rules), is the component type right, does the
   expected output follow from the prompt and not only from the reference? Drop and count the ones that fail this.
3. Run c13c on it exactly as pool 1 was run (`scripts/agent_harness_run.sh` and `scripts/agent_harness_rows_run.sh` with
   `URL` set; both modes, 2 rounds, with and without `--rows-feedback`), `--runs 2` so each cell has n ≥ 240.
4. Report pool_tweak against pool 1 (first attempt, after error feedback, after rows feedback; by component; the compile
   causes). The question is one number: **does c13c hold its pool-1 pass rate on prompts nobody here wrote?** State the
   difference with a 95% CI.

## Part B — ground truth for validate

Two sources, both judge-free. Score answers with a small parser, not an LLM.

**B1. Planted defects with executor-verified failure.** Take the pool-1 tasks whose reference passes (all of them) and
derive validate prompts by mutating the reference code with one defect of a known kind, then confirming on the server
that the mutant fails (or, for a semantic defect, produces wrong rows against the fixture):

| mutation kind | example | expected finding |
|---|---|---|
| missing Rollup lifecycle function | delete `finishGroup` | ERROR naming `finishGroup` |
| output to an unconnected port | `$out.0` → `$out.1` in DataIntersection or a one-output Reformat | ERROR naming `$out.1` |
| field not in metadata | rename one output assignment's field | ERROR naming the field |
| wrong return constant | `return OK` → `return SKIP` in a transform that must emit | ERROR/WARNING on the return |
| off-by-one / inverted condition | `>=` → `>` on a stated threshold | finding on that condition (data-dependent → WARNING per §7) |
| null guard removed | drop a `x == null ? … :` on a nullable field | WARNING naming the field |
| nothing (control) | the reference unchanged | PASS, no ERROR finding |

Aim for ~150 mutants + 50 controls across components, each stored with: the prompt ("Validate this <component> against
its metadata and requirements…" plus the task text and the mutant code, no hints), the mutation kind, the **anchor**
(the identifier the finding must name: the function, field, port or line), the server's verdict on the mutant (init
error / wrong rows), and the expected severity under §7 (certain failure → ERROR; data-dependent → WARNING).

**B2. Corpus validate records with reference answers.** About 100 validate records across the sets have
`ISSUES / SUGGESTIONS / VERDICT` reference answers, and the Rollup lifecycle set has structured defect lists
(`logs/rollup_lifecycle_runtime/cases.json`, field `defects`, 65 cases; the Normalizer manifest has `defect`). Convert
each to the same record shape: anchors parsed from the reference's ISSUES lines (identifiers in backticks, function
names, port numbers) and the reference VERDICT. Keep the ones whose anchors are unambiguous; count the rest as dropped.

**Scoring (parser only):**
- **verdict accuracy:** the answer's `VERDICT:` line against the truth (PASS/FAIL);
- **defect recall:** an ISSUES line that names the anchor (case-insensitive, backticks optional);
- **false alarm on clean code:** any `[ERROR]` finding on a control / PASS record;
- **severity accuracy** on the planted defects (ERROR vs WARNING as expected);
- **finding count per answer** (precision proxy: findings not matching any anchor on a one-defect mutant).

Report these for c13c (thinking off and on) and for rb1011, rb1011s2 and rb1012 from stored exports if serving them is
cheap, so that the new measure can be set against the judge-based validate numbers of §3.34: does it separate the models
the same way, and is the seed spread smaller?

## Deliverables

1. `spec/harness_measurement_findings.md` with: Part A acceptance statistics and the hand check; the pool_tweak vs pool 1
   table with CIs; Part B dataset statistics (mutants by kind and component, controls, dropped); the validate ground-truth
   table per model and mode; and an **Indications** section answering: (1) does c13c hold on fresh prompts, and where not;
   (2) does the ground-truth validate measure agree with the judge ranking; (3) what is the model's clean-code false-alarm
   rate, the number that matters for "precision over recall"; (4) which measure should gate validate from now on.
2. Scripts under `scripts/harness_measurement/` (mutation generator, parser-scorer, table), data under
   `data/agent_harness/` (pools, mutants), results under `results/agent_harness/`.
3. A WORKLOG entry and a findings §3.35 stub (numbers and verdicts only).

## Do not

- Use an LLM to score Part B.
- Change rubrics, references or `ctl2-basics.md`.
- Put any pool_tweak or mutant prompt into training data; they are evaluation sets from now on.
- Touch `~/venv`, other users' processes, or other sessions' uncommitted files.
