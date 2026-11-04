# Belief correction — infix `in` and declared-variable defaults

**72 new SFT records and 32 DPO pairs that correct two false CTL2 beliefs. Answers only — no
`reasoning_content`.** Everything above the "Internal tracking" section at the end is a
self-contained brief. It assumes CTL2 knowledge (the language, the CloverDX component model,
and the `ISSUES:` / `SUGGESTIONS:` / `VERDICT:` review format) but no other context about this
project.

You are working inside the `ctl_lora_training` repository:

| path | what it is |
|---|---|
| `sft_training_data/` | the training corpus, one JSON file per set |
| `sft_training_data/CTL_SFT_example_guidelines.md` | house rules for every record; §3.2 and §4.1 matter most here |
| `sft_training_data/CTL_LoRA_validate_examples.json` | the bulk of the existing validate records, for the format |
| `sft_training_data/CTL_LoRAT_fix_to_spec.json` | fix-to-spec records, for the fix format |
| `sft_training_data/CTL_LoRA_DPO_semantic_pairs.jsonl` | DPO pairs, for the pair format |
| `references/CTL2_Reference_for_LLM_compact.md` | the language reference |
| `references/ctl-function-library.json` | every built-in function and each of its overloads |
| `references/componet_contracts.md` | which functions each component must define, and what may be written where |

## Why this exists

The model holds two false beliefs about CTL2 and states them in nearly every answer where they
come up. Both were measured on the evaluation suite with thinking on, 20 runs per test:

| belief | where it shows | how often |
|---|---|---|
| CTL2 has an infix membership operator: `x in [...]`, `x !in [...]` | a Rollup fix task seeds that line as its compile error; the model keeps it in the "corrected" code | missed or wrongly explained in 37 of 40 runs |
| a variable declared without an initializer starts as `null` | a Denormalizer fix task whose globals are correct as declared; the model "fixes" them and says they were null | 40 of 40 runs |
| (same belief) | a Partition fix task with a correct `date prevShip;` compared with `<` | 10 of 10 runs |

Neither belief comes from the corpus. Across the 11,821 phase-1 records, the 1,887 DPO pairs
and the 1,077 thinking records, no answer states either one. But almost nothing corrects them
either:

| | infix `in` | declared defaults |
|---|---|---|
| answers that state the correct rule | 5 | 7 |
| prompts whose code contains the construct for the model to find or fix | 0 | ~0 |
| DPO pairs that contrast it | 0 | 0 |
| code that shows the right form | ~150 answers use `in()`, `.in()` or `containsValue()` | 267 lists declared without an initializer, but 278 with an unneeded `= []` and 258 scalars declared `= null` |

Both beliefs are carried in from other languages: Python's `in` and Java's null default. The
corpus reinforces the second without meaning to: half of its list declarations add an
initializer the language does not need, so the model concludes one is required.

**Do not edit the existing `= []` and `= null` initializers.** They are valid code. The new
records must use bare declarations where the default is what the code needs, and must say why
that is correct.

## The facts

Each fact below is checked against the compiler, the function library or the language
reference. Where a record states a rule, it states it with its qualifier.

**Membership.**
- The membership test is the function `in(element, collection)`, or its object-notation form
  `element.in(collection)`. The collection is a list, a map (the test is on the keys) or a
  variant holding one of them. Negation is `!in(x, list)` or `!x.in(list)`.
- `containsValue(list, value)` and `containsValue(map, value)` also exist. The second tests the
  map's values, not its keys.
- `x in [...]` and `x !in [...]` do not compile. The compiler reports a syntax error on the
  token `in` or `!`.
- There is no `.contains()` method on lists. `contains(string, string)` is the string function.

**Declared-variable defaults.**
- A variable declared without an initializer starts at its type default, never null:
  - `integer`, `long`, `decimal`: 0
  - `number`: 0.0
  - `boolean`: false
  - `string`: `""`
  - `date`: the epoch, 1970-01-01 00:00:00 GMT
  - a list: empty; a map: empty
- A module-level variable keeps its value across records and groups for the whole run. That is
  why a Denormalizer's `clean()` has to reset it.
- **Things that ARE null.** State these as the exceptions they are:
  - a declared `variant`, `byte` or `cbyte`;
  - a field of a Rollup group accumulator that `initGroup()` does not assign, at the start of
    every group. A `default` attribute on the accumulator metadata does not change that: it is
    applied when data is read, not to accumulator state;
  - a nullable input field; a lookup that misses; a map key that is absent; `poll()` or `pop()`
    on an empty list.
- An initializer that sets the default (`string[] ids = [];`, `integer n = 0;`) is harmless
  style. It is never a fix.

## Part A — infix `in` (36 SFT records)

File: `sft_training_data/CTL_LoRA_belief_membership.json`, ids prefixed `belin_`.

| group | records | what it is |
|---|---|---|
| A1 validate, the construct is a defect | 12 | code uses `x in [...]`, `x !in [...]` or `x in listVar`; the review flags it as ERROR (does not compile) |
| A2 validate, correct membership | 8 | code uses `in(x, list)`, `x.in(list)`, `!in(...)`, `in(key, map)` or `containsValue(...)`; the review does not flag it |
| A3 fix to spec | 10 | the infix form is the one compile error among 2–3 spec defects; the corrected code uses `in()` |
| A4 generate | 6 | a task that needs a membership test; the code uses `in()` |

- **A1.** In 8 of the 12 the construct sits beside one or two independent other findings. In 4
  it is the only defect. Vary the form: list literal, list variable, negated, inside `&&`, in a
  ternary, in a Filter expression. The finding line quotes the construct in backticks and gives
  the mechanism with its qualifier: "CTL2 has no infix membership operator; membership is the
  function `in(element, collection)`, so this line does not compile."
- **A2 is the precision half.** At least 4 of the 8 have no issue at all (`[INFO] No issues
  found.`, VERDICT PASS). In the rest the membership call is correct and another,
  independent WARNING is the only finding. Include one `in(key, map)` (tests keys) and one
  `containsValue(map, v)` (tests values) where the difference is exactly what the task needs.
- **A3.** The corrected code is complete and compiles. The list of fixes names the infix form
  in prose, with its reason. The other defects are spec violations that compile, so the infix
  error is not the only thing to find.
- **A4.** Code first, then at most two sentences. One of them may say that membership is the
  `in()` function. Use at least 4 components.
- **Components across Part A.** At most 10 Reformat. Include Filter, Partition, Rollup,
  Denormalizer, ExtHashJoin and DataGenerator.

## Part B — declared-variable defaults (36 SFT records)

File: `sft_training_data/CTL_LoRA_belief_defaults.json`, ids prefixed `beldef_`.

| group | records | what it is |
|---|---|---|
| B1 validate, correct code that relies on a default | 12 | the review does not flag the bare declarations |
| B2 validate, minimal pairs | 8 (4 pairs) | the same construct where null is right and where it is not |
| B3 fix to spec | 8 | the real defect is state that leaks between groups; the declarations are correct |
| B4 explanation | 8 | a short question about the default rule, answered with the rule and its exceptions |

- **B1.** Code relies on the default and is correct: `turn++` on a bare `integer turn;`,
  `push()` or `clear()` on a bare list, `lastDate < $in.0.d` on a bare `date` (safe, because the
  epoch is earlier than any real date the prompt allows), `+=` on a bare string, `put()` on a
  bare map. At least 6 of the 12 have no issue (`[INFO] No issues found.`, PASS). The others
  carry one unrelated WARNING. Where the review mentions the declaration at all, it is an
  `[INFO]` line that says the variable starts at its type default and why that is enough here.
  Components: Denormalizer, Normalizer, Partition, DataGenerator, Reformat, Rollup (module
  variables, not accumulator fields).
- **B2 pairs** differ only in what decides null:
  - a Rollup accumulator field left unassigned in `initGroup()` and then used in arithmetic in
    `updateGroup()` is null, so the failure is certain: ERROR, FAIL. The same arithmetic on a
    bare module-level `decimal` is correct: no finding;
  - a declared `variant` that is read before it is assigned is null; a declared `string` is `""`.

  Tag the two records of a pair `"pair:<n>"`.
- **B3.** Denormalizer or Rollup code with a correct bare declaration and a missing reset in
  `clean()` (or `initGroup()`), so one group's value leaks into the next. The fix resets to the
  type default (`zeroDate()`, `0`, `clear(list)`), or to null together with a guard. The list of
  fixes says the first group was correct because of the default, and that the defect is the
  missing reset. It never says the variable started null.
- **B4.** Three to six sentences, with positive code only. Examples: "Do I need `= []` on a
  list I only `push()` to?", "What does a date variable hold before I assign it?", "Why is my
  Rollup accumulator total null when my global total is 0?". At least 3 of the 8 answer with
  an exception from the list above, so the model learns where the rule stops.

## Part C — DPO pairs (32)

File: `sft_training_data/CTL_LoRA_DPO_beliefs.jsonl`, ids prefixed `dpobel_`, 16 pairs per
belief. Use the `pair_type` values `belief_infix_in` and `belief_null_default`.

- **The prompt** is a validate or fix task (at least 12 of 16 per belief); the rest are generate
  tasks.
- **`chosen`** is a correct answer written to the Part A/B rules.
- **`rejected` is the same answer with only the belief changed**: for infix `in`, the corrected
  code keeps the infix form, or a review passes it as fine; for the default, the answer claims
  the bare declaration starts null and adds an initializer or a guard "to fix" it. Everything
  else is identical, so the preference can only be learned from the belief.
- A DPO `rejected` answer is the one place invalid code belongs. It is not a supervised target.

## Rules for every record (Parts A–C)

- **Guidelines §3.2 and §4.1 apply to every SFT answer and every DPO `chosen`.** No invalid code
  in a code block: not as a contrast, not commented out, not as "do not do this". A review or
  a list of fixes may quote the defective construct in inline backticks when it names the
  defect. That is the only place it appears.
- **Validate prompts end with the standard format instruction, verbatim.** It is added to
  every validate prompt automatically at inference:

  ```
  Report independent findings in code order using ISSUES, SUGGESTIONS, and VERDICT, in this layout:

  ISSUES:
    [ERROR] <location> — <what is wrong and why>
    [WARNING] <location> — <what is wrong and why>

  SUGGESTIONS:
    - <a concrete repair for each finding>

  VERDICT: PASS or FAIL

  Classify as ERROR code that does not compile, a runtime failure that is certain, and output that violates a stated requirement (for example adding where the specification says subtract). Classify as WARNING a runtime risk that depends on the data (a nullable field that may be null, a lookup that may miss, input that may be malformed) and a suspicious choice that still produces the specified output. If the code has no issues, write `[INFO] No issues found.` under ISSUES, omit SUGGESTIONS, and give VERDICT: PASS.
  ```

- **Severities follow that rule.** Infix `in` is ERROR (it does not compile). An unassigned
  accumulator field used in arithmetic is ERROR (the failure is certain on every group).
- **Every finding line is at least 35 words**, in order: the construct in backticks, the
  mechanism with its qualifier, the consequence.
- Prompts give port metadata as `<Metadata><Record>` XML. Rollup prompts include the
  accumulator `<Record>` or state that none is configured.
- **No `reasoning_content` and no `<think>` tags.**
- Every SFT record carries `id`, `messages` (system, user, assistant), `component` and `tags`.
  Use the system message of `CTL_LoRA_validate_examples.json`.
- **Reuse neither scenarios nor sentences** from one another, from the existing corpus, or from
  the evaluation suite. The suite's fix tests are a Denormalizer summing shipped orders per
  customer, a Rollup of stock lines per warehouse, and a Partition routing shipments by
  service, promise date and weight. Use none of those scenarios.

## Verification

Run from `ctl_lora_training/`. The belief scan uses `self_distill.belief_hits` from the
`llama_train` repository that contains `ctl_lora_training/`, the same check that filters self-distilled data.

```python
import json, re, sys, collections
sys.path.insert(0, '..')   # llama_train, which contains ctl_lora_training/
from self_distill import belief_hits

FORMAT_TAIL = "give VERDICT: PASS."
TARGET = {"infix `in` operator", "declared variables start null"}
FENCE = "`" * 3   # built, so this snippet can sit inside a Markdown fence
code_blocks = lambda t: re.findall(FENCE + r"(?:ctl)?\n(.*?)" + FENCE, t, re.S)
INFIX = re.compile(r"\$(?:in|out)\.\w+\.\w+\s+!?in\s+(?:\[|\w+\s*\))|\b\w+\s+!?in\s+\[\s*\"")
NULL_DECL = re.compile(r"\b(?:integer|long|decimal|number|string|boolean|date)(?:\[\])?\s+\w+\s*=\s*null\s*;")

for path in ('sft_training_data/CTL_LoRA_belief_membership.json', 'sft_training_data/CTL_LoRA_belief_defaults.json'):
    R = json.load(open(path))
    user = lambda e: next(m['content'] for m in e['messages'] if m['role'] == 'user')
    ans = lambda e: next(m['content'] for m in e['messages'] if m['role'] == 'assistant')
    print('==', path, len(R), 'records;', dict(collections.Counter(t for e in R for t in e.get('tags', []) if not t.startswith('pair:'))))
    print('answers stating a target belief (want 0):', [e['id'] for e in R if TARGET & set(belief_hits(ans(e)))])
    print('infix `in` inside an answer code block (want 0):', [e['id'] for e in R if any(INFIX.search(b) for b in code_blocks(ans(e)))])
    print('`= null` declarations in answer code (want 0):', [e['id'] for e in R if any(NULL_DECL.search(b) for b in code_blocks(ans(e)))])
    val = [e for e in R if 'ISSUES:' in ans(e)]
    print('validate prompts without the format instruction (want 0):', sum(1 for e in val if not user(e).rstrip().endswith(FORMAT_TAIL)))
    print('FAIL without ERROR or PASS with ERROR (want 0):',
          sum(1 for e in val if ('VERDICT: FAIL' in ans(e)) != ('[ERROR]' in ans(e).split('SUGGESTIONS:')[0])))
    print('records with reasoning_content or <think> (want 0):',
          sum(1 for e in R for m in e['messages'] if m.get('reasoning_content') or '<think>' in m.get('content', '')))
    print('components:', dict(collections.Counter(e.get('component') for e in R)))

P = [json.loads(l) for l in open('sft_training_data/CTL_LoRA_DPO_beliefs.jsonl')]
print('== DPO', len(P), 'pairs;', dict(collections.Counter(p['pair_type'] for p in P)))
kind = {'belief_infix_in': "infix `in` operator", 'belief_null_default': "declared variables start null"}
print('chosen stating the belief (want 0):', [p['id'] for p in P if TARGET & set(belief_hits(p['chosen']))])
print('rejected NOT stating its belief (review each):', [p['id'] for p in P if kind[p['pair_type']] not in belief_hits(p['rejected'])])
```

`rejected` answers that the scan does not flag are not necessarily wrong. The scan covers the
common phrasings, not all of them. Read each one it lists.

Check by hand what the script cannot:
- **Compile everything.** Every code block in an SFT answer and a DPO `chosen` compiles, and so
  does every snippet in a SUGGESTIONS line. Use the `ctl_validate` MCP tool where it applies.
  Every A1 prompt's code fails only on the infix line.
- **Traps.** Every B1 prompt's code is correct as written. The epoch default is enough for
  every comparison it makes.
- **Pairs.** The two records of each B2 pair differ only in what decides null, and each DPO
  pair differs only in the belief.

Then, as for every corpus addition: no prompt that already exists in the corpus or in the eval
sets, rebuild the merged training files, and re-run the standard pre-flight.

---

## Internal tracking (not part of the generation brief above)

**How success is measured.** After the next training run that includes these records, on the
suite v4 fix tests with thinking on, 20 runs:

| metric | now (fix6 SFT+DPO / sd1 ep2) | target |
|---|---|---|
| T40.FP1 fires (declared globals called null) | 40/40 | ≤ 10/40 |
| T42.FP6 fires (`date prevShip;` called null) | 10/10 (n=5 each) | ≤ 25% |
| T41.B1 not CAUGHT (infix `in` kept or wrongly explained) | 37/40 | ≤ 10/40 |
| suite generate / validate | 2×2 baselines | no drop > 0.01 |

The belief scan also runs on sampled answers:
- **`self_distill.py` now rejects both beliefs.** `KNOWN_FALSE_BELIEFS` has `infix \`in\`
  operator` and `declared variables start null`. It catches 38 of the 40 T40 answers and 38
  of the 38 T41 answers (fix-only repeat plus the first calibration) that missed B1.
- **Fix, 2026-09-30:** the infix pattern used to reject correct answers that quote
  `x in [...]` in order to flag it. It now skips a match followed by "is not valid", "no
  infix", "does not compile" or "syntax error". 3 of 3 T41 answers that caught B1 are now clean.

**Related fix, still open.** `resources/ctl2-basics.md` line 1078 reads "Unset record fields are
null (not type default) unless metadata defines a Default." For Rollup accumulator state, the
user verified on a real graph that the metadata Default is not applied. The line needs that
qualifier.

**Where the numbers come from.**
- **Corpus scan:** phase-1 SFT `CTL_LoRA_training_data.json`, DPO `CTL_LoRA_DPO_data.jsonl` and
  the thinking set `CTL_LoRA_training_data_think.json`, all 2026-09-30.
- **Suite rates:**
  - T40 and T41: the fix-only repeat, `results/results_qwen38_2x2_{base_on,sd1ep2_on}_20260930T07*.json`.
  - T42.FP6: the T42 v3 calibration, 5 runs per model.
