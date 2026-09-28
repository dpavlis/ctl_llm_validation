# Fix-to-spec records — teaching the enumerate-then-correct task

**Amend the 24 records that already exist — do not regenerate them.** Everything above the
"Internal tracking" section at the end is a self-contained brief. It assumes CTL2 knowledge (the language and the CloverDX component
model) but no other context about this project.

> **Amendment, 2026-09-28 — read this before generating.** A first batch of 24 records
> written to the original version of this document was trained and measured. The
> enumeration half improved (words per issue 26 → 29, and the model's wrong-explanation
> rate fell to its best in five runs) but the **fix score went down**, because the
> *corrected code* got worse: it began breaking requirements the broken code satisfied,
> introducing code that does not compile, and "fixing" constructs that were already
> correct.
>
> The cause was an imbalance in this document: it specified the enumeration in detail and
> the corrected code barely at all. Two sections are new and are the priority for this
> batch — **"The corrected code is a minimal repair"** and **"Seed constructs that look
> broken but are correct"**. An audit of the first batch found 0 of 24 records seeding a
> correct-but-suspicious construct, and only 6 of 24 reasoning traces affirming anything
> as already correct.
>
> **This is an edit pass, not a regeneration.** The 24 records in
> `sft_training_data/CTL_LoRAT_fix_to_spec.json` pass every other check in this document:
> the component mix and defect distribution are exact, every enumerated item clears the
> 35-word floor (median 47, minimum 40), no record calls a function outside the library or
> omits a required contract function, and every prompt carries a real numbered
> specification. The fault is something *missing*, not something wrong. Keep those records,
> keep their ids, and add what they lack. Regenerating would discard properties that are
> already verified and reintroduce variance for no gain.

You are working inside the `ctl_lora_training` repository. Everything referenced below is
in it:

| path | what it is |
|---|---|
| `sft_training_data/` | the training corpus, one JSON file per set |
| `sft_training_data/CTL_LoRA_fix_this_code.json` | 126 existing fix records — read, but see the warning below |
| `sft_training_data/CTL_LoRAT_fix_this_code_think.json` | 4 fix records that carry reasoning |
| `references/CTL2_Reference_for_LLM_compact.md` | the language reference |
| `references/ctl-function-library.json` | every built-in function and its signature |
| `references/componet_contracts.md` | which functions each component must define, and what may be written where |
| `references/CTL2_Example_Generation_Playbook.md` | house style for generate records |
| `references/CTL2_SFT_Validation_Playbook.md` | house style for validate records |
| `references/CTL2_Reasoning_Trace_Playbook.md` | house style for `reasoning_content` |
| `utils/convert_think.py` | merges `reasoning_content` into the tagged form |

Edit `sft_training_data/CTL_LoRAT_fix_to_spec.json` in place. It holds 28 records: the 24
to amend, with ids prefixed `fixtospec_`, and 4 older ones (`fixthiscc4_133` through
`fixthiscc4_136`) that predate this document. **Leave the four alone** — they are a
different, prose-form shape and the verification script below flags them; that is expected,
not something to fix.

## The task to teach

A **fix-to-spec** prompt supplies three things: a numbered specification, a CTL2
transform that is supposed to implement it, and an instruction of the form

> *"Fix the following CTL2 &lt;component&gt; transform so that it compiles and does what the
> specification says. List every problem you fix with the reason, then give the complete
> corrected code."*

It is a **compound** task. The answer has two halves, and both are graded:

1. **Enumerate every defect, each with the reason it is a defect** — what the construct
   does, the mechanism by which that diverges from the specification, and the concrete
   consequence in the output.
2. **Then** give the complete corrected transform, not a diff and not a fragment.

The order is part of the task: reasons first, code second.

### What makes this different from the fix records already in the corpus

The corpus has 1222 fix-like records. They teach a *different* task — "here is broken
code, give me working code" — and 87% of them enumerate nothing at all. The defects they
seed are overwhelmingly **syntax typos**: `isNull` for `isnull`, `int` for `integer`,
`$in[1].f` for `$in.1.f`, a missing colon after `default`. Those are found by reading, not
by reasoning about behaviour.

The task here turns on **semantic defects that compile and run**. Code that a compiler
accepts, that produces output, and whose output is wrong against the specification. A good
record mixes both kinds, weighted toward the semantic ones. Worked categories:

- **Integer division** where a decimal was meant — `qty * price * (100 - pct) / 100` in
  integer arithmetic truncates, and a discount under 1 unit zeroes the line total.
- **Date-format letter case** — `mm` is minutes, `MM` is months; `dd` is day-of-month,
  `DD` is day-of-year. The code compiles and silently formats the wrong field.
- **Off-by-one on a 1-based built-in** — subtracting 1 from a function that already
  returns a 1-based value, and the same call throwing on a null input.
- **A null that is not guarded** — the specification says a null counts as zero or is
  dropped; the code propagates it into arithmetic or a comparison.
- **A condition that is inverted, or that uses the wrong comparison** — `>=` where the
  spec says strictly greater, or a string compared case-sensitively where the spec
  guarantees uppercase and the code lowercases one side.
- **Rounding mode or scale** — truncation where the spec says round half-up, or the wrong
  number of decimal places.
- **The wrong return value for the component contract** — returning `OK` where a port
  number is required, `ALL` where one port was meant, or omitting `SKIP` so a record that
  the spec says to drop is emitted anyway.
- **A field the specification requires that is never assigned** — it silently stays at
  the type default.

Each of these is invisible to a reader skimming for syntax and obvious to one who checks
the code against the specification line by line. That check is what the record teaches.

## What to produce

**The 24 existing records, amended.** Each one keeps its id, component, specification,
broken code and defect set. What changes in each:

1. **Add one correct-but-suspicious construct** (two in the 5- and 6-defect records) to the
   broken code where the record does not already contain one, and add the matching
   affirmation item to the answer's list. See "Seed constructs that look broken but are
   correct" below.
2. **Add the same affirmation to the `reasoning_content`**, reached the same way the trace
   reaches a defect.
3. **Re-check the corrected code against every numbered requirement** and against the
   minimal-repair rule below; trim any change that does not trace to a listed item.

Adding an affirmation item does **not** change a record's defect count — the distribution
below is a count of *defects*, and it must still hold after the edit. The tables in this
section are therefore unchanged targets, not new ones to hit.

If a record already contains a construct that happens to be correct-but-suspicious, name it
rather than inventing a second one.

Should a record turn out to be unsalvageable — the specification is ambiguous, or a claimed
defect is not actually a defect — replace that one record and say which, rather than
regenerating the set.

### Defect count per record

| defects seeded | records |
|---|---|
| 3 | 6 |
| 4 | 8 |
| 5 | 7 |
| 6 | 3 |

At least **two thirds of the defects in every record must be semantic** — compile-and-run
defects that break the specification. A record may seed at most **two** pure compile
errors, and several should seed none at all: a transform that compiles cleanly and is
still wrong is the hardest and most valuable case.

### Component mix

Spread across components rather than clustering on Reformat, which the existing fix
records already over-represent (353 of 1222):

| component | records |
|---|---|
| Reformat | 5 |
| Rollup | 4 |
| Denormalizer | 3 |
| Normalizer | 3 |
| Join (Hash / Merge / ExtHash) | 3 |
| Partition | 2 |
| Filter | 2 |
| DataGenerator | 2 |

Use both `//#CTL2` and `//#CTL2:COMPILE` headers across the set, roughly half and half.
The compiled-mode header changes nothing about which constructs are legal — the
conditional-fail expression (` : `) works identically in both — so do not seed a defect
that claims otherwise.

### Every record needs a real specification

Write the specification as a numbered list of 4–8 requirements in the prompt, in the same
register a CloverDX developer would receive it: field by field, naming the metadata, and
stating the null and edge-case behaviour explicitly. The specification is what makes a
semantic defect *checkable*. A vague specification produces a record where the model
cannot tell a defect from a design choice, and the record then teaches guessing.

Every seeded defect must be a demonstrable divergence from a numbered requirement. Before
writing the answer, check the broken code against the specification line by line and
confirm the defect list is **exhaustive** — a record whose answer misses a defect that is
genuinely present teaches the model to stop looking early.

## Seed constructs that look broken but are correct

**Every record must seed at least one construct that looks defective and is not**, and the
answer must name it and say it is correct. In records with 5 or 6 defects, seed two.

This is the single most important addition to this document. Without it, a record teaches
only "scan this transform and report what is wrong", and a model trained on nothing but
that reports things that are not wrong — which is how the first batch lost more points
than it gained. The correct-but-suspicious construct is what teaches the model where to
stop.

Good candidates, all of them true CTL2 facts that read as bugs to a careless reviewer:

- **Declared-but-unassigned variables are not null.** They start at their type defaults: a
  numeric type at 0, a `date` at the epoch, a `list` or `map` as an empty container, a
  `boolean` at false. So a first `+`, a first comparison or a first `append()` on an
  unassigned global does **not** throw, and adding explicit initializers is a style choice,
  not a bug fix.
- **`++` and `--` work on any writable numeric l-value**, including output record fields
  (`$out.0.counter++`) and the fields of an accumulator or internal record (`acc.count++`).
  Only read-only targets are invalid — input fields (`$in.0.f`), literals, and list or map
  elements. Rewriting `$out.0.n++` as `$out.0.n = $out.0.n + 1` is equivalent, not a fix.
- **`~=` is a whole-string regex match** and `?=` is the contains match. `$in.0.code ~=
  "CZ|SK"` matches exactly "CZ" or "SK" and is the right operator when the spec asks for
  either of two exact values.
- **A Rollup group always contains at least one record**, so a divide-by-group-count guard
  against zero is defending against a case that cannot occur.
- **The conditional-fail expression works in both `//#CTL2` and `//#CTL2:COMPILE`.** The
  header does not change which constructs are legal.
- **Returning an output port number from `updateTransform()` or `transform()` is correct**
  — it emits to that one port and re-invokes the function with `counter + 1`, which a
  `counter` guard terminates. `ALL` is not a synonym; it broadcasts to every connected
  port.

State the affirmation in the same register as a defect item, at the same length, and place
it in the list with the defects rather than in a separate afterthought section:

> 4. `acc.total` is declared without an initializer and first used in `acc.total = acc.total
>    + $in.0.amount`. This is **correct as written** and needs no change: an unassigned
>    `decimal` starts at 0, not null, so the first addition of a group is well-defined.
>    Requirement 3 is already satisfied here.

Number these items in sequence with the defects. The point is that the model cannot tell
in advance which items will turn out to be defects and which will not.

## The corrected code is a minimal repair

**Change only what the enumerated defects require. Everything else stays byte-identical to
the input.** This is a hard rule and the second reason the first batch regressed.

Concretely, before you write the corrected block:

1. **Re-read every numbered requirement against your corrected code**, not just the ones
   you fixed. A fix that satisfies requirement 2 and breaks requirement 5 scores worse than
   no fix at all. This is the single most common way the task is failed.
2. **The corrected code must compile.** Every function named must exist in
   `references/ctl-function-library.json` with that signature; every component contract
   function required by `references/componet_contracts.md` must be present, including the
   ones you did not touch.
3. **Do not trade one runtime failure for another.** Guarding a null in one place while
   leaving the same value unguarded in the comparison two lines down is not a fix.
4. **Do not restructure what already works.** Renaming variables, reordering assignments,
   changing formatting or "tidying" untouched functions all count as unrequested changes.

A record may restructure substantially **only when a requirement genuinely demands it** —
for example, when the spec requires skipping null inputs and the transform must build a
filtered list to do so. When that happens, the enumerated item must say why the
restructure is necessary, so the record teaches the reason rather than the habit.

The test to apply to your own record: diff the broken and corrected code, and check that
every changed line traces to a numbered item in your list. If a changed line does not,
either remove the change or add the item it belongs to.

## The length floor — the point of this document

**Every enumerated defect needs at least 35 words of explanation.** This is the binding
constraint, and it is why the existing fix records cannot be used as a style model.

Below roughly 25 words per item, this model compresses a true statement into a false one:
it keeps the claim and drops the qualifier that made it true, and the judge scores the
result WRONG rather than incomplete. The corpus currently teaches 10–13 words per item on
exactly this task, and the measured consequence is that on the benchmark's fix tests
*every* failure is a wrong explanation rather than a missed defect.

Each item must carry all three of:

- **the construct** — name the function, operator or field, as it appears in that record;
- **the mechanism, with its qualifier** — what it actually does, including the condition
  under which it does it. The qualifier is the part that gets dropped under compression
  and the part that makes the statement true;
- **the consequence** — what appears in the output, in terms of that record's fields.

Too short, and wrong as a result:

> - `getMonth()` is 1-based, so `- 1` is an off-by-one.

Correct, at 47 words:

> - `getMonth($in.0.order_date) - 1` is wrong twice over. `getMonth()` already returns a
>   1-based month, so subtracting 1 yields 0 for January and shifts every month down one
>   position. It also throws on a null `order_date`, which requirement 5 says must produce
>   an empty `period` rather than an error.

Do not pad to reach the floor. Length comes from naming the specific construct, stating
the qualifier, and following the consequence into the output. If an item is short because
the defect is simple, say what the specification required as well as what the code does —
that is the part the terse version omits, and it is what the reader needs.

## Examples to read first

**Read these for task shape only, not for style.** These nine are the closest the corpus
has to the target shape, and all nine average 10–13.5 words per item — the exact habit
this document exists to correct. Read them to see the prompt construction, then write
answers that look nothing like theirs.

In `sft_training_data/CTL_LoRA_fix_this_code.json`, by `id`:

| id | defects listed | words per item |
|---|---|---|
| `fixthiscc4_24` | 4 | 13.5 |
| `fixthiscc4_50` | 8 | 10.2 |
| `fixthiscc4_54` | 7 | 10.9 |
| `fixthiscc4_56` | 7 | 13.0 |
| `fixthiscc4_58` | 8 | 10.9 |
| `fixthiscc4_60` | 6 | 10.3 |
| `fixthiscc4_63` | 7 | 10.3 |
| `fixthiscc4_66` | 6 | 10.3 |
| `fixthiscc4_67` | 6 | 10.3 |

Note also that all nine put the corrected code **first** and a terse "What was fixed:"
list after it. Invert that: reasons first, code second.

For the explanation style you *do* want, read the multi-defect validate records in
`sft_training_data/CTL_LoRAT_multibug_validate_thinking.json`. Their per-finding prose is
the register to match; the difference is that a fix record must also produce the corrected
code.

For the reasoning style, read the four records in
`sft_training_data/CTL_LoRAT_fix_this_code_think.json` (`fixthiscc4_133` through
`fixthiscc4_136`) — their `reasoning_content` is well-judged at 163–202 words, though they
write their answers as prose rather than an enumerated list.

## Format

```
PROBLEMS FIXED:
  1. <construct> — <mechanism with its qualifier> — <consequence against requirement N>
  2. ...

CORRECTED CODE:
```ctl
//#CTL2
...
```
```

The corrected code is the complete transform: every function the component contract
requires, not only the ones that changed. Check `references/componet_contracts.md` — a
Rollup needs all five lifecycle functions even when four are untouched.

The list contains the correct-but-suspicious affirmations alongside the defects, numbered
in one sequence — an item is not necessarily a defect, and that is the point.

Number the items and reference the requirement each one bears on by its number. That
grounding is cheap and it is what keeps the explanation anchored to the specification
rather than drifting into general commentary.

### Every record must carry `reasoning_content` — this is not optional

**Write a `reasoning_content` field on every one of the 24 records.** `content` holds the
answer, `reasoning_content` holds the thinking, and `convert_think.py` merges them. Never
hand-write `<think>` tags: the merge needs an exact literal spelling and a hand-typed
variant fails silently, training the reasoning with loss where it should carry none.

**Why it is mandatory here.** The pipeline builds two datasets. Phase 1 trains on every
record, answers only. Phase 3 trains *only* on records that have reasoning, runs last, and
sets the shape of the answer the model actually produces. The gap is far worse in phase 3:

| | fix-like records | of the task shape above |
|---|---|---|
| phase 1 (11797 records) | 1222 (10.4%) | 9 |
| **phase 3 (1053 records)** | 90 (8.5%) | **0** |

Phase 3 has never seen a single record of this shape. Records written without
`reasoning_content` land in phase 1 only and leave that zero untouched — fixing the phase
that is not driving the problem. With reasoning on all 24, phase 3 goes from 0 to 24.

**What the reasoning should say.** Walk the specification against the code, requirement by
requirement, and reach each defect the way a reviewer would: read requirement 3, look at
what the code does for that field, notice the divergence, work out what reaches the output.
Reason about the *behaviour* — what the value is at that line, what happens when the field
is null, what the arithmetic produces — rather than narrating the code. Name the fields and
functions of that specific record; a trace that would fit any record teaches nothing.
**Reach the correct-but-suspicious construct in the trace too**, and reach it the same
way — look at it, work out what it actually does, conclude it is fine. Only 6 of the first
batch's 24 traces did this; it is mandatory, not a flourish. A trace that finds a defect in
every construct it examines teaches the model that every construct it examines is
defective. Around 250–350 tokens is right, and the length
must come from grounding, not restatement.

### Record fields

Every record needs `id`, `messages`, `component`, and `source_file` / `source_index` /
`source_id` where it derives from an existing record (leave them out where it does not).
Use the `id` prefix `fixtospec_`.

## Verification

Run from the repository root. All five checks must pass.

```python
import json, re, statistics as st

R = json.load(open('sft_training_data/CTL_LoRAT_fix_to_spec.json'))
asst = lambda e: ''.join(m.get('content','') or '' for m in e['messages'] if m['role']=='assistant')
rea  = lambda e: ''.join(m.get('reasoning_content','') or '' for m in e['messages'] if m['role']=='assistant')
user = lambda e: next(m['content'] for m in e['messages'] if m['role']=='user')

print('records (want 28: the 24 amended + 4 untouched older ones):', len(R))
print('ids preserved (want 24 fixtospec_*):',
      sum(1 for e in R if str(e.get('id','')).startswith('fixtospec_')))

# 1. reasoning on every record, and no hand-written tags anywhere
print('missing reasoning_content (want 0):', [e['id'] for e in R if not rea(e).strip()])
print('hand-written <think> (want 0):',
      sum(1 for e in R if '<think>' in asst(e) or '<think>' in rea(e)))

# 2. the length floor — the check this document exists for
bad = []
for e in R:
    prose = re.sub(r'```.*?```', '', asst(e), flags=re.S)
    items = re.findall(r'^\s*\d+[.)]\s+\S.*$', prose, re.M)
    if not items:
        bad.append((e['id'], 'no enumerated items')); continue
    w = len(prose.split()) / len(items)
    short = [i for i in items if len(i.split()) < 35]
    if short:
        bad.append((e['id'], f'{len(short)} of {len(items)} items under 35 words'))
print('records failing the 35-word floor (want 0):', bad)

# 3. defect-count distribution
from collections import Counter
counts = Counter(len(re.findall(r'^\s*\d+[.)]\s+\S',
                 re.sub(r'```.*?```','',asst(e),flags=re.S), re.M)) for e in R)
print('defects per record (want 3:6, 4:8, 5:7, 6:3):', dict(sorted(counts.items())))

# 4. order — reasons before code, and the code is complete and fenced
print('code before the list (want 0):',
      [e['id'] for e in R if asst(e).index('```') < (asst(e).find('1.') if '1.' in asst(e) else 10**9)])
print('answers with no //#CTL2 header (want 0):',
      [e['id'] for e in R if '//#CTL2' not in asst(e)])

# 5. the prompt actually carries a numbered specification and broken code
print('prompts with no numbered spec (want 0):',
      [e['id'] for e in R if len(re.findall(r'^\s*\d+[.)]\s+\S', user(e), re.M)) < 4])
print('prompts with no code block (want 0):', [e['id'] for e in R if '```' not in user(e)])

# 6. NEW — every record affirms at least one construct as already correct,
#    in the answer AND in the reasoning
OK = re.compile(r'correct as written|already correct|is correct and|needs no change|'
                r'not a defect|no change (is )?(needed|required)', re.I)
print('answers with no already-correct affirmation (want 0):',
      [e['id'] for e in R if not OK.search(re.sub(r'```.*?```','',asst(e),flags=re.S))])
print('reasoning with no already-correct affirmation (want 0):',
      [e['id'] for e in R if not OK.search(rea(e))])

# 7. NEW — minimal repair: every changed line should trace to an enumerated item.
#    This prints the change ratio for a human to eyeball; a record rewriting most of
#    the transform needs a stated reason in its list, so inspect anything over ~50%.
import difflib
def last_code(t):
    m = re.findall(r'```(?:ctl)?\n(.*?)```', t, re.S)
    return m[-1] if m else ''
for e in R:
    b = [l.strip() for l in last_code(user(e)).strip().splitlines() if l.strip()]
    c = [l.strip() for l in last_code(asst(e)).strip().splitlines() if l.strip()]
    if not b or not c: continue
    sm = difflib.SequenceMatcher(None, b, c)
    ch = sum(max(i2-i1, j2-j1) for tag,i1,i2,j1,j2 in sm.get_opcodes() if tag != 'equal')
    pct = 100*ch/len(b)
    if pct > 50:
        print(f'  INSPECT {e["id"]}: {pct:.0f}% of lines changed — is every change in the list?')

# uniqueness
print('duplicate prompts (want 0):',
      len(R) - len({' '.join(user(e).split()) for e in R}))
```

Then confirm the corpus-level effect, from the repository root:

```python
import json, glob, re
FIX  = re.compile(r'\b(fix|correct|repair|debug)\w*\b', re.I)
SPEC = re.compile(r'\bspecification\b|\bspec\b|\brequirements?\b', re.I)
def load(f):
    d = json.load(open(f))
    return d if isinstance(d, list) else (d.get('examples') or d.get('records') or [])
p3 = shaped = 0
for f in glob.glob('sft_training_data/*.json'):
    if 'DPO' in f: continue
    for e in load(f):
        if not isinstance(e, dict) or not e.get('messages'): continue
        r = ''.join(m.get('reasoning_content','') or '' for m in e['messages'] if m['role']=='assistant')
        if not r.strip(): continue
        p3 += 1
        u = next((m.get('content','') for m in e['messages'] if m['role']=='user'), '')
        a = ''.join(m.get('content','') or '' for m in e['messages'] if m['role']=='assistant')
        n = len(re.findall(r'^\s*(?:[-*]|\d+[.)])\s+\S', re.sub(r'```.*?```','',a,flags=re.S), re.M))
        if FIX.search(u) and '```' in u and '```' in a and n >= 3 and SPEC.search(u):
            shaped += 1
print(f'phase 3: {p3} records, {shaped} of the fix-to-spec shape  (was 1053 / 0; want ~24)')
```

Finally, regenerate the merged corpora with `utils/convert_think.py` and confirm the new
records appear in both the phase-1 and phase-3 files with balanced `<think>` tags.

---

## Internal tracking (not part of the generation brief above)

Benchmark coverage: `T39` (Reformat, compiled, 4 seeded defects — one compile error and
three semantic) and `T40` (Denormalizer, 4 seeded defects). These are the two `fix`-type
tests added to `ctl2_test_suite_v4.json`, and they are the weakest tests for every model
measured (0.44–0.79, none above 0.8).

Failure signature that motivated this spec, from findings §3.10: across `qwen38_fix5` and
`qwen38_fix5_p3ck100`, every T39/T40 finding scored `WRONG`, never `MISSED` — the model
enumerates and explains incorrectly. Words-per-issue tracks the score directly:

| model | words/issue | fix score |
|---|---|---|
| fix3 | 27 | 0.792 |
| fix5 | 26 | 0.610 |
| fix5 @ p3 ckpt-100 | 17 | 0.440 |

Specific rubric items that fail repeatedly: `T39.B3` (date mask `mm` is minutes, not
months — 3 of 5 runs WRONG in both models), `T40.B1` and `T40.B4`. B3 and B4 are both
cases where the terse statement is a true fact stripped of the qualifier that made it
true, which is the §3.8 mechanism operating on this task.

Do not cite test IDs in the brief above — the generating agent must not be able to target
the benchmark.
