# Brief: date-unit keywords as variable names — a wrong compiler message (CTL2 parser / compiler)

**For the agent working on the CTL2 parser / compiler.** Evidence in `spec/ctl2_training_findings.md` §3.29 (the
compile causes) and §3.31 (the agentic harness). Verification tool: `ctl_validate` on the CloverDX server (MCP,
localhost:8083).

## The problem

CTL2 reserves the date-unit keywords `millisec`, `second`, `minute`, `hour`, `day`, `week`, `month`, `year` (the unit
arguments of `dateAdd`, `dateDiff`, `trunc`, …). Declaring a variable with one of these names is a compile error, but
the message does not say so:

```ctl
//#CTL2
function integer transform() {
    integer month = getMonth($in.0.tested_at);     // <- the error is here
    $out.0.calendar_value = month;
    return OK;
}
```

```
Syntax error on token 'integer'
Syntax error on token ')'
Syntax error on token 'month'
```

The message points at `integer` (the token before the name), then at a later `)` or `,`, and never at the cause.
Compiler-verified 2026-10-22 (findings §7, "syntax pitfalls"):
- `integer mon = …` compiles; `quarter` is not reserved;
- metadata fields named `month` are fine (`$in.0.month` works), only declared identifiers are affected;
- the same happens for function parameters (`function integer f(integer year)`) and loop variables
  (`for (integer day = 0; …)`).

## Why it matters

- **Humans and models both write `month`/`year`/`day`; both get stuck on the message.** In an agentic loop that feeds
  the compiler message back to the model (c13c, 137 execution-scored tasks, 2 retries) this was the single most common
  compile error — 25 of 36 thinking-off and 13 of 24 thinking-on compile attempts — and every task that stayed stuck on
  a compile error through all retries thinking on (7 of 137) was this one. Given the message, the model changes
  something else (`date2num` → `getMonth`, parentheses) and fails again:

  | task | attempt 1 | attempt 2 | attempt 3 |
  |---|---|---|---|
  | `syntax_r1_01` | `integer month = date2num(...)`, `integer hour = ...` | same names, other functions | same |
  | `syntax_r1_06` | `integer second = getSecond(...)` | same | same |
  | `syntax_r1_07` | `integer month = getMonth(...)` | same | same |

- The habit did not move with 130 corpus training examples (rb1012, §3.30). The compiler is the cheaper lever.

## Options

### Option 1 — stop reserving the date-unit names (preferred if the grammar allows it)

The eight words are only meaningful in a unit-argument position (`dateAdd(d, 1, month)`, `dateDiff(a, b, day)`,
`trunc(d, month)`, …). Check whether the grammar can treat them as plain identifiers everywhere else — a declaration,
an assignment target, a parameter, an expression operand — and as unit constants only where a unit is expected, or when
no variable of that name is in scope. Things to settle:
- precedence when a variable `month` is in scope and `dateAdd(d, 1, month)` is written: the variable (an integer) would
  be a type error in the unit slot, so the two uses do not actually collide; decide and document which wins;
- the public docs that list the words as reserved;
- backward compatibility: every existing transform that compiles today must still compile with the same meaning
  (`dateAdd(d, 1, month)` with no variable `month` must still mean the unit).

If this is feasible, it removes the error class entirely for users and models alike.

### Option 2 — report the problem correctly (do this at least)

When the parser fails on a declaration, parameter or assignment target whose identifier is one of the eight date-unit
keywords, report it at the identifier, naming the cause:

```
'month' is a reserved date-unit keyword (millisec, second, minute, hour, day, week, month, year) and cannot be used as
a variable or parameter name. Use another name, e.g. 'mon' or 'monthNo'.
```

Then look for the same failure shape elsewhere: any other reserved word that a user may plausibly choose as an
identifier and that today produces a "Syntax error on token <previous token>" instead of a message naming the word.
Candidates to test (not verified; some may already report well):
- the return constants `OK`, `SKIP`, `STOP`, `ALL` used as variable names, and in a ternary operand (`b ? ALL : 1` fails
  today with "Syntax error on token '?'", findings §7 — the message should say that return constants cannot be ternary
  operands, or the grammar should allow it);
- type names as identifiers (`string date = …`, `integer number = …`, `boolean boolean`);
- `in`, `function`, `return`, `null`, `true`/`false` as identifiers;
- any other keyword list the grammar carries.

For each, the message should name the offending word and say it is reserved, at the position of the word.

## How to check

- `ctl_validate` on the snippet above: option 1 → PASS; option 2 → FAIL with the new message at the identifier.
- Must still compile unchanged: `integer mon = …`, `$in.0.month`, `dateAdd(d, 1, month)`, `dateDiff(a, b, day)`,
  `trunc(d, month)`, and the whole existing CTL2 test suite of the compiler.
- The reserved-word probes above: each produces a message that names the word.
- Optional end-to-end check: rerun the stuck tasks in the harness (`agent_harness.py`, pool
  `data/agent_harness/pool1.jsonl`, compare with `results/agent_harness/c13c_pool1_rows.summary.md`); with option 2 the
  model should recover on the first retry, with option 1 the tasks should pass at the first attempt.
