# Rollup lifecycle validate set, round 2: natural explanations, the PASS format, indented code

**Revise the two files delivered in `ctl_lora_training` `b6fe5f8`:**
- `CTL_LoRA_rollup_lifecycle_validate_sft.json` (50);
- `CTL_LoRA_DPO_rollup_lifecycle_validate.jsonl` (25).

Keep the counts, task mix, coverage, facts and DPO categories. `spec/rollup_lifecycle_validate_brief.md` still applies;
this brief says what to change.

## What is good

**Facts and coverage:**
- every absent function is reported by name, and no present function is reported missing;
- every absence is explained as an initialization failure, never as "the group emits nothing";
- no answer says a nullable accumulator field starts at zero or at a metadata default;
- the coverage tables match the brief.

**Independent re-run:** all 94 graphs in `logs/rollup_lifecycle_runtime/graphs/` were re-run on our server, and every
status matches the log:
- 44 fail with "Required function(s) … are missing!";
- 14 fail on the intended second defect;
- 36 finish, including all 10 corrected fix answers.

**Other checks:** the hint check passes, and the overlap with the excluded suite tests is at most 0.056.

Keep all of that.

## 1. Rewrite the templated explanations

**The problem: the explanations are a few templates with the scenario name inserted.** Masked, 12 sentences of 12 or more
words each appear in more than 3 records. Mask this way:
- the scenario and record names (e.g. `FerryPassengerParity`, "kiln thermal excursions") → `NAME`;
- backticked code → `` `X` ``;
- snake_case field names → `FIELD`.

| records | masked sentence |
|---|---|
| 13 | SUGGESTIONS: - Add `X` with the behavior required by the NAME specification. |
| 12 | SUGGESTIONS: - Add `X` with the group behavior described in the request. |
| 10 | The diagnostic includes an initialization diagnostic listing `X` among the required missing functions, so this transform never starts processing source rows. |
| 9 | Rollup fails during component initialization with an initialization diagnostic listing `X` among the required missing functions; |
| 8 | This is an initialization error, reported as an initialization diagnostic listing `X` among the required missing functions, before the first group can be processed. |
| 7 | [ERROR] `X` is absent from the NAME Rollup, leaving the per-group initialization entry point undefined; |
| 4 | the supplied domain-specific processing bodies do not provide this definition, and the NAME component consequently fails at initialization before processing records. |
| 4 | [ERROR] `X` is absent from the NAME Rollup, leaving the per-record output entry point undefined; |
| 4 | [ERROR] `X` is absent from the NAME Rollup, leaving the group-completion decision entry point undefined; |
| 4 | [ERROR] The required `X` function is absent from this NAME transform. |
| 4 | [ERROR] Rollup cannot initialize because `X` is not defined with its required lifecycle name. |
| 4 | [ERROR] No callable `X` lifecycle definition is provided for accumulator NAME. |

**Affected (28 records: 21 SFT, 7 DPO):**
- SFT 001, 002, 003, 005, 006, 007, 009, 010, 012, 018–029;
- DPO lines 1, 2, 3, 4, 10, 11, 12;
- the DPO rejected answers built from them.

The diversity log reports PASS only because each copy carries a different name. Training on these would teach a stock
formula in stilted language ("leaving the group-completion decision entry point undefined", "the supplied
domain-specific processing bodies do not provide this definition").

**How to rewrite them:**
- **Write each finding as a reviewer would**, in plain words, about this code. Name the missing function and what the
  server does:
  > `finishGroup()` is not defined. A Rollup needs all five lifecycle functions, so the component fails at startup with
  > "Required function(s) finishGroup() are missing!" and no group is processed.

  Vary the wording across records. The consequence can be told from the specification ("so none of the gallery counts is
  ever written") rather than from a generic diagnostic.
- **Do not pad sentences with the scenario name** to make them unique. Mention the domain only where it carries meaning
  (which output field, which business count).
- **SUGGESTIONS:** give the actual function, not "Add X with the behavior required by the specification". Write its
  signature and a body that fits the task, e.g. `function boolean finishGroup(GalleryState a) { return true; }`.
- **Measure with the masking above:**
  - no masked sentence of 12 or more words in more than 3 records;
  - no masked `[ERROR]` line opening (its first 8 words) in more than 4 records.

  Report both in the log, before and after.

## 2. The PASS format

The 8 clean PASS answers (SFT 013, 014, 015, 030, 031, 046, 047, 048) are `ISSUES: [INFO] No issues found.` The validate
format our suite and corpus use says:

```
ISSUES: none
VERDICT: PASS
```

Use exactly that.
- Where a PASS case has a tempting non-bug worth naming (`updateGroup` returning false, the plain count divisor), an
  `[INFO]` line explaining why it is correct is fine.
- An `[INFO]` line saying there are no issues is not.

## 3. Code and prompt form

- **Indentation:** SFT 003, 004, 007, 009, 010, 011, 012, 014, 015 and 016 have no indentation inside function bodies.
  Indent them like the rest (4 spaces). Keep the line structure, so the runtime results and line numbers in findings stay
  valid; update any line numbers an answer cites.
- **Prompt opening:** 26 prompts (17 SFT, 9 DPO) open with "<Name> operations: Validate this Rollup transform." Vary
  the opening: no first-five-word pattern, names masked, in more than 5 prompts.
- **009 and 045:** the code is identical after masking (a validate task and a fix task). Change one of them to a
  different accumulation shape.

## Validation

For changed records only:
- the compiler, and a graph run with the same expected outcome as before (code changes are indentation and the 009/045
  rewrite only);
- the hint check, and the overlap check for 009/045;
- the masked-sentence measure from section 1, before and after.

Update the validation log with:
- the file hashes;
- the masked measure;
- the opening-pattern count;
- a `round2` list of the changed ids.

Commit the validation log and `logs/rollup_lifecycle_runtime/` with the data. The round-1 commit carried only the two data
files.
