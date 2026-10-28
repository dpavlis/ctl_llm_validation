# Validate-precision OPCD (valprec1): findings

Brief: `spec/validate_precision_brief.md`. Run: `valprec1` (`configs/opcd_valprec1.yaml`), c13c continued on validate
reviews whose teacher has the CloverDX server's verdict on the very code under review in context.
Status: **done** (trained 2026-10-27 23:04 – 10-28 12:50, gates 12:54 – 16:21). **Verdict: not adopted; one more round
with a rebalanced review set** (Indication 5). Thinking on it is clearly better than c13c (B1 false alarm 0.14 → 0.01,
recall 0.86 → 0.96, lifecycle 0.35 → 0.83); thinking off lifecycle recall rose (0.18 → 0.67) but the false-alarm rate
did not fall with the format and doubled without it (0.30 → 0.61), with new false claims.

## Setup

### Fact probes (Data 3)

Before the fact sheet was written, 29 one-expression probes were run on the server (`scripts/validate_precision/probe_facts.py`,
`results/validate_precision/fact_probes.json`; REFORMAT, one input row, nulls from the reader's `__NULL__`).

| claim (B1-tweak thinking-off false alarms, §4.8) | server |
|---|---|
| a nullable field compared with `>` / `<` without a guard "can throw" | **true when the value is null**: `null > 5`, `null < 5`, `null > null`, a null date `< today()`, a null decimal `> 5D` and `if (null > 5)` all throw a NullPointerException |
| `null + 1` throws | true (integer, decimal, and a local holding null) |
| `==` / `!=` with null throw | false: `null == 5` is false, `null != 5` true, null string `== "x"` false |
| assigning null to a `long` / `integer` / `decimal` local throws | false: assigned, the local holds null |
| `!` / `if` on a null boolean | throws |
| string + null | `"a" + null + "b"` = `anullb` |
| "a decimal divided by an integer literal truncates" | false: `7.50D / 2` = 3.75 (also stored in a decimal) |
| "an integer literal compared with a decimal does not compile" | false: compiles, `7.50 > 7` is true, `7.50 == 7` false |
| integer / integer, long / integer | truncate: 7 / 2 = 3 (number / integer = 3.75, integer / `2D` = 3.5) |
| "DST breaks UTC millisecond arithmetic" | false: `date2long` difference across 2026-03-29 = 48 h exactly |

So the null claim is not simply false: an unguarded relational or arithmetic use of a null throws. Under §7 it is a
data-dependent risk, i.e. a WARNING, unless the task's inputs make the null certain or a requirement covers it. The fact
sheet says exactly that; the decimal and DST claims are false and the sheet says so.

**Fact sheet** (`scripts/validate_precision/build_context.py` `FACTS`, the source of each line is commented there):
Rollup's five lifecycle functions are required (§7); `initGroup` runs once per group as its first record arrives, a
counter incremented there numbers the first group 1 (§3.35 probes); accumulator fields reset per group from metadata,
nullable → null, non-nullable → zero / default, globals keep their value until assigned (§7, §3.35 probes);
DataIntersection's CTL writes `$out.0` only (§7); millisecond date arithmetic is UTC without DST, `dateAdd(…, day)` and
zone-less date functions use the server's zone (ctl2-basics §13.3, probe); the null semantics above; the decimal / integer
results above; the §7 severity rule. The declaration-defaults rule is the rulev6 teacher's system prompt (c13c's).

### Review prompts (Data 1–2)

- **Source:** the 257 exec-RFT pool records minus the 97 whose reference hash is a pool-1 (B1) reference = **160
  references** (the other 10 of pool 1's 107 are in the exec-RFT holdout, which is not read). Sets: syntax pitfalls 49,
  SCD-2 36, Normalizer multi-row 23, Rollup accumulator 23, DataIntersection 13, Rollup lifecycle 10, zeroDate 6; 128
  generate and 32 fix tasks.
- **Builder:** `scripts/harness_measurement/make_mutants.py --exec-rft` (seed 13; B1 11, B1-tweak 12), every confirmed
  mutant and every reference kept (`scripts/validate_precision/make_review_set.sh`). The prompt is B1's; fix tasks lose
  their faulty code and fix instruction.

| kind | DataGenerator | DataIntersection | Denormalizer | ExtHashJoin | ExtMergeJoin | Normalizer | Partition | Reformat | Rollup | all |
|---|---|---|---|---|---|---|---|---|---|---|
| clean (reference) | 1 | 22 | 9 | 2 | 1 | 37 | 1 | 36 | 51 | **160** |
| missing lifecycle |  |  |  |  |  |  |  |  | 51 | 51 |
| unconnected port | 1 | 20 | 9 | 2 | 1 | 37 |  | 36 | 51 | 157 |
| unknown field | 1 | 20 | 9 | 2 | 1 | 37 |  | 36 | 51 | 157 |
| `return SKIP` |  | 15 | 9 |  | 1 | 37 |  | 30 |  | 92 |
| inverted condition |  |  |  |  |  | 14 | 1 | 10 | 17 | 42 |
| null guard removed |  |  | 9 |  |  | 5 |  | 11 | 29 | 54 |
| **planted** |  |  |  |  |  |  |  |  |  | **553** |

  Server status of the planted ones: unconnected port 157 init error; unknown field 157 graph validation; SKIP 92 wrong
  rows; lifecycle 51 init error; inverted condition 42 wrong rows (43 tries were equivalent and dropped); null guard 31
  runtime error + 23 wrong rows (22 equivalent). The planted half is dominated by the two compile-type kinds (57%); the
  brief's "every confirmed mutant" was followed.
- **Exclusions checked** (`build_context.py` asserts; `opcd.py prepare` output): no task of pool 1, pool_tweak or the
  exec-RFT holdout; no code or prompt of B1 / B1-tweak; no replay, target, contrast or hard prompt from pool 1, pool_tweak,
  B1, B1-tweak, the validate corpus records or the exec pool. Three `c13b_keep` DataIntersection prompts (di_sft_001/013/028)
  are exec-RFT holdout prompts and were dropped from the anchor (`data/validate_precision/c13b_keep_no_holdout.jsonl`).
- **Format conditions:** each prompt appears in both thinking modes, with the suite's output-format system prompt
  (`gen_answers.FORMAT`, via the new per-prompt `system_extra`) in one mode and without it in the other, alternating within
  each kind: clean 80 / 80 / 80 / 80 and planted 278 / 275 / 275 / 278 rows (format on, plain on, plain off, format off).
  No format instruction is appended to the user message (`validate_format: false`).

### Teacher context

Per row, appended to the rulev6 teacher's system prompt only (`teacher_context`, the c11 mechanism):
- **clean:** the brief's sentence with the fixture's input-row count ("… compiled and run on the CloverDX server against the
  task's fixture (N input rows) and produced exactly the required output rows. Report an [ERROR] only …");
- **planted:** "This code was run on the CloverDX server: <status>: <detail>. Find the statement responsible …", the detail
  being the init / compile message, the runtime exception with its CTL snippet, or "output port K: n rows, expected m;
  first difference at row R: expected {…}, got {…}" (≤ 500 characters);
- the fact sheet (2.1k characters). Contexts are 2.5–2.8k characters.

Guards: `quote_guard` (rule citations, as c13c) and the new `train.context_guard`, a regex for quotes of the context ("was
run on", "on the CloverDX server", "the fixture", "server verdict / result / run", "produced exactly the required"); a
matching sample is dropped and counted (`metrics.json` `skipped_context_quote`, per tag in `by_tag`). In OPCD the teacher
does not write answers; it scores the student's samples, so "the teacher's answer is checked" means these guards plus the
usual belief / quote scans.

### Anchors and schedule

As c13c: target (dpodef1 train, dpodef3b_plain), contrast, hard sets 1–2 with the rulev6 teacher; `c13b_keep` minus the
holdout prompts with their component-guide teachers, both modes; replay 0.4 with the plain-model anchor. The anchors'
weights are c13c's ×2 so that the 1426 review rows are **61%** of the non-replay weight (review 1426, anchors 902).
c13c's per-step hyperparameters (lr 2e-5, k 2, 32 prompts and 2 steps per round, LoRA r32, init c13c round 15).
**123 rounds** = every review row drawn about once (11.6 review draws per round). Sampler: vLLM on GPU 3 (:3011, served as
`rb1009_vp`); training on GPU 1.

**Smoke** (`logs/validate_precision/smoke.log`, c13c's adapter, 6 samples incl. one clean and one planted review, 4 steps):
KL per token 0.0305 → 0.0256, finite, 58 GB peak; the review samples start at KL 0.09 / 0.12 against 0.001–0.03 for the
belief and replay samples. Student and teacher prompts checked: the student has neither the rule nor the server context;
the teacher has both; the output format is in both system prompts on format rows.

## Results

### Training (`results/validate_precision/round_stats_valprec1.md`)

123 rounds, 5.7 min each, adapter of round 122 evaluated. **Guard rejections:** the context guard never fired (0 of 2860
review samples quoted the server verdict, "the fixture", "on the CloverDX server" …); the rule-citation guard dropped 25
review samples (all thinking on); 34 samples were dropped as truncated, none hit the cutoff. Belief stayed at 0.0 on all
31 probes and on the target / hard sets; replay KL stayed ≤ 0.003 (no drift).

Teacher–student KL per token, first → last 10 rounds:

| review slot | samples | KL first 10 | KL last 10 |
|---|---|---|---|
| clean, format, off / on | 160 / 160 | 0.054 / 0.054 | −0.007 / 0.002 |
| **clean, plain, off** / on | 160 / 160 | **0.190** / 0.109 | **0.095** / 0.002 |
| planted, format, off / on | 550 / 556 | 0.155 / 0.080 | 0.004 / 0.029 |
| planted, plain, off / on | 558 / 556 | 0.157 / 0.073 | 0.031 / 0.030 |

Every slot converged except clean / plain / thinking off, the one with the largest initial gap and the fewest samples:
the student still answers clean code differently from the teacher there at round 122. That is the slot where the plain
gate failed.

### Validate ground truth (no judge; `results/validate_precision/gt_*.md`, 2 runs per record, Wilson / paired-bootstrap 95% CIs)

| gate | mode | c13c | valprec1 | difference (paired bootstrap) | pass condition | |
|---|---|---|---|---|---|---|
| **B1-tweak** control false alarm (n 100) | off | 0.24 [0.17, 0.33] | 0.23 [0.16, 0.32] | −0.01 [−0.10, +0.08] | down by > 0.08 | **fail** |
| B1-tweak lifecycle recall (n 32) | off | 0.31 [0.18, 0.49] | 0.75 [0.58, 0.87] | +0.44 | up by > 0.15 | pass |
| B1-tweak defect recall (n 292) | off | 0.80 | 0.91 | +0.11 [+0.06, +0.16] | – | better |
| B1-tweak control false alarm | on | 0.08 [0.04, 0.15] | 0.04 [0.02, 0.10] | −0.04 [−0.08, −0.01] | not worse by > 0.08 | pass (better) |
| B1-tweak defect recall / lifecycle | on | 0.89 / 0.28 | 0.97 / 0.78 | +0.08 [+0.04, +0.13] / +0.50 | – | better |
| **B1** control false alarm (n 100) | off | 0.41 [0.32, 0.51] | 0.35 [0.26, 0.45] | −0.06 [−0.14, +0.02] | same direction | not beyond noise |
| B1 lifecycle recall (n 60) | off | 0.18 [0.11, 0.30] | 0.67 [0.54, 0.77] | +0.49 | same direction | pass |
| B1 defect recall (n 338) | off | 0.75 | 0.85 | +0.10 [+0.04, +0.15] | – | better |
| B1 control false alarm | on | 0.14 [0.09, 0.22] | **0.01** [0.00, 0.05] | **−0.13 [−0.23, −0.05]** | – | better |
| B1 defect recall / lifecycle | on | 0.86 / 0.35 | 0.96 / 0.83 | +0.11 [+0.07, +0.15] / +0.48 | – | better |
| **B1 plain** (no format) control false alarm | off | 0.30 [0.22, 0.40] | **0.61** [0.51, 0.70] | **+0.31 [+0.20, +0.42]** | not higher than with the format (0.35) | **fail** |
| B1 plain defect recall / lifecycle | off | 0.69 / 0.18 | 0.83 / 0.77 | +0.14 [+0.08, +0.20] / +0.59 | – | better |

Recall rose for every kind except inverted condition and null guard thinking off (flat within CIs); wrong `return SKIP`
off 0.84 → 0.98 (B1), 0.77 → 0.97 (B1-tweak). The defect finding is reported as ERROR as before.

### Generate, belief and judge gates (`scripts/validate_precision/gates_table.py` → `results/validate_precision/gates_valprec1.md`; Newcombe / Welch 95% CIs)

| gate | c13c | valprec1 | difference, 95% CI | pass condition | |
|---|---|---|---|---|---|
| gap tests off, execution pass rate (3 × n10 × 11; runs 0.391 / 0.400 / 0.427) | 133/330 (0.403) | 134/330 (0.406) | +0.003 (−0.071, +0.077) | within ±0.06 | pass |
| gap tests on, execution pass rate (runs 0.682 / 0.718 / 0.745) | 251/330 (0.761) | 236/330 (0.715) | −0.045 (−0.112, +0.022) | within ±0.06 | pass (at the edge; c13c's own runs 0.727–0.782) |
| harness pool 1 off, first attempt | 89/137 (0.650) | 178/274 (0.650) | +0.000 (−0.095, +0.099) | within the CI | pass |
| harness pool 1 on, first attempt | 113/137 (0.825) | 216/274 (0.788) | −0.036 (−0.112, +0.048) | within the CI | pass |
| T40 on, below full (2 × n20) | 1/20 | 0/40 | −0.050 (−0.236, +0.047) | as c13c | pass |
| T42 on, below full (2 × n20) | 7/20 | 10/40 | −0.100 (−0.343, +0.127) | as c13c | pass |
| hard sets 1 / 2 / 3, belief claims (k4) | 0/160, 1/60, 0/160 | 0/160, 0/60, 0/160 | – | as c13c | pass |
| hard set 3 by direction: nullable / non-nullable / metadata default / first-record sentinel wrong | 14/40, 2/20, 4/20, 0/80 | 10/40, 0/20, 0/20, 2/80 | −0.10 / −0.10 / −0.20 (−0.42, +0.00) / +0.03 | nullable ≤ 14/40 | pass |
| T54 off, `$out.1`/`$out.2` (n20) | 0/20 | 0/20 | +0.000 (−0.161, +0.161) | ≤ 1/20 | pass |
| judge validate off ×9 excl. T18/T22, mean | 0.935 (495) | 0.920 (495) | −0.016 (−0.035, +0.004) | §4.7 band | pass |
| **judge validate off ×9, WRONG share of findings** | 25/1135 (2.2%) | 44/1148 (3.8%) | **+0.016 (+0.002, +0.031)** | regression check | **worse** (CI optimistic) |
| thinking on, full v4 n5: validate / fix / generate | 0.850 / 0.826 / 0.970 | 0.843 / 0.814 / 0.978 | −0.007 / −0.012 / +0.008 (all CIs span 0) | within noise | pass |

Generate and belief hold. The judge's thinking-off WRONG share rose on the test.py path, the path the plain gate
measures, so it agrees with that gate.

**Hand read, 10 thinking-on judge-suite validate answers** (seed 7, `results_qwen38_vp_v4_valprec1_on_20261028T132406Z.json`):
8 are correct and well explained. Two answers say a reference-backed fact that came from the teacher's fact sheet ("`==` with a
string literal is null-safe in CTL2 (`null == "EU"` evaluates to `false` without throwing)", T14 ×2). Two T28 answers
have WRONG findings ("assigning a `long` to an `integer` … will not compile"; "`date + integer` is not a valid CTL2
expression"), the same T28 pattern c13c shows. Lengths 87–336 words; no sign of shortened or degraded explanations.

### Hand check: 10 B1-tweak controls c13c flagged (format, thinking off, runs 1–2)

| control | c13c (flagged runs) | valprec1 | what changed |
|---|---|---|---|
| `tweak_1cc9686f0e` Normalizer | 2/2: "divides decimal exposure by integer literal 10, which CTL2 evaluates as decimal division and truncates toward zero" | 0/2: "ISSUES: none" | decimal-division claim gone |
| `tweak_52fc41d5cf` DataIntersection | 1/2: "compares a `decimal` difference with an integer literal. CTL2 does not implicitly upcast … the transform does not compile" | 0/2 | decimal-compare claim gone |
| `tweak_25e8556b15` Normalizer | 2/2: "CTL2 performs the final division as integer division and truncates" | 1/2: "The warranty allocations use integer division before assigning the decimal result … PARTS becomes 70.00D instead of 70.35D" | halved, same false claim |
| `tweak_6dad0285ec` Rollup | 1/2: "`totalHours / acc.eligible_count` performs integer division" | 1/2: "divides a `decimal` by a `long` and therefore produces a `number` … is a type error. The code does not compile" | **replaced** by a new false type claim |
| `tweak_9aad59554d` Rollup | 1/2: "When `refund_sgd` is null … the addition throws a runtime CTLException" | 0/2 | null claim gone |
| `tweak_18f7eea38f` Reformat | 1/2: "assigns them directly to `long` locals. CTL2 does not implicitly substitute zero for a null long; either input null can throw" | 1/2: "The service-agent check applies the LOY pattern to the trimmed card text instead of the raw service_agent field" | null-to-local claim gone, **replaced** by a requirement misreading |
| `tweak_37ded87466` Normalizer | 1/2: "The first row of a new identity can emit BEGIN without an opening interval" | 0/2 | gone |
| `tweak_39113072ba` Normalizer | 1/2: "The first room assignment for an identity therefore produces no START row" | 0/2 | gone |
| `tweak_3865d205fb` DataIntersection | 1/2: "The ordered risk comparison can throw for a matched packet whose proposed risk_points is null" | 2/2: "`$in.0.risk_points > $in.1.risk_points` compares nullable risk_points without guarding either operand … can throw at runtime" | null-compare ERROR **more often** |
| `tweak_b7245bff9c` Reformat | 2/2: "compares nullable `transfer_aed` with `10000` without guarding null … can execute and throw" | 2/2: "`$in.0.transfer_aed <= 10000` compares a nullable decimal without guarding null. The ordered comparison throws" | unchanged, still ERROR |

So on B1-tweak thinking off, the claims the fact sheet refutes mostly disappeared: decimal / integer arithmetic (5 → 1
ERRORs over all controls, by keyword) and null-to-local. The null-comparison claims (true when the value is null, but a
WARNING under §7) stayed and are still ERRORs: 8 ERROR / 0 WARNING (c13c 7 / 2). Three controls c13c passed are now
flagged with new claims. One is "`raiseError` is not a built-in; the call fails at compile time" (`tweak_c0a8fceeea`),
which contradicts §7. The others are a whole-string-match reading of `~=` (`tweak_398f323394`) and a reversed reading of a
null-prior rule (`tweak_9cfdb1fbed`).

**B1 plain thinking off (the regression), by claim** (keyword-classified [ERROR] lines on the 100 control answers):

| claim | c13c | valprec1 |
|---|---|---|
| answers with any [ERROR] | 30 | 61 |
| Rollup / group state (initGroup numbering, "accumulator not reset / uninitialized", leaks) | 11 | 17 |
| requirement misreadings (SCD-2 close boundaries, rule order, T46 / T66 / T68 / T70 / T73 contracts) | 8 | 18 |
| null "throws" | 8 | 10 |
| compile / signature claims | 0 | 5 |
| DataIntersection / ExtMergeJoin "`$out.0` is the wrong port" | 2 | 4 |
| DST / time zone | 2 | 3 |

The new compile claims are false by the reference and the server (these controls compiled and passed). Examples: "getDayOfWeek
returns 1 for Sunday and 7 for Saturday" (ctl2-basics: 1 = Monday), "getMinute has no overload accepting a time-zone
string" (it has), and "the final `else if (true)` makes the following `return 0;` unreachable. CTL2 rejects that". Thinking
off, the plain-prompt model also says "the transform writes `$out.0` … the component rejects" on clean DataIntersection
code (T53 2/2, scd2_021). That is the opposite of §7 and of the fact sheet. It still says "emittedGroups is incremented in
initGroup, so the first group receives ordinal two" (rollup_acc_007 / 018, 4/4), against the fact-sheet line written
from §3.35's probes. The DST claim on `86400000L` subtraction in UTC (scd2_045, 2/2) also survives. The fact sheet did
not reach these claims in the plain, thinking-off condition.

## Indications

1. **The false-alarm rate fell thinking on, not thinking off.** Thinking on: B1 0.14 → 0.01 (−0.13 [−0.23, −0.05]),
   B1-tweak 0.08 → 0.04. Thinking off with the format: B1 0.41 → 0.35 and B1-tweak 0.24 → 0.23, both within noise and
   short of the hypothesis (below 0.25 / 0.15). Thinking off without the format it doubled (0.30 → 0.61).
   - **Gone:** the claims the fact sheet refutes, i.e. decimal / integer division and comparison ("truncates", "does
     not compile") and "null assigned to a long local throws".
   - **Stayed:** the null-comparison ERRORs (true for a null value, but data-dependent, so a WARNING under §7; 0
     WARNINGs). Also Rollup ordinals and state resets, and DST on UTC milliseconds.
   - **New:** a decimal / long "type error", `raiseError` "not a built-in", getDayOfWeek / getMinute signatures,
     "unreachable return", DataIntersection `$out.0` "wrong port", and more requirement misreadings.
2. **Lifecycle recall rose sharply in every condition:** B1 off 0.18 → 0.67, on 0.35 → 0.83, plain off 0.18 → 0.77;
   B1-tweak off 0.31 → 0.75. That passes the gate. Overall defect recall rose 0.08–0.14, and `return SKIP` recall is
   0.97–1.00.
3. **The plain and format conditions did not move together thinking off.** Recall rose in both, but the false-alarm rate
   fell slightly with the format and doubled without it, and the judge (test.py path) shows the same as WRONG 2.2% →
   3.8%. The training stats point to the cause: clean / plain / thinking off is the only review slot whose KL did not
   converge (0.190 → 0.095; every other slot ≤ 0.03). It had 160 samples (about 1.3 per prompt) against about 550 per
   planted slot. With 78% planted reviews, the thinking-off student learned "find the defect" faster than "this code
   ran clean". That cause is an inference from the stats and was not tested separately.
4. **No generate or belief regression.**
   - Gap-test execution off is 0.406 vs 0.403. On it is 0.715 vs 0.761 (−0.045, inside the ±0.06 band but at its edge;
     worth a re-run before any adoption).
   - Harness first attempt is 0.65 / 0.79 vs 0.65 / 0.82, within the CIs.
   - T40/T42, the hard sets (set 3: nullable 10/40 vs 14/40, metadata default 0/20 vs 4/20) and T54 (0/20) are at
     c13c's level or better.
   - The judge's thinking-on suite is flat.
5. **Verdict: not adopted; run a second round with a rebalanced review set, not more of the same.**
   - The method works when the model reasons, so do not stop and leave precision to the system prompt. Thinking-on
     precision and recall are better than any model so far, at no generate cost.
   - c13c's successor must not double the thinking-off false-alarm rate on the test.py path, so this adapter is not
     the candidate.
   - Changes for valprec2:
     - **clean reviews at ≥ 50% of review weight**, with clean / plain / thinking off over-sampled until its KL
       converges;
     - the compile-type mutants (unconnected port, unknown field; 57% of planted now, already at recall ≈ 1.0)
       down-sampled;
     - controls of the claims that survived: clean DataIntersection `$out.0`, initGroup ordinals, UTC millisecond
       arithmetic, nullable comparisons whose fixture has no null;
     - a teacher-context line that names the WARNING form for a data-dependent null ("report it as [WARNING], not
       [ERROR]"), since the §7 severity sentence alone moved nothing.
   - Same gates, plus B1 plain thinking on.

## Files

- Scripts: `scripts/validate_precision/{probe_facts.py, make_review_set.sh, build_context.py, vllm_sampler_3011.sh, smoke.sh,
  run.sh, gates.sh, round_stats.py, gates_table.py}`; `scripts/harness_measurement/make_mutants.py` (`--exec-rft`); `opcd.py` (`system_extra`,
  `validate_format`, `context_guard`, per-tag stats, target / contrast weights, `smoke --review`).
- Config: `configs/opcd_valprec1.yaml`.
- Data: `data/validate_precision/{review_mutants.jsonl, review_prompts.jsonl, c13b_keep_no_holdout.jsonl}` + reports;
  run folder `data/opcd/valprec1/`; probes `results/validate_precision/fact_probes.json`.
