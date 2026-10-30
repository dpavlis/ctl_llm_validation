# valprec2: weaknesses that neither thinking mode solves (2026-10-30)

Sources, all on the adopted candidate valprec2 (c13c's generate numbers where valprec2 has no run): gap tests 3×n10
execution-scored both modes (`results/validate_precision/gaps_valprec2.json`), harness pool_tweak 2 runs × 2 feedback
rounds (`results/agent_harness/valprec2_pool_tweak.jsonl`), harness pool 1 first attempts (`valprec2_pool1_first_*`) and
c13c's pool 1 with feedback (`c13c_pool1.jsonl`), validate ground truth B1 / B1-tweak (`gt_*_valprec2_fmt.md`), judge
suite v4 off ×9 / on n5. "Both modes" means the failure is there thinking on as well as off; thinking-off-only gaps are
listed last, since deployment is thinking on with the retry loop.

## A. Generate / fix: execution-verified, both modes, survive error feedback

1. **CTL2 syntax habits the model cannot repair even when shown the compiler error.** In c13c's pool 1 with two
   feedback rounds, 4 of the 12 tasks that fail in both modes end on `reserved_time_unit` in every attempt (a local
   named `day`, `month`, `week`, … → "Syntax error on token"); the model renames something else or repeats the code.
   valprec2 first attempts: 10 of 22 both-mode pool-1 failures are reserved time unit, regex negation (`!~`) or a
   ternary with a constant branch. These are the §3.29 habits; no training lane so far has moved them (rb1012 syntax
   set, exec-RFT, retry1).
2. **try/catch misuse (corrected 2026-10-30; the first draft wrongly said CTL2 has no try/catch).** The model uses
   CTL2's `try { } catch (CTLException ex) { }` correctly in the inner blocks, then breaks it in the outer handler in
   three ways: `raiseError(ex)` with the exception record where `raiseError(string)` is required (`ex.message` would
   compile; T73 4 of 12 failures); `throw ex` / `raise ex`, Java/Python re-throw statements CTL2 does not have (T73 6,
   each also reported as "Duplicate variable 'ex'" because the parser reads `raise ex` as a declaration of a second
   `ex`); `catch (Exception e)` with the Java type instead of `CTLException` (T67 4 of 9 failures). The pattern is
   always a defensive wrapper around the whole `transform()` / `getOutputPort()` body that the task did not ask for.
   Both modes.
3. **Rollup accumulator: fields that only exist in the input/output records are assigned to the accumulator.** T57's
   `Receipt` input and `ReceiptDecision` output carry `receipt_id`, `amount`, `voided`, …; the `ReceiptAcc` accumulator
   has the shared passthrough fields plus `n`, `accepted`, `has_winner` only. In 21 of 30 thinking-on answers `initGroup`
   does `acc.receipt_id = null; acc.amount = null; acc.voided = false;` and compilation fails with "Field 'receipt_id'
   does not exist in record 'ReceiptAcc'". The model initialises the accumulator from the output record's field list,
   not from the accumulator metadata it was given (thinking off 28 of 30 fail, mostly the same way). T63 (off 0/30,
   on 17/30): a non-nullable accumulator field (`received_at`) never assigned → `NullDataFormatException` at
   `Rollup failed!` in 7–8 of the 13 failures. Pool 1 Rollup fix/generate tasks sft_003 / 019 / 044 fail in both modes
   after feedback with wrong rows. The validate side mirrors it: judge T22 scores 0.60 off / 0.67 on, missing
   "acc.count starts null and acc.count + 1 throws".
4. **Denormalizer / SCD-2 contract.** T61 (off 0/30, on 13/30): "transform function must be defined" 5, unresolved
   sequence 2, record type mismatch between the two metadata; the model leaves out a required lifecycle function or
   assigns records across types. Pool-tweak tasks `0b81eab5cc` and `dba012e9f6` fail in all 4 runs on "Unable to resolve
   sequence": the model calls `sequence(Name)` for a version number the graph has no sequence for, instead of counting.
5. **Specification misreads on multi-rule Reformat / Normalizer tasks**: wrong rows that no feedback round fixes, both
   modes: pool_tweak `17d03508af`, `9254fc2558` (3 of 165 tasks), pool 1 T48, T50, scd2_sft_045, syntax_r3_01, r3_05.
   The failing row is always a rule the prompt states (a sign, a precedence between two status rules, an "otherwise"
   branch). Not a language gap; a reading-comprehension gap on long requirement lists.
6. **DataIntersection output metadata, thinking on only:** 4 pool_tweak tasks fail in both thinking-on runs with
   "Field 'x' does not exist in record 'Y'" or "Cannot write to output port '1'" while thinking off passes them. The
   `$out.1` habit is mostly gone (c13c → retry1 first attempts 20 → 6 of 102; valprec2 T54 0/20) but the field-name
   invention on the joined output record remains.

## B. Validate: ground truth and judge, both modes

7. **Severity calibration, ERROR vs WARNING.** Judge T24 (0.60 off / 0.80 on) and T5 (0.76 / 0.72): correct finding,
   wrong severity in both directions (date-format letters as ERROR, null concatenation below the WARNING minimum).
   Ground truth agrees: every planted defect is reported as ERROR (B1 severity table, 0 WARNINGs), and on clean code
   the thinking-off reviewer still raises an [ERROR] on 25% of controls (B1), 15% (B1-tweak); thinking on 2–3%.
8. **Wrong mechanism with the right fix** (T5.B3: "isNull() is undefined" when the real defect is its arity; T39
   explanation overstates the affected range). The verdict is right, the stated reason is not; the judge counts it WRONG.
9. **Inverted condition** is the one defect kind thinking off still misses a third of the time (B1-tweak recall 0.67 off,
   0.93 on). Missing lifecycle function, the old gap, is fixed (0.18 → 0.73 off, 0.35 → 0.83 on).
10. **Rollup clean code, thinking off:** the control false-alarm rate on Rollup references is 0.50 on B1 (0.05 thinking
    on): group-state leaks and `initGroup` ordinal claims. Thinking-off only, but it is the component that also fails
    generate.

## C. Thinking-off-only generate gaps (for completeness)

T60 0/30 (on 27/30), T62 7/30 (27), T63 0/30 (17), T61 0/30 (13), T67 6/30 (21), T44 13/30 (28): the multi-function
components collapse without thinking. Not a deployment target.

## What this suggests

- Items 1–3 are small, enumerable CTL2 facts (reserved identifiers, `raiseError` takes a string and there is no
  `throw`/`raise`, `catch` takes `CTLException`, the accumulator is its own record whose non-nullable fields must be
  assigned) that the model holds wrong under both modes and under
  feedback. They are candidates for a corpus brief with execution-verified records, or for the system prompt of the
  deployment (a short "catch (CTLException ex); re-raise with raiseError(ex.message), no throw; never name a variable day/month/…" list), which
  costs nothing and can be measured on T57/T63/T67/T73 and the syntax pool before any training.
- Item 5 is not fixable by language facts; it is where a rows-feedback round helps (c13c 0.88 → 0.92 on pool 1).
- Items 7–8 are the validate residue: severity rules and "explain the mechanism" are rubric-level facts the judge
  suite checks but the ground-truth gate does not; the system prompt route applies there too.
