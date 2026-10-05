# Fix-to-spec examples: correct fixes, correctly explained

**Write 120–150 new answer-only "fix to spec" records.** Each one gives broken CTL2 code with a
specification; the answer lists every problem with the *exact* reason, then the complete
corrected code. The goal is not harder bugs. The goal is to teach the model to **explain fixes
truthfully** and to **stop "fixing" correct code** on the strength of false beliefs. Everything
above "Internal tracking" is the brief.

You are working in the `ctl_lora_training` repository:

| path | what it is |
|---|---|
| `sft_training_data/CTL_LoRAT_fix_to_spec.json` | **house style for this task**: prompt wording, answer layout |
| `references/CTL2_Reference_for_LLM_compact.md` | the language reference |
| `references/ctl-function-library.json` | every built-in function and overload |
| `sft_training_data/componet_contracts.md` | component contracts: lifecycle functions, what may be read or written where |

## Why

The model under training usually produces the **right corrected code** for a fix task. It loses
points because its **explanation of a fix is false**, or because it "fixes" correct code. Here is
what it got wrong on our five fix benchmarks, 20 attempts each. Both the current and the previous
model fail the same way, so this is entrenched:

| failure | how often | the truth |
|---|---|---|
| Claims an uninitialised `date` or list variable "starts null" and adds guards or initialisers | **20/20** on two benchmarks | A declared `date` starts at the epoch (1970-01-01). A declared list starts empty, and a map starts empty. Only `variant`, `byte`, `cbyte` start null. |
| Replaces `list.contains(x)` with `contains(list, x)` | 13/20 | `contains(string, string)` is a **string** function. For lists use `in(x, list)` or `containsValue(list, x)`. `list.contains()` does not compile. |
| Says `?=` is a whole-string match | 10/20 | `?=` is a regex **contains** match (`"EXPRESS_SAVER" ?= "EXPRESS"` is true). `~=` is the whole-string regex match. `==` is plain equality. |
| Explains `.equals()` as a "null-receiver runtime crash", or recommends `equals(a, b)` | 15/20 | `.equals()` does not exist in CTL2, so the original **does not compile**. There is no `equals()` function. Use `==`, which is null-safe. |
| Says reading a field of the unmatched slave record in a left outer join throws, or that "the whole slave record is null" | frequent | On an unmatched row the slave record **exists with null fields**. Reading `$in.1.x` returns null and does not throw. Using that null in arithmetic, or in an ordered comparison, can throw. |
| Says `getMonth(null)` throws | frequent | It **returns null**. The failure in such code comes from what is done with the null, e.g. `getMonth(d) - 1`. |
| Gets the arithmetic of integer division wrong (`(100 - 10) / 100` "is 9") | 2/20 | Integer division truncates: 90 / 100 = **0**. Explanations must state the actual wrong value. |
| Says a date pattern with `mm` (minutes) "fails to parse" valid dates | 2/20 | It **parses**, and silently puts the month digits into the minutes field. That makes the result wrong, not an error. Months are `MM`. |
| Describes `dateDiff` with swapped arguments as "never true" or "admits dates in the past" | 2/20 | The signature is `dateDiff(later, earlier, unit)`. Swapping the arguments flips the sign, so a `<= 2` test becomes true for every date in the future. |
| Says an unassigned Rollup accumulator field "keeps the previous group's value" | occasional | It is **null** at the start of every group unless `initGroup()` assigns it. |
| Calls valid code a problem: two-argument `substring(s, from)`, `push(list, x)`, `return ALL` with one output port, `~=` | frequent extra "fixes" | All of these are valid. A fix answer must not list them as problems or change them. |

## The owner rulings (binding)

These take precedence over any older text in the corpus:

1. `return STOP;` aborts the component. DataGenerator `generate()` must return `OK` or `ALL`.
2. Denormalizer `transform()` may read `$in.0`, which holds the **last** record of the group.
   Values needed from the first record must be saved in `append()`.
3. A never-assigned **non-nullable** output field is emitted as its type's zero value
   (`""`, `0`, `0.0`), never null. A nullable one is null.
4. `*OnError` callbacks are valid. They should log (`printLog(error, …)`). Returning `SKIP`
   without logging is tolerated; returning `OK` without logging is a defect.
5. Rollup `transform()` and `updateTransform()` may read `$in.0`, for example the group key.
6. Writing `$out.0` in a Denormalizer `append()` has no effect on the emitted record. It is not a
   runtime error.

## What to write

Records in the house style of `CTL_LoRAT_fix_to_spec.json`:
- **User prompt:** "Fix the following CTL2 <COMPONENT> transform so that it compiles and does
  what the specification says. List every problem you fix with the reason, then give the
  complete corrected code." It continues with a numbered specification, the port and
  accumulator metadata, and the broken code.
- **Answer:** a numbered list of problems, each with **what was wrong**, **the exact mechanism**
  and **what the fix is**, then the complete corrected code in one ` ```ctl ` block.
- **Answer only.** Do **not** add `reasoning_content` or `orig_reasoning_content`.

Each record plants **2–4 real defects** and **at least one trap**: correct code that looks
suspicious and must be left alone. The answer must leave every trap unchanged and must not
mention it as a problem. A trap stays silent, not explained: the explanation's job is the real
defects.

Cover these themes. The count is the number of records where the theme is a planted defect or
trap. A record can cover several themes.

| theme | records | as a defect | as a trap (leave unchanged) |
|---|---|---|---|
| declaration defaults | ≥ 30 | — | a bare `date d;` compared or used before assignment, `string[] l;` appended to, `map[…] m;` used, `integer n;` incremented |
| list / map membership | ≥ 20 | `list.contains(x)`, `contains(list, x)`, Java-style `.indexOf`, `x in [..]` (infix) | `in(x, list)`, `containsValue(list, x)`, `x.in(list)` |
| `?=` / `~=` / `==` | ≥ 20 | `?=` where exact match is specified (state the substring case it wrongly admits), `~=` used as contains | `~=` correctly used for a whole-value pattern |
| Java/Python idioms that do not exist | ≥ 15 | `.equals()`, `.length()` on a list where `length(list)` is needed, `.size()`, `str.isEmpty()`, `equals(a,b)` | — |
| null semantics | ≥ 20 | arithmetic or an ordered comparison on a nullable value without a guard; `getMonth(d) - 1` with `d` nullable | an unguarded `getMonth(d)` assignment to a nullable field; `==` with a null operand; reading an unmatched slave field |
| exact wrong values | ≥ 15 | integer division, `mm` against `MM`, `dateDiff` argument order, `round` against truncation | — |
| over-fixing bait | in every record | — | two-argument `substring`, `push`, `return ALL` with one output, `~=`, `nvl` with mixed numeric types, `isnull` |

Spread the records over components: Reformat/Map, Filter, Partition, Normalizer, Denormalizer,
Rollup, Join (inner and left outer), DataGenerator. Use about 10–25 records per component, and
vary the domains.

**Explanation standard.** Each listed problem names:
- the line or construct;
- why it is wrong: a compile error, a certain runtime failure, or a wrong value for a stated
  requirement, with the concrete wrong value or the input that triggers it;
- the fix.

No hedging and no invented mechanisms. If the original compiles and runs but gives a wrong
value, say so; don't call it a crash. If it does not compile, say that; don't call it a runtime
failure.

## What not to do

- **Don't copy the benchmark scenarios.** Don't reuse these combinations, which the evaluation
  uses:
  - a Reformat that parses `dd.mm.yyyy` dates and computes a discounted total;
  - a Denormalizer that collects order statuses into a list;
  - a Rollup counting warehouse backorders with an infix `in`;
  - a Partition routing shipments by express service code with a `prevShip` date;
  - a left outer Join that derives a customer tier and an e-mail domain.

  Use the same *concepts* in other components and domains.
- Don't plant defects that are only typos or Java/Python syntax slips. The model already fixes
  those.
- Don't make claims you haven't verified. Check every function and overload against
  `ctl-function-library.json`.

## Checks before you write a record

- [ ] The corrected code **compiles**. Use the CloverDX CTL2 compiler if you have it; otherwise
      check every call against the function library and every callback against
      `componet_contracts.md`. Record which was used.
- [ ] Every planted defect is **really** a defect, and every claimed compile error really fails
      to compile.
- [ ] Every trap is correct CTL2, is unchanged in the corrected code, and is not mentioned as a
      problem.
- [ ] No statement in the answer contradicts the reference, the library, the rulings or the
      table above.
- [ ] The prompt does not duplicate an existing corpus prompt or a benchmark scenario.

## Output

Write **`sft_training_data/CTL_LoRAT_fix_to_spec_explained.json`**, in the same record shape as
`CTL_LoRAT_fix_to_spec.json` (`id`, `component`, `tags`, `messages`, `reviewed_date`). Use ids
`fixexpl_NNN`. `tags` lists the themes covered, e.g.
`["fix_code","declaration_defaults","membership","trap:substring"]`.

Also write **`sft_training_data/CTL_LoRAT_fix_to_spec_explained_log.md`**. It holds the count per
theme and per component, the compile method per record, and any construct whose behaviour you
had to verify with the compiler, along with the result.

Commit both files and push.

---

## Internal tracking

Not part of the brief.

- **Source of the failure table:** suite v4 fix tests T39–T43 × n=20, thinking on, judged against
  eval_snapshot_20261003, for rb1005 (`results_qwen38_rb1005_on_…`, 100 runs) and base
  (re-judged). The traps T40.FP1 and T42.FP6 fire 20/20 in both models even after the 36
  `CTL_LoRA_belief_defaults.json` records, so the defaults belief needs much more coverage, in
  the fix context specifically.
- **Plan** (memory: rb1005-own-trace-mixed-sft):
  1. These records go into the next retrain (rb1006) as answer-only data.
  2. Their prompts and references then serve as the pool for distilling fix traces from rb1005
     (k=8, judge + compile + belief scan) for the thinking share.
- **Success measures**, rb1006 against rb1005, fix with thinking on, n=20:
  - T40.FP1 and T42.FP6 fire in ≤ 25% of runs;
  - WRONG on T40.B1, T42.B3 and T43.B1 falls by half;
  - fix ≥ 0.72 with no generate or validate regression.
