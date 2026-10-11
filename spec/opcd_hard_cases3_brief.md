# OPCD hard cases, round 3: first-record sentinels in generated code, and Rollup accumulator nullability

**Write 40 new prompts, prompts only with no answers, in two parts:**
- **Part A:** 20 *generate* prompts whose natural solution needs a "first record of the group"
  sentinel.
- **Part B:** 20 Rollup *validate/fix* prompts about accumulator-field nullability.

This extends `data/opcd/hard_cases.jsonl` and `hard_cases2.jsonl`. The briefs
`spec/opcd_hard_cases_brief.md` and `spec/opcd_hard_cases2_brief.md` still apply (facts, owner
rulings, checks, output conventions). This file says only what is different.

## Why

After four OPCD runs the model reviews and fixes declarations correctly:
- T40 false fix 3/20;
- 0% belief on the held-out hard cases;
- fix score up by 0.05.

Two gaps remain, and every prompt so far missed both.

1. **Code generation (suite T33).** Asked to write a Denormalizer that captures the group key once,
   the model writes:
   ```ctl
   long batchId;
   function integer append() { if (batchId == null) batchId = $in.0.shipment_batch_id; ... }
   ```
   `batchId` starts at 0, not null, so the test never fires and every batch emits key 0. The judge
   notes: "the explanation incorrectly assumes codes starts null". All earlier hard cases were
   review or fix tasks; the model never had to *write* the sentinel itself.
2. **Rollup accumulators (suite T22).** The training taught "declared variables are not null". The
   model now carries that over to accumulator fields, which are record fields and follow their
   metadata:
   - nullable with no default → null at the start of each group;
   - non-nullable → its type's zero value;
   - a metadata default → that default.

   It now writes "`acc.count` starts at 0, the increment is safe" for a nullable field. In T22 the
   accumulator type is given in prose with no nullability ("count (integer), total (decimal)").
   **In CloverDX, metadata fields are nullable unless marked `nullable="false"`,** so `count`
   starts null and `acc.count + 1` throws.

## Part A: 20 generate prompts with a first-record sentinel

- **Form:** "Write the complete CTL2 <Component> transform that …", with input and output metadata
  (CloverDX XML) and a short specification, in the style of the suite's generate tests.
- **What makes the task hard:** the natural solution must notice the first record of a group (or
  of the whole input), or capture a value once. Typical needs:
  - capture the group key or the first value once per group;
  - compare with the previous record;
  - emit something only from the second record on;
  - track "has anything been seen yet".
- **Correct solutions** use one of these:
  - a `boolean` flag or a counter, reset in `clean()` / `initGroup()`;
  - assignment on every record when that is equivalent;
  - an explicit `= null` initializer **and** the same reset, when null is a deliberate sentinel.

  A bare declaration tested with `== null` / `isnull()` is the bug we target. **Don't mention
  this pitfall in the prompt.**
- **Vary the sentinel type:** `long` / `integer` keys (start at 0), `string` keys (start at `""`),
  `date` previous values (start at the epoch), lists (start empty).
- **Components:**
  - 6 Denormalizer and 4 Rollup;
  - 4 Reformat (previous-record or running logic over the whole input);
  - 3 Partition (previous-record routing);
  - 3 Normalizer or joiner.
- **Domains:** new ones. Don't reuse T33's scenario (cold-chain batches, exception codes) or any
  earlier hard-case scenario.
- **Every prompt must be solvable cleanly in CTL2.** Write a reference solution for yourself and
  compile it with `ctl_validate`. It is not part of the output, apart from the
  `"reference_compiles"` flag.

## Part B: 20 Rollup prompts on accumulator nullability (12 validate, 8 fix)

Each prompt gives the accumulator record type. **Vary how it is given:**
- in prose ("Accumulator record type (Acc): count (integer), total (decimal)"), as in T22;
- as XML metadata with no nullable attribute;
- as XML with explicit `nullable="true"` / `nullable="false"`;
- sometimes with a `default="…"` attribute.

| kind | count | situation | correct answer |
|---|---|---|---|
| `acc_nullable_uninit` | 10 | a nullable (or unmarked) accumulator field used in arithmetic, a comparison or concatenation in `updateGroup()` without being initialised in `initGroup()` | real defect: it is null at the start of each group, so the first use throws or gives the wrong result; initialise it in `initGroup()` |
| `acc_nonnullable_uninit` | 5 | the same pattern, but the field is `nullable="false"` | **no** null defect: it starts at its type's zero value. Explicit initialisation is good style, not a fix for a null |
| `acc_metadata_default` | 5 | the field has a metadata `default`; the code relies on it | no defect from the missing initialisation: it starts at the default. Make the spec need that default |

- **Each prompt also has 2–3 other real defects of the T22 kind:**
  - a missing required lifecycle function (`initGroup`, `updateGroup`, `finishGroup`,
    `updateTransform`, `transform`; all five are required);
  - a wrong return value;
  - the per-record output loop suppressed by mistake;
  - and similar.

  This way the accumulator question is one finding among several, as in the suite.
- **Mix in 1–2 declared global variables per prompt** (a bare `integer` / `string` / list) used
  correctly from their defaults. The model must keep the declared-variable fact *and* the
  record-field fact apart.
- Fix prompts use the fix-to-spec wording with a numbered spec. Validate prompts use "Validate this
  Rollup component CTL2 transform …" with no format instruction.
- Compile every prompt with `ctl_validate`. Rollup with a given accumulator type works as in the
  earlier sets.

## Output

`/home/pavlisd/llama_train/data/opcd/hard_cases3.jsonl`, one object per line:

```json
{"id": "opcd_hard3_01", "part": "A", "task_type": "generate", "component": "DENORMALIZER",
 "user": "<full prompt>",
 "kind": "gen_first_record_sentinel",
 "sentinel": {"name": "the variable a naive solution would test", "type": "long", "default": "0"},
 "expected": "one sentence: what a correct solution does (e.g. boolean flag reset in clean())",
 "reference_compiles": true}
```

```json
{"id": "opcd_hard3_21", "part": "B", "task_type": "validate", "component": "ROLLUP",
 "user": "<full prompt>",
 "kind": "acc_nullable_uninit | acc_nonnullable_uninit | acc_metadata_default",
 "acc_fields": [{"name": "count", "type": "integer", "nullability": "unmarked | nullable | non-nullable", "default": null}],
 "trap_vars": [{"name": "...", "type": "...", "scope": "global", "first_use": "..."}],
 "expected": "one sentence on the accumulator field's start value and whether it is a defect",
 "other_defects": ["..."],
 "compile_expected": "ok | error: <intended message>", "compile_result": "<ctl_validate output>"}
```

---

## Internal tracking (not part of the brief)

- **Hold out 3 prompts from Part A and 4 from Part B** (2 nullable, 1 non-nullable, 1 default)
  for measurement.
- **Teacher check** (rule v3 teacher, thinking on, k=4):
  - Part A: the share of solutions with a bare-declaration `== null` sentinel must be ≤ 5%, judged
    on the code;
  - Part B: the accumulator start value must be stated correctly in ≥ 90% of answers, and
    non-nullable fields must not be flagged as null.
- **`eval_hard_cases.py` needs two new judge questions:** "uses a bare declaration as a null
  sentinel" for A, and "states the accumulator field's start value correctly" for B.
- **c5:**
  - continue from c4 at round 15, with these drawn ×3 and set 2 ×1;
  - generate prompts with thinking on, Part B validate with thinking on (rule v3 teacher);
  - gates: T33 back to ≥ 0.90, thinking-off validate WRONG ≤ 5% (T22), T40/T42 not worse.
