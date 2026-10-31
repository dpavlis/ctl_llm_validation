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

## Verdict

- **Thinking on, the deployment mode:** the seven rule lines remove the try/catch, reserved-name and null-accumulator
  errors entirely and lift the four gap tests from 0.53 to 0.73 and the syntax-pitfall pool from 0.44 to 0.85, with no
  loss on the Rollup-accumulator pool (−0.04 [−0.16, +0.09]). Adopt `rules_v1.txt` in the deployment system prompt.
- **What remains in thinking on** is the T57 habit of assigning input fields to the accumulator record (12/30 still)
  and the T67 port routing; both are task-reading errors, not language facts, and are the compile-and-retry loop's job
  (the harness fixes most of them after one feedback round, §3.31).
- **No training lane follows from this.** A corpus brief for A1–A3 would buy what the prompt already gives; the
  remaining failures need rows feedback, not facts.
