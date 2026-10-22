# CTL2 syntax pitfalls: a compiler-verified contrast set

**Write one new set in `ctl_lora_training/sft_training_data/`,** in the format and to the validation standard of the
Rollup accumulator set (round 2):

| file | records |
|---|---|
| `CTL_LoRA_syntax_pitfalls_sft.json` | 80 SFT |
| `CTL_LoRA_DPO_syntax_pitfalls.jsonl` | 40 DPO pairs |

## Why

We ran every stored generate answer of 9 trained models on the CloverDX server (suite v5, 11 tests × n10 × 2 modes).
- **706 answers do not compile.** The judge gave many of them 0.6–0.9.
- **89% of those fall into a handful of causes**, each a wrong habit carried over from Java, JavaScript or a regex
  dialect. Each was confirmed with `ctl_validate` on 2026-10-22.
- **Feedback does not fix them reliably.** Given the compiler message, the best model repairs most compile failures with
  thinking on, but few with thinking off. One message is actively misleading: a reserved name `month` reports "Syntax
  error on token 'integer'".

The model should not write these in the first place.

## The rules

All compiler-verified (`ctl_validate`, 2026-10-22); record your own verification runs in the log.

| # | wrong habit | what the compiler says | correct CTL2 |
|---|---|---|---|
| R1 | a variable named after a time unit: `integer month = getMonth(d, "UTC");` (also `year`, `week`, `day`, `hour`, `minute`, `second`, `millisec`) | `Syntax error on token 'integer'` (misleading) | any other name: `integer mon`, `integer orderYear`. These words are reserved date-unit keywords (used in `dateAdd(d, 1, month)`); `quarter` is not reserved. |
| R2 | a return constant in a ternary: `return hasCurrent ? ALL : 1;`, `? SKIP : ALL`, `? OK : SKIP` | `Syntax error on token '?'` | `if (hasCurrent) return ALL; return 1;` A ternary of plain integers (`b ? 0 : 1`) compiles. |
| R3 | regex negation `x !~ "re"` | `Syntax error on token '!'` | `!(x ~= "re")`; there is no `!~` operator |
| R4 | `!x ~= "re"` | `Operator '!' is not defined for type 'string'` | `!(x ~= "re")`, or `!matches(x, "re")` |
| R5 | a backslash regex escape in a double-quoted string: `"[0-9]+(\.[0-9]+)?"`, `"\d+"` | `Invalid escape sequence: \.` | double the backslash, `"[0-9]+(\\.[0-9]+)?"`, or use a single-quoted string, which takes the backslash as written: `'[0-9]+(\.[0-9]+)?'` |
| R6 | `str2date(s, fmt, true, "UTC")`, `isDate(s, fmt, true, "UTC")` | `Function str2date() is not applicable for the arguments (string, string, boolean, string)` | `(s, fmt)`, `(s, fmt, strict)`, `(s, fmt, locale)`, `(s, fmt, locale, tz)`, `(s, fmt, locale, tz, strict)`. The strict flag comes last, after locale and time zone. |
| R7 | invented functions: `raise(ex)`, `raise error;`, `sendPort(0)`, `getDictionaryValue(...)`, `date2year(d)` | `Function 'raise' is not declared` | `raiseError("message")`; `getYear(d, tz)`; port routing by the component's return value; a dictionary entry as `dictionary.<entryName>` with exactly the entry name the graph declares (no nesting such as `dictionary.runConfig.auditEnabled`) |
| R8 | a field that is not in the given metadata (e.g. an accumulator field the code needs but the metadata does not have) | `Field 'receipt_id' does not exist in record 'ReceiptAcc'` | use only declared fields. Keep the extra state in a declared module-level variable, or derive it from declared fields. Never add fields to metadata the task gives. |

Also covered in the corpus, so only a few examples each here:
- DataIntersection writes only `$out.0`, never `$out.1`/`$out.2` (`ctl2-basics.md` §8.9);
- a type name as a variable (`string date`).

## Content

### SFT (80)

| task | count | shape |
|---|---|---|
| generate | ~40 | Ordinary tasks where the natural solution needs the construct, e.g. a month bucket, a "reject unless it matches" check, a decimal-with-optional-fraction regex, a strict date parse in UTC, a conditional return of `ALL`/`SKIP`, a fatal error on bad input, state that the accumulator metadata does not hold. The answer uses the correct form without comment. |
| fix-to-spec | ~25 | Code with 1–3 of the wrong habits (and sometimes one unrelated defect). "Fix … so that it compiles and does what the specification says. List every problem you fix with the reason, then give the complete corrected code." Each fix states the compiler's message and the rule in one sentence. |
| validate | ~15 | `ISSUES:` / `VERDICT:`. About a third are PASS cases using the correct but unusual forms (`!(x ~= "re")`, single-quoted regex, `b ? 0 : 1`, a variable named `mon`), so the model does not flag them. |

**Coverage:**
- **Per rule:** each of R1–R8 appears in at least 10 SFT records, spread over generate, fix and validate.
- **Components:** Reformat, Rollup, Normalizer, Denormalizer, Partition, DataGenerator, ExtMergeJoin.
- **Code length:** about a third of the code is 60+ lines, where the pitfall sits inside realistic business logic.
- **Thinking:** answer-only, no thinking traces. The target is first-attempt correctness without thinking.

### DPO (40)

Each rejected answer is the chosen answer with **one** pitfall reintroduced: 5 pairs per rule (R1–R8). The rejected code
must fail `ctl_validate` with the expected message (record it); the chosen code must pass and run.

## Form

- **No hints in the user turn.** State the requirement and the metadata. Never write "do not use `!~`" or "avoid
  reserved words".
- **Realistic metadata,** varied formats; domain field names. Fields and variables that would naturally be called
  month, year, day, week, hour and so on are welcome: that is the trap. A **metadata field** named `month` or `year` is
  fine (`$in.0.month`, `$out.0.year` compile); only declared variable names are restricted.
- **Varied wording:** no explanation sentence of 12 or more words in more than 3 answers. No opening phrase (first five
  words) in more than 5 prompts.

## No overlap

**Do not reuse these scenarios:**
- suite v5 T44–T73 (the source of the error statistics);
- suite v4 T1–T43;
- `llama_train/data/opcd/*.jsonl`.

**Check:** 5-gram Jaccard below 0.30, with field names masked.

## Validation

- **Compiler:** every chosen code block passes `ctl_validate`. Every rejected DPO block and every fix-task input fails
  with the expected message; log the message.
- **Runtime:** every generate and fix answer runs in a real graph in sandbox `MiscExamples`, folder `syntax_pitfalls/`
  (never `DPOForge`), with 8–15 input records covering every branch; check the output rows.
- **Claims:** every rule stated in an explanation matches the table above or a logged probe.
- **Independent review:** a reviewer re-derives 10 answers from the user turn alone.

## Deliverables

In `ctl_lora_training/sft_training_data/`:
- the two data files above;
- `logs/CTL_LoRA_syntax_pitfalls_validation.json`, with:
  - counts per rule and per task;
  - compiler and runtime results with run ids;
  - the hint check, diversity, the overlap check and the review;
- graphs and fixtures under `logs/syntax_pitfalls_runtime/`.

The `CTL_LoRA_DPO_` prefix is required: the rebuild script reads DPO pairs only from `CTL_LoRA_DPO_*.jsonl`.

---

## Internal tracking (not part of the brief)

- **Evidence:** findings §3.29 (cause table, 706 `init_error` answers) and the compile-and-retry experiment.
  - DataIntersection `$out.1` (213) is mostly in the rebuilds, and the existing DataIntersection set plus OPCD fixes it,
    so it is not repeated here.
- **Use:** the next rebuild; the prompts can also serve as an OPCD set with a compiler-filtered teacher.
- **Gates:**
  - an `init_error` count by cause on the suite-v5 gap tests (`data/suite_v5/exec_score.py`), target at least half
    fewer;
  - thinking-off pass rate;
  - thinking-off validate WRONG, which must not rise.
