# Fix-to-spec examples: declared variables are not null

**Write 80 new answer-only "fix to spec" records** that teach one thing: a variable declared
without an initializer starts at its type's default value, not null. In a fix answer, such a
variable must not be "fixed" with a null guard or an initializer presented as a null fix. Only
`variant`, `byte` and `cbyte` start null. Everything above "Internal tracking" is the brief.

You are working in the `ctl_lora_training` repository, as for `CTL_LoRA_fix_to_spec_explained.json`.
Use the same house style, record shape, rules and checks as that set's brief
(`spec/fix_examples_brief.md`) and the dedup brief (`spec/fix_examples_dedup_brief.md`). This
brief only says what is different.

## Why

The model trained on `CTL_LoRA_fix_to_spec_explained.json` now explains real defects correctly.
But on two fix benchmarks it still claims, in **20 out of 20 attempts**, that an uninitialised
`date` (or list) "starts null". It then adds a guard or an initializer and lists it as a fix.
That set had this construct as a **silent** trap in 69 records. Leaving a trap unmentioned did
not unteach the belief, so these records name it.

## The rule (owner ruling, binding)

A variable declared without an initializer, global or local, starts at its type's default.
**Only `variant`, `byte` and `cbyte` start null.**

| type | starts as |
|---|---|
| `integer`, `long`, `decimal` | `0` |
| `number` | `0.0` |
| `boolean` | `false` |
| `string` | `""` |
| `date` | the epoch, 1970-01-01 00:00:00 |
| `T[]` list, `map[K,V]` | empty, the same as `= []` / `= {}` |
| `variant`, `byte`, `cbyte` | **null** |

So:
- `count++`, `total = total + x` and `s = s + x` are safe from the first use.
- `append(l, x)` and `m[k] = v` are safe from the first use.
- `prev < d` and `dateDiff(d, prev, day)` are safe from the first use. They work with the epoch,
  which is far in the past.
- `isnull(prev)` on a declared `date` is **never true**. Code that relies on it to detect the
  first record is a real logic defect (see "Contrast records").

The rule covers **declared variables only**. These are null and still need handling:
- nullable input fields;
- fields of an unmatched slave record in a left outer join;
- a Rollup accumulator field that `initGroup()` does not assign;
- a nullable output field that is never assigned (a non-nullable one is its zero value);
- a missing map key read with `m[k]`;
- function results that can be null, e.g. `getMonth(null)`, `parseJson`;
- a declared `variant`, `byte` or `cbyte`.

## What to write

### 60 "tempting declaration" records

Each record contains **at least one variable declared without an initializer, placed exactly
where a reader is tempted to guard it**:
- a `date` compared, or used in `dateDiff`, before any assignment on the first record;
- a counter or total incremented before any assignment;
- a list appended to, or a map written, before any assignment;
- a `string` concatenated onto;
- a `boolean` flag tested before it is set.

The specification must make the default value the **right** behaviour. For example, "the first
record of a customer always counts as a new visit" is right when the code tests
`dateDiff($in.0.visit_date, lastVisit, day) > 30` with `lastVisit` still at the epoch. State
that in the answer with the concrete value. Vary the type: about 25 `date`, 15 numeric, 10 list
or map, 10 `string` or `boolean`.

The record still plants **2–4 real defects** from the earlier briefs' themes, so it is a real
fix task. The correct answer:
1. lists the real defects, numbered, in the house style;
2. adds, after the numbered list, **one short line per tempting declaration** that says it is
   not a defect, why, and the concrete value it has on first use. For example:

   > Left unchanged: `date lastVisit;` starts at the epoch (1970-01-01), not null, so on a
   > customer's first visit `dateDiff(visit_date, lastVisit, day)` is about 20,000 and the visit
   > counts as new, as item 2 requires.

3. gives the corrected code with the declaration **unchanged**: no `= null`-style initializer,
   no `isnull()` guard and no `nvl()` around it.

Keep the "Left unchanged" line short: one sentence, two at most. Write it for that record's code
and values, not as a fixed phrase repeated verbatim. Vary the wording.

### 20 contrast records

These teach the model to tell the declared-variable case from real nulls. Each one has a
**real null-related defect** next to a declared variable that stays unchanged. Spread them over:

- **Real nulls that need a guard** (≥ 8): a nullable input field in arithmetic or an ordered
  comparison; an unmatched slave field; an unassigned Rollup accumulator field; a missing map
  key read with `m[k]`; a declared `variant` used before assignment.
- **`isnull(declaredVar)` used to detect "first record" or "not yet set"** (≥ 6). This is never
  true, so the first-record branch never runs. Name the wrong value it produces, then fix it
  with a `boolean` flag, a counter, or a comparison against a sentinel the specification
  supports.
- **A redundant initializer that is not the bug** (≥ 4): code with `integer n = 0;` or
  `string[] l = [];` next to a real defect. Leave the initializer alone and don't call it a fix.

## What not to do

- **Don't copy the two benchmark scenarios** that test this belief:
  - a Denormalizer with `integer shippedCount; decimal shippedTotal; date lastOrderDate;` and a
    `.contains()` status check;
  - a Partition routing shipments by service code with `integer turn; date prevShip;`.

  Also avoid the other scenarios listed in `fix_examples_brief.md`.
- Use `byte` or `cbyte` at most in a few contrast records. They are rare in transforms.
- Don't let "Left unchanged" lines mention anything other than tempting declarations. Other
  traps (two-argument `substring`, `push`, `return ALL`, `~=`, …) stay silent, as before.
- Don't reuse code from `CTL_LoRA_fix_to_spec_explained.json`.

## Checks

- [ ] All checks of `fix_examples_brief.md`: the corrected code compiles; every defect is real;
      compile errors are confirmed with the compiler; owner rulings 1–6 hold.
- [ ] **Each tempting declaration is really safe:** trace the first record by hand with the
      default value and confirm that the specification's required output comes out. Note the
      traced value in the log.
- [ ] **Each `isnull(declaredVar)` contrast was confirmed with the compiler and a run,** if you
      can run CTL2. Otherwise mark it unverified in the log.
- [ ] The dedup check from `fix_examples_dedup_brief.md` passes on this file. It also passes
      against `CTL_LoRA_fix_to_spec_explained.json` (no pair above 0.85), and no "Left unchanged"
      sentence repeats verbatim.

## Output

- **`sft_training_data/CTL_LoRA_fix_defaults_explained.json`**: ids `fixdef_001`–`fixdef_080`;
  tags as before plus `defaults:<type>` per tempting declaration and `contrast:<kind>`.
- **`sft_training_data/logs/CTL_LoRA_fix_defaults_explained_log.md`**: counts per component,
  type and contrast kind; the compile method per record; the traced first-record values.

Commit and push.

---

## Internal tracking

Not part of the brief.

- **Source:** rb1006 fix ON n=20 (results_qwen38_rb1006_on_20261006T011305Z). T40.FP1 and T42.FP6
  fired 20/20, as they did in rb1005 and base, while fix rose to 0.863 and fix WRONG fell from
  43/412 to 6/420. Memory: rb1006-fix-explained-results.
- **Owner, 2026-10-06:** declared variables start at type defaults; only variant, byte and cbyte
  start null (matches the references and memory ctl2-declaration-defaults). Companion audit:
  `declaration_defaults_audit_brief.md`.
- **Success measure:** the next retrain against rb1006, fix with thinking on, n=20. T40.FP1 and
  T42.FP6 fire in ≤ 25% of runs, with no loss on fix, generate or validate WRONG.
