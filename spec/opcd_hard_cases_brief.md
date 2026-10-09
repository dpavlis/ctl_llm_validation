# OPCD hard-case prompts: declaration-default traps next to real nulls

**Write 40 new prompts, prompts only with no answers, in which a declared but uninitialised CTL2
variable sits next to nullable input fields that really do need a guard.** They are training
prompts for on-policy context distillation (`spec/onpolicy_context_distillation_spec.md`).
- The model under training writes the answers.
- A copy of the same model, with the CTL2 declaration rule in its system prompt, grades them token
  by token.
- So the prompts need no reference answers. What matters is the **structure**.

## Why these prompts

Every method so far has fixed the easy cases but not two benchmark tests:
- **T40:** a Denormalizer with `lastOrderDate` and a statuses list;
- **T42:** a Partition with `prevShip` and a service code.

In both, a module-level `date` declared without an initializer is compared, or used in
`dateDiff`, on the first record of a group or input. **Right next to it** are real nullable input
fields that do need a guard. The model guards those correctly, then carries the same reasoning
over to the declared variable: "`lastOrderDate` is null on the first record, add a null check".
That fix is wrong.

## The facts

- **Declared CTL2 variables start at their type's default.** This holds for global and local
  variables, with no initializer:
  - `integer`/`long`/`decimal` start at 0, `number` at 0.0, `boolean` at false;
  - `string` starts at `""`, `date` at the epoch (1970-01-01 00:00:00);
  - lists and maps start empty.
- **Only `variant`, `byte` and `cbyte` start null.**
- **Null, as usual:**
  - nullable input fields;
  - `m[k]` for a missing key;
  - unmatched slave fields in a left outer join;
  - function results that can be null;
  - a variable explicitly initialised `= null`;
  - Rollup accumulator fields, which reset from metadata: nullable with no default is null,
    non-nullable is its zero value.

The owner rulings in `ctl_lora_training/spec/fix_examples_brief.md` are binding. Rollup
accumulator fields are **not** declared variables: don't use them as the trap.

## Each prompt must have

1. **A trap.** One or more declared variables (`date`, `string`, `string[]`, `map[...]`,
   `integer`/`decimal`) with no initializer. Each must be read **before** its first assignment on
   the first record or group:
   - compared;
   - passed to `dateDiff` / `dateAdd`;
   - concatenated;
   - appended to;
   - used in `.contains()` / `length()`.

   **The code must behave correctly with the type default.** The default value must be exactly
   what the specification needs at that point:
   - `if (shipDate > maxShip) maxShip = shipDate;` starts correctly from the epoch;
   - `total = total + amount` starts from 0;
   - `ids = ids + "," + id` with a separate first-item check;
   - `append(seen, code)` works on an empty list.

   Alternatively, the first record is handled by a flag or counter, so the epoch value never
   reaches the result.

   Either way, **the correct review says nothing needs fixing about the trap.** A null check or
   an initializer added "to avoid a null on the first record" is the wrong fix being targeted.
2. **Real nulls next to it.** One or more nullable input fields (or a map lookup, or an outer-join
   slave field) used without a guard, in a way that does fail or violates the specification on
   null. The correct answer guards them.
3. **Two or three other real defects of any kind:**
   - a wrong function;
   - a missing reset between groups;
   - a wrong port;
   - a spec condition inverted;
   - a compile error;
   - an off-by-one.

   These give the model real work, as in the multi-defect fix-to-spec records.

## Mix

- **28 `fix` prompts (fix to spec).** "Fix the following CTL2 <COMPONENT> transform so that it
  compiles and does what the specification says. List every problem you fix with the reason, then
  give the complete corrected code." Include:
  - the input and output metadata, with nullability stated per field;
  - a numbered specification;
  - the current transform in a ```ctl block, with a `//#CTL2` or `//#CTL2:COMPILE` header.
- **12 `validate` prompts (review).** "Review this CTL2 <COMPONENT> transform …", with the
  metadata and the code. Don't add an output-format instruction; the pipeline adds the standard
  one.
- **Components:**
  - at least 5 each of Denormalizer, Partition, Reformat/Map, and the ExtHashJoin/ExtMergeJoin
    transform;
  - at least 3 each of Rollup (with a **global** declared trap variable, not an accumulator
    field), Normalizer and DataGenerator.
- **Trap types:**
  - `date` in at least 20 prompts;
  - lists/maps in at least 8;
  - `string` in at least 6;
  - numbers in the rest;
  - 10 prompts with two trap variables.
- **Placement:** half global (module-level), half local inside a function.
- **Domains:** vary them (logistics, billing, telemetry, HR, retail…).
- **Don't reuse** the T40 scenario (Denormalizer, `lastOrderDate`, `.contains()` on statuses) or
  the T42 scenario (Partition, `prevShip`, service codes).

## Checks

- Compile the code of every prompt with the `ctl_validate` MCP tool, as for the earlier sets.
  - Code that should compile must compile.
  - Code with an intended compile error must fail **only** with that error.
- Re-read each trap. Walk the first record or group by hand and confirm that the type default
  produces the specified result.

## Output

One JSON object per line in `/home/pavlisd/llama_train/data/opcd/hard_cases.jsonl`:

```json
{"id": "opcd_hard_01", "task_type": "fix", "component": "PARTITION",
 "user": "<the full prompt text>",
 "trap_vars": [{"name": "lastSeen", "type": "date", "scope": "global", "first_use": "if (ts > lastSeen)"}],
 "real_nulls": ["delivered_at (nullable) passed to dateDiff unguarded"],
 "other_defects": ["getOutputPort() returns 2 for an unmatched region instead of 1", "..."],
 "compile_expected": "ok | error: <the intended message>",
 "compile_result": "<what ctl_validate returned>"}
```

`component` uses the corpus names: `DENORMALIZER`, `PARTITION`, `REFORMAT`, `ROLLUP`,
`NORMALIZER`, `DATA_GENERATOR`, `JOIN` (for both joiners).

---

## Internal tracking (not part of the brief)

- `opcd.py prepare` reads this file when it exists:
  - it fills `prompt_id` (`self_distill.make_prompt_id(user)`);
  - it adds the validate format instruction (`self_distill.with_validate_format`).
- **Teacher check before training:** sample the teacher on these prompts with
  `self_distill.py sample --eval-config configs/eval_rb1006_rulev2_on.yaml --k 4`, then filter.
  The belief rate must be ≤ 5% (scan + judge, as in `data/self_distill/dpodef2/build_ctx_pairs.py`).
  Drop any prompt the teacher gets wrong more than once in four.
