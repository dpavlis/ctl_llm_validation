# Deployment system-prompt rules on valprec2's residual weaknesses (2026-10-30/31)

Question (owner, 2026-10-30): does a short list of compiler-verified CTL2 facts in the deployment system prompt fix
the weaknesses in `spec/valprec2_weaknesses.md` items A1–A3 (reserved names, `!~`, constant ternaries, try/catch
misuse, Rollup accumulator record), without any training?

## Setup

- **Model:** valprec2 (rb1009 export + `data/opcd/valprec2/round_155`), vLLM on :3012, both thinking modes.
- **Rules:** `data/sysprompt/rules_v1.txt` (7 lines: reserved words, no `!~`, ALL/OK/SKIP not ternary operands,
  `"\\."` escapes, `catch (CTLException ex)` / no throw or raise / `raiseError(ex.message)`, accumulator is its own
  record and every non-nullable field is assigned in initGroup). Appended to the suite's generate/validate/fix system
  prompts (`configs/eval_sp_v5gaps_valprec2_rules_{on,off}.yaml`) and to the harness prompt
  (`agent_harness.py --system-extra`).
- **Measures:** execution pass (`exec_score.py`) on suite v5 T57/T63/T67/T73, thinking on 3×n10, thinking off 1×n10,
  against valprec2's stored n30 baseline (`results/validate_precision/gaps_valprec2.json`); first-attempt harness pass
  on the 52 pool-1 tasks of the syntax-pitfalls and Rollup-accumulator sets (`data/agent_harness/pool1_weak.jsonl`,
  2 runs, `--rounds 0`), against valprec2's pool-1 first-attempt files. CIs are Newcombe 95%.
- Scripts: `scripts/sysprompt/run.sh`; results `results/sysprompt/gaps_valprec2_rules.json`,
  `results/agent_harness/valprec2_rules_pool1_weak_{off,on}.jsonl`.

## Result

### Suite gap tests, execution pass

| test | mode | valprec2 | with rules | diff [95% CI] |
|---|---|---|---|---|
| T57 Rollup accumulator | on | 8/30 (0.27) | 14/30 (0.47) | +0.20 [−0.04, +0.41] |
| T63 Rollup non-nullable acc | on | 17/30 (0.57) | 24/30 (0.80) | +0.23 [−0.00, +0.44] |
| T67 5-port try/catch | on | 21/30 (0.70) | 21/30 (0.70) | 0.00 [−0.22, +0.22] |
| T73 date parse try/catch | on | 18/30 (0.60) | 29/30 (0.97) | +0.37 [+0.16, +0.55] |
| **all four** | **on** | **64/120 (0.53)** | **88/120 (0.73)** | **+0.20 [+0.08, +0.31]** |
| T57 | off | 2/30 (0.07) | 0/10 | −0.07 [−0.21, +0.22] |
| T63 | off | 0/30 | 0/10 | 0.00 [−0.11, +0.28] |
| T67 | off | 6/30 (0.20) | 5/10 (0.50) | +0.30 [−0.02, +0.58] |
| T73 | off | 21/30 (0.70) | 2/10 (0.20) | −0.50 [−0.70, −0.14] |
| all four | off | 29/120 (0.24) | 7/40 (0.17) | −0.07 [−0.19, +0.09] |

Judge scores on the same answers moved at most 0.13 (T67 off +0.13, T73 off −0.08) and otherwise ±0.03: the judge
does not see these errors, as in §3.28.

### Harness, 52 weak pool-1 tasks, first attempt

| set | mode | valprec2 | with rules | diff [95% CI] |
|---|---|---|---|---|
| syntax pitfalls (24 tasks) | off | 15/48 (0.31) | 32/48 (0.67) | +0.35 [+0.15, +0.52] |
| syntax pitfalls | on | 21/48 (0.44) | 41/48 (0.85) | +0.42 [+0.23, +0.57] |
| Rollup accumulator (28 tasks) | off | 46/56 (0.82) | 47/56 (0.84) | +0.02 [−0.12, +0.16] |
| Rollup accumulator | on | 51/56 (0.91) | 49/56 (0.88) | −0.04 [−0.16, +0.09] |
| all | off | 61/104 (0.59) | 79/104 (0.76) | +0.17 [+0.05, +0.29] |
| all | on | 72/104 (0.69) | 90/104 (0.87) | +0.17 [+0.06, +0.28] |

### What the rules fixed and what they did not (compiler error classes, counted per answer)

| weakness | baseline | with rules | verdict |
|---|---|---|---|
| try/catch misuse (`Duplicate variable 'ex'`, `raise`/`throw`, `raiseError(record)`, `catch (Exception)`): T73 on 10/30, T67 on 4/30 | 14 | 0 | fixed |
| reserved names as tokens (`integer`, `month`, `date`): T63 off 20/30, on 6/30; T73 off 1 | 27 | 0 | fixed on the suite; halved on the harness (reserved_time_unit 15 → 8 off, 14 → 5 on) |
| regex negation (`!~`): harness 5 off / 7 on; T63+T67 off `Syntax error on token '!'` 8 | 20 | 3 | fixed in thinking on, mostly off |
| constant ternary (ALL/SKIP as operand): harness 3 off / 2 on | 5 | 2 | mostly |
| non-nullable accumulator field left null (T63 on `received_at` / `business_ref` NullDataFormatException) | 8 | 0 | fixed |
| accumulator assigned input/output field names (T57 on, `Field 'receipt_id'/'amount'/'voided' does not exist in record 'ReceiptAcc'`) | 22/30 | 12/30 | halved, not fixed |
| T67 port routing (wrong rows on ports 2–4): on 5/30, off 15/30 | — | on 9/30, off 5/10 | untouched; a spec misread (weakness A5), not a language fact |

### New thinking-off collapse (T73 off 21/30 → 2/10)

The passing baseline answers test the date with `!isDate(text, pattern, "en.US", "UTC", true)`. With the rules, 3 of 10
answers write `!(str2date(...) : null) != null`, a fusion of the rule's `!(x ~= re)` example with the conditional-fail
idiom (`Operator '!' is not defined for type 'date'`), one answer inserts type tokens into expressions
(`dictionary.auditEnabled boolean`), and 4 pass compilation but produce wrong rows at row 1–2. Thinking on is not
affected (29/30). n10 against n30, but the CI excludes zero. Thinking off is not the deployment mode (owner,
2026-10-30), so this is a footnote; if thinking-off ever matters, the regex line should give the `!matches(x, re)` form
only.

## Deployment recipe check: rules on the broad pool and on validate (2026-10-31/11-01)

`scripts/sysprompt/recipe_check.sh`: the same rules on (1) the fresh-domain pool_tweak harness, 165 tasks, thinking
on, 2 runs, 2 feedback rounds, paired per task-run with valprec2's §3.38 run, and (2) the B1-tweak validate ground
truth, both modes, 2 runs, format prompt, paired bootstrap against `validate_gt_tweak_valprec2_fmt`
(`results/agent_harness/valprec2_rules_pool_tweak.jsonl`, `validate_gt_tweak_valprec2rules_fmt.jsonl`,
`results/sysprompt/gt_tweak_valprec2_rules.md`).

| measure | valprec2 | valprec2 + rules | paired diff [95% CI] |
|---|---|---|---|
| pool_tweak first attempt, thinking on (n330) | 269/330 (0.815) | 259/330 (0.785) | −0.030 [−0.079, +0.018] |
| pool_tweak after 2 feedback rounds | 291/330 (0.882) | 278/330 (0.842) | −0.039 [−0.076, +0.000] |
| B1-tweak defect recall, off | 0.88 | 0.86 | −0.024 [−0.065, +0.017] |
| B1-tweak defect recall, on | 0.96 | 0.91 | −0.048 [−0.086, −0.014] |
| B1-tweak clean-code false alarm, off | 0.15 | 0.38 | +0.230 [+0.110, +0.350] |
| B1-tweak clean-code false alarm, on | 0.02 | 0.08 | +0.060 [+0.020, +0.110] |

- **Generate:** the pool holds only inside the band, and the loss is one component. DataIntersection first attempt
  76/102 → 68/102; its `Cannot write to output port '1'` misses go 21 → 32. Reformat, Normalizer, Rollup, Partition are
  unchanged (74/75, 81/80, 32/32, 4/4). The syntax habits the rules target barely occur on this pool (valprec2 has 3
  reserved-name and 1 regex miss in 330), so there was nothing to gain and the DataIntersection belief had room to
  get worse.
- **Validate, thinking on:** all 6 new false alarms are DataIntersection controls with the same claim: "`return ALL`
  sends the matched record to all three ports / matched records belong on port 1" (owner fact §7: `ALL` or `OK` from a
  DataIntersection transform routes to the *both* port and CTL writes `$out.0`). The ternary line of the rules names
  `ALL`, and that mention appears to prime the model's DataIntersection port confusion (weakness A6) in both generate
  and review.
- **Validate, thinking off:** false alarms 15 → 38 across every component (Normalizer 13, DataIntersection 9,
  Reformat 9, Rollup 5), mostly new "other" claims (null handling, lane logic, long-vs-decimal). A list of
  prohibitions in the system prompt makes the thinking-off reviewer hunt for violations. Thinking off is not the
  deployment mode, but this shows the rules must not be in a validate prompt served without thinking.

## DataIntersection framing test (2026-11-01)

Owner idea (2026-11-01): the DataIntersection confusion comes from teaching three output ports and then imposing
"the CTL writes `$out.0`". Teach it instead as a join-like transform: two input records, one output record, no ports.
Tested as a system-prompt paragraph on valprec2, DataIntersection subsets only (`scripts/sysprompt/di_frame.sh`,
`di_frame2.sh`; text `data/sysprompt/di_frame_v1.txt`, `di_frame_v2.txt`). The paragraph names no port numbers: the
transform is a joiner over matched pairs, `$in.0` the A record, `$in.1` the B record, one output record `$out.0`,
return OK to emit or SKIP to drop, one-sided records never reach the CTL and the component's routing of them is not the
CTL's business, the return value chooses no port, there is no `$out.1`/`$out.2`. v2 adds one sentence: ALL, 0 and 1
are accepted and mean the same as OK.

| measure (thinking on unless noted) | valprec2 | framing v1 | framing v2 |
|---|---|---|---|
| harness, 51 pool_tweak DI tasks, first attempt (paired, n102) | 76/102 | 99/102, +0.225 [+0.147, +0.314] | 98/102, +0.216 [+0.137, +0.304] |
| same, after 2 feedback rounds | 89/102 | 99/102, +0.098 [+0.049, +0.157] | 101/102, +0.118 [+0.059, +0.186] |
| first-attempt `Cannot write to output port` misses | 21 | 0 | 2 |
| suite T54 execution pass (n30) | 26/30 | 29/30, +0.10 [−0.06, +0.27] | – |
| suite T53 | 30/30 | 30/30 | – |
| B1-tweak DI controls, any [ERROR], on (n24) | 0.08 | 0.42, +0.333 [+0.125, +0.583] | 0.00, −0.083 [−0.208, +0.000] |
| B1-tweak DI controls, any [ERROR], off (n24) | 0.08 | 0.67, +0.583 [+0.333, +0.833] | 0.17, +0.083 [−0.167, +0.333] |
| B1-tweak DI defect recall, on (n56) | 0.98 | 0.98 | 0.95, −0.036 [−0.125, +0.036] |

- **Generate:** the largest single-component move measured in this project. 23 of the 51 prompts describe the three
  outputs ("A-only on 0, both on 1, B-only on 2") and the paragraph still wins on them: the port talk in the prompt no
  longer pulls the code to `$out.1`.
- **Validate v1 false alarms were the text's omission, not the framing's.** All 12 clean controls use `return ALL`
  (the corpus idiom); v1 said only "return OK", so the reviewer called `return ALL` invalid in 10 of 24 thinking-on
  control answers. v2's one sentence removes them (0 of 24) and keeps the generate gain. The thinking-off +0.08 is two
  answers inside the ±0.15 single-kind band.
- **Compare with rules_v1 on the same component:** the three-port text plus the word `ALL` made DataIntersection worse
  in both generate and review; the join-like paragraph without port numbers fixes it. The framing matters, not the
  number of facts.

**Verdict:** v2 is the proven wording. Next (owner's call, correctness rule "update every copy"): rewrite §8.9 of
`resources/ctl2-basics.md` and its §13 line in this framing, propagate to both eval snapshots, the rule teacher and
the corpus reference, write the corpus brief for the DI sets (join-like explanation, no port numbers in the CTL
explanation, a share of prompts that still describe three outputs so the model stays robust to them), and run OPCD
with the rewritten §8.9 as teacher context. Open question for the brief: whether the corpus idiom moves from
`return ALL` to `return OK`; if it does, the clean controls of B1/B1-tweak change with it.

## Verdict (rules_v1)

- **rules_v1 is not adopted as written.** On the tests it targets it works (gap tests 0.53 → 0.73 thinking on, syntax
  pool 0.44 → 0.85, try/catch, reserved-name and null-accumulator errors gone), but on the broad fresh-domain pool it
  costs DataIntersection (−0.03 overall, [−0.08, +0.02]) and in validate it raises the thinking-on false alarm 0.02 →
  0.08 with one new claim, all on DataIntersection, and doubles the thinking-off false alarm.
- **Next:** rules_v2 that (a) drops `ALL`/`OK`/`SKIP` from the ternary line or states the DataIntersection port fact
  outright (matched records are written to `$out.0`, `return OK`/`ALL` routes them to the *both* port; `$out.1` does not
  exist in the transform), and (b) goes into the generate and fix prompts only, not the validate prompt. Measured the
  same way: gap tests + syntax pool for the gain, pool_tweak paired + B1-tweak for the cost.
- **What remains in thinking on** after the rules is the T57 habit of assigning input fields to the accumulator record (12/30 still)
  and the T67 port routing; both are task-reading errors, not language facts, and are the compile-and-retry loop's job
  (the harness fixes most of them after one feedback round, §3.31).
- **No training lane follows from this.** A corpus brief for A1–A3 would buy what a prompt can give; the remaining
  failures need rows feedback, not facts.
