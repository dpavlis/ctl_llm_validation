# Validate coverage — multi-finding reviews and PASS-with-warnings

**A small severity audit of existing records, then 100 new records. Answers only — no
`reasoning_content`.** Everything above the "Internal tracking" section at the end is a
self-contained brief. It assumes CTL2 knowledge (the language, the CloverDX component model,
and the `ISSUES:` / `SUGGESTIONS:` / `VERDICT:` review format) but no other context about this
project.

You are working inside the `ctl_lora_training` repository:

| path | what it is |
|---|---|
| `sft_training_data/` | the training corpus, one JSON file per set |
| `sft_training_data/CTL_LoRA_validate_examples.json` | 937 validate records — the bulk of the existing coverage |
| `sft_training_data/CTL_LoRAT_multibug_validate_thinking.json` | 42 multi-defect reviews, the house style for deep reviews |
| `sft_training_data/system_message_validate.txt` | the validate system message; its "PASS (with warning) for runtime-data risks" is the rule below |
| `references/CTL2_Reference_for_LLM_compact.md` | the language reference |
| `references/ctl-function-library.json` | every built-in function and each of its overloads |
| `references/componet_contracts.md` | which functions each component must define, and what may be written where |
| `references/CTL2_SFT_Validation_Playbook.md` | house style for validate records |

## Why this exists

The model reviews clean code and single-defect code well. It fails two kinds of review
almost completely:

| kind of review | samples judged correct |
|---|---|
| 3 or more findings | 1 of 34 |
| PASS with warnings (code is correct, but carries a data risk or looks unintended) | 0 of 12 |
| for comparison: clean code, PASS | 14 of 20 |
| for comparison: exactly 1 finding | 9 of 16 |

- **PASS with warnings fails on severity.** In every rejected review the model graded a
  data-dependent runtime risk — a nullable field in an ordered comparison, an unguarded
  lookup result — as ERROR and the verdict as FAIL. The rule below says WARNING and PASS.
- **Multi-finding reviews fail on truth and completeness.** The model reports about one
  finding fewer than a correct review, and 21 of 34 of its reviews contain a false statement
  about CTL2.

Part A makes the existing records apply the severity rule consistently. Part B adds records
built to teach the rule and the two multi-finding failures.

## The severity rule

The question to ask of every finding is: **is the failure certain, or does it depend on the
data?**

- **ERROR**
  - the code does not compile;
  - the code compiles but a runtime failure is **certain** — it happens whatever the data:
    dereferencing a variable the code itself has just set to null, a cast the declared types
    guarantee to fail, an unconditional division by zero;
  - the code runs but **violates a stated requirement** — it emits the wrong result for rows
    the task describes: adding where the specification says subtract, the wrong port for a
    stated routing rule, a boundary the task defines as inclusive tested as exclusive.
- **WARNING**
  - a runtime risk that **depends on the data**: a nullable field that may be null in an
    ordered comparison or in arithmetic, a lookup that may miss, a string that may be
    malformed. The code is not wrong just because it could fail at runtime;
  - a suspicious choice that still produces the specified output: a suspicious pattern letter
    (`DD`, `YYYY`, `mm`), a dead store, a redundant guard, a silent `transformOnError`.
- **INFO** — a remark that is not a defect, including an explicit statement that a construct
  which *looks* wrong is correct here.
- **Verdict**: any ERROR makes it FAIL. WARNING and INFO lines alone leave it PASS.

A WARNING about a data risk names the data that would trigger it ("a row with a null
`quantity` throws in the multiplication"). It does not claim the code is wrong.

## Part A — severity audit (an edit pass)

**Edit records in place. Keep every id. Change answers only.** This is not a regeneration.
Most of the corpus already follows the rule; this pass fixes the exceptions.

The script under "Verification" prints the worklist in three groups:

1. **ERROR lines about a data-dependent risk** (about 25). If the failure really depends on the
   data, downgrade the line to `[WARNING]`, and set the verdict to PASS when no ERROR is left.
   If it is in fact certain, keep ERROR and say why in the line.
2. **WARNING lines about a certain failure** (about 1). Upgrade to `[ERROR]` and set the
   verdict to FAIL.
3. **WARNING lines that mention a requirement or a wrong result** (about 29). Most are
   correctly WARNING ("no stated limit makes this a proven violation"). Upgrade only those
   where the task states the requirement and the code emits a wrong result for rows it
   describes.

**Known wrong references, found by compiling the task code** with the real CTL2 compiler:
`trolluppbd_25` (`CTL_LoRAT_rollup_per_record_new.json`) and `trollupu62_contrast_02`
(`CTL_LoRAT_rollup_update_transform_examples.json`) call writing to `$out.1` on an unconnected
port harmless dead code (WARNING, PASS). It is a compile error: *"Cannot write to output port
'1' — the port has no edge connected"*. Both become ERROR, verdict FAIL. Also check
`conversa78_1225` (`CTL_LoRA_conversations.json`), which discusses the same case. And
`tvalidat22_37` (`CTL_LoRAT_validate_thinking.json`) grades writing `0D` for a null
`credit_amount` as a WARNING, but the task says to preserve `credit_amount` exactly — a
stated-requirement violation, so ERROR, verdict FAIL.

In any group, **a line that is wrong about CTL2 gets corrected**, whatever its severity. One
known example: a review claiming an uninitialized `string[]` is null. CTL2 initializes a
declared list or map to empty, not to null.

Do not add or remove findings beyond what the severity change requires. Leave records outside
the worklist untouched.

## Part B — 100 new records

Two new files, answers only:

| file | records | what it teaches |
|---|---|---|
| `sft_training_data/CTL_LoRA_validate_multifinding.json` | 60 | reviews with 3–6 independent findings |
| `sft_training_data/CTL_LoRA_validate_pass_warnings.json` | 40 | PASS reviews of code whose only findings are WARNINGs |

### B1 — multi-finding reviews (60)

| findings | records |
|---|---|
| 3 | 18 |
| 4 | 18 |
| 5 | 14 |
| 6 | 10 |

- **Components.** At most 12 Reformat. Cover the rest with at least 6 each of Rollup,
  Denormalizer, Normalizer, ExtHashJoin/ExtMergeJoin, Partition, Filter and DataGenerator,
  and include Map-with-lookup. Component lifecycle gives defect material a plain Reformat
  cannot: which function may read `$in.0` or write `$out.*`, accumulator state that is never
  reset, `VoidMetadata` parameters when no accumulator is configured, multi-port routing.
- **Independent defects**: different lines, different mechanisms. Do not seed one mistake
  several times.
- **Severities follow the rule above.** Every record carries at least one ERROR; at least 40
  of the 60 also carry a WARNING. Across the set, at least 20 of the ERRORs are
  business-rule violations (code that runs and emits the wrong result), because those are the
  findings the model misses most. Do not always put the warning last.
- **Order `ISSUES:` lines as the constructs appear in the code**, not by severity.
- **Every finding line gets at least 35 words**, stating in order: (1) the construct, quoted
  in backticks; (2) the mechanism *with its qualifier*; (3) the concrete consequence — the
  compile error, the certain failure, or the row whose output is wrong or which may throw.
  The qualifier is what keeps the line true: say "`isNull()` takes a record and a field index
  or name, so a single value argument does not resolve", never "`isNull()` does not exist".
  Grounding, not padding: quote the metadata that makes a field nullable, and trace the row.
- **`SUGGESTIONS:` has one concrete repair per ERROR and WARNING finding**, and every
  suggested line must compile.
- **A trap in at least 20 of the 60**: a construct that looks wrong but is correct in
  context. The review leaves it unflagged or marks it `[INFO]`, saying plainly that it is
  fine and why.
- **Reuse neither scenarios nor sentences** from the existing multi-defect records or from
  one another. A new record is not an old one with the field names changed.

**Build traps and correct explanations from the beliefs the model currently gets wrong.**
Each of these was a false claim in the model's reviews. Each fact below is checked against
the function library and the language reference:

| the model believed | what is true |
|---|---|
| assigning one list or map variable to another aliases them | `=` makes a deep copy of lists, maps, records and dates |
| map `appendAll` does not exist | `appendAll(map, map)` exists, alongside the list and variant overloads |
| `byte2hex` takes exactly one argument | `byte2hex(byte)` and `byte2hex(byte, string)` both exist |
| `num2str` has one two-argument form | `num2str(any, string)` (format) and `num2str(integer\|long\|number, integer)` (radix) both exist |
| `isNull()` does not exist | `isNull(record, integer)` and `isNull(record, string)` exist; `isnull(any)` is the single-value test |
| `getWeek(date)` is a function | it is not; week numbers come from date functions that exist in the library |
| `dateAdd` changes its argument | dates are immutable; `dateAdd` returns a new date |
| `cast(v, decimal)` works on any JSON number | `parseJson` returns whole numbers as `integer`/`long` and decimals as `number`, so casting such a value to `decimal` fails |
| Rollup functions may omit their parameter when no accumulator is configured | they take `VoidMetadata` (for example `initGroup(VoidMetadata groupAccumulator)`) |

Use these as correct code the review must not flag (a trap), and, where natural, as the
mechanism inside a genuine finding. Do not build a record whose only point is one of these
facts.

### B2 — PASS with warnings (40)

- **No ERROR, verdict PASS.** The code compiles, no runtime failure is certain, and it meets
  every stated requirement. There are 1 or 2 WARNINGs per record: 24 records with one, 16
  with two.
- **At least 25 of the 40 carry a data-dependent runtime risk as a WARNING**: a nullable field
  in an ordered comparison or in arithmetic, a lookup result dereferenced without a guard, a
  parse of a string the task does not guarantee to be well-formed. The line names the data
  that would trigger it and says the code is correct for every other row. This is the case
  the model currently escalates to ERROR and FAIL.
- **The rest carry suspicious-but-correct choices**: pattern letters, a dead store, an unused
  variable, a redundant guard, a silent error handler, a rounding or formatting choice the
  task does not ask for.
- **Each WARNING line is at least 35 words**, in the same construct → mechanism → consequence
  order. The consequence is the data that would trigger it, or what a reader would expect
  instead.
- **10 minimal pairs across B1 and B2.** The same construct appears twice, differing only in
  what decides severity:
  - in B2, a data-dependent risk: WARNING, verdict PASS;
  - in B1, the same construct where the failure is certain, or where it breaks a stated
    requirement: ERROR, verdict FAIL.

  For example, an unguarded `lookup(...).get(key)` dereference is a WARNING. The same
  dereference after the code has itself overwritten the key with a value the lookup cannot
  contain is an ERROR. Record the pairing in `tags` (`"pair:<n>"`). Nothing teaches the
  severity rule more directly.
- **Components**: spread as in B1, with at most 10 Reformat.

### Prompts and format — both files

- **The user prompt ends with the standard format instruction, verbatim.** It is added to
  every validate prompt automatically at inference, so the training prompts must carry it:

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

- The prompt gives the code, the input and output metadata as `<Metadata><Record>` XML (not
  prose), and the requirements. Rollup prompts include the accumulator `<Record>`, or state
  that none is configured.
- The system message is the one used by `CTL_LoRAT_multibug_validate_thinking.json`.
- **No `reasoning_content` and no `<think>` tags.** Authored reasoning was measured to make
  the model worse; the model's own reasoning is trained separately.
- Every record carries `id`, `messages`, `component` and `tags`. Ids are prefixed
  `vmulti_` (B1) and `vpasswarn_` (B2).

## Verification

**Part A worklist.** Run it before the audit to get the three groups, and again after it:
every line it still prints must be one you kept deliberately.

```python
import json, glob, re
COND = re.compile(r"\b(may|might|can|could|if|when|whenever|would)\b", re.I)
DATA = re.compile(r"\bnull(?:able)?\b|lookup miss|misses|not found|malformed|non-numeric|invalid (?:input|value|date|number)|unparseable|empty", re.I)
FAIL = re.compile(r"throws?|CTLException|NullPointer|fail|abort|exception|error", re.I)
CERTAIN = re.compile(r"\balways\b|every (?:row|record|input)|unconditional|certain|on each (?:row|record)|for all (?:rows|records)", re.I)
REQUIREMENT = re.compile(r"instead of|requirement|specif(?:ied|ication)|the (?:prompt|task|request) (?:says|asks|requires)|contradicts|wrong (?:result|value|output)|violat", re.I)

for path in sorted(glob.glob('sft_training_data/*.json')):
    try:
        records = json.load(open(path))
    except (json.JSONDecodeError, UnicodeDecodeError):
        continue
    for rec in records if isinstance(records, list) else []:
        answer = next((m.get('content', '') for m in rec.get('messages', []) if m.get('role') == 'assistant'), '')
        if 'ISSUES:' not in answer or 'VERDICT:' not in answer:
            continue
        for line in answer.split('ISSUES:', 1)[1].split('SUGGESTIONS:')[0].splitlines():
            text = ' '.join(line.split())
            group = None
            if text.startswith('[ERROR]') and COND.search(text) and DATA.search(text) and FAIL.search(text) and not CERTAIN.search(text):
                group = '1 ERROR on a data risk'
            elif text.startswith('[WARNING]') and CERTAIN.search(text) and FAIL.search(text):
                group = '2 WARNING on a certain failure'
            elif text.startswith('[WARNING]') and REQUIREMENT.search(text):
                group = '3 WARNING citing a requirement'
            if group:
                print(group, '|', path.split('/')[-1], rec.get('id'), '|', text[:150])
```

**Part B.** Run from `ctl_lora_training/`:

```python
import json, re, collections
LIB = set(json.load(open('references/ctl-function-library.json'))['functions'])
FORMAT_TAIL = "give VERDICT: PASS."
KEYWORDS = {'if','while','for','foreach','switch','return','function','lookup','sequence','catch','try'}
HOOKS = {'transform','transformOnError','getOutputPort','generate','initGroup','updateGroup','finishGroup',
         'updateTransform','append','count','clean','init','preExecute','postExecute'}

def parse(a):
    body = a.split('ISSUES:', 1)[1]
    issues = body.split('SUGGESTIONS:')[0].split('VERDICT:')[0]
    lines = [' '.join(l.split()) for l in issues.splitlines() if re.match(r'\s*\[(ERROR|WARNING|INFO)\]', l)]
    verdict = re.search(r'VERDICT:\s*(PASS|FAIL)', a).group(1)
    sugg = a.split('SUGGESTIONS:', 1)[1].split('VERDICT:')[0] if 'SUGGESTIONS:' in a else ''
    return lines, verdict, sugg

for path, want, floor_sevs in (('sft_training_data/CTL_LoRA_validate_multifinding.json', 60, ('ERROR', 'WARNING')),
                               ('sft_training_data/CTL_LoRA_validate_pass_warnings.json', 40, ('WARNING',))):
    R = json.load(open(path))
    print('==', path, len(R), f'records (want {want})')
    user = lambda e: next(m['content'] for m in e['messages'] if m['role'] == 'user')
    ans = lambda e: next(m['content'] for m in e['messages'] if m['role'] == 'assistant')
    P = [parse(ans(e)) for e in R]
    finds = [sum(1 for l in ls if not l.startswith('[INFO]')) for ls, _, _ in P]
    print('findings per record:', dict(collections.Counter(finds)))
    print('verdicts:', dict(collections.Counter(v for _, v, _ in P)))
    print('FAIL without ERROR / PASS with ERROR (want 0):',
          sum(1 for ls, v, _ in P if (v == 'FAIL') != any(l.startswith('[ERROR]') for l in ls)))
    short = [l[:60] for ls, _, _ in P for l in ls if l.split()[0][1:-1] in floor_sevs and len(l.split()) < 35]
    print('finding lines under 35 words (want 0):', len(short), short[:3])
    print('components:', dict(collections.Counter(e.get('component') for e in R)))
    print('prompts without the format instruction (want 0):', sum(1 for e in R if not user(e).rstrip().endswith(FORMAT_TAIL)))
    print('records with reasoning_content or <think> (want 0):',
          sum(1 for e in R for m in e['messages'] if m.get('reasoning_content') or '<think>' in m.get('content', '')))
    unknown = collections.Counter()
    for _, _, sugg in P:
        for span in re.findall(r'`([^`\n]+)`', sugg):
            for name in re.findall(r'\b([A-Za-z_]\w*)\s*\(', span):
                if name not in LIB and name not in KEYWORDS and name not in HOOKS:
                    unknown[name] += 1
    print('suggested calls not in the function library (want none):', dict(unknown))
    lines = collections.Counter(l for ls, _, _ in P for l in ls)
    print('issue lines repeated (want 0):', sum(n for n in lines.values() if n > 1))
```

Check by hand what the script cannot:
- every B2 record's code meets every stated requirement and has no certain failure;
- every data-risk WARNING names the data that would trigger it;
- the two records of each pair differ only in what decides severity.

Then, as for every corpus addition: no prompt that already exists in the corpus or in the
eval sets, rebuild the merged training files, and re-run the standard pre-flight.

---

## Internal tracking (not part of the generation brief above)

**The severity rule** was set by the project owner on 2026-09-29: a data-dependent runtime
risk is a WARNING. ERROR is for a compile failure, a certain runtime failure, or a violation of
a stated requirement. It matches `system_message_validate.txt` and T16/T24 in
`resources/ctl2_test_suite_v4.json`. T18.B2 (an unguarded lookup-result dereference) used to
require ERROR; on 2026-09-29 it was changed to WARNING in the v4 and v2 suites. T18's verdict
stays FAIL because of T18.B1, a compile error. T18 scores from before that date are not
comparable with later ones.

**Measurements behind this spec** (self-distillation pilots, `data/self_distill/pilot{1,2}`,
teacher `qwen38_fix6_sftdpo`, thinking on, effort medium, judged against the reference answer
plus a false-claim pass):

| validate group | samples accepted |
|---|---|
| clean code, PASS | 14/20 |
| 1 finding | 9/16 |
| 2 findings | 2/16 |
| ≥3 findings (both pilots) | 1/34 |
| PASS with warnings | 0/12 |

On the ≥3-finding reviews: the model reported a median of 1 finding fewer than the
reference; 21/34 reviews contained a false CTL2 claim, 19/34 missed a finding, and 8/34
disagreed on severity. The belief table in B1 comes from those reviews and from the
`false_claim` rejections.

All three PASS-with-warnings prompts in pilot2 were rejected for grading a data-dependent risk
ERROR/FAIL: a nullable field in an ordered comparison (`nullcmp_sft_08`, `validateb8_960`) and
an unguarded lookup result (`treasoniae_71`). The references were right under the rule. The
format instruction appended to those prompts then said "runtime exceptions → ERROR", which
pushed the teacher the wrong way; it has since been corrected to state the rule. **pilot2's
PASS-with-warnings result therefore overstates the gap — re-measure it before relying on
it.**

Existing coverage is not small: 161 validate records with ≥3 findings and 293 PASS with
warnings, mostly in `CTL_LoRA_validate_examples.json`, 47 of the 161 with no identifiable
component. The corpus already applies the severity rule almost everywhere; Part A's worklist
is about 55 lines. The problem is quality — completeness, false claims, and too few
business-rule ERRORs among plain data-risk WARNINGs — which is why Part B is 100 targeted
records rather than a bulk batch.

**Follow-up in `llama_train` once this lands:**

1. **Done 2026-09-29** (`data/self_distill/passwarn1`, `passwarn1b`): PASS-with-warnings
   re-measured with the corrected instruction on the current teacher — 19/60 samples
   accepted, 19/48 excluding three prompts whose references turned out to be wrong (listed
   under Part A). It is back in `FULL_PLAN` (30 prompts); the three are held out through
   `KNOWN_WRONG_REFERENCES` until Part A corrects them. Part B's B2 records remain worth
   writing: 22/60 answers still escalated a data risk to ERROR.
2. Retrain SFT+DPO and export; that export becomes the new teacher.
3. Add the two new files to `self_distill.py`'s prompt sources (today it reads
   `CTL_LoRAT_*.json` plus the fix top-up), and extend its eval-set exclusion if any of these
   records go to an eval set.
4. Rerun a pilot restricted to `validate_multi3`. Put a group back into `FULL_PLAN` (removing it from
   `FULL_EXCLUDED_GROUPS`) once at least 25% of its samples are accepted.
5. The eval suite's 13 validate prompts do not carry the format instruction either. If it is
   added automatically in real use, the eval should add it too, or the eval measures a prompt
   the model will never see.
