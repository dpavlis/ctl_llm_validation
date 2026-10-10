# OPCD hard cases, round 2: date traps shaped like T40/T42

**Write 15 new prompts, prompts only with no answers, in which a bare `date` declaration plays the
same role as `lastOrderDate` in T40 and `prevShip` in T42.** This extends the 40 prompts in
`data/opcd/hard_cases.jsonl`; brief: `spec/opcd_hard_cases_brief.md`. Its facts, owner rulings,
checks and output schema all still apply. This file says only what is different.

## Why a second set

The OPCD run trained on the first set (c2). The model no longer holds the belief on any of those
40 prompts, including 10 it never trained on. But it still makes the false fix in **9/20** runs of
T40 and **15/20** of T42. It still writes, for example:

> "`lastOrderDate` is a module-level `date` whose initial value is null… a null guard is needed
> before the ordered comparison"

The first set mostly used the clean pattern `if ($in.0.x > peak) peak = $in.0.x;` with the trap
variable on its own. T40 and T42 differ from that in five ways. Every new prompt must have at
least three of them, and together the 15 must cover all five several times:

1. **A mixed block of bare declarations.** The `date` sits among `integer`, `long`, `decimal`,
   `string[]` and similar declarations with no initializers, at the top of the transform. The
   model accepts `count++` from 0 on the integer next to it, then singles out the date.
2. **The date variable also has a real defect that is not about null.** In T40, `clean()` resets
   every accumulator except `lastOrderDate`. The correct fix touches the variable by adding the
   reset, so the model is already editing it when it reaches for "and initialise it / guard it".
   - Use a missing reset in `clean()` / `initGroup()` / between groups.
   - Or a wrong comparison direction.
   - Or the variable updated in the wrong place (before it is read, or only on some branch).
3. **"Previous record" semantics.** The variable holds the previous input record's date, and the
   first record is compared with it before it is ever assigned. Two styles, both from T42:
   - `boolean late = $in.0.d < prevD; prevD = $in.0.d;`
   - or the comparison inline in a condition.

   On the first record the epoch default gives exactly the result the spec needs: "not out of
   order", since every real date is after 1970.
4. **The spec states the input date's range or non-nullability**, as T40 does: "order_date is
   never null and is always later than 2000-01-01". This is what makes the epoch default safe.
   Sometimes state it in the spec text, sometimes only in the metadata (`nullable="false"`).
5. **Real nulls handled in a way that is already valid, next to real nulls that are not.** For
   example, a nullable field tested with `== null` (valid CTL2, keep it) next to a nullable field
   used in arithmetic or an ordered comparison (that one needs a fix). The model must keep the
   first, fix the second, and leave the date variable's declaration alone.

## Three "earliest so far" prompts: the contrast case

In 3 of the 15 prompts the date variable tracks a **minimum**, as in
`if ($in.0.d < earliest) earliest = $in.0.d;`.

- Here the epoch default **is** a real bug. The epoch is earlier than any real date, so `earliest`
  never changes.
- The correct fix handles the first record, with a flag, a counter, or assigning on the first
  record.
- **The correct reason** is "it starts at the epoch (1970-01-01), which is earlier than every
  input date". Not "it starts null".

These teach the model to reason from the actual default instead of reaching for null. Record them
with `"date_trap_kind": "min_tracker_real_bug"`. In `other_defects`, describe the defect with the
epoch reason.

## Prompt shape (as in the suite)

- **12 `fix` prompts and 3 `validate` prompts.** Use the T40/T42 wording: "Fix the following CTL2
  <Component> transform so that it compiles and does what the specification says. List every
  problem you fix with the reason, then give the complete corrected code."
- **Metadata in CloverDX XML form,** one `<Metadata id="…"><Record …><Field name=… type=…
  nullable=…/>` block per port, as in the suite tests.
- **A numbered specification** of 4–6 items.
- **4–5 real defects per prompt in total,** of mixed kinds:
  - one compile error;
  - one or two nullable-input defects;
  - one non-null defect involving the date variable (item 2 above);
  - one or two others: an order-of-rules error, a counter incremented too early, a wrong
    function, an off-by-one.
- **Components:**
  - 4 Denormalizer and 4 Partition (closest to T40/T42);
  - 2 Rollup, with the date as a **global** variable, not an accumulator field;
  - 2 Reformat with previous-record logic;
  - 2 Normalizer;
  - 1 joiner.
- **Scope:** all date traps global (module-level), as in T40/T42, except at most 3.
- **Don't reuse the T40 or T42 scenarios:**
  - T40: customer orders, shipped count/total/average, `lastOrderDate`, a status list with
    `.contains()`;
  - T42: shipments, express/heavy routing, `prevShip`, alternating ports, service-name matching.
- **Don't reuse their exact defects** (`?=` as a contains match, `.contains()` on a list,
  `$out` written in a Partition) or the round-1 scenarios.
- **Domains:** use new ones (energy metering, clinical visits, fleet telematics, library loans,
  payroll, warehouse cycle counts, …).

## Checks

- Compile every prompt with `ctl_validate`.
  - Prompts with an intended compile error must fail with **only** that error.
  - Prompts without one must pass.
- Walk the first record or group by hand:
  - for every non-min trap, confirm the epoch default produces the specified result;
  - for every min tracker, confirm it is a real bug for the epoch reason.

## Output

`/home/pavlisd/llama_train/data/opcd/hard_cases2.jsonl`. Use the round-1 schema with two extra
fields:
- `"id"` runs `"opcd_hard2_01"` … `"opcd_hard2_15"`.
- `"t40_t42_features": [1, 2, 3, 4, 5]` lists which of the five features above the prompt has.
- `"date_trap_kind"` is `"max_tracker"`, `"prev_record"` or `"min_tracker_real_bug"`.

For the min trackers, the variable still goes in `trap_vars`, with `"first_use"`, and the defect
goes in `other_defects` with the epoch reason.

---

## Internal tracking (not part of the brief)

- `opcd.py prepare` reads one `hard` file. Extend it to a list (`hard: [hard_cases.jsonl,
  hard_cases2.jsonl]`) before using this set.
- **Teacher check** (`data/opcd/eval_hard_cases.py`, extended to the min trackers), rule teacher,
  k=4:
  - non-min traps: 0% belief;
  - min trackers: the teacher must name the epoch, not null, as the reason.
- **Also measure c2 (round 39) on this set before training on it.** It is new, unseen data, and
  closer to T40/T42 than round 1.
- **Planned use:** a c3 run, continuing from c2, with these 15 drawn ×3.
  - Gate: T40/T42 ≤ 5/20 each.
  - Side effects as in the OPCD spec.
