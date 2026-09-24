# Fix list — multi-defect reasoning records

Generated 2026-09-24. Keyed to `source_file` / `source_id` / `source_index` so it can be
applied to the originals in `sft_training_data/`, not to the merged corpus.

**The fix is to the `reasoning_content` field in the source records** (pre-`convert_think.py`),
plus the `content` answers where noted. Do not hand-edit `<think>` tags.

---

## Scope: one file

Of the 35 multi-defect records now in the corpus, the problem is confined to the 30 new ones:

| source_file | records | distinct defect kinds / slots | reasoning sentences verbatim-repeated | issue lines verbatim-repeated | ERROR:WARNING |
|---|---|---|---|---|---|
| `CTL_LoRAT_multibug_validate_thinking.json` | 30 | 23 / 145 | 91% | 48% | 3.83 |
| `CTL_LoRAT_validate_thinking.json` | 4 | 16 / 17 | 55% | 0% | 1.0 |
| `CTL_LoRAT_sft_misc_new_think.json` | 1 | 4 / 4 | 0% | 0% | 3.0 |

`CTL_LoRAT_validate_thinking.json` and `CTL_LoRAT_sft_misc_new_think.json` are fine — leave them alone. **All the work
below is in `CTL_LoRAT_multibug_validate_thinking.json`.**

---

## What is wrong

### 1. The 30 records are ~6 templates with field names permuted  *(primary)*

- **91% of reasoning sentences are verbatim repeats** across records:
  453 sentences, only 118 distinct.
- **48% of issue lines are verbatim repeats**: 145 lines,
  94 distinct.
- 145 defect slots are drawn from only **23 distinct defect kinds**
  (counting a construct as the same kind when only the field name or literal differs).

Most-reused defect kinds (`FIELD` = any `$in.N.x`/`$out.N.x`, `STR` = any string literal):

| times used | defect kind |
|---|---|
| 9 | `FIELD / FIELD` |
| 8 | `replace(FIELD, STR, STR)` |
| 8 | `STR + FIELD` |
| 8 | `FIELD = FIELD` |
| 7 | `size(FIELD)` |
| 7 | `BIGNUM` |
| 7 | `FIELD / 2` |
| 7 | `FIELD` |
| 7 | `substring(FIELD, 0, 3)` |
| 7 | `sha1(FIELD)` |
| 6 | `isNull(FIELD)` |
| 6 | `FIELD > 100D` |

Even the example data is shared — `AB.CD-17` is the worked example in 8 records. The closing
formula `"N ERRORs and 1 WARNING; FAIL."` appears in 23 of 30.

Most-repeated reasoning sentences:

- **×13** — 3 ERRORs and 1 WARNING; FAIL.
- **×10** — 4 ERRORs and 1 WARNING; FAIL.
- **×8** — replace interprets the pattern as regex.
- **×8** — A single dot matches A, B, the period, and every remaining character in AB.CD-17, so almost the whole identifier is replaced.
- **×8** — The intended escaped dot would match the one punctuation character only.
- **×8** — Follow that row through the + operator: CTL2 concatenates null as the four letters null, giving Ref:null.
- **×8** — The requested null-row display is Ref: alone, so the emitted string is demonstrably wrong despite compiling.
- **×7** — Searching the built-ins finds no size function, while the identifier is declared string, so this is a name-resolution failure rather than a nullable-v
- **×7** — The output integer type is otherwise compatible.
- **×7** — The destination is long, but the literal is classified before assignment.

**Why it matters.** 30 records built from ~6 templates do not give 30 records of signal. Verbatim
sentence reuse at 91% is a memorisation target: the model can learn to emit these exact strings
when it sees a multi-defect prompt, which is the opposite of learning to explain a defect it has
not seen. It also undercuts the reason the records exist — the per-finding word floor is supposed
to buy *grounding*, and identical boilerplate across records is not grounding.

### 2. ERROR:WARNING is 3.83:1 in this file  *(watch, do not fix by relabelling)*

Severities in this file: {'ERROR': 115, 'WARNING': 30}. That pulls the whole reasoning corpus from 1.76:1 to
2.28:1, against the ~1.3:1 the targeted-examples spec asked for.

**The individual labels are correct — I verified them and they should not be changed.** Spot checks
against `resources/ctl-function-library.json` and the suite rubric:

- `size()` genuinely is not in the library → ERROR is right.
- `sha1()` returns byte and `sha1HexString()` exists alongside `md5HexString`/`sha256HexString`
  → the finding and its suggested fix are both right.
- `substring(arg, fromIndex, length)` → the third-parameter claim is right.
- Null concat and `~=`: the suite rubric marks these "WARNING minimum" and "WARNING or ERROR",
  so ERROR is acceptable and not a rubric violation.

So the skew is a property of the *content* — code seeded with 4-7 independent defects is genuinely
error-dense — not a labelling mistake. **Rebalance by adding WARNING-side defects to the mix, not
by relabelling correct ERRORs.** Downgrading a true compile error to WARNING would make the data wrong.

### 3. Reasoning length  *(low confidence, probably fine)*

Reasoning runs ~52 tokens per defect against the `explanation_budget_spec.md` figure of 240 + 120
per extra defect. **I do not think this needs fixing.** Reading the traces, they do address every
defect in order with the correct mechanism and a concrete consequence; the budget formula in the
spec was written before any multi-defect trace existed and is too generous — a per-defect segment
does not need to repeat the framing overhead a single-defect trace carries. Treat the spec figure
as wrong rather than the data.

One thing worth changing anyway: the traces refer to fields generically ("the key field is non-null
by metadata") rather than by name. Naming the field costs a few words and is what makes a segment
specific to its record instead of reusable boilerplate — it addresses issue 1 directly.

---

## The reference to copy: `CTL_LoRAT_validate_thinking.json`

Its 4 multi-defect records are what the multibug file should look like: 17 defect slots across
16 distinct kinds, 0% issue-line reuse, ERROR:WARNING 1.0.
Same format, same floor, no templating. Use them as the standard when regenerating.

---

## What to do

Regenerate the 30 records in `CTL_LoRAT_multibug_validate_thinking.json`, keeping the format and the per-finding word floor, and:

1. **Raise defect-kind diversity from 23 to 60+.** No defect kind should appear more than 3 times
   across the file. The `explanation_budget_spec.md` defect menu (wrong arity, overflow literals,
   null dereference, unreachable code, undeclared output field, nullable concat, whole-string vs
   substring matching, unguarded division, mode-dependent constructs, type mismatches) is wider
   than what was used — most records currently draw from the same six.
2. **No verbatim sentence reuse across records.** Each defect gets an explanation written for its
   own record, naming its own field and its own worked example. Retire `AB.CD-17` as the universal
   example and drop the `"N ERRORs and 1 WARNING; FAIL."` closing formula.
3. **Rebalance to roughly 2:1 ERROR:WARNING within this file** by seeding more valid-but-suspicious
   constructs, not by relabelling. Good WARNING-side material: format-pattern letter case, dead
   stores, implausible-but-valid literals, redundant defensive guards, naming inconsistencies.
4. **Name the field in the reasoning** rather than referring to "the key field" / "the nullable metadata".

Record-by-record inventory follows so you can see which templates each one came from.

---

## Inventory — `CTL_LoRAT_multibug_validate_thinking.json`

| source_id | idx | findings | severities | reasoning tok | defect kinds |
|---|---|---|---|---|---|
| `multibug_001` | 0 | 4 | EEEW | 204 | `isNull(FIELD)`, `FIELD > 100D`, `FIELD ~= STR`, `nvl(FIELD, STR)` |
| `multibug_002` | 1 | 4 | EEEW | 241 | `size(FIELD)`, `FIELD / FIELD`, `replace(FIELD, STR, STR)`, `trim(trim(FIELD))` |
| `multibug_003` | 2 | 4 | EEEW | 204 | `BIGNUM`, `STR + FIELD`, `FIELD / 2`, `upperCase(upperCase(FIELD)` |
| `multibug_004` | 3 | 4 | EEEW | 208 | `FIELD`, `substring(FIELD, 0, 3)`, `if(FIELD > 0, true, false)`, `isnull(FIELD) || FIELD == ` |
| `multibug_005` | 4 | 4 | EEEW | 238 | `FIELD++`, `date2num(str2date(FIELD, S`, `sha1(FIELD)`, `str2date(STR, STR)` |
| `multibug_006` | 5 | 4 | EEEW | 206 | `FIELD = FIELD`, `FIELD / FIELD`, `FIELD ~= STR`, `nvl(FIELD, 0D)` |
| `multibug_007` | 6 | 4 | EEEW | 201 | `isNull(FIELD)`, `replace(FIELD, STR, STR)`, `substring(FIELD, 0, 3)`, `trim(trim(FIELD))` |
| `multibug_008` | 7 | 4 | EEEW | 209 | `size(FIELD)`, `FIELD > 100D`, `STR + FIELD`, `nvl(FIELD, STR)` |
| `multibug_009` | 8 | 4 | EEEW | 234 | `BIGNUM`, `FIELD / 2`, `date2num(str2date(FIELD, S`, `upperCase(upperCase(FIELD)` |
| `multibug_010` | 9 | 4 | EEEW | 212 | `FIELD`, `if(FIELD > 0, true, false)`, `sha1(FIELD)`, `isnull(FIELD) || FIELD == ` |
| `multibug_011` | 10 | 4 | EEEW | 209 | `FIELD++`, `FIELD ~= STR`, `FIELD / FIELD`, `str2date(STR, STR)` |
| `multibug_012` | 11 | 4 | EEEW | 232 | `FIELD = FIELD`, `replace(FIELD, STR, STR)`, `STR + FIELD`, `nvl(FIELD, 0D)` |
| `multibug_013` | 12 | 4 | EEWE | 198 | `isNull(FIELD)`, `substring(FIELD, 0, 3)`, `nvl(FIELD, STR)`, `FIELD = FIELD` |
| `multibug_014` | 13 | 5 | EEEEW | 268 | `size(FIELD)`, `BIGNUM`, `FIELD > 100D`, `contains(FIELD, FIELD)`, `trim(trim(FIELD))` |
| `multibug_015` | 14 | 5 | EEEEW | 258 | `FIELD`, `FIELD / FIELD`, `STR + FIELD`, `replace(FIELD, STR, STR)`, `upperCase(upperCase(FIELD)` |
| `multibug_016` | 15 | 5 | EEEEW | 285 | `if(FIELD > 0, true, false)`, `FIELD / 2`, `date2num(str2date(FIELD, S`, `sha1(FIELD)`, `isnull(FIELD) || FIELD == ` |
| `multibug_017` | 16 | 5 | EEEEW | 256 | `FIELD++`, `FIELD = FIELD`, `substring(FIELD, 0, 3)`, `FIELD ~= STR`, `str2date(STR, STR)` |
| `multibug_018` | 17 | 5 | EEEEW | 254 | `isNull(FIELD)`, `BIGNUM`, `replace(FIELD, STR, STR)`, `FIELD / FIELD`, `nvl(FIELD, 0D)` |
| `multibug_019` | 18 | 5 | EEEEW | 257 | `size(FIELD)`, `FIELD`, `FIELD > 100D`, `FIELD / 2`, `nvl(FIELD, STR)` |
| `multibug_020` | 19 | 5 | EEEEW | 260 | `sha1(FIELD)`, `STR + FIELD`, `date2num(str2date(FIELD, S`, `contains(FIELD, FIELD)`, `trim(trim(FIELD))` |
| `multibug_021` | 20 | 5 | EEEEW | 290 | `FIELD++`, `if(FIELD > 0, true, false)`, `FIELD ~= STR`, `FIELD > 100D`, `upperCase(upperCase(FIELD)` |
| `multibug_022` | 21 | 5 | EEEEW | 265 | `BIGNUM`, `FIELD = FIELD`, `FIELD / FIELD`, `replace(FIELD, STR, STR)`, `isnull(FIELD) || FIELD == ` |
| `multibug_023` | 22 | 5 | EEEWE | 254 | `size(FIELD)`, `STR + FIELD`, `date2num(str2date(FIELD, S`, `str2date(STR, STR)`, `FIELD = FIELD` |
| `multibug_024` | 23 | 6 | EEEEEW | 292 | `isNull(FIELD)`, `FIELD`, `FIELD / 2`, `sha1(FIELD)`, `substring(FIELD, 0, 3)`, `nvl(FIELD, 0D)` |
| `multibug_025` | 24 | 6 | EEEEEW | 350 | `BIGNUM`, `FIELD > 100D`, `FIELD / FIELD`, `contains(FIELD, FIELD)`, `replace(FIELD, STR, STR)`, `nvl(FIELD, STR)` |
| `multibug_026` | 25 | 6 | EEEEEW | 309 | `size(FIELD)`, `if(FIELD > 0, true, false)`, `STR + FIELD`, `date2num(str2date(FIELD, S`, `FIELD = FIELD`, `trim(trim(FIELD))` |
| `multibug_027` | 26 | 6 | EEEEEW | 300 | `FIELD++`, `FIELD`, `substring(FIELD, 0, 3)`, `FIELD / 2`, `sha1(FIELD)`, `upperCase(upperCase(FIELD)` |
| `multibug_028` | 27 | 6 | EEEEEW | 325 | `isNull(FIELD)`, `BIGNUM`, `FIELD / FIELD`, `STR + FIELD`, `FIELD ~= STR`, `isnull(FIELD) || FIELD == ` |
| `multibug_029` | 28 | 7 | EEEEEEW | 358 | `size(FIELD)`, `FIELD`, `contains(FIELD, FIELD)`, `replace(FIELD, STR, STR)`, `FIELD / 2`, `sha1(FIELD)`, `str2date(STR, STR)` |
| `multibug_030` | 29 | 6 | EEEEEW | 342 | `FIELD++`, `FIELD = FIELD`, `substring(FIELD, 0, 3)`, `if(FIELD > 0, true, false)`, `FIELD / FIELD`, `nvl(FIELD, 0D)` |

Severity column: `E`=ERROR, `W`=WARNING, `I`=INFO, in the order the findings appear.

---

## Verification after regeneration

```python
import json, re, collections
R = json.load(open('CTL_LoRAT_multibug_validate_thinking.json'))   # source file, pre-convert
ans = lambda e: ''.join(m.get('content','') for m in e['messages'] if m['role']=='assistant')
rea = lambda e: ''.join(m.get('reasoning_content','') for m in e['messages'] if m['role']=='assistant')

def lines(a):
    b = a.split('ISSUES:',1)[1].split('SUGGESTIONS:')[0].split('VERDICT:')[0]
    return [' '.join(l.split()) for l in b.splitlines() if re.match(r'\s*\[(ERROR|WARNING|INFO)\]', l)]
def kind(c):
    c = re.sub(r'\$(in|out)\.\d+\.\w+','FIELD',c); c = re.sub(r'"[^"]*"','STR',c)
    return ' '.join(re.sub(r'\b\d{4,}\b','BIGNUM',c).split())

L = [lines(ans(e)) for e in R]
K = collections.Counter(kind(re.search(r'`([^`]+)`', l).group(1)) for ls in L for l in ls if '`' in l)
print('defect kinds:', len(K), 'distinct /', sum(K.values()), 'slots   (want >=60 distinct)')
print('any kind used >3 times (want none):', [(k,n) for k,n in K.items() if n>3])

S = collections.Counter()
for e in R:
    for s in re.split(r'(?<=[.])\s+', rea(e)):
        s = ' '.join(s.split())
        if len(s.split()) >= 6: S[s] += 1
print('reasoning sentences verbatim-repeated: %d%% (want 0)' %
      (100*sum(n for n in S.values() if n>1)/max(1,sum(S.values()))))

sev = collections.Counter(re.match(r'\[(\w+)\]', l).group(1) for ls in L for l in ls)
print('ERROR:WARNING = %.2f  (want ~2.0)' % (sev['ERROR']/max(1,sev['WARNING'])))
short = [len(l.split()) for ls in L for l in ls if len(l.split()) < 35]
print('issue lines under the 35-word floor (want 0):', len(short))
```

Then rebuild the combined corpora and re-run the dedup/self-containment pre-flight before training.