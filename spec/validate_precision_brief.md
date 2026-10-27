# Brief: validate-precision OPCD — distil the server's verdict into the review

**For the executing agent.** Read `CLAUDE.md` and `WORKLOG.md`, then findings §3.19 (OPCD, the method), §3.25 (c13c, the
rule teacher), §3.21/§3.23 (c11: a per-prompt teacher context), §3.33 (exec-RFT, what did not work), §3.35 and §4.8
(the validate ground truth and its gate) and `spec/harness_measurement_findings.md` Part B. Follow the shared-machine,
git and correctness rules in `CLAUDE.md`. Do not commit; list what should be committed.

## Why

- **Validate's measured defect is precision, not recall** (§3.35). Thinking off, c13c puts an `[ERROR]` on 41% of
  clean, server-passing code (rb1011 line 28–35%); thinking on 7–14%. Every one of the 19 flagged controls is a false
  claim: 11 contradict §7 or the server run, 8 were refuted by server probes (32 probes, all outputs as required).
  The claims recur: "`initGroup` runs before the first record, so the counter numbers the first group 2";
  "accumulator state leaks into the next group"; "a non-nullable accumulator field is never initialised and throws";
  "DST breaks UTC millisecond arithmetic"; "DataIntersection must write output 1"; "REMOVE retracts only the first
  duplicate".
- **c13c's one recall gap is a compiler fact:** a Rollup missing one of its lifecycle functions fails at init
  (`Required function(s) … are missing`, live-verified 2026-10-22, §7), and c13c answers "ISSUES: none, VERDICT: PASS"
  on such code (0.18 recall thinking off, 0.35 on).
- **The belief fix did not transfer to reviews.** c13c passes T40/T42 at 0/20, yet in a validate review of clean
  Rollup code it still writes "`visits_seen` is never initialized". OPCD moved the belief on the prompt shape it was
  taught (fix / explain), not on validate-shaped reviews of correct code. Reviews need their own distillation.
- **The method is the one that has worked here:** on-policy context distillation, where the teacher is the same model
  with something extra in context. Here the extra context is the **server's verdict on the very code under review**:
  "this code compiled and produced exactly the required rows" for a clean reference, or the init error / first row
  difference for a planted defect. The student sees only the review prompt and learns to judge as if it had run the
  code. The triples cost nothing to build: no sampling run, the references and their fixtures already exist.

- **On fresh references the false alarms change character** (B1-tweak, §4.8: c13c thinking off false alarm 0.24,
  lifecycle recall 0.31): fewer Rollup beliefs, more "a nullable field is compared / assigned without a guard and can
  throw" (6 of 16 flagged controls), decimal-by-integer arithmetic claims ("truncates", "does not compile"; the code
  compiled and passed) and rule misreadings. **Probe the null-comparison claims on the server before writing the
  fact sheet** (what `null > 5`, `null + 1`, a null assigned to a `long` local actually do in CTL2); only a verified
  fact goes into the teacher, and a data-dependent risk the task does not exclude is a WARNING under §7, never an
  ERROR.

**Hypothesis:** training c13c on server-verdict-conditioned reviews lowers its clean-code false-alarm rate thinking
off (B1 0.41 → below 0.25, B1-tweak 0.24 → below 0.15) and raises missing-lifecycle recall (0.18 / 0.31 → above 0.6)
on the held-out planted-defect sets, without moving generate (execution pass rate, harness first attempt) or the
belief gates.

## Data

1. **Source code: the exec-RFT pool minus the evaluation sets.** `data/exec_rft/pool.jsonl` + `holdout.jsonl` are 297
   corpus generate / fix prompts with server-verified reference graphs (`manifest.graph_file`, the Test node holds the
   reference CTL). **107 of them are pool 1's corpus tasks, i.e. B1's references: drop them** (match on
   `manifest.reference_sha256` against `data/agent_harness/pool1.jsonl` `manifests[].reference_sha256`; the overlap
   was checked on 2026-10-27: 107 by prompt text and by reference hash). Drop the 40 holdout records too (they stay the
   exec-RFT holdout). About 150 references remain, across SCD-2, syntax pitfalls, Rollup accumulator, Normalizer,
   DataIntersection, Rollup lifecycle and zeroDate. Nothing from pool_tweak, the suite, the hard sets or B1/B1-tweak.
2. **Review prompts** with `scripts/harness_measurement/make_mutants.py` (adapt it to the exec-RFT record shape:
   `manifest` singular, graphs under `data/exec_rft/graphs/`; `--pool`, `--out`):
   - **clean:** every reference unchanged (~150);
   - **planted:** the six kinds, each confirmed failing on the server as the script does; take every confirmed mutant,
     not 30 per kind (expect 300–500). Use `--seed` ≠ 11, 12 so the sites differ from B1 / B1-tweak's choices.
   - Prompt text exactly as B1's: "Validate this <component> transform against its metadata and requirements." + the
     task text with the generate/fix instructions and code blocks stripped + the code. **No hint** about the defect.
   - **Half of the prompts carry the suite's output-format instruction** (`gen_answers.py` `FORMAT`) in the system
     prompt and half do not, so the behaviour is learned in both the test.py condition and the parser condition.
3. **Teacher context per prompt** (the c11 mechanism: a `hard` file with `teacher_context_field`; `opcd.py` appends
   it to the teacher's system prompt only, line ~273). Build it from the server result stored with the record:
   - **clean:** "This code was compiled and run on the CloverDX server against the task's fixture (N input rows) and
     produced exactly the required output rows. Report an [ERROR] only for a violation of a stated requirement or a
     compiler rule that you can point to in the code; a run that met the requirements cannot have one. Do not
     invent inputs the task does not describe. If nothing qualifies, answer ISSUES: none, VERDICT: PASS."
   - **planted:** "This code was run on the CloverDX server: <status>: <error text, or 'output port K: first difference
     at row R: expected … got …'>. Find the statement responsible and report it as the finding; do not report anything
     else as an ERROR unless you can point to it."
   - **plus the fact sheet** (same for all prompts), only facts from §7 or live-verified: the five Rollup lifecycle
     functions are required and `initGroup` runs once per group as its first record arrives, so a counter incremented
     there numbers the first group 1; accumulator fields reset per group from metadata (nullable → null, non-nullable →
     zero / default), so arithmetic on a non-nullable field needs no initialisation; declaration defaults (the rulev6
     text, `configs/eval_rb1006_rulev6_*`); DataIntersection's CTL writes `$out.0` only; date arithmetic in
     milliseconds is UTC and has no DST. Verify any fact you add with the server first and record the probe.
   - The teacher's answer is checked before it is trained on, as OPCD always does; additionally **reject a teacher
     sample that quotes the context** ("the server", "was run", "the fixture") — count them. `quote_guard` covers
     the rule marker; set `rule_marker` to a phrase that occurs in the fact sheet, and add the server-sentence check
     to the per-prompt context the same way if `opcd.py` does not already apply the guard to `teacher_context`.
4. **Anchors**, as `configs/opcd_c13c.yaml`: the belief prompts with the rulev6 teacher (target, contrast, hard sets
   1–2), `c13b_keep` (the gap / DI generate prompts that hold c13c's generate gains; exec-RFT left them out and lost T54),
   `replay_share` 0.4 with the plain-model anchor. The new review prompts take the place of the exec set: about
   60–65% of the non-replay weight, both thinking modes (`modes: validate: both` or a mode field per prompt, as
   `c13b_keep` does with `modes: ["on", "off"]`).

## Training

- Fresh run name `valprec1`, `configs/opcd_valprec1.yaml`, `init_adapter: data/opcd/c13c/round_015/adapter`, c13c's
  per-step hyperparameters (lr 2e-5, k 2, 32 prompts and 2 steps per round, LoRA r32). Rounds: enough to draw every
  review prompt about once per mode (exec-RFT's arithmetic: 19 non-replay draws per round). Smoke first (`opcd.py
  smoke`), then `prepare` before `train`. One GPU trains, one serves the sampler (`scripts/vllm_*` on a free GPU;
  check `nvidia-smi`, GPUs 0 and 2 belong to another user as of 10-27).
- Record per round: the share of teacher samples rejected by the guards, and the probe (T40/T42-style) as usual.

## Gates (against c13c, same vLLM path; the validate gates need no judge)

| gate | how | pass |
|---|---|---|
| **B1-tweak** false alarm and recall, both modes | `gen_answers.py --format` on `data/agent_harness/validate_mutants_tweak.jsonl`, 2 runs, `score_validate.py --records …` ; c13c's baseline is in `results/agent_harness/validate_gt_tweak_c13c_fmt.jsonl` (§4.8) | thinking off false alarm down by > 0.08 and lifecycle recall up by > 0.15; thinking on not worse by > 0.08 |
| **B1** same | `validate_mutants.jsonl`, stored c13c baseline (§3.35) | same direction |
| B1 plain condition, thinking off | without `--format` (the test.py path) | false alarm not higher than with the format |
| gap tests execution pass rate | 3 × n10 both modes, `exec_score.py` (c13c: 0.403 off / 0.761 on, 10-26 runs) | within ±0.06 |
| harness pool 1 first attempt | `agent_harness.py run --rounds 0 --runs 2`, both modes (c13c 0.65 / 0.82) | within the CI |
| T40 / T42, hard sets 1–3 by direction | 2 × n20, k4 | as c13c |
| T54 off `$out.1` | n20 | ≤ 1/20 |
| judge validate off ×9, WRONG excl. T18/T22, and thinking-on full suite n5 | regression check only | within §4.7 bands; explanation quality by a hand read of 10 answers |

## Deliverables

1. `spec/validate_precision_findings.md`: data statistics (clean / planted by kind and component, the two format
   conditions), teacher acceptance and guard rejections, the gate table with n and 95% CIs, a hand check of 10 controls
   c13c flagged and the trained model's answers to them (quote the sentence that changed), and **Indications**:
   (1) did the false-alarm rate fall, in which mode, and did the recurring claims disappear or get replaced by new ones
   (list them); (2) did lifecycle recall rise; (3) did the plain and format conditions move together; (4) generate and
   belief regressions; (5) verdict — adopt as the candidate (then c13c's successor), run a second round with more
   data, or stop and leave precision to the system prompt.
2. Configs, the adapted mutant builder and the context builder in the repo; raw data under `data/opcd/valprec1/`,
   `data/validate_precision/`, `results/`; a WORKLOG entry and a findings §3.37 stub.

## Do not

- Train on pool 1, pool_tweak, B1, B1-tweak, the suite, the hard sets or the exec-RFT holdout.
- Reuse a run folder; `opcd.py` resumes silently.
- Change rubrics, references or `ctl2-basics.md`; put no fact in the teacher that is not in §7 or server-verified.
- Touch `~/venv`, other users' processes, or other sessions' uncommitted files.
