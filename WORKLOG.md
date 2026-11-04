# Work log

Important progress and decisions, newest first. Details and numbers: `spec/ctl2_training_findings.md` (section in brackets).

## Where we are (2026-11-03)

- **Ship candidate: valprec2** (since 2026-10-30, §3.38), the rb1009 base plus OPCD adapter
  `data/opcd/valprec2/round_155`. **Merged, deployable export (2026-11-03): `~/exports/qwen38_ctl2_deploy_valprec2`** (README and
  system prompt inside). It succeeds c13c (`data/opcd/c13c/round_015`), which was confirmed by 20-sample checks
  and by running the generated code on the server. valprec2 is c13c plus validate-review OPCD:
  - it matches c13c on generate (fresh-domain harness, paired);
  - it is the best validate model measured.
  The c13c numbers below remain the generate reference.
- **Deploy with thinking on and a compile-and-retry loop.** In the agentic harness (§3.31) c13c passes 88% of 137
  execution-scored tasks thinking on with error feedback, 92% when the failing test rows are fed back too (28/30 real-world
  suite tests); thinking off 69% / 80%. It holds on 165 fresh-domain prompts nobody here wrote (§3.36): 86% / 91%
  thinking on, within ±0.08 of pool 1's corpus tasks.
- **Biggest real gap:** generate without thinking. Only 44% of c13c's answers run correctly (§3.28).
- **Validate is gated on ground truth now** (§3.35, §4.8): planted server-confirmed defects, parser-scored, sets B1 and
  B1-tweak. Thinking-off validate flags 24–41% of clean code with an [ERROR]; c13c misses a removed Rollup lifecycle
  function 7 times in 10; the judge's 0.04 seed gaps are not reproduced.
- **valprec2 adopted (§3.38).**
  - **Method:** OPCD with the server's verdict in the teacher's context, rebalanced to 68% clean reviews.
  - **Thinking-off false alarm, format path:** B1 0.41 → 0.25, B1-tweak 0.24 → 0.15.
  - **Plain path:** back at c13c's 0.30.
  - **Thinking on:** false alarm 0.00–0.03, recall 0.96.
  - **Generate:** the same as c13c on the fresh-domain harness (first attempt 0.73 / 0.82 vs 0.72 / 0.81, paired CIs
    ±0.04).
  - **Still open:** thinking-off false alarms (null as ERROR, initGroup state, DataIntersection `$out.0`). These are
    left to the system prompt or the retry loop.
  - **Deployment prompt rules (2026-10-31/11-01):** seven CTL2 fact lines (`data/sysprompt/rules_v1.txt`) lift the
    four residual gap tests 0.53 → 0.73 thinking on and remove the try/catch / reserved-name / null-accumulator errors,
    but on the broad fresh-domain pool they cost DataIntersection (−0.03) and raise the validate false alarm (on 0.02 →
    0.08, off 0.15 → 0.38) by priming the DataIntersection port belief with the word `ALL`. Not adopted as written.
  - **DataIntersection framing (2026-11-01):** a join-like paragraph with no port numbers (`data/sysprompt/di_frame_v2.txt`)
    takes the DI harness tasks 76 → 98/102 first attempt thinking on with validate false alarms flat. §8.9 rewritten,
    corpus round 3 in (`spec/dataintersection_join_framing_brief.md`). **OPCD difr1 with §8.9 as teacher (2026-11-02):**
    DI generate 76 → 90/102 first attempt thinking on, but the reviewer learned to flag `return ALL` on clean code (DI
    control false alarm 0.08 → 0.38 thinking on). difr2 (false alarms dropped, on-policy pairs) keeps the generate gain
    with the same false alarm; difr3 (fixed DPO pairs against the ALL flags) halves the false alarm at best and loses the
    generate gain (79 vs 91/102). None adopted; the reviewer's and the generator's port belief move together, and the
    deployment-prompt framing does the job without the trade-off (see the three 2026-11-02 entries).
  - **Deployment prompt decided (2026-11-03): `data/sysprompt/deploy_v1.txt`** = rules + DI paragraph. Thinking on:
    fresh-domain first attempt 0.815 → 0.918 (+0.10 [+0.05, +0.16]), DI 102/102, gap tests 64 → 85/120, validate false
    alarm 0.02 → 0.00, recall flat. The rules-only false-alarm rise is gone.
    A severity paragraph on top (deploy_v2, 2026-11-03) was not adopted: severity labelling +0.03 (noise), mutant FAIL
    verdicts −0.03 in both modes (CI excludes zero), generate −0.015/−0.030 (not significant).
  - **rb1013 rebuild on the round-3/4 DataIntersection corpus (2026-11-03): not adopted.** T53/T54 thinking off 0/10
    with `$out.1` in 10/10 (rb1011, same recipe on the old sets, is the same), thinking on unchanged, DI validate
    controls worse (false alarm 0.38 on), validate ×9 0.777 (T38 collapse). The port belief is not fixed by the DI
    sets; the prompt is the fix. rb1009 stays the base.
- **Training on the model's own harness-corrected answers (retry1) did not help either** (§3.39): +0.10 first-attempt
  pass on the fresh-domain pool thinking off, but gap-test execution pass −0.06 off / −0.15 on, no-code answers thinking
  on, the accumulator belief back in hard set 2. Not adopted; the compile-and-retry loop at inference does the same job.
- **Training on the model's own server-verified answers (exec-RFT) did not help** (§3.33): one round moved neither the
  gap-test pass rate nor a held-out pool, and pushed T54 thinking off back to `$out.1`. Not adopted.
- **rb1012 not adopted** (§3.30). The two new corpus sets showed no gain in two seeds, and both seeds regressed on the
  Rollup accumulator explanation. Neither set is in the default rebuild recipe. The regression is in the SFT records (§3.32, §3.34), not in the DPO pairs
  (§3.32); rb1011 seed 7 shows it is the new SFT records, not seed luck (§3.34).

## 2026-11-03 — Deployable export: `~/exports/qwen38_ctl2_deploy_valprec2`

- **What:** the valprec2 adapter (`data/opcd/valprec2/round_155`) merged into the rb1009 SFT+DPO export with
  `opcd.py export` (`scripts/export_deploy_valprec2.sh`, one minute on one GPU). Full HF checkpoint, 12 shards + the
  base's vision tensors as `model-visual.safetensors`, base `config.json` (vLLM refuses the text-only
  `Qwen3_5TextConfig` that `AutoModelForCausalLM` writes, so the export keeps the multimodal config and the untouched
  vision tower: 52 GB, a drop-in replacement for the rb1009 folder). `README.md` and `system_prompt.txt` (base prompt +
  deploy_v1) inside the folder give the serving command and request settings.
- **Checked:** the LoRA target weights differ from the base, everything else is bit-identical. Teacher-forced on 12
  pool_tweak prompts × 300 tokens (vLLM, merged vs rb1009 + hot-loaded adapter): mean |Δ logprob| 0.009 per token,
  p95 0.055, max 0.26 (bf16 rounding); the plain rb1009 base is at 0.049 mean with gaps up to 3.1. Greedy outputs
  identical on 4/12 prompts and divergent at near-ties on the rest, as expected across a merge.
- **Serve:** `--model ~/exports/qwen38_ctl2_deploy_valprec2`, no `--enable-lora`; thinking on, the system prompt from
  the folder, compile-and-retry loop (how-to §9).

## 2026-11-03 — Severity paragraph in the deployment prompt (deploy_v2): not adopted, deploy_v1 stays

- **What:** `data/sysprompt/severity_v1.txt`, one paragraph stating the §7 severity ruling (ERROR only for a compile
  failure, a certain runtime failure or a violated stated requirement; data-dependent risk is WARNING; style is INFO;
  verdict FAIL only with an ERROR), appended to deploy_v1 as `data/sysprompt/deploy_v2.txt`. valprec2, thinking on
  and off, deploy_v1 vs deploy_v2 under the same server (`scripts/sysprompt/severity.sh`, configs
  `configs/eval_sp_v4val_valprec2_deploy{1,2}_{on,off}.yaml`).
- **Ground truth B1-tweak, format path, 2 runs** (`results/sysprompt/gt_tweak_valprec2_deploy2.md`, deploy2 − deploy1,
  paired bootstrap):
  - the "severity ok" column, the target, moves 0.91 → 0.94 thinking on and 0.91 → 0.93 off — inside the noise band;
  - the mutant verdict FAIL rate drops in both modes and the CI excludes zero: on −0.027 [−0.055, −0.007],
    off −0.034 [−0.062, −0.014]. The rule makes the model call a removed null guard "data-dependent" (null_guard_removed
    named as WARNING 5/19 on, 2/18 off, versus 0 under deploy_v1) and drops missing_lifecycle recall 0.72 → 0.59 thinking
    on, so a planted defect gets a PASS verdict;
  - defect recall −0.014 both modes (CI touches zero); clean-code false alarm on 0.00 → 0.01, off 0.17 → 0.11
    (−0.06 [−0.13, 0.00]), the only move in the right direction and still inside the ±0.08 band.
- **Judge, suite v4 validate tests, n5:** mean on 0.821 → 0.829, off 0.799 → 0.777. Per test the moves are mixed and
  individually inside seed noise except T22 on +0.33 (the severity-grading test) against T12 on −0.20 and T18 off −0.24.
  WRONG rate (excl. T18/T22) on 0.141 → 0.116, off 0.047 → 0.069; both below the 0.04 judge noise.
- **Generate guard, harness pool_tweak thinking on, 2 runs, paired against the deploy_v1 run:** first attempt 303 → 298/330
  (−0.015 [−0.060, +0.029]), final 311 → 301/330 (−0.030 [−0.071, +0.010]); DataIntersection 102 → 99/102, Reformat
  −0.06/−0.08. Nothing significant, but no gain anywhere to pay for a downward drift on the primary objective.
- **Decision:** deploy_v1 stays the deployment prompt. The paragraph buys +0.03 on severity labelling, which is noise,
  and costs mutant FAIL verdicts and T18 (a generation-time explanation test). The ruling is better applied by the judge
  rubrics and by the corpus reviews than by the review prompt, where it reads as "downgrade when in doubt". Not in the
  how-to; `severity_v1.txt` and `deploy_v2.txt` kept for the record.

## 2026-11-03 — rb1013: rebuild on the round-3/4 DataIntersection corpus — not adopted, the port belief is not in the DI sets

- **What:** rb1011 recipe (rb1009 SFT lr 5e-5 2 ep + DPO lr 5e-6 1 ep, seed 42, `--sd=c13c_belief:1`, rb1012 sets
  excluded) on corpus 3de7b55: the first base trained on DataIntersection rounds 3 and 4 (answers say the CTL sees one
  output record, `return OK`, rejected = wrong code) and the revised SCD2 DI rows. SFT 13433 / DPO 2083, same counts as
  rb1011. Export `/home/pavlisd/exports/qwen38_rb1013_sftdpo`. Gates `scripts/base_eval.sh` (now `OFF_GPU`/`ON_GPU`),
  DI subsets `scripts/base_di_check.sh`. Single seed; band ±0.07 on validate and the gap tests.
- **The question it was built for: no.** T53/T54 thinking off, n10: judge 0/10 and 0/10, `$out.1` written in 10/10
  and 10/10 (rb1009 10/10 pass with 0 `$out.1`, rb1011 — same recipe, old DI data — 0/10 with 10/10 `$out.1`, rb1012
  5/10 and 7/10). Thinking on 3/10 and 4/10 with `$out.1` in 7 and 6, the same as rb1009 (2/10, 6/10; 6 and 3) and
  rb1011 (4/10, 1/10). The only thing the new sets changed: `return ALL` is gone from the answers (0 of 40, rb1009 and
  rb1011 10 of 10). The port habit is unmoved and thinking off is at the bad end of a seed band that already spans 0–10.
  DI harness subset (102, thinking on, no prompt): first attempt 37/102 vs valprec2 76 (−0.38 [−0.50, −0.25]), 63
  attempts hit `Cannot write to output port '1'`; after two feedback rounds 83 vs 89 (within CI). valprec2 is OPCD on
  rb1009, so this pairing overstates the base difference; the rb1009 base was not run on the subset.
- **DI validate controls (B1-tweak DI, 24 clean):** false alarm 0.25 off / 0.38 on vs valprec2 0.08 / 0.08; recall flat
  (0.91 / 0.95 vs 0.93 / 0.98). `results/di_check/gt_tweak_di_rb1013.md`.
- **Other gates vs rb1009:** suite v4 generate 0.950 off / 0.982 on (rb1009 0.966 off); validate thinking off ×9 mean
  0.777 vs rb1009 0.861, rb1011 0.891, rb1012 0.854 — below the band. Most of it is T38 at 0.00 in 9 of 9 (answers
  "No issues found" to updateGroup returning false; the rb1003 collapse again, run-specific) and T24 0.68 → 0.26
  (date-pattern severity, "invalid pattern" wording). Gap tests thinking off exec 18/110 (base without OPCD or prompt;
  T63 fails on a local named `month`). Belief on recipe: T40 18/20, T42 5/20 (rb1009 0/20, 0/20), hard set 2 trap
  belief 0.55 (rb1011 0.57, rb1009 0.92).
- **Decision:** not adopted; rb1009 stays the base under valprec2. The DataIntersection port belief is not fixed by the
  DI sets, where the requests still name the three outputs; `deploy_v1` (DI paragraph in the prompt) remains the fix.
  No Stage 3 on rb1013.
- **Mishap, fixed:** at 03:28 `scripts/sysprompt/deploy.sh`'s cleanup killed every server of mine on :3012, including
  the rb1013 thinking-on server; the first restart was killed by `base_eval.sh`'s substring match and my own kill hit
  the thinking-off branch. Nothing ran 03:32–07:48. The prompt-test scripts now stop only the server they started
  (`pkill -P $SERVER`) and wait only on their own jobs; the lost gates were rerun by `scripts/rb1013_gates_resume.sh`.
  GPU 1 showed 100 % utilisation with 0 MiB afterwards: a stale counter, cleared by the first kernel launched.

## 2026-11-03 — Deployment prompt deploy_v1 (rules + DataIntersection framing) holds on every gate; rb1013 rebuild started

- **What:** `data/sysprompt/deploy_v1.txt` = the seven rule lines (`rules_v1.txt`) followed by the join-like
  DataIntersection paragraph (`di_frame_v2.txt`). Measured on valprec2 thinking on against valprec2 without a prompt,
  paired on the same prompts; the rules-only run of 2026-10-31 for the gap tests. Config
  `configs/eval_sp_v5gaps_valprec2_deploy_on.yaml`, script `scripts/sysprompt/deploy.sh`.
- **Fresh-domain harness (pool_tweak, 165 tasks × 2 runs, 2 feedback rounds):** first attempt 0.815 → 0.918
  (+0.10 [+0.05, +0.16]), after feedback 0.882 → 0.942 (+0.06 [+0.02, +0.11]). DataIntersection 76 → 102/102 first
  attempt, `$out.1` errors 21 → 0. Rollup 32 → 30/32, Normalizer 80 → 84/94, Reformat 75 → 81/96, all within their
  CIs. First-attempt compile errors 35 → 13. Results `results/agent_harness/valprec2_deploy_pool_tweak.jsonl`.
- **Residual gap tests T57/T63/T67/T73, execution-scored n30 each:** 64/120 no prompt, 88/120 rules only, 85/120
  deploy_v1 (+0.18 [+0.05, +0.29] over no prompt; −0.02 [−0.14, +0.09] vs rules only). T57 8/30 vs 14/30 rules only
  is inside the one-test band. `results/sysprompt/gaps_valprec2_deploy.json`.
- **Validate ground truth B1-tweak (format path):** thinking on recall 0.96 → 0.95, clean-code false alarm 0.02 → 0.00;
  thinking off recall 0.88 → 0.89, false alarm 0.15 → 0.17. All inside noise. The rules-only prompt's false-alarm rise
  (on 0.08, off 0.38) is gone: the DI paragraph neutralises the `ALL` priming. `results/sysprompt/gt_tweak_valprec2_deploy.md`.
- **Decision:** deploy_v1 is the deployment system prompt for valprec2 (thinking on, compile-and-retry loop). It costs
  nothing measured and fixes the DataIntersection port habit and the try/catch, reserved-name and null-accumulator
  errors at inference. The rebuild how-to serving section should carry it.
- **rb1013 rebuild (running):** rb1011 recipe (rb1009 SFT + DPO + `--sd=c13c_belief:1`, seed 42, rb1012 sets excluded)
  on corpus 3de7b55, i.e. the first base trained on DataIntersection rounds 3 and 4 and SCD2 rows that say the CTL sees
  one output record. SFT 13433 (12275 corpus + 694 traces), DPO 2083, same counts as rb1011. Trained 22:08–03:10 on
  GPU 1, export `/home/pavlisd/exports/qwen38_rb1013_sftdpo`; `scripts/base_eval.sh` gates started 03:17 on GPUs 0/1
  (the script now takes `OFF_GPU`/`ON_GPU`, defaults unchanged). Question for its gates: does the DI port belief go
  without the prompt (T53/T54 thinking on, DI harness subset, DI validate controls)? Config `configs/qwen38_rb1013.yaml`,
  script `scripts/rb1013_run.sh`.

## 2026-11-02 — Rebuild how-to

- **`spec/model_rebuild_howto.md`:** the step-by-step recipe from Qwen3.8-27B to valprec2, with Mermaid diagrams. It
  covers the data build, rb1009 SFT + DPO, OPCD c13 → c13b → c13c → valprec2, reference numbers and serving. It lists
  adopted stages only, so findings §5 (still written for rb1006 + c4) is no longer the place to look for the recipe.
- **Fallout from the cleanup, fixed:** `data/build_sft_rebuild.py` loaded its tokenizer from the deleted fix6 export.
  It now uses the rb1006 export, whose tokenizer is identical to rb1009's.
- **Fallout from the cleanup, not fixed:** `logs/evals/opcd_vllm_serve.sh` (the old rb1006 sampler, not in git) points
  at the deleted `vllm_check` adapter.
- `scripts/validate_precision/vllm_sampler_3011.sh` now takes `NAME` for the served-model name.
- **Inputs committed:** `data/self_distill/dpodef1/prompts.jsonl` and `dpodef3b_plain/prompts.jsonl`. Every OPCD
  config reads them; they were the last OPCD inputs missing from git.

## 2026-11-02 — Lifecycle disk cleanup

- **`scripts/cleanup_lifecycle.sh`** (supersedes `disk_cleanup.sh` and `cleanup_tier1.sh`) deleted 720 GB of weights,
  optimizer states and debris; `/home` used 1.6 TB → 890 GB. difr2 (training at the time) was excluded and kept running.
- **Models left:**
  - exports `qwen38_rb1009_sftdpo` and `qwen38_rb1006_sftdpo` (the path behind every `eval_rb1006_*` / rulev3
    config) plus `qwen38_base`;
  - OPCD adapters `valprec2/round_155`, `c13c/round_015`, `difr1/round_019`, and all of difr2;
  - LlamaFactory final adapters of rb1009 and rb1006.
- **Gone:** every OPCD `optimizer.pt`; all other round adapters (c4, c10, c13d, c14, s3b-rb1011, valprec1, retry1,
  exec_rft1, difr1's other rounds, smoke tests, `vllm_check`); all LlamaFactory checkpoints; the weights of every other
  rebuild and DPO / self-distill run (fix1–6, rb1003–1008, rb1009s2, rb1010–1012, dpoiso); the merged exports of fix6,
  rb1009s2, rb1010a, rb1011/s2, rb1012/s2 and their dead symlinks; the May Qwen3.5-9B copy in `~/LlamaFactory/~`; the
  `*.pre_rulings1004` backups and other debris.
- **Kept everywhere:** results, logs, specs, configs, training data, and the small files of every OPCD round
  (samples, metrics, probes) and LlamaFactory run (trainer logs, training configs, loss plots). A run listed as gone
  needs a retrain from its config to be served again.

## 2026-11-02 — DataIntersection round 4: the requests name three outputs, the answers now say the CTL sees one

- **Owner ruling:** `return ALL` is valid in a DataIntersection transform; the only defect is writing `$out.1`/`$out.2`.
- **Audit (where the "ALL broadcasts to three ports" belief is taught):** about a third of the corpus DI prompts say
  "All outputs are connected: 0=A-only, 1=both, 2=B-only" (DI SFT 12/35, DI DPO 11/37, SCD2 6–7) and no rb1009-era
  answer said the CTL has one output record; the compact reference had no DI section until 2026-11-01. Round 3 §3 had
  put the false-alarm sentence itself into five DPO rejected rationales. The SCD2 sets (18 SFT, 16 DPO chosen `return
  ALL` with port-number prose) were never revised. The eval prompts carry the same wording (pool_tweak_di 42/51,
  di_frame_prompts 72/100, validate controls) and keep it on purpose.
- **Brief** `spec/dataintersection_single_output_brief.md`, implemented in `ctl_lora_training` (uncommitted, checked by
  `scripts/corpus_checks/di_round4_check.py`, all checks pass): prompts unchanged; 53 DI SFT and 25 DI DPO chosen
  answers get a varied single-output sentence; 6 explanation-only rejected answers replaced by code defects (`$out.1`
  ×3, `$out.2`, inverted test, wrong side); SCD2 DI rows moved to `return OK` and the join framing (19 SFT, 11 DPO
  lines), downstream Reformat expanders untouched; 42 round-4 and 60 round-3 code blocks compile-checked (`$out.1`/
  `$out.2` rejected answers fail, everything else passes); both validation logs now record rounds 3 and 4. Goes into
  the next rebuild.

## 2026-11-02 — difr3: fixed DPO pairs (teacher's clean reviews vs the student's `return ALL` flags) — false alarm only partly down, DataIntersection generate gain lost

- **Change** (`configs/opcd_difr3.yaml`, `scripts/opcd_difr3_run.sh`, `scripts/difr3/build_pairs.py`, `opcd.py`
  `prompts.exec_fixed`): difr2 plus 60 fixed DPO pairs through the exec-set path (beta 0.1, weight 0.02, drawn with
  prompt weight 16 ≈ 4 pairs per round). Rejected = difr2_r39's thinking-on reviews with an [ERROR] on 22 training DI
  controls that return ALL (54 of 60 are the "ALL broadcasts to all three ports" claim); chosen = the review teacher's
  clean verdicts on the same prompts with the context removed and context quotes filtered (50 format, 10 plain). The
  student starts from valprec2 round_155 as before. 40 rounds, 16:06–20:18.
- **Training:** the pairs are learned at once — DPO margin 0.6 at round 0, 13–23 from round 3 on, accuracy 1.0. Yet the
  on-policy clean_guard dropped 79 false alarms over the run (difr2: 31) and formed 15 on-policy pairs. Belief probe
  0.00, quote rate 0.08–0.18, KL 0.007–0.010.
- **Round check, DI subsets, paired with valprec2** (`results/agent_harness/difr3_r{19,39}_pool_tweak_di.*`,
  `results/difr3/gt_tweak_di_*.md`):

  | | valprec2 | difr3 r19 | difr3 r39 | difr2 r19 |
  |---|---|---|---|---|
  | DI harness first attempt, on (n102) | 76 | 71 (−0.049 [−0.170, +0.074]) | 79 (+0.029 [−0.088, +0.145]) | 91 |
  | after 2 feedback rounds | 89 | 92 (+0.029 [−0.060, +0.119]) | 89 (0.00 [−0.094, +0.094]) | 96 |
  | `$out.1` compile errors, first attempt | 17 | 25 | 16 | 4 |
  | DI validate controls any [ERROR], off (n24) | 0.08 | 0.25 (+0.17 [−0.05, +0.37]) | 0.08 (0.00) | 0.00 |
  | DI validate controls any [ERROR], on (n24) | 0.08 | 0.29 (+0.21 [−0.02, +0.42]) | 0.17 (+0.08 [−0.12, +0.28]) | 0.29 |
  | DI defect recall on / off | 0.98 / 0.93 | 0.98 / 0.91 | 0.93 / 0.95 | 0.98 / 0.91 |

  Every flagged thinking-on control still says `return ALL` broadcasts to three ports; the thinking-off flags at r19 are
  the old `$out.1` port claim (gone again by r39). The fixed pairs reduce the ALL false alarm by half at best (0.17, not
  separable from valprec2's 0.08 at n24) and at the same time take back the DataIntersection generate gain of difr1/difr2:
  r39 first attempt 79 vs difr2 r19's 91 (−0.118 [−0.219, −0.015]), `$out.1` errors back at 16–25. Pushing the reviewer
  away from "ALL goes to all ports" pushes the generator back toward writing `$out.1`: the two tasks share the port
  belief, and the pairs move it in the wrong direction for generate.
- **Not adopted; full gates not run.** The three difr lanes together: the join-framing teacher gives +0.13–0.15 DI
  first-attempt pass thinking on but installs the ALL false alarm in the reviewer; dropping false alarms (difr2) and
  fixed DPO against them (difr3) cannot remove it without losing the generate gain. The system-prompt framing
  (`data/sysprompt/di_frame_v2.txt`, 76 → 98/102 with validate false alarms flat) does the same job at inference with
  no trade-off, and the corpus round 3 goes into the next rebuild. Recommended: stop the difr OPCD lanes, keep valprec2,
  take the DI framing from the deployment prompt and the rebuild.

## 2026-11-02 — difr2: difr1 + clean_guard (false alarms on clean reviews dropped, on-policy DPO pairs) — generate up, thinking-on ALL false alarm stays

- **Change** (`configs/opcd_difr2.yaml`, `opcd.py` train.clean_guard): a review sample on a clean record (tag review_clean*,
  server PASS) with any [ERROR] is not trained as an OPCD sample; when the sibling sample of the round is clean the two
  form an on-policy DPO pair (chosen = clean sibling, rejected = false alarm, reference = current policy, beta 0.1).
  40 rounds, 08:58–13:23. Over the run: 31 false alarms removed, **only 9 pairs** (k = 2, both siblings usually flag).
  Probes: belief 0.00 (one answer at round 36), unclosed thinking 0 after round 4, quote 0.05–0.15.
- **Round check, DI subsets, paired with valprec2** (`results/agent_harness/difr2_r{19,39}_pool_tweak_di.*`,
  `results/difr2/gt_tweak_di_*.md`):

  | | valprec2 | difr2 r19 | difr2 r39 | difr1 r19 |
  |---|---|---|---|---|
  | DI harness first attempt, on (n102) | 76 | 91 (+0.147 [+0.041, +0.251]) | 89 (+0.127 [+0.019, +0.233]) | 90 |
  | after 2 feedback rounds | 89 | 96 (+0.069 [−0.013, +0.153]) | 98 (+0.088 [+0.011, +0.170]) | 94 |
  | `$out.1` compile errors, first attempt | 17 | 4 | 8 | 6 |
  | DI validate controls any [ERROR], off (n24) | 0.08 | 0.00 (−0.08 [−0.25, 0]) | 0.00 | 0.17 |
  | DI validate controls any [ERROR], on (n24) | 0.08 | 0.29 (+0.21 [0.00, +0.46]) | 0.38 (+0.29 [+0.08, +0.54]) | 0.38 |
  | DI defect recall on / off | 0.98 / 0.93 | 0.98 / 0.91 | 0.96 / 0.93 | 1.00 / 0.93 |

  Best DataIntersection generate from training so far (r39 final pass significant), thinking-off reviews clean, but the
  thinking-on false alarm on `return ALL` controls (every flagged control says "ALL broadcasts to all three ports") is
  unchanged from difr1. Full gates not run.
- **The teacher is not the problem** (`scripts/difr2_teacher_all_probe.py`, `results/difr2/teacher_all_probe.json`): the
  review teacher (rb1009 base, rulev6 validate prompt + format + teacher_context, thinking on) on 22 training DI
  controls that return ALL: with its context 3/22 any [ERROR], **0 mention ALL**; without the context 15/22, all ALL
  (three-port routing, "needs transformOnlyA"). So the context works for the teacher; what fails is the transfer: the
  reverse-KL loss on a long review is dominated by shared tokens and the disagreement sits in a few decision tokens
  (KL mean ≈ 0 on the flagged samples, difr1), and the DPO pairs were 9 in 40 rounds.
- **Options for difr3:** (1) more samples per clean DI review (k 4–6 on review_clean DI rows, or an extra DI-control
  prompt file with weight) so pairs form; (2) `loss_by_teacher: topk` for the review teacher on clean rows, option B
  cross-entropy toward what the teacher would write at the decision token; (3) fixed DPO pairs from the teacher's clean
  reviews (context removed, context-guard filtered) as chosen against the student's ALL flags as rejected, via the exec
  set path. Owner's call.

## 2026-11-02 — difr1: OPCD with the join-framing §8.9 as teacher (not adopted as is)

- **Run:** valprec2 `round_155` continued 40 rounds (`configs/opcd_difr1.yaml`, 19:32–23:47 on GPUs 0/1): the join
  teacher (rulev6 + the rewritten §8.9) for the 100 revised corpus DI prompts (76 after holdout/duplicate exclusion, both
  modes, weight 4) and the c13b_keep DI anchors; reviews `review_prompts_v3` with the DI fact in the join framing.
  KL per token 0.010–0.015, probes belief 0.00 and unclosed thinking 0 throughout, quote rate 0.05 → 0.15 → 0.125.
- **Round pick on the DI subsets, rounds 19 and 39 hot-loaded on rb1009, paired with valprec2**
  (`scripts/difr1_di_check.sh`, `results/agent_harness/difr1_r{19,39}_pool_tweak_di.*`, `results/difr1/gt_tweak_di_*.md`):

  | | valprec2 | difr1 r19 | difr1 r39 | prompt only (di_frame_v2) |
  |---|---|---|---|---|
  | DI harness first attempt, on (n102) | 76 | 90 (+0.137 [+0.030, +0.242]) | 85 (+0.088 [−0.024, +0.198]) | 98 |
  | DI harness after 2 feedback rounds | 89 | 94 (+0.049 [−0.037, +0.136]) | 94 (+0.049) | 101 |
  | `$out.1` compile errors, first attempt | 17 | 6 | 10 | 2 |
  | DI validate controls, any [ERROR], on (n24) | 0.08 | 0.38 (+0.29 [+0.08, +0.50]) | 0.42 (+0.33 [+0.13, +0.54]) | 0.00 |
  | DI validate controls, any [ERROR], off | 0.08 | 0.17 (+0.08 [0, +0.21]) | 0.17 | — |
  | DI defect recall on / off | 0.98 / 0.93 | 1.00 / 0.93 | 0.98 / 0.93 | — |

- **Verdict: not adoptable as is.** Generate moves half-way to what the prompt alone gives, but the reviewer now flags
  `return ALL` on clean code: every one of the 9 (r19) / 10 (r39) thinking-on control false alarms says "`return ALL`
  broadcasts the record to all three ports". All 12 B1-tweak DI controls return `ALL` (pre-round-3 corpus idiom), which
  the ruling tolerates as OK. The student did this in 36 of 58 DI review samples with `return ALL` during training and the
  review teacher let it pass (KL median ≈ 0 on those samples) although its fact sheet says "ALL, 0 and 1 behave like OK
  and are not an error" — the server-verdict teacher does not push back on a wrong *reason* when the verdict line is
  what it scores. Same failure as di_frame_v1 (2026-11-01), now learned instead of prompted.
- **Full gates not run** (pool_tweak, B1-tweak, T40/T42, hard set 3): the validate precision gate is already failed on
  the DI subset; the eval server on :3012 was stopped, GPUs 0–3 free.
- **Options for difr2:** (a) drop or penalise review samples that put an [ERROR] on a return constant the server passed
  (an explicit filter like `context_guard`, since the teacher's KL does not carry the correction); (b) add the "ALL is
  accepted" sentence to the review teacher's *verdict* line, not only the fact sheet; (c) keep the generate half only:
  train the DI generate prompts without the DI reviews and check the review false alarm does not move. Owner's call.

## 2026-11-01 — DataIntersection framing: one paragraph fixes the port confusion

- **Owner idea:** stop teaching DataIntersection as three ports plus a `$out.0` rule; teach it as a join-like transform
  (two input records, one output record `$out.0`, OK/SKIP, one-sided records never reach the CTL, no port numbers).
- **Tested as a system-prompt paragraph on valprec2** (`data/sysprompt/di_frame_v2.txt`, `spec/sysprompt_rules_findings.md`):
  harness pool_tweak DI tasks first attempt 76/102 → 98/102 (+0.216 [+0.137, +0.304], paired n102), after feedback
  89 → 101/102; `$out.1` misses 21 → 2; T54 26/30 → 29/30. Validate DI controls false alarm thinking on 0.08 → 0.00,
  recall flat. v1 of the text omitted that `ALL` is accepted and the reviewer flagged every `return ALL` control; v2
  fixed that. Largest single-component move so far, on prompts that still describe three outputs.
- **Next (owner):** rewrite §8.9 of `ctl2-basics.md` in this framing and propagate it (snapshots, rule teacher, corpus
  reference), corpus brief for the DI sets, then OPCD with the rewritten §8.9 as teacher. Open: whether the corpus
  idiom moves from `return ALL` to `return OK`.
- **Owner rulings and reference change (same day):** DataIntersection is taught as a join-like transform, the idiom is
  `return OK`. §8.9 of `resources/ctl2-basics.md` rewritten in that framing (no port numbers in the CTL explanation,
  `$out.1`/`$out.2` fail at init, older `ALL`/`0`/`1` tolerated as OK), §13 line and a §8.1 note changed; applied to
  the suite v5 snapshot and both corpus references (`spec/di_section_8_9_rewrite.md`). Suite v4 snapshot has no DI
  section, rule teachers never mention DI. Both repos pushed.
- **Re-judge check passed:** valprec2's stored T53/T54 answers (n30 per mode) judged against the rewritten reference:
  T53 identical on all 60 answers, T54 mean 0.971 → 0.974 off and 0.962 → 0.946 on (4 of 60 answers moved, judge
  nondeterminism, CIs include 0). The reference change moves nothing on its own.
- **`spec/validate_falsealarm_brief.md` closed, not run (owner ruling):** a thinking-off review call will not ship; the
  deployment validate call is thinking on (false alarm 0.02–0.03). The rules_v1 result (fact list raises false alarms) and
  the DI port-number phrasing of its R3 line argued against arm R anyway; E/V stay unrun.
- **Corpus brief written:** `spec/dataintersection_join_framing_brief.md` (DI set round 3: `return OK` everywhere,
  explanations in the join framing with no port numbers, 6 DPO pairs re-targeted at the "ALL sends to all ports / $out.1
  is the both port" explanation, prompt mix with port talk kept at about half, acceptance greps). Next: hand the brief
  to the corpus authors; OPCD with §8.9 as teacher on valprec2.

## 2026-10-31 — deployment rules prompt tested on valprec2's weaknesses

- **Seven compiler-verified rule lines in the system prompt** (`data/sysprompt/rules_v1.txt`: reserved names, no `!~`,
  no constant ternary, escapes, `catch (CTLException ex)` / `raiseError(ex.message)` / no throw, accumulator is its own
  record with every non-nullable field assigned) tested on valprec2 without training (`spec/sysprompt_rules_findings.md`).
- **Thinking on (the deployment mode):** gap tests T57/T63/T67/T73 execution pass 64/120 (0.53) → 88/120 (0.73),
  +0.20 [+0.08, +0.31]; T73 0.60 → 0.97, T63 0.57 → 0.80, T57 0.27 → 0.47, T67 flat. The try/catch, reserved-name and
  null-into-non-nullable compile errors disappear completely. Harness syntax-pitfall pool first attempt 0.44 → 0.85,
  Rollup-accumulator pool unchanged (0.91 → 0.88, in band).
- **Recipe check on the broad pool and on validate (11-01) says not as written.** pool_tweak thinking on, paired n330:
  first attempt 0.815 → 0.785 (−0.030 [−0.079, +0.018]), after feedback 0.882 → 0.842 (−0.039 [−0.076, +0.000]); the
  whole loss is DataIntersection (76 → 68/102, `$out.1` misses 21 → 32), the other components are flat. B1-tweak
  validate: thinking-on false alarm 0.02 → 0.08 (+0.060 [+0.020, +0.110]), all six new alarms the same DataIntersection
  "return ALL sends to all three ports" claim; thinking-off false alarm 0.15 → 0.38; recall on −0.05. The ternary line
  names `ALL` and primes the DataIntersection port confusion; a prohibition list makes the thinking-off reviewer hunt.
  **rules_v1 not adopted.** Next: rules_v2 without the `ALL` mention (or with the DataIntersection port fact stated),
  in the generate/fix prompts only, measured the same way (`scripts/sysprompt/recipe_check.sh`).
- **Thinking off:** syntax pool 0.31 → 0.67, but T73 regresses 0.70 → 0.20 (n10): the `!(x ~= re)` example fuses with
  the conditional-fail idiom into `!(str2date(…) : null)`. Not the deployment mode; noted.
- **Left after the rules:** T57 still assigns input field names to the accumulator record in 12/30 thinking-on
  answers (was 22/30); T67 port routing is untouched. Both are task-reading errors for the retry loop, not language
  facts. No training lane follows.
- Tooling: `agent_harness.py --system-extra <file>`, `scripts/sysprompt/run.sh`,
  `configs/eval_sp_v5gaps_valprec2_rules_{on,off}.yaml`, `data/agent_harness/pool1_weak.jsonl` (52 tasks).

## 2026-10-30 — retry1 gates, disk and server cleanup

- **retry1 (retry-loop distillation) not adopted** (`spec/retry_distill_findings.md`, findings §3.39).
  - **Data:** 453 triples (281 off / 172 on) from two new pools sampled by c13c in the harness, feedback references
    stripped; 906 exec rows, 67 rounds from c13c (`data/opcd/retry1/round_066`).
  - **Gain:** pool_tweak thinking off first attempt 0.72 → 0.82 (+0.10 [+0.04, +0.17]), compile errors 0.13 → 0.05;
    DataIntersection `$out.1` thinking on 20 → 6 of 102.
  - **Loss:** gap-test execution pass off 0.40 → 0.34, on 0.76 → 0.62 (CI excludes 0); 12/330 thinking-on answers with
    no code; hard set 2 belief claims 1 → 10 of 60; B1-tweak thinking-off false alarm 0.24 → 0.33. Pool 1, T40/T42,
    T54, validate judge suite flat.
  - **Hand check:** gains are corrected logic slips; losses are new habits not in the targets (createDate without time
    zone, accumulator reset to 0, reserved-token globals).
  - **Lesson:** exec SFT/DPO rows from Rollup fix tasks carry the accumulator belief in code, invisible to the OPCD
    probes (same as exec-RFT and rb1012). Any retry: thinking-off compile-error triples only, accumulator rows out.
- **Disk:** `/home` free 304 GB → 3.5 TB. Pruned retry1 / exec_rft1 per-round weights (`scripts/disk_cleanup.sh`,
  KEEP_ROUND extended to retry1 r066, valprec1 r122, valprec2 r155) and deleted one 3.2 TB CloverDX output CSV from a
  runaway Rollup in my pool_retry sampling on 10-28.
- **Harness and exec_score now cap and clean up:** every candidate graph's writer gets `recordsCount` = max(1000,
  10 × expected rows) and the graph plus its outputs are deleted from the sandbox after scoring (`agent_harness.py`,
  `data/suite_v5/exec_score.py`; a capped output is noted in the wrong-rows detail). Verified on the server.
- **Uncommitted:** `scripts/retry_distill/*`, `configs/opcd_retry1.yaml`, `configs/eval_rd_*.yaml`,
  `data/retry_distill/*`, `data/agent_harness/pool_retry_on.jsonl`, the harness and exec_score edits.

## 2026-10-30 — valprec2 adopted

- **Fresh-domain harness on valprec2** (`scripts/validate_precision/harness_tweak.sh`, pool_tweak, 2 runs, both modes,
  paired with c13c's §3.36 run):
  - first attempt 0.730 / 0.815 vs 0.721 / 0.812 (+0.009 [−0.024, +0.042] / +0.003 [−0.036, +0.045]);
  - after feedback 0.818 / 0.882 vs 0.803 / 0.858.
  - Generate holds, so the adoption criterion from the 10-29 entry is met.
- **valprec2 (`data/opcd/valprec2/round_155` on rb1009) replaces c13c as the ship candidate** (§3.38,
  `spec/validate_precision2_findings.md`).
- **Weakness inventory for valprec2, both modes** (`spec/valprec2_weaknesses.md`): what neither thinking mode nor the
  feedback loop fixes: reserved time-unit names / `!~` / constant ternaries even after the compiler error, try/catch
  misuse: raiseError(ex), throw/raise, catch (Exception) (T67/T73), Rollup accumulator metadata and null-into-non-nullable (T57/T63/T22), Denormalizer
  contract and invented sequences (T61), ERROR-vs-WARNING severity in validate. Thinking-off-only collapses listed apart.
- **Disk cleanup:** I removed the valprec1 / valprec2 leftover weights and optimizer states, about 6.6 GB. The adapters
  of valprec1 round 122 and valprec2 round 155 are kept.

## 2026-10-29 — valprec2 gates

- **valprec2 gates** (`spec/validate_precision2_findings.md`, findings §3.38). **Successor candidate, not yet adopted.**
  - **Run:** c13c + OPCD, 156 rounds, with clean reviews at 68% of the review weight (round 1: 22%), claim controls ×2,
    compile-type mutants down-sampled, the CLEAN2 severity / "it compiled" line, and FACTS2.
    - FACTS2's server probes: getDayOfWeek 1 = Monday … 7 = Sunday; date parts take a time zone; else-if (true) compiles.
    - The clean / plain / off KL converged (0.168 → 0.005).
  - **Interruption:** the trainer died in round 10 when `/home` hit 100%.
    - I pruned valprec1's per-round weights for rounds 000–121 (about 290 GB) and resumed after round 9.
    - `scripts/validate_precision/prune_rounds.sh` now keeps only the newest 2 rounds' weights while a run trains.
  - **Thinking-off false alarm:**
    - B1 with the format: 0.41 → 0.25 (−0.16 [−0.27, −0.06]; vs valprec1 −0.10);
    - B1-tweak with the format: 0.24 → 0.15 (−0.09 [−0.19, +0.01]);
    - B1 plain: 0.31, at c13c (valprec1 0.61).
    - The fall is mostly requirement misreadings.
    - These stay: null "throws" as ERROR (no move to WARNING), Rollup group state, the DataIntersection `$out.0` port
      claim, and Sunday = 1 in 1 of 2 runs.
  - **Thinking on:** false alarm 0.03 / 0.02, recall 0.96, lifecycle 0.83. Plain thinking on: false alarm 0.00, recall
    0.87 (c13c 0.29).
  - **Plain answers drift from the layout:** without a format instruction, 26% of thinking-off answers lose
    `ISSUES:` / `VERDICT:`.
    - The parser then under-reads recall (plain thinking on reads as 0.02).
    - The findings use a format-independent re-score.
  - **Generate, belief and judge:**
    - gap tests 0.382 / 0.736 (c13c 0.403 / 0.761);
    - harness first attempt 0.617 / 0.785 (0.650 / 0.825);
    - all inside the bands but all below c13c;
    - T40/T42, hard sets, T54 as c13c;
    - judge WRONG share 2.6% (gate 2.5%, c13c 2.2%; inside noise);
    - fix n5 0.826 → 0.922.
  - **Next:** a fresh-domain harness on pool_tweak (`--runs 2`, both modes) against §3.36. Adopt if generate is within
    ±0.03 of c13c.
- **`gates_table.py`** takes an optional LAST argument for the round label.

## 2026-10-28

- **valprec1 gates** (`spec/validate_precision_findings.md`, findings §3.37). **Not adopted; a second round with a
  rebalanced review set is next.**
  - **Thinking on:** better than c13c on both ground-truth sets.
    - B1: false alarm 0.14 → 0.01 (−0.13 [−0.23, −0.05]), recall 0.86 → 0.96, lifecycle 0.35 → 0.83.
    - B1-tweak: false alarm 0.08 → 0.04, recall 0.89 → 0.97.
  - **Thinking off, with the format:** lifecycle recall 0.18 → 0.67 (B1) and 0.31 → 0.75 (B1-tweak), and recall
    +0.10. The false alarm did not move: B1 0.41 → 0.35, B1-tweak 0.24 → 0.23, both within noise. The gate needed −0.08.
  - **Thinking off, plain (the test.py path):** false alarm 0.30 → **0.61** (+0.31 [+0.20, +0.42]); judge WRONG 2.2% →
    3.8%.
    - New false claims: DataIntersection `$out.0` "wrong port", getDayOfWeek / getMinute signatures, "unreachable
      return", more requirement misreadings.
    - Kept: initGroup ordinal, UTC-millisecond DST, null-compare as ERROR.
    - The clean / plain / off review slot is the only one whose KL did not converge (0.19 → 0.095). It had 160 samples
      against about 550 per planted slot (78% of reviews were planted).
  - **Fact sheet:** it removed the claims it refutes (decimal / integer "truncates" / "does not compile", null to a
    local). The §7 severity sentence moved nothing: null-compare findings are still ERROR.
  - **Generate and belief hold:**
    - gap tests off 0.406 vs 0.403; on 0.715 vs 0.761 (−0.045, inside ±0.06 but at its edge);
    - harness first attempt 0.65 / 0.79 vs 0.65 / 0.82;
    - T40/T42, hard sets, T54 0/20: as c13c or better;
    - context guard never fired.
  - **valprec2 proposal:**
    - clean reviews ≥ 50% of review weight, clean / plain / off over-sampled;
    - compile-type mutants down-sampled;
    - controls for the surviving claims;
    - a teacher line that names [WARNING] for data-dependent nulls;
    - add B1 plain thinking on to the gates.

## 2026-10-27 (night)

- **valprec1 started** (`spec/validate_precision_brief.md`, `spec/validate_precision_findings.md`, findings §3.37): OPCD on
  c13c with validate reviews whose teacher sees the CloverDX server's verdict on the code under review.
  - **Fact probes first** (29 runs, `results/validate_precision/fact_probes.json`): an unguarded `>`/`<`, arithmetic, `!`
    or `if` on a null **does throw** (NullPointerException); `==`/`!=` with null and assigning null to a local do not;
    decimal / integer is a decimal (7.50 / 2 = 3.75) and a decimal compared with an integer literal compiles; UTC
    millisecond arithmetic has no DST shift. So B1-tweak's "nullable compared without a guard can throw" is true, but
    data-dependent: the teacher's fact sheet calls it a WARNING (§7), never an ERROR. The decimal claims are false.
  - **Data:** 160 exec-RFT references (pool minus the 97 B1 references; holdout unread) → 160 clean + 553 server-confirmed
    planted reviews (seed 13, every confirmed mutant), each in both modes with the output format in one of them: 1426
    rows. Exclusions checked against pool 1, pool_tweak, B1, B1-tweak and the holdout (3 `c13b_keep` DI prompts were
    holdout prompts and were dropped from the anchor).
  - **Run:** c13c's anchors at ×2 weight so reviews are 61% of the non-replay weight; 123 rounds (each review row once),
    ~7 min per round; `opcd.py` gained a per-prompt system addition, a context-quote guard and per-tag stats. Smoke: KL
    falls; review samples start at KL 0.09–0.15 per token against ≤ 0.03 for the anchors. Gates run automatically after
    training (`scripts/validate_precision/run.sh` → `gates.sh`).

## 2026-10-28 (early) — retry-distill data step 1 done

- Sampling run for `spec/retry_distill_brief.md` finished (c13c, GPU 2, 23:02–04:29): training pool
  `data/agent_harness/pool_retry.jsonl` (160 exec-RFT prompts not in pool 1, holdout excluded) × 4 runs × 2 modes, 2
  feedback rounds with `--rows-feedback` → `results/agent_harness/c13c_pool_retry_rows.jsonl` (1,280 records, 0 model
  errors; summary `.summary.md`; script `scripts/retry_distill_sample.sh`).
- First attempt 0.51 off / 0.65 on, final 0.75 / 0.89 (this pool is harder than pool 1: 0.65 / 0.82 first there).
- **Triples (attempt 0 failed, later attempt passed): 150 off (66 distinct prompts) + 149 on (80 prompts) = 299.**
  By attempt-0 cause: wrong_rows 56/62 (off/on), undeclared_variable 28/9, wrong_arguments 18/23, out_port 1/14,
  regex_negation 4/10, other 31/13, runtime 7/8. By set: syntax_pitfalls 54/59, scd2 23/26, rollup_accumulator 19/19,
  normalizer_multirow 19/20, dataintersection 18/11, rollup_lifecycle 12/5, zerodate 5/9.
- Note: thinking on is *worse* than off on DataIntersection here (first 0.53 vs 0.59, final 0.72 vs 0.90; 23 compile
  errors, mostly `$out.1`), consistent with §3.36.
- **Step 1b, the second `--tweak` batch (same day, 10:00–17:28):** seeds 201–202 on the six sets + 203–205 Rollup-only
  (`scripts/retry_distill_tweak.sh`; `merge_pools.py --dir/--exclude`) → `data/agent_harness/pool_retry_tweak.jsonl`,
  190 tasks (acceptance 0.66; DI 49, Reformat 47, Normalizer 49, Rollup 42; zerodate kept none, 22 prose-origin
  dropped), no overlap with pool_tweak by id. c13c sampled the same way → `results/agent_harness/c13c_pool_retry_tweak_rows.jsonl`
  (1,520 records, 0 model errors). First 0.64 off / 0.70 on, final 0.81 / 0.85. **Triples 131 off (57 prompts) + 120 on
  (63 prompts) = 251.** Causes: wrong_rows 45/64, other compile 22/4, out_port 4/22, undeclared_variable 21/3,
  wrong_arguments 18/8, reserved_time_unit 6/13. Thinking on again loses most on DataIntersection (`$out.1`).
- **Training pool total: 550 triples** (281 off / 269 on) over 350 prompts; the §3.29 habits (`$out.1`, time-unit names,
  argument order, undeclared variables) are all present. Training waits for the validate-precision run (valprec1) and
  starts from the winning adapter.

## 2026-10-27 (evening)

- **Validate gate adopted: the planted-defect ground truth, not the judge** (`CLAUDE.md` measurement rules, findings §4.8).
  Both modes, format prompt, 2 runs; report defect recall and the clean-code false-alarm rate; bands recall ±0.05, false
  alarm ±0.08, one kind ±0.15. Judge validate differences below 0.04 are seed noise. The judge suite stays for what the
  parser cannot see.
- **B1-tweak built and c13c measured** (`data/agent_harness/validate_mutants_tweak.jsonl`, 146 server-confirmed defects +
  50 controls from the pool_tweak references, which no model was trained on). Reason: B1's references are pool-1 corpus
  code; 27 of its 30 lifecycle mutants come from the Rollup-accumulator set that rb1011/rb1012 saw in SFT and c13c did
  not, so cross-model claims on B1 are confounded.
  - c13c thinking off: recall 0.80, false alarm 0.24 (B1: 0.75 / 0.41); thinking on 0.89 / 0.08 (B1: 0.86 / 0.14).
  - **The lifecycle gap is real** (0.31 / 0.28 recall on code it never saw).
  - **The false-alarm rate depends on the reference style:** B1's corpus Rollup controls are flagged 0.80 of the time
    thinking off, B1-tweak's LLM-written Rollups 0.09; on B1-tweak the false alarms are null-guard "can throw" claims,
    decimal/integer arithmetic claims and rule misreadings instead (not probed).
- **Checked the two harness-measurement findings** (§3.35, §3.36): the headline numbers reproduce from the raw files
  (pool_tweak pass rates; c13c control false alarms 41/100 off, 14/100 on; lifecycle recall 11/60). The lifecycle misses
  are "ISSUES: none, VERDICT: PASS" on Rollups the server rejects at init. One caveat added (the B1 familiarity confound
  above).
- **Next experiment: `spec/validate_precision_brief.md`** — OPCD on validate-shaped prompts where the teacher has the
  server's verdict on the code under review in context (clean references and planted mutants from the exec-RFT pool
  minus pool 1 and the holdout), gated on B1 / B1-tweak and the generate gates. Motivation: c13c's T40/T42 belief fix
  did not transfer to reviews (it still writes "never initialized" on clean Rollup code), and the recurring false claims
  are a short, refuted list. `spec/retry_distill_brief.md` stays queued behind it; its sampling phase can run on the
  other free GPU meanwhile.

## 2026-10-27

- **Fresh-domain pool (Part A of the harness-measurement brief): c13c holds.** (§3.36,
  `spec/harness_measurement_findings.md`)
  - **Pool:** gpt-6.1-sol rewrote the generate prompts of the runtime-harness corpus sets into new domains and wrote
    fixtures. Tasks were kept only if their reference reproduced the expected rows on the server: 190 of 322 (59%).
    - One fixture-prompt fix, for Rollup: 0 of 20 accepted before it.
    - Hand check: 12 of 15 passed; the 3 failures were prose questions. The pool-wide drop of prose questions removed 25.
    - Final pool 165 tasks (`data/agent_harness/pool_tweak.jsonl`, evaluation only).
  - **Run:** c13c as pool 1 was run, both modes, 2 runs per task.
  - **Result, against pool 1's 107 corpus tasks (95% CI):**
    - thinking on: 0.81 / 0.86 / 0.91 (first / error feedback / rows feedback), differences −0.02 / −0.01 / −0.01
      (±0.07–0.09);
    - thinking off: 0.72 / 0.80 / 0.89, differences −0.01 / +0.06 / +0.07 (±0.09–0.11).
  - **Weak spots:** DataIntersection 0.83 / 0.85; thinking on writes `$out.1`/`$out.2` in 13 of 51 DataIntersection
    tasks; SCD-2 rewrites 0.68 / 0.76; thinking off `isDate`/`str2date` argument order.
  - **Caveats:**
    - 19 prompts carry a contradictory component header; the result is the same without them.
    - The acceptance filter under-samples pitfall-inviting tasks.
  - **Incident:** the first run was killed at 23:24 by Part B's `run_models.sh` cleanup, which kills any server named
    rb1009. The failed records were rerun; `run_c13c.sh` now serves the base as `rb1009_hm`.

- **Validate ground truth (Part B of the harness-measurement brief).** (§3.35, `spec/harness_measurement_findings.md`)
  - **Setup:**
    - 169 single defects planted in pool-1 references, each confirmed failing on the CloverDX server, plus 50 clean
      controls;
    - answers scored by a parser, no judge;
    - c13c, rb1011, rb1011s2 and rb1012, both modes, with the suite's output-format system prompt.
  - **Recall:** rb1011 0.82 / 0.88 (off / on), rb1011s2 0.81 / 0.86, rb1012 0.81 / 0.91, c13c 0.75 / 0.86.
    - c13c's gap is missing Rollup lifecycle functions (0.18 off).
    - rb1012, trained on that set, is best there (0.73).
  - **Seed spread:** recall ±0.02, false alarm ±0.04; the judge put the same pair 0.04 apart. The judge's rb1011s2
    deficit is not reproduced.
  - **Largest finding:** thinking off puts an [ERROR] on 28–41% of clean, server-passing code (thinking on 7–14%). All
    19 flagged controls are false claims: 11 by §7 facts, 8 by server probe (32 probes, all as required).
  - **Format:** test.py's validate path sends no output format; then 44–71% of thinking-on answers have no VERDICT line,
    so parser scores need the format prompt.
  - **Proposal:** gate validate on planted-defect recall and clean-code false alarm (format prompt, both modes, about
    25 min per model), and stop reading 0.04-level judge validate differences.

## 2026-10-26

- **Exec-RFT pilot on c13c: no gain, not adopted.** (§3.33, `spec/exec_rft_pilot_findings.md`)
  - **Setup:** 297 corpus generate/fix prompts with server-verified fixtures (40 held out). c13c sampled 8 answers per
    prompt in both modes, each run on the server. Its passing answers (375, by NLL) and passer-vs-failure pairs (331, light
    DPO) were trained for one round, with c13c's belief and replay anchors in the mix.
  - **Result:** execution pass rate on the gap tests −0.03 off, +0.04 on; on the held-out pool +0.02 / +0.01. All inside
    the 95% CIs and inside c13c's own ±0.03 run-to-run spread. The compile habits did not move (`month` as a variable name
    not at all).
  - **Side effects:** belief gates unchanged; thinking-off validate WRONG 2.2% → 0.9%; T54 thinking off regressed
    (`$out.1` 8/40 against 0/50), which fails its gate.
  - **Why little could move:** 57–68% of prompts were all-pass or all-fail for c13c, so only 200 prompt-modes gave
    signal; the habits occur in ~12% of samples.
  - **Decision:** no second round. A full run would need harder prompts (c13c at 1–4 of 8, gap-test-like), prompts that
    invite each habit, and a token-level signal.
  - **Tooling kept:** `scripts/exec_rft/` (pool builder, k-sample execution scorer, cause tally, gates), `opcd.py`
    `prompts.exec` (fixed NLL/DPO samples next to OPCD anchors).

- **rb1012 DPO isolation:** the accumulator regression is not caused by DPO. (§3.32, `spec/rb1012_dpo_isolation_findings.md`)
  - **Setup:** the DPO phase alone, rerun on rb1011's SFT adapter.
  - **Results:** rb1011's pairs (A) reproduce rb1011: T22 "starts at zero" 19 against 20/45, T41 0.83 against 0.82.
    Adding the 25 lifecycle pairs (B: 15/45, 0.79), or all of rb1012's DPO pairs (C: 18/45, 0.85), does not bring back
    rb1012's 36/45.
  - **Conclusions:**
    - the DPO phase adds little noise;
    - the regression comes from rb1012's SFT phase, either the 130 new SFT records or SFT-seed luck.
  - **Check 1 done: rb1012's SFT adapter plus rb1011's DPO pairs** reproduces most of rb1012's profile:
    - T22 B1 WRONG 28/45;
    - B4 caught 33 against 45/45 (CI excludes zero);
    - T41 0.77;
    - the same T40/T42 pattern.

    The regression comes with rb1012's SFT adapter.
  - **Still open:** the SFT records or the seed. It needs the rb1011 seed-7 rebuild (about 5.5 h; config and run script
    ready, not started). That decides whether an SFT ablation (about 24 GPU-h) is needed.
- **The shared run-history log `logs/Qwen3.8-27B.yaml` was torn** by concurrent `train.py`/`test.py` writes on 10-25
  around 21:16. From then on, every run's final log append failed; results were not affected. The log was repaired, and
  a backup kept. Parallel runs will tear it again until the writers take a lock.

## 2026-10-26 (evening)

- **rb1011 seed 7 (rb1011s2):** T22.B1 13/45 — the rb1012 accumulator regression is in its 130 new SFT records, not seed
  luck (§3.34). Neither set goes into the recipe; the SFT ablation is not run (no gain to recover).
- **Second variance pair.** Between seeds of one recipe: generate/fix/gap judge ±0.01–0.05, thinking-off validate 0.04–0.13,
  execution pass rate up to 0.14, single tests up to 1.0 (T22.B4 2 → 45). §4.7 now carries per-gate noise bands; a
  single-test result of one rebuild is never a property of the corpus.
- CloverDX server hung (listening, not answering) and was restarted by hand.

## 2026-10-25

- **Agentic harness built** (`agent_harness.py`, from `mut_validate.py` + `exec_retry.py`): prompt → model → compile →
  run → error fed back → retry, verdict by output rows. Pool 1: 137 execution-scored tasks (30 suite v5 + 107 corpus
  prompts c13c never trained on).
- **c13c in the loop:** 0.65 → 0.69 thinking off, 0.82 → 0.88 on, after two feedback rounds. Real-world suite tests:
  13/30 off, 25/30 on. The residue is wrong rows; the compile habit that survives is `month`/`year` as a variable name,
  because the server's message does not name it. DataIntersection: 23/24 first try. With the failing test rows fed back
  as well: 0.80 off / 0.92 on; real-world suite 22/30 off, 28/30 on. (§3.31)
- Briefs written for two experiments to hand to another agent: `spec/exec_rft_pilot_brief.md` (execution-verified
  on-policy training) and `spec/rb1012_dpo_isolation_brief.md` (is the rb1012 regression the DPO pairs?).

## 2026-10-23

- **rb1012** (rb1011 + the lifecycle and syntax sets), two seeds: **not adopted**. (§3.30)
  - **Syntax set:** no measurable effect. Compile failures from the targeted rules were 28–40 against 36, inside seed
    noise; the total swings 71–122 between seeds alone.
  - **Lifecycle set:** no gain. Its premise was wrong: the plain rebuilds already catch T22's missing functions thinking
    off (rb1011 43/40 of 45). The miss is specific to rb1009 and its OPCD line.
  - **Regression in both seeds:** T22 "count starts at zero" 20 → 36/45; T41 0.82 → 0.72–0.76. No cause found in the
    lifecycle set; only an ablation would tell.
  - **Decision:** c13c stays the candidate. Syntax habits are handled by thinking on plus compile-and-retry.
- **zeroDate records added to the corpus** (10 SFT, 6 DPO), written and server-verified here.
  - rb1012s2 wrote the bare `zeroDate` 48 times. The corpus code always uses `zeroDate()`, but never explained it.
  - The reference now says it is a function. (§3.30, §7)

## 2026-10-22

- **Syntax pitfalls set** (80 SFT, 40 DPO) delivered and **accepted** after an independent check:
  - all 185 compiler requests replayed with 0 differences;
  - all 216 runtime graphs re-run with 0 differences.

  Two small fixes were made directly: the PASS format, and a duplicated month computation.
- **Rebuild rb1012 started** with both new sets, in two seeds because single-seed differences below ±0.06 are not
  evidence. The corpus differs from rb1011 only by the two sets (+130 SFT, +65 DPO).
  - **Success:** fewer compile failures by cause in the execution scoring, and T22's missing lifecycle functions found
    thinking off.
  - **Must not regress:** belief gates and thinking-off validate WRONG.
- **New measure: run the generated code.** `data/suite_v5/exec_score.py` runs each answer in its test graph and checks
  every output row.
  - Pass rates are far below judge scores: c13c 0.44 off / 0.78 on, against judge 0.77 / 0.92.
  - 151 answers the judge scored 0.9 or higher do not work.
  - **Decision:** rank generate on this pass rate from now on. (§3.28)
- **OPCD c14** (Rollup accumulator set) fixed some wrong explanations but not the T41/T22 scores. **Decision:** keep
  c13c; stop distilling toward the accumulator rule. (§3.28)
- **Compile-and-retry:** feeding the server error back to c13c gives 0.78 → 0.93 thinking on, 0.44 → 0.51 off. (§3.29)
- **Why code does not compile:** 89% of failures come from 11 causes, each confirmed with the compiler. Examples: `$out.1`
  in DataIntersection, invented fields and functions, `!~`, `month` as a variable name, `str2date` argument order.
  - The rules are now in `ctl2-basics.md` and the corpus reference.
  - Corpus brief written: `spec/ctl2_syntax_pitfalls_brief.md`. (§3.29)
- **Facts corrected** (server-verified):
  - a Rollup accumulator's metadata default applies only to non-nullable fields; a nullable field starts null even with
    a default;
  - a missing Rollup lifecycle function fails the component at startup; it does not silently emit nothing.

  The reference, the teachers, and the T41, T6 and T22 rubrics were updated. (§7)
- **Rollup lifecycle validate set** (for T22): requested, delivered, and fixed over 3 rounds. **Accepted** for the next
  rebuild.

## 2026-10-21

- **An independent review withdrew s3b-rb1011 as candidate.** It breaks T54 without thinking (`$out.1` in 20/20) and
  makes compile errors on T40. Most of its "wins" were noise. **Decision: c13c stays.** (§3.27)
- **Found:** the declaration-belief fix overgeneralizes. Models learn "nothing is null" and then misexplain nullable Rollup
  accumulator fields (T41, T22). (§3.27)
- **Your ruling on T18:** any explicit lookup-miss handling counts (SKIP, null, defaults, reject port). All stored answers
  were re-judged. (§7)

## 2026-10-19 / 20

- **Rebuild variance is large.** Retraining rb1009 with another seed moved validate by 0.07 and lost DataIntersection.
  rb1009's DataIntersection result was a lucky seed. Single-seed rebuild comparisons below about ±0.06 are not evidence.
  (§3.27)
- **rb1011** (rb1010a plus the revised Rollup/Normalizer sets): no measurable effect from the new sets.
- **Stage 3 OPCD on rb1011 (s3b-rb1011)** was first called the new candidate, then withdrawn on 10-21.

## 2026-10-18

- **Part B:** putting c13c's own belief-free answers into the SFT corpus (rb1010a) removes most of the declaration belief
  from the base model, without hurting validate. (§3.26)
- **c13d:** OPCD does not fix T41. T41 and T60 went to a corpus brief (Rollup/Normalizer sets). (§3.25)

## 2026-10-16 / 17

- **rb1009 rebuild** with the DataIntersection and SCD-2 sets: T53 without thinking 0.38 → 1.00. (§3.24)
- **OPCD c13 → c13c on rb1009:** a rulev6 teacher fixes T42. **c13c becomes the ship candidate.** (§3.25)

## 2026-10-14 / 15

- **c9/c10:** a component-guide teacher closes most thinking-off generate gaps; c10 (skip truncated samples) is the best of
  that line. (§3.21, §3.22)
- **c11/c12:** the DataIntersection rule does not transfer through OPCD → **decision: fix it in the corpus** (rebuild).
  (§3.22, §3.23)

## 2026-10-13

- **Owner decision:** the recipe is rb1006 plus OPCD c4. The older three-phase recipe is retired. (§5)
- **Suite v5:** 30 real-world generate tests added. The models tie there and share the same gaps. (§3.20)

## 2026-10-06 – 10-09

- **rb1006** (fix-to-spec explained set): fix with thinking 0.70 → 0.86. It becomes the base. (§3.16)
- **The declaration belief** ("uninitialized variables are null") survived SFT, thinking traces and DPO (rb1007, rb1008,
  dpodef1).
- **Putting the rule in the system prompt fixes it,** so we distill that prompt into the model: on-policy context
  distillation (dpodef2, then the OPCD runs c1–c8). (§3.19)
- **Judge switched** to the local gpt-6.1-sol (10-09). Compare only within one judge. (§4.6)

## Before 2026-10-01

- Self-distillation, DPO rounds and targeted repairs gave no measurable gain. The three-phase recipe of that period is
  documented in §1–§3.15 and retired.
