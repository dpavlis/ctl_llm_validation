# Audit: records that teach "declared variables start null"

**Go over the whole training corpus and correct every record that teaches that a declared,
uninitialised variable is null.** Only `variant`, `byte` and `cbyte` start null. Fix the
records in place, log every change, then commit and push. Everything above "Internal tracking" is the brief.

You are working in the `ctl_lora_training` repository.

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

Below, a "non-null-default" type is any type except `variant`, `byte` and `cbyte`.

**Out of scope: these are null, and teaching that is correct.** Don't change records for
saying so:
- nullable input fields;
- fields of an unmatched slave record in a left outer join;
- a Rollup accumulator field that `initGroup()` does not assign;
- a nullable output field that is never assigned (a non-nullable one is its zero value);
- a missing map key read with `m[k]`;
- function results that can be null;
- dictionary entries;
- a declared `variant`, `byte` or `cbyte`;
- a variable explicitly assigned `null` or a nullable value.

## Where to look

- every file in `sft_training_data/` (`*.json` and `CTL_LoRA_DPO_*.jsonl`), including
  `reasoning_content` / `orig_reasoning_content` traces, not only the final answers;
- `sft_eval_data/`;
- `references/CTL2_Reference_for_LLM_compact.md` and `sft_training_data/componet_contracts.md`.

## What counts as a wrong record

1. **Text claims.** The answer or trace says a declared non-null-default variable "starts as null",
   is "null until assigned" or "uninitialised (therefore null)". Or it says a string built with
   `s = s + x` "starts null" and needs `nvl(s, "")`, or a declared list or map needs `= []` /
   `= {}` "to avoid null". Example found by a quick scan: `training6f_170`, "Prefer `+=` when
   building strings that start as null". `conversa78_49` is another candidate.
2. **Code that relies on the false belief, in an answer presented as correct:**
   - `isnull(x)` or `x == null` on a declared non-null-default variable, used to detect "first
     record" or "not set yet". It is never true, so the code is **wrong**, not just redundant;
   - `nvl(x, …)` on a declared non-null-default variable, justified as null safety;
   - an initializer or guard with a comment like `// avoid null` / `// initialise to avoid NPE`.

   An explicit initializer **without** a null justification (`integer n = 0;`) is fine style.
   Leave it alone.
3. **Wrong verdicts.** A validate or review answer reports an uninitialised declaration as a
   null risk (ERROR or WARNING), or a fix answer lists such a guard as a fix.
4. **DPO pairs** where the **chosen** side does any of the above. A **rejected** side that holds
   the false belief is fine, even useful, as long as the chosen side is correct. Leave those.

**A record that states the rule correctly is not wrong,** for example "Unlike typed lists and
maps, a `variant` declared without an initializer starts as null." Neither is a record whose null
concerns one of the out-of-scope cases. Some records state a correct exception: "a date starts
at the epoch, so an explicit null state is needed when the epoch is a legitimate value", for
example `fixthiscc4_79`. Read such cases carefully and keep them when the reasoning holds.

## How to search

Regex alone over-matches heavily, since most "is null" text is about input fields. Use it to
build candidates, then **read every candidate**:
- **Text:** phrases near "declared", "uninitiali[sz]ed", "without an initializer", "starts",
  "defaults to", "until assigned" that are followed by "null".
- **Code:** find each declaration without an initializer and its type, then look for
  `isnull(<name>)`, `<name> == null`, `<name> != null` and `nvl(<name>` on the same name, for
  every non-null-default type. Also look for initializers carrying null-related comments.

A quick scan of answers only found about 50 text candidates over 17 files. Many of them are
correct (variant, accumulator, input fields). Code patterns and traces will add more.

## How to fix

- **Text claims:** rewrite the sentence to the true behaviour, with the actual default value. If
  the point of the passage collapses (e.g. "guard against the null start"), remove it and fix
  the surrounding text so it still reads well.
- **Code relying on `isnull(declaredVar)`:** fix the logic with a `boolean` flag, a counter, or a
  sentinel that the task supports. Then update the explanation. The corrected code must compile
  and must do what the prompt asks.
- **Redundant null guards on declared variables presented as fixes:** remove the guard if the
  record's purpose is a fix or review, and remove it from the list of fixes. Keep the rest of the
  answer.
- **Wrong verdicts:** remove the finding, or replace it with a real one if the record is meant to
  have one. Keep the ISSUES / VERDICT format and adjust the verdict if it changes.
- **DPO chosen sides:** correct them as above. If the pair no longer has a meaningful difference
  between chosen and rejected, drop the pair and log it.
- **If a record can't be repaired cleanly,** drop it and log why.
- **References:** `CTL2_Reference_for_LLM_compact.md` and `componet_contracts.md` state the rule
  correctly in their type tables. Fix only passages elsewhere in them that contradict it, if any.

Don't change anything else in a record. Keep its ids, its layout, and its tags, unless a tag names
the wrong belief.

## Checks

- [ ] Every changed code block compiles, checked with the CloverDX compiler if available.
      Otherwise check against `ctl-function-library.json` and say which was used.
- [ ] No changed text contradicts the owner rulings in `fix_examples_brief.md`.
- [ ] Re-run the candidate scan after fixing. Every remaining hit has a reason to stay
      (variant, out-of-scope case, rejected DPO side, correct exception) in the log.

## Output

- Corrected files in place.
- **`sft_training_data/logs/CTL_declaration_defaults_audit_log.md`**:
  - one row per changed or dropped record: file, id, category (1–4 above), before and after
    excerpt, compile method;
  - one row per candidate kept unchanged, with the reason;
  - counts per file.

Commit and push.

---

## Internal tracking

Not part of the brief.

- **Owner, 2026-10-06:** only variant, byte and cbyte start null, which matches the references,
  `resources/ctl2-basics.md` and memory ctl2-declaration-defaults. No reference changes needed.
- **Why now:** rb1006 still claims "uninitialised date/list starts null" in 20/20 runs of T40 and
  T42 (memory: rb1006-fix-explained-results). The corpus may be carrying the belief alongside the
  sets that refute it. The companion set is `spec/fix_defaults_brief.md`.
- **llama_train side,** not for the agent: `self_distill.py` already has the "declared variables
  start null" belief pattern (around line 1887). Re-scan the self-distilled traces in
  `data/self_distill/*` with it after the audit.
