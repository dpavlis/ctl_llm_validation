# Fix spec round 2 — invented / malformed functions in the training corpus

Scope: **2 bugs, 4 records**, plus **1 catalog gap**.
Audited against the combined corpus of 11468 records (11016 non-reasoning + 452 reasoning).

Round 1 (`results/data_fix_spec_20260918.md`) is fully applied and verified — see
*Already fixed* at the end. This round covers what a corrected sweep found afterwards.

**Where to apply.** Fix these in the original per-dataset source files on the authoring
machine, then re-combine and re-upload. The combined corpus on the training host is a
derived artifact — edits made there are silently overwritten by the next upload.

Every record below is identified by `source_file` + `source_index` + `source_id`. Those
fields are added during combining (`dpo_forge/loader.py:206`) and do not exist in the source
files themselves, which carry only `id` and `messages`.

**`source_index` is the zero-based array position within its source file**, so it addresses
the record directly upstream. Verified for both files below: their `source_index` values run
contiguously from 0 to n−1 with no gaps.

| source file | records upstream | to fix |
|---|---|---|
| `CTL_LoRA_dynamic_field_functions.json` | 70 (idx 0–69) | 3 |
| `CTL_LoRA_component_suggest_1.json` | 253 (idx 0–252) | 1 |

Each fix below also quotes the exact line to change, so a record can be located by content
if indices have shifted since this audit.

> **Do not fix in `data/sft_input/` on the training host.** That directory is not the
> pipeline input. Neither file above is present there, and of the files that are, one is
> stale against the corpus (20 records locally vs 22 in the combined data) and another
> contributes zero records. Treat it as unrelated scratch.

---

## BUG-4 — three function declarations missing the `function` keyword

| | |
|---|---|
| `source_file` | `CTL_LoRA_dynamic_field_functions.json` |
| `source_index` | 1, 11, 19 |
| `source_id` | `dynamicf90_1`, `dynamicf90_11`, `dynamicf90_19` |

Every CTL2 function definition must begin with `function`. These three omit it, so the
declaration does not compile.

| source_index | current | replacement |
|---|---|---|
| 1  | `integer findFirstExisting(record r, string[] names) {`    | `function integer findFirstExisting(record r, string[] names) {` |
| 11 | `string firstExistingNonNull(record r, string[] names) {`  | `function string firstExistingNonNull(record r, string[] names) {` |
| 19 | `integer firstDiscountIdx(record r) {`                     | `function integer firstDiscountIdx(record r) {` |

Prepend the keyword only. Change nothing else on the line or in the body.

**Why this is the whole fix.** The corpus declares functions **8181** times with the
keyword and **3** times without — these three. Everything else in the bodies checks out:
`getFieldIndex`, `getDecimalValue` and `isNull(record, index)` are all catalogued, and
`record` as a parameter type appears in 11 places across 9 records including
`dynamicf90_25` and `dynamicf90_32`, which use the keyword correctly. So `record` is an
established corpus pattern and is **out of scope here** — it has not been verified against
the CTL2 grammar either way, and changing it is a separate question.

---

## BUG-5 — `lowercase()` should be `lowerCase()`

| | |
|---|---|
| `source_file` | `CTL_LoRA_component_suggest_1.json` |
| `source_index` | 119 |
| `source_id` | `componene2_119` |

The CTL2 function is `lowerCase` (capital C) — 9 catalog hits for `"lowerCase"`, zero for
`"lowercase"`. `resources/ctl2-basics.md:1314` lists `toLowerCase`→`lowerCase` among the
top hallucinations, and wrong casing is the same defect class.

**Current** (assistant `ctl` block, DataGenerator email construction):
```ctl
    $out.0.email = lowercase(firstNames[fnIdx]) + "." +
    lowercase(lastNames[lnIdx]) + counter + "@" + domains[dmIdx];
```

**Replace with:**
```ctl
    $out.0.email = lowerCase(firstNames[fnIdx]) + "." +
    lowerCase(lastNames[lnIdx]) + counter + "@" + domains[dmIdx];
```

Two occurrences, same record, same line pair.

---

## CATALOG-1 — `formatMessageWithLocale` is missing from the function library

**Not a training-data bug. Do not edit the 5 records that use it.**

`formatMessageWithLocale` appears 11 times across `stringfue9_134`, `stringfue9_135`,
`stringfue9_136`, `trainingb9_160` and one other. It has no entry in
`resources/ctl-function-library.json`, but the catalog's own prose names it as real, in the
`formatMessage` description:

> "The formatMessage and formatMessageWithLocale functions support using multi-line
> strings as the template…"

So the catalog is incomplete, not the corpus. Add an entry for it. This matters beyond
tidiness: the review judge is offered the catalog as a tool, so a missing entry invites a
false positive against correct code.

---

## Verified NOT bugs — do not re-open

My first sweep reported these as invented built-ins. That was a **scanner defect, not a
data defect**, and the finding was wrong:

| reported | reality |
|---|---|
| `parseVersion`, `parseMoney`, `parseCron`, `convertAllFields`, `parseAddress`, `parseDN`, `convertKeysToCamelCase` | All defined in the same answer, e.g. `function map[string, variant] parseVersion(string version) {`. Legitimate helper functions. |
| `toTitleCase` (`trainingb9_97`) | Supplied by `import "lib/utils.ctl";` in the same snippet, and the comment says so. |
| `rounded`, `entry`, `policy`, `characters`, `warn` | Text inside string literals — `"Subtotal rounded (roundHalfToEven): "`, `"(?i)warn(ing)?"` — never calls. |
| `lowercase` in `bridgese8a_40`, `conversa78_1255`, `fixthiscc4_40`, `fixthiscc4_55` | English prose ("convert strings to lowercase … with `lowerCase()`"), or a `CTL_LoRA_fix_this_code` record quoting `lowercase(` precisely to teach that it is wrong. Only `componene2_119` calls it in real code. |

Two scanner faults caused this:

1. Local-definition detection used `function\s+[\w\[\]]+\s+(\w+)\s*\(`, which cannot match a
   generic return type such as `map[string, variant]` (space and comma), so every helper
   returning a map looked undefined.
2. Comments were stripped but **string literals were not**, so any `word (` inside a message
   or regex looked like a call.
3. Scanning whole assistant turns rather than just ```` ```ctl ```` blocks pulls in prose and,
   worse, the `CTL_LoRA_fix_this_code` records, which quote broken CTL on purpose. Always
   scan code blocks only, or a correct teaching example reads as a defect.

Use this scanner for future sweeps:

```python
import json, re, collections
cat = set(json.load(open('resources/ctl-function-library.json')))   # or extracted name set
KW = {'if','for','while','switch','return','function','catch','try','else','import','new',
      'integer','string','decimal','long','double','boolean','date','byte','list','map',
      'variant','void','number','printErr','printLog','raiseError','lookup','sequence',
      'true','false','null','CTL2','foreach'}
DEF = re.compile(r'function\s+[A-Za-z_][\w\[\]<>,\s]*?\s+(\w+)\s*\(')   # generic return types
def strip_code(b):
    b = re.sub(r'/\*.*?\*/', '', b, flags=re.S)
    b = "\n".join(re.sub(r'//.*$', '', l) for l in b.split("\n"))
    return re.sub(r'"(?:[^"\\]|\\.)*"', '""', b)                        # blank string literals
```

Match calls with `(?<![\w.$"])([a-zA-Z_]\w*)\s*\(`, and build the local-definition set from
the **whole conversation** (user turns can define helpers too), not the assistant turn alone.

---

## Verification

Run against the original source datasets (preferred — that is where the fix lands), or
against a combined corpus, by passing whichever files apply:

```bash
python3 check_round2.py CTL_LoRA_dynamic_field_functions.json CTL_LoRA_component_suggest_1.json
# or, post-combine:  python3 check_round2.py <combined>.json [<combined_think>.json]
```

```python
import json, re, sys
# source files carry only id/messages; source_id and source_index appear after combining
D = [(f, i, e) for f in sys.argv[1:] for i, e in enumerate(json.load(open(f)))]
tag = lambda f, i, e: e.get('source_id') or f"{f}#{e.get('source_index', i)}"
a = lambda e: "\n".join(m.get('content','') for m in e['messages'] if m['role']=='assistant')
TYPES = r'(?:integer|long|string|decimal|number|double|boolean|date|void|variant|byte|cbyte)'
noky = [tag(f, i, e) for f, i, e in D for b in re.findall(r'```ctl\n(.*?)```', a(e), re.S)
        for l in b.split("\n")
        if re.match(TYPES + r'(?:\[[^\]]*\])?\s+\w+\s*\([^;]*\)\s*\{\s*$', l.strip())]
# code blocks only -- prose says "lowercase" in English, and CTL_LoRA_fix_this_code
# records quote lowercase( precisely to teach that it is wrong
low  = [tag(f, i, e) for f, i, e in D for b in re.findall(r'```ctl\n(.*?)```', a(e), re.S)
        if re.search(r'(?<![\w.])lowercase\s*\(', b)]
print("BUG-4  declarations missing 'function':", len(noky), "(want 0)", noky)
print("BUG-5  lowercase( in ctl blocks       :", len(low),  "(want 0)", low)
print("records scanned                      :", len(D))
```

Also confirm the three BUG-4 bodies are otherwise untouched, and that no records were lost
in the edit — the two source files above hold their original record counts, and the combined
corpus still totals 11468 (11016 + 452) after the next upload.

---

## Already fixed (round 1, verified 2026-09-19)

- **BUG-1** `llmaugmec4_973` — the `isnull($in.0) // is the record null?` line is gone, and a
  counter-example was added (`isnull($in.1)` marked WRONG for JOIN no-match detection).
- **BUG-2** `componen9c_3/6/7/19` — `randomDouble()` → `random()`, a real catalog function.
  Note that round 1's recommendation of `randomDecimal` was **wrong on the type argument**:
  `ctl2-basics.md:231` states `decimal` combined with `number` evaluates to `decimal`, and
  assigning `number` into a `decimal` field is valid widening. `random() * 490.0D + 10.0D`
  is type-correct as written, and all four ranges match their prompts.
- **BUG-3** `nullcmp_partition_tv_02` — unreachable code retagged `[WARNING]` → `[ERROR]`;
  0 WARNING vs 26 ERROR corpus-wide. The duplicate `nullcmp_sft_10` was dropped.
