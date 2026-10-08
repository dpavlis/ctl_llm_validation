# Contrast records: CTL2 declaration defaults against Java, C#, JavaScript and Python

**Write 50–60 new answer-only records that set CTL2's declaration defaults explicitly against
how Java, C#, JavaScript and Python behave.** The model under training knows the CTL2 rule. When
the rule is stated in its system prompt, it applies it perfectly. Without it, its reasoning falls
back to Java/C# field semantics: "a declared `date` / list / string starts null". These records
name that habit at the point where it fires and replace it with the CTL2 fact. Everything above
"Internal tracking" is the brief.

You are working in the `ctl_lora_training` repository, as for the earlier fix sets. House style,
record shape and checks are as in `spec/fix_examples_brief.md`. The owner rulings there are binding.

## The facts (verify anything you add beyond these)

| declaration | Java | C# | JavaScript | Python | **CTL2** |
|---|---|---|---|---|---|
| object-type **field** (`Date d;`, `String s;`, `List<…> l;`) | `null` | `null` | — | — | **epoch / `""` / empty list** |
| numeric / boolean **field** | `0` / `false` | `0` / `false` | — | — | **`0` / `false`** (the same) |
| **local** variable used before assignment | compile error (definite assignment) | compile error (CS0165) | `let x;` is `undefined` | no declarations; `NameError` / `UnboundLocalError` | **type default** (local and global alike) |
| string built by `s = s + "a"` from an unassigned start | `"nulla"` (field) | `"a"` (`null + "a"`) | `"undefineda"` | — | **`"a"`** |
| list / map used before assignment | `NullPointerException` (field) | `NullReferenceException` (field) | `TypeError` on `undefined` | — | **works:** it is empty |

CTL2 declaration defaults: `integer`/`long`/`decimal` 0, `number` 0.0, `boolean` false,
`string` `""`, `date` the epoch (1970-01-01 00:00:00), lists and maps empty. **Only `variant`,
`byte` and `cbyte` start null.**

**What is null in CTL2, just as in the other languages.** Teach these as "the same", so the
records don't overshoot into "nothing is null":
- nullable input fields;
- a missing map key read with `m[k]` (like Java `map.get(k)`);
- fields of an unmatched slave record in a left outer join;
- Rollup accumulator fields: they reset from metadata, so a nullable field without a default is
  null and a non-nullable one is its type's zero value;
- a nullable output field never assigned;
- function results that can be null;
- a declared `variant`, `byte` or `cbyte`.

## What to write

1. **Explanations (about 15):** a user asks how a CTL2 declaration behaves, or why code that would
   fail in Java works in CTL2. Examples:
   - "In Java I always initialise my `Date lastSeen` field to avoid an NPE. Do I need that in a
     CTL2 Denormalizer?"
   - "Why doesn't `string[] tags; append(tags, x);` throw in CTL2?"

   The answer states the CTL2 default, names the Java/C# behaviour it differs from in one
   sentence, and gives a short CTL2 example with the concrete first-use value.
2. **Ports (about 15):** port a Java, C#, JavaScript or Python snippet into a CTL2 transform. The
   source must contain declaration idioms whose meaning changes. The answer must get the
   difference right in both directions:
   - Java's `if (lastDate == null)` first-record test, or Python's `last = None` … `if last is
     None:`, must **not** become a bare `date lastDate;` plus `isnull(lastDate)`. That is never
     true in CTL2. Use a `boolean` flag, a counter, or an explicit `date lastDate = null;` when
     null is the intended sentinel.
   - Java's defensive `List<String> tags = new ArrayList<>();` becomes a plain `string[] tags;`
     (or `= []`; both are fine), with a one-line note that it is already empty.
   - A Java `String` field concatenated before assignment (`"null…"`) has no CTL2 equivalent: the
     CTL2 port starts from `""`.
3. **Fix answers with a contrast line (about 15):** in the house style of
   `CTL_LoRA_fix_defaults_explained.json`, with 2–3 real defects. The "Left unchanged" line for
   the tempting declaration adds the contrast, e.g. "Left unchanged: `date prevScan;` starts at
   the epoch, so the first comparison is safe. Unlike a Java `Date` field, it is never null."
   Vary the wording; don't repeat a fixed phrase.
4. **Reviews (about 10):** validate-style answers (`ISSUES:` … `VERDICT:`). A reviewer with Java
   habits would flag a bare declaration. The answer doesn't, and reports the real issues
   instead. At least 3 of these contain a **real** null issue (nullable input, missing map key,
   declared `variant`) that must be reported, so the contrast cuts both ways.

Spread over components (Reformat, Filter, Partition, Normalizer, Denormalizer, Rollup, Join,
DataGenerator) and over types: about 40% `date`, 30% list/map, 30% `string`/numeric/`boolean`.

## What not to do

- Don't copy the two benchmark scenarios:
  - a Denormalizer with `integer shippedCount; decimal shippedTotal; date lastOrderDate;` and a
    `.contains()` status check;
  - a Partition routing shipments by service code with `integer turn; date prevShip;`.

  Also avoid the other scenarios listed in `spec/fix_examples_brief.md`.
- Don't claim language behaviour you haven't checked. Java/C# locals don't default to anything;
  they fail to compile. Only fields default.
- Don't reuse code from `CTL_LoRA_fix_defaults_explained.json` or
  `CTL_LoRA_fix_to_spec_explained.json`.
- **Answer only:** no `reasoning_content` or `orig_reasoning_content`.

## Checks

- [ ] Every CTL2 code block compiles: use the CloverDX compiler, as for the earlier sets.
- [ ] Each first-use value claimed for a CTL2 declaration was traced by hand, and is written in
      the log.
- [ ] Each Java/C#/JS/Python claim matches the table above, or was checked separately (note how
      in the log).
- [ ] The "same as Java" null cases are stated correctly (accumulator per the metadata-reset rule).
- [ ] Dedup: no broken- or source-code pair above 0.85 similarity within the set or against the
      two fix sets (use the check script in `spec/fix_examples_dedup_brief.md`). No repeated
      contrast sentence.

## Output

- **`sft_training_data/CTL_LoRA_declaration_defaults_contrast.json`**:
  - ids `declcontrast_001`…;
  - `tags` include the record kind (`explain` / `port` / `fix_code` / `validate`), the source
    language (`lang:java` / `lang:csharp` / `lang:js` / `lang:python`), the CTL2 type
    (`defaults:<type>`) and `realnull:<kind>` where a real null is involved.
- **`sft_training_data/logs/CTL_LoRA_declaration_defaults_contrast_log.md`**: counts per kind,
  language, component and type; the compile method per record; the traced first-use values.

Commit and push.

---

## Internal tracking

Not part of the brief.

- **Evidence, 2026-10-08:**
  - With the rule in the fix system prompt (`configs/eval_rb1006_rule_on.yaml`), rb1006 makes the
    false fix in 0/20 runs on T40 and on T42. Without it, 20/20.
  - Answer-only records and SFT thinking traces did not move the belief (rb1006–rb1008). Neither
    did the dpodef1 DPO: held-out 22%→21%, its own training prompts 71%→65%.
  - Memory: dpodef1-thinking-dpo-results.
- **Role:** these records strengthen the knowledge and help generate/validate answers. The main
  lever for the reasoning is context distillation (run dpodef2): sample with the rule in the
  prompt, train without it. Expect these records to help mostly when paired with that.
