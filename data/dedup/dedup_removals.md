# Corpus deduplication — removal list

Generated 2026-09-24 against the **combined** corpora, so they can be deduplicated
in place without re-merging from sources.

- `CTL_LoRA_training_data.json` — 11827 records
- `CTL_LoRA_training_data_think.json` — 1036 records

Records are identified by their top-level `id`, which is unique in both files (verified: 11827/11827 and 1036/1036).

## How to apply

`dedup_removals.json` is the machine-readable form. Section 1 below is safe to apply
as-is; section 2 needs a decision per prompt.

```python
import json
D = json.load(open('dedup_removals.json'))
drop = {(r['file'], r['id']) for r in D['removals']}   # section 1 only
for fn in (D['phase1_file'], D['think_file']):
    R = json.load(open(fn))
    R = [e for e in R if (fn, e['id']) not in drop]
    json.dump(R, open(fn, 'w'), indent=1, ensure_ascii=False)
```

**Invariant that must hold after any removal:** every prompt in the think corpus must
still be present in the phase-1 corpus — `configs/qwen38.yaml`'s `sft:` section trains
one self-contained dataset and depends on it. The section-1 list preserves this (checked:
0 orphans). Re-check it after applying any section-2 decision.

---

## 1. Safe to remove automatically — 78 records

| file | category | records |
|---|---|---|
| `CTL_LoRA_training_data.json` | AUTO-1 | 32 |
| `CTL_LoRA_training_data.json` | AUTO-2 | 14 |
| `CTL_LoRA_training_data_think.json` | AUTO-1 | 32 |

- **AUTO-1 (64)** — same prompt *and* byte-identical answer as an earlier record. Pure
  duplication; the only effect of keeping them is double-weighting that prompt in training.
- **AUTO-2 (14)** — same prompt, *different* answer, where one variant is exactly the
  reasoning-corpus answer and the others are not. The reasoning corpus is treated as
  authoritative (same premise as `dedup_reasoning.py`), so the competitors go. This is the
  pattern that caused the 2026-09-21 regression — 115 prompts then, 11 now.

### `CTL_LoRA_training_data.json` — 46 to remove

| remove id | idx | cat | keep instead | reason |
|---|---|---|---|---|
| `akmrx-609` | 608 | AUTO-1 | `akmrx-11` | identical answer to an earlier record with the same prompt |
| `akmrx-610` | 609 | AUTO-1 | `akmrx-12` | identical answer to an earlier record with the same prompt |
| `akmrx-611` | 610 | AUTO-1 | `akmrx-13` | identical answer to an earlier record with the same prompt |
| `akmrx-612` | 611 | AUTO-1 | `akmrx-14` | identical answer to an earlier record with the same prompt |
| `akmrx-613` | 612 | AUTO-1 | `akmrx-15` | identical answer to an earlier record with the same prompt |
| `akmrx-614` | 613 | AUTO-1 | `akmrx-16` | identical answer to an earlier record with the same prompt |
| `akmrx-615` | 614 | AUTO-1 | `akmrx-17` | identical answer to an earlier record with the same prompt |
| `akmrx-616` | 615 | AUTO-1 | `akmrx-18` | identical answer to an earlier record with the same prompt |
| `akmrx-617` | 616 | AUTO-1 | `akmrx-19` | identical answer to an earlier record with the same prompt |
| `akmrx-618` | 617 | AUTO-1 | `akmrx-20` | identical answer to an earlier record with the same prompt |
| `akmrx-619` | 618 | AUTO-1 | `akmrx-21` | identical answer to an earlier record with the same prompt |
| `akmrx-620` | 619 | AUTO-1 | `akmrx-22` | identical answer to an earlier record with the same prompt |
| `akmrx-621` | 620 | AUTO-1 | `akmrx-23` | identical answer to an earlier record with the same prompt |
| `akmrx-622` | 621 | AUTO-1 | `akmrx-24` | identical answer to an earlier record with the same prompt |
| `akmrx-623` | 622 | AUTO-1 | `akmrx-25` | identical answer to an earlier record with the same prompt |
| `akmrx-624` | 623 | AUTO-1 | `akmrx-26` | identical answer to an earlier record with the same prompt |
| `akmrx-625` | 624 | AUTO-1 | `akmrx-27` | identical answer to an earlier record with the same prompt |
| `akmrx-626` | 625 | AUTO-1 | `akmrx-28` | identical answer to an earlier record with the same prompt |
| `akmrx-627` | 626 | AUTO-1 | `akmrx-29` | identical answer to an earlier record with the same prompt |
| `akmrx-628` | 627 | AUTO-1 | `akmrx-30` | identical answer to an earlier record with the same prompt |
| `akmrx-629` | 628 | AUTO-1 | `akmrx-31` | identical answer to an earlier record with the same prompt |
| `akmrx-630` | 629 | AUTO-1 | `akmrx-32` | identical answer to an earlier record with the same prompt |
| `akmrx-631` | 630 | AUTO-1 | `akmrx-33` | identical answer to an earlier record with the same prompt |
| `akmrx-632` | 631 | AUTO-1 | `akmrx-34` | identical answer to an earlier record with the same prompt |
| `akmrx-633` | 632 | AUTO-1 | `akmrx-35` | identical answer to an earlier record with the same prompt |
| `akmrx-634` | 633 | AUTO-1 | `akmrx-36` | identical answer to an earlier record with the same prompt |
| `akmrx-635` | 634 | AUTO-1 | `akmrx-37` | identical answer to an earlier record with the same prompt |
| `akmrx-636` | 635 | AUTO-1 | `akmrx-38` | identical answer to an earlier record with the same prompt |
| `akmrx-637` | 636 | AUTO-1 | `akmrx-39` | identical answer to an earlier record with the same prompt |
| `akmrx-638` | 637 | AUTO-1 | `akmrx-40` | identical answer to an earlier record with the same prompt |
| `akmrx-639` | 638 | AUTO-1 | `akmrx-41` | identical answer to an earlier record with the same prompt |
| `akmrx-640` | 639 | AUTO-1 | `akmrx-42` | identical answer to an earlier record with the same prompt |
| `akmrx-657` | 656 | AUTO-2 | `akmrx-656` | competes with the reasoning-corpus answer for the same prompt |
| `akmrx-658` | 657 | AUTO-2 | `akmrx-649` | competes with the reasoning-corpus answer for the same prompt |
| `akmrx-979` | 978 | AUTO-2 | `akmrx-975` | competes with the reasoning-corpus answer for the same prompt |
| `akmrx-11535` | 11534 | AUTO-2 | `akmrx-799` | competes with the reasoning-corpus answer for the same prompt |
| `akmrx-11541` | 11540 | AUTO-2 | `akmrx-802` | competes with the reasoning-corpus answer for the same prompt |
| `akmrx-11591` | 11590 | AUTO-2 | `akmrx-803` | competes with the reasoning-corpus answer for the same prompt |
| `akmrx-11619` | 11618 | AUTO-2 | `akmrx-798` | competes with the reasoning-corpus answer for the same prompt |
| `akmrx-11811` | 11810 | AUTO-2 | `akmrx-889` | competes with the reasoning-corpus answer for the same prompt |
| `akmrx-11813` | 11812 | AUTO-2 | `akmrx-891` | competes with the reasoning-corpus answer for the same prompt |
| `akmrx-11814` | 11813 | AUTO-2 | `akmrx-888` | competes with the reasoning-corpus answer for the same prompt |
| `akmrx-11816` | 11815 | AUTO-2 | `akmrx-892` | competes with the reasoning-corpus answer for the same prompt |
| `akmrx-11818` | 11817 | AUTO-2 | `akmrx-890` | competes with the reasoning-corpus answer for the same prompt |
| `akmrx-11819` | 11818 | AUTO-2 | `akmrx-893` | competes with the reasoning-corpus answer for the same prompt |
| `akmrx-11820` | 11819 | AUTO-2 | `akmrx-894` | competes with the reasoning-corpus answer for the same prompt |

### `CTL_LoRA_training_data_think.json` — 32 to remove

| remove id | idx | cat | keep instead | reason |
|---|---|---|---|---|
| `jdixp-609` | 608 | AUTO-1 | `jdixp-11` | identical answer to an earlier record with the same prompt |
| `jdixp-610` | 609 | AUTO-1 | `jdixp-12` | identical answer to an earlier record with the same prompt |
| `jdixp-611` | 610 | AUTO-1 | `jdixp-13` | identical answer to an earlier record with the same prompt |
| `jdixp-612` | 611 | AUTO-1 | `jdixp-14` | identical answer to an earlier record with the same prompt |
| `jdixp-613` | 612 | AUTO-1 | `jdixp-15` | identical answer to an earlier record with the same prompt |
| `jdixp-614` | 613 | AUTO-1 | `jdixp-16` | identical answer to an earlier record with the same prompt |
| `jdixp-615` | 614 | AUTO-1 | `jdixp-17` | identical answer to an earlier record with the same prompt |
| `jdixp-616` | 615 | AUTO-1 | `jdixp-18` | identical answer to an earlier record with the same prompt |
| `jdixp-617` | 616 | AUTO-1 | `jdixp-19` | identical answer to an earlier record with the same prompt |
| `jdixp-618` | 617 | AUTO-1 | `jdixp-20` | identical answer to an earlier record with the same prompt |
| `jdixp-619` | 618 | AUTO-1 | `jdixp-21` | identical answer to an earlier record with the same prompt |
| `jdixp-620` | 619 | AUTO-1 | `jdixp-22` | identical answer to an earlier record with the same prompt |
| `jdixp-621` | 620 | AUTO-1 | `jdixp-23` | identical answer to an earlier record with the same prompt |
| `jdixp-622` | 621 | AUTO-1 | `jdixp-24` | identical answer to an earlier record with the same prompt |
| `jdixp-623` | 622 | AUTO-1 | `jdixp-25` | identical answer to an earlier record with the same prompt |
| `jdixp-624` | 623 | AUTO-1 | `jdixp-26` | identical answer to an earlier record with the same prompt |
| `jdixp-625` | 624 | AUTO-1 | `jdixp-27` | identical answer to an earlier record with the same prompt |
| `jdixp-626` | 625 | AUTO-1 | `jdixp-28` | identical answer to an earlier record with the same prompt |
| `jdixp-627` | 626 | AUTO-1 | `jdixp-29` | identical answer to an earlier record with the same prompt |
| `jdixp-628` | 627 | AUTO-1 | `jdixp-30` | identical answer to an earlier record with the same prompt |
| `jdixp-629` | 628 | AUTO-1 | `jdixp-31` | identical answer to an earlier record with the same prompt |
| `jdixp-630` | 629 | AUTO-1 | `jdixp-32` | identical answer to an earlier record with the same prompt |
| `jdixp-631` | 630 | AUTO-1 | `jdixp-33` | identical answer to an earlier record with the same prompt |
| `jdixp-632` | 631 | AUTO-1 | `jdixp-34` | identical answer to an earlier record with the same prompt |
| `jdixp-633` | 632 | AUTO-1 | `jdixp-35` | identical answer to an earlier record with the same prompt |
| `jdixp-634` | 633 | AUTO-1 | `jdixp-36` | identical answer to an earlier record with the same prompt |
| `jdixp-635` | 634 | AUTO-1 | `jdixp-37` | identical answer to an earlier record with the same prompt |
| `jdixp-636` | 635 | AUTO-1 | `jdixp-38` | identical answer to an earlier record with the same prompt |
| `jdixp-637` | 636 | AUTO-1 | `jdixp-39` | identical answer to an earlier record with the same prompt |
| `jdixp-638` | 637 | AUTO-1 | `jdixp-40` | identical answer to an earlier record with the same prompt |
| `jdixp-639` | 638 | AUTO-1 | `jdixp-41` | identical answer to an earlier record with the same prompt |
| `jdixp-640` | 639 | AUTO-1 | `jdixp-42` | identical answer to an earlier record with the same prompt |

---

## 2. Needs a decision — 24 prompts

Same prompt, materially different answers, and **no reasoning-corpus answer to arbitrate**
(except the three think-corpus cases at the end, where both variants are in that corpus).
Most look like independently-written but equally valid answers. Two things worth weighing:

1. Keeping both double-weights the prompt in phase 1.
2. Where the variants differ a lot in **length**, they teach an inconsistent verbosity
   signal for the same prompt — which works against `spec/explanation_budget_spec.md`.
   Where that applies, prefer the longer, more grounded answer.

Pick one `id` per prompt to keep and remove the others, or keep both deliberately.

### 1. `CTL_LoRA_training_data.json` — 2 variants  ·  **2.2× length spread**

**Prompt**

```
I know SQL. I need a timestamp type. Does CTL have separate Date and DateTime types?
In SQL I might do:
`DATE vs TIMESTAMP`
How do I do this in CTL2?
```

**Variant `akmrx-1053`** (index 1052, 220 words)

```
CTL2 has a single `date` data type which always contains both date and time components (it stores a full timestamp; you can ignore the time part or set it to midnight if you only care about the date).

Key points:

- There is no separate `DATE` vs `TIMESTAMP`/`DATETIME` distinction like in many SQL dialects.
- `date` in CTL2 corresponds most closely to a SQL `TIMESTAMP` (date + time).
- If you only need a "date-only" value, you typically:
  - parse a string with a pattern that doesn't include time, or
  - zero-out the time portion using helper functions like `extractDate()`.

Examples:

```ctl
// Current date and time (like SQL CURRENT_TIMESTAMP)
date now = today();

// Parse a date-only string (time part becomes 00:00:00 in the default time zone)
date somedate = str2date("2020-12-31", "yyyy-MM-dd");

// Parse a full timestamp string
date somedatetime = str2date("2020-12-31 12:30:30", "yyyy-MM-dd HH:mm:ss");

// If you want to drop the time part from an existing date:
date dateOnly = extractDate(now);   // sets time to 00:00:00

// Or just format without the time when outputting:
string outDate = date2str(now, "yyyy-MM-dd");
string outTimestamp = date2str(now, "yyyy-MM-dd HH:mm:ss");
```

So, conceptually:

- SQL `DATE` -> CTL2 `date`, but you only use/format the date part (`extractDate()` / `date2str(..., "yyyy-MM-dd")`).
- SQL `TIMESTAMP` -> CTL2 `date` with both date and tim
… [truncated, 220 words total]
```

**Variant `akmrx-1047`** (index 1046, 99 words)

```
CTL2 has a single `date` data type which always contains both date and time components (it stores a full timestamp internally).

```ctl
date now = today(); // Returns current date AND time
```

There is no separate "date-only" vs "datetime/timestamp" type like in many SQL dialects. You handle both concepts with the same `date` type and control what you care about via:

- Formatting/parsing patterns with `str2date()` and `date2str()`  
- Functions like `extractDate()` (keep only date part) and `extractTime()` (keep only time part)  
- Component metadata `format` attribute (e.g. `yyyy-MM-dd` vs `yyyy-MM-dd HH:mm:ss`) to control how dates are read/written.
```

---

### 2. `CTL_LoRA_training_data.json` — 2 variants

**Prompt**

```
I know Python. I need a dictionary mapping IDs (string) to counts (integer).
In Python I might do:
`my_dict = {'A': 1}`
How do I do this in CTL2?
```

**Variant `akmrx-1055`** (index 1054, 37 words)

```
CTL2 uses strong typing for maps. You must declare Key and Value types (unless using variant type). Static maps are declared as {<key> -> <value>}

```ctl
map[string, integer] my_dict = {"A" -> 1};
my_dict['B'] = 2;
```
```

**Variant `akmrx-1049`** (index 1048, 33 words)

```
CTL2 uses strong typing for maps. You must declare Key and Value types.

```ctl
map[string, integer] my_dict;
my_dict['A'] = 1;
//or use static initialization
map[string, integer] my_dict2 = { "A" -> 1};
```
```

---

### 3. `CTL_LoRA_training_data.json` — 2 variants  ·  **2.5× length spread**

**Prompt**

```
Component: MAP (Reformat)

Is this CTL2 valid? If not, correct it.

Input metadata:
<Metadata id="In"><Record name="InRec"><Field name="s" type="string"/></Record></Metadata>

Output metadata:
<Metadata id="Out"><Record name="OutRec"><Field name="out" type="string"/></Record></Metadata>

```ctl
//#CTL2
function integer transform() {
    $out.0.out = replace($in.0.s, quote("."), "_");
    return ALL;
}
```
```

**Variant `akmrx-1419`** (index 1418, 80 words)

```
Not valid: `quote()` is not available. Implement a local escaping helper.

```ctl
//#CTL2
function string regexQuote(string s) {
    string meta = ".^$*+?()[]{}|\\";
    string out = "";
    integer i;
    for (i = 0; i < length(s); i++) {
        string ch = substring(s, i, i + 1);
        if (indexOf(meta, ch) >= 0) out = out + "\\" + ch;
        else out = out + ch;
    }
    return out;
}

function integer transform() {
    $out.0.out = replace($in.0.s, regexQuote("."), "_");
    return ALL;
}
```
```

**Variant `akmrx-11679`** (index 11678, 32 words)

```
`quote()` is not a CTL2 built-in. `replace()` takes a regex, so escape a literal dot as `"\\."`.

```ctl
//#CTL2
function integer transform() {
    $out.0.out = replace($in.0.s, "\\.", "_");
    return ALL;
}
```
```

---

### 4. `CTL_LoRA_training_data.json` — 2 variants  ·  **2.1× length spread**

**Prompt**

```
Component: MAP (Reformat)

Pick the first non-blank of (a,b,c); if all are blank or null, output "0". Use a ternary chain.

Input metadata:
<Metadata id="In"><Record name="InRec"><Field name="a" type="string" nullable="true"/><Field name="b" type="string" nullable="true"/><Field name="c" type="string" nullable="true"/></Record></Metadata>

Output metadata:
<Metadata id="Out"><Record name="OutRec"><Field name="val" type="string"/></Record></Metadata>
```

**Variant `akmrx-1448`** (index 1447, 53 words)

```
```ctl
//#CTL2
function integer transform() {
    // When $out.0.val is NOT NULLABLE, assigning null to it fails.
    // That makes the fail-expression ':' useful as a fallback chain.
    $out.0.val =
        (!isBlank($in.0.a)) ? $in.0.a : null
      : (!isBlank($in.0.b)) ? $in.0.b : null
      : (!isBlank($in.0.c)) ? $in.0.c : null
      : "0";

    return ALL;
}
```
```

**Variant `akmrx-11683`** (index 11682, 25 words)

```
```ctl
//#CTL2
function integer transform() {
    $out.0.val = !isBlank($in.0.a) ? $in.0.a
              : !isBlank($in.0.b) ? $in.0.b
              : !isBlank($in.0.c) ? $in.0.c
              : "0";
    return ALL;
}
```
```

---

### 5. `CTL_LoRA_training_data.json` — 3 variants

**Prompt**

```
What does `normalizeDecimal()` do in CTL2?
```

**Variant `akmrx-3532`** (index 3531, 70 words)

```
`normalizeDecimal(string)` takes a string and returns a normalized string representation of the numeric content. It removes formatting characters such as currency symbols and thousands separators and normalizes the decimal separator to `.`. It does not return `decimal` and it does not format a decimal value into a string.

```ctl
//#CTL2
string a = normalizeDecimal("1,035.24");    // "1035.24"
string b = normalizeDecimal("€127");        // "127"
string c = normalizeDecimal("123 456,789"); // "123456.789"
```
```

**Variant `akmrx-3523`** (index 3522, 67 words)

```
`normalizeDecimal()` preprocesses a numeric string and returns a normalized `string`. It is used before parsing text as decimal, especially when the source text may contain currency symbols, spaces, or locale-style separators.

```ctl
//#CTL2
string a = normalizeDecimal("€1 234,50");
string b = normalizeDecimal("USD 1,234.50");
decimal x = str2decimal(a);
decimal y = str2decimal(b);
```

It is not a decimal-to-string formatting function and it does not take a `decimal` argument.
```

**Variant `akmrx-9930`** (index 9929, 57 words)

```
`normalizeDecimal(string)` preprocesses decimal number strings by removing non-numeric characters, standardizing the decimal separator, and removing thousand separators and currency symbols.

```ctl
//#CTL2
string a = normalizeDecimal("1,035.24");     // "1035.24"
string b = normalizeDecimal("123 456,789");  // "123456.789"
string c = normalizeDecimal("€127");         // "127"
```

It returns a normalized string, not a decimal value. You typically use it before `str2decimal()`.
```

---

### 6. `CTL_LoRA_training_data.json` — 2 variants  ·  **8.4× length spread**

**Prompt**

```
What does `getMonth()` return for January in CTL2?
```

**Variant `akmrx-10387`** (index 10386, 42 words)

```
`1` - `getMonth()` is 1-based: January = 1, February = 2, ..., December = 12.

```ctl
getMonth(2025-01-15)  // returns 1
getMonth(2025-12-31)  // returns 12
```

`createDate()` also uses 1-based months:
```ctl
date d = createDate(2025, 1, 15);  // January 15, 2025
```
```

**Variant `akmrx-3592`** (index 3591, 5 words)

```
`getMonth()` returns `1` for January.
```

---

### 7. `CTL_LoRA_training_data.json` — 2 variants

**Prompt**

```
In MAP/REFORMAT, log an info message once per run with today(), then pass records through.
```

**Variant `akmrx-3809`** (index 3808, 39 words)

```
```ctl
//#CTL2
boolean started; //global variable, by default initialized to false value

function integer transform() {
  if (!started) {
    started = true;
    printLog(info, "Job started at " + date2str(today(), "yyyy-MM-dd HH:mm:ss"));
  }
  $out.0.* = $in.0.*;
  return ALL;
}
```
```

**Variant `akmrx-3783`** (index 3782, 27 words)

```
```ctl
//#CTL2
function boolean init() {
    printLog(info, "Job started at " + today());
    return true;
}

function integer transform() {
    $out.0.* = $in.0.*;
    return ALL;
}
```
```

---

### 8. `CTL_LoRA_training_data.json` — 2 variants

**Prompt**

```
In MAP/REFORMAT, parse JSON and cast to map. If cast fails, log error and skip.
```

**Variant `akmrx-3792`** (index 3791, 74 words)

```
```ctl
//#CTL2
function integer transform() {
  try {
    if (isnull($in.0.json)) {
      printLog(error, "Expected JSON object but got null for raw_id=" + nvl($in.0.raw_id, ""));
      return SKIP;
    }
    variant v = parseJson($in.0.json);
    map[string, variant] m = cast(v, map, string, variant);
    $out.0.id = cast(m["id"], string) : null;
    return ALL;
  } catch (CTLException ex) {
    printLog(error, "Expected JSON object but got different structure for raw_id=" + nvl($in.0.raw_id, "") + ": " + ex.message);
    return SKIP;
  }
}
```
```

**Variant `akmrx-3812`** (index 3811, 67 words)

```
```ctl
//#CTL2
function integer transform() {
  try {
    variant v = parseJson(nvl($in.0.json, ""));
    map[string, variant] m = cast(v, map, string, variant); //casting to map reuqires also specifying key and value types
    $out.0.id = cast(m["id"], string) : null;
    return ALL;
  } catch (CTLException ex) {
    printLog(error, "Expected JSON object but got different structure for raw_id=" + nvl($in.0.raw_id, "") + ": " + ex.message);
    return SKIP;
  }
}
```
```

---

### 9. `CTL_LoRA_training_data.json` — 2 variants

**Prompt**

```
In MAP/REFORMAT, if required map key is missing, log error and skip record.
```

**Variant `akmrx-3813`** (index 3812, 102 words)

```
```ctl
//#CTL2
function integer transform() {
  if (isnull($in.0.json)) {
    printLog(error, "Missing json for raw_id=" + nvl($in.0.raw_id, ""));
    return -1;
  }

  variant v = parseJson($in.0.json);
  if (isnull(v)) {
    printLog(error, "Invalid json for raw_id=" + nvl($in.0.raw_id, ""));
    return -1;
  }

  map[string, variant] m = cast(v, map, string, variant); // casting to container type map requires additional type paremerers for key and value

  if (!containsKey(m,"customer_id")) {
    printLog(error, "Missing customer_id in json for raw_id=" + nvl($in.0.raw_id, ""));
    return -1;
  }

  $out.0.customer_id = cast(m["customer_id"], string) : null;
  if (isnull($out.0.customer_id)) {
    printLog(error, "Null/invalid customer_id in json for raw_id=" + nvl($in.0.raw_id, ""));
    return -1;
  }

  return ALL;
}
```
```

**Variant `akmrx-3793`** (index 3792, 60 words)

```
```ctl
//#CTL2
function integer transform() {
  if (isnull($in.0.json)) {
    printLog(error, "Missing customer_id in json for raw_id=" + $in.0.raw_id);
    return -1;
  }

  variant v = parseJson($in.0.json);
  map[string, variant] m = cast(v, map, string, variant);

  if (m["customer_id"] == null) {
    printLog(error, "Missing customer_id in json for raw_id=" + $in.0.raw_id);
    return -1;
  }

  $out.0.customer_id = cast(m["customer_id"], string) : null;
  return ALL;
}
```
```

---

### 10. `CTL_LoRA_training_data.json` — 2 variants

**Prompt**

```
In MAP/REFORMAT, detect schema mismatch: expecting revenue_amount as string, but got null. Log fatal and raiseError.
```

**Variant `akmrx-3796`** (index 3795, 59 words)

```
```ctl
//#CTL2
function integer transform() {
  variant v = parseJson($in.0.json);
  map[string, variant] m = cast(v, map, string, variant);

  if (m["revenue_amount"] == null) {
    printLog(fatal, "Schema mismatch: revenue_amount missing/null for raw_id=" + $in.0.raw_id);
    raiseError("Schema mismatch: revenue_amount is required in JSON for raw_id=" + $in.0.raw_id);
  }

  decimal rev = str2decimal(nvl(cast(m["revenue_amount"], string) : null, ""));
  $out.0.revenue_amount = rev;
  return ALL;
}
```
```

**Variant `akmrx-3814`** (index 3813, 54 words)

```
```ctl
//#CTL2
function integer transform() {
  variant v = parseJson($in.0.json);

  if (isnull(v) || !containsKey(v,"revenue_amount") || isnull(v["revenue_amount"])) {
    printLog(fatal, "Schema mismatch: revenue_amount missing/null for raw_id=" + nvl($in.0.raw_id, ""));
    raiseError("Schema mismatch: revenue_amount is required in JSON for raw_id=" + nvl($in.0.raw_id, ""));
  }

  decimal rev = (str2decimal(cast(v["revenue_amount"], string)) : null);
  $out.0.revenue_amount = rev;
  return ALL;
}
```
```

---

### 11. `CTL_LoRA_training_data.json` — 2 variants

**Prompt**

```
In MAP/REFORMAT, parse JSON, and if parsing fails, log fatal and raiseError with user-friendly context.
```

**Variant `akmrx-3797`** (index 3796, 61 words)

```
```ctl
//#CTL2
function integer transform() {
  try {
    variant v = parseJson($in.0.json);
    map[string, variant] m = cast(v, map, string, variant);
    $out.0.id = cast(m["id"], string);
    return ALL;
  } catch (CTLException ex) {
    printLog(fatal, "Unrecoverable JSON parse failure for raw_id=" + nvl($in.0.raw_id, "") + ": " + ex.message);
    raiseError("Invalid JSON for raw_id=" + nvl($in.0.raw_id, "") + ": " + ex.message);
  }
}
```
```

**Variant `akmrx-3815`** (index 3814, 58 words)

```
```ctl
//#CTL2
function integer transform() {
  variant v = null;
  try {
    v = parseJson($in.0.json);
    $out.0.id = cast(v["id"], string) : null;
    return ALL;
  } catch (CTLException ex) {
    printLog(fatal, "Unrecoverable JSON parse failure for raw_id=" + nvl($in.0.raw_id, "") + ": " + ex.message);
    raiseError("Invalid JSON for raw_id=" + nvl($in.0.raw_id, "") + ": " + ex.message);
  }
}
```
```

---

### 12. `CTL_LoRA_training_data.json` — 2 variants

**Prompt**

```
In MAP/REFORMAT, parse date with str2date(input, pattern). If parsing fails, raiseError mentioning expected pattern and value.
```

**Variant `akmrx-3816`** (index 3815, 61 words)

```
```ctl
//#CTL2
const string pat = "yyyy-MM-dd"; //pattern defined at global level as constat - non modifiable after initialization

function integer transform() {
  try {
    date d = str2date($in.0.ds, pat);
    $out.0.dt = d;
    return ALL;
  } catch (CTLException ex) {
    raiseError("Invalid date '" + nvl($in.0.ds, "") + "'; expected pattern " + pat + ": " + ex.message);
  }
}
```
```

**Variant `akmrx-3799`** (index 3798, 47 words)

```
```ctl
//#CTL2
function integer transform() {
  string pat = "yyyy-MM-dd";
  try {
    date d = str2date($in.0.ds, pat);
    $out.0.dt = d;
    return ALL;
  } catch (CTLException ex) {
    raiseError("Invalid date '" + $in.0.ds + "'; expected pattern " + pat + ": " + ex.message);
  }
}
```
```

---

### 13. `CTL_LoRA_training_data.json` — 2 variants

**Prompt**

```
In MAP/REFORMAT, input JSON is expected to be an array. If it's not, raiseError with a message that explains the expected shape.
```

**Variant `akmrx-3803`** (index 3802, 64 words)

```
```ctl
//#CTL2
function integer transform() {
  try {
    if (isBlank($in.0.json)) {
      raiseError("Expected JSON array in field json for id=" + nvl($in.0.id, "") + ".");
    }
    variant v = parseJson($in.0.json);
    list[variant] arr = cast(v, list, variant);
    $out.0.count = length(arr);
    return ALL;
  } catch (CTLException ex) {
    raiseError("Expected JSON array in field json for id=" + nvl($in.0.id, "") + ". " + ex.message);
  }
}
```
```

**Variant `akmrx-3818`** (index 3817, 56 words)

```
```ctl
//#CTL2
function integer transform() {
    variant v = null;
    if (isnull($in.0.json)) {
       raiseError("Expected JSON array in field json for id=" + toString($in.0.id) + ". Input json is null.");
    }
    v = parseJson($in.0.json);
    if(!(v typeof list)){
       raiseError("Expected JSON array in field json for id=" + toString($in.0.id) + ".");
    }
    $out.0.count_items = length(v);
    return ALL;

}
```
```

---

### 14. `CTL_LoRA_training_data.json` — 2 variants

**Prompt**

```
In MAP/REFORMAT, if revenue_amount exceeds an absolute maximum, raiseError to stop processing.
```

**Variant `akmrx-3819`** (index 3818, 55 words)

```
```ctl
//#CTL2

const  decimal max = 999999999D; //max defined as constant

function integer transform() {
  decimal rev = $in.0.revenue_amount;
  if (!isnull(rev) && rev > max) {
    raiseError("Revenue too large for customer_id=" + nvl($in.0.customer_id, "") + " rev=" + rev + " (max " + max + ")");
  }

  $out.0.* = $in.0.*;
  return ALL;
}
```
```

**Variant `akmrx-3804`** (index 3803, 51 words)

```
```ctl
//#CTL2
function integer transform() {
  decimal rev = $in.0.revenue_amount;
  decimal max = 999999999D;

  if (!isnull(rev) && rev > max) {
    raiseError("Revenue too large for customer_id=" + nvl($in.0.customer_id, "") + " rev=" + nvl(rev, 0D) + " (max " + max + ")");
  }

  $out.0.* = $in.0.*;
  return ALL;
}
```
```

---

### 15. `CTL_LoRA_training_data.json` — 2 variants

**Prompt**

```
After normalizeDecimal turns a euro-formatted value into 9876.50, should I still pass a German pattern to str2decimal?
```

**Variant `akmrx-4326`** (index 4325, 44 words)

```
No. Normalization has already produced a plain decimal string, so use the one-argument overload:

string normalized = normalizeDecimal($in.0.amountText);
decimal amount = str2decimal(normalized);

A format and locale describe the original presentation. For a known German source, parse the raw value directly with str2decimal($in.0.amountText, "#,##0.00", "de.DE").
```

**Variant `akmrx-4348`** (index 4347, 44 words)

```
No. Normalization has already produced a plain decimal string, so use the one-argument overload:

string normalized = normalizeDecimal($in.0.amountText);
decimal amount = str2decimal(normalized);

A format and locale describe the original presentation. For a known German source, parse the raw value directly with str2decimal($in.0.amountText, "#.##0,00", "de.DE").
```

---

### 16. `CTL_LoRA_training_data.json` — 2 variants

**Prompt**

```
I need letters only from A-17 blue, producing Ablue. Is getAlphanumericChars suitable?
```

**Variant `akmrx-4349`** (index 4348, 36 words)

```
No. getAlphanumericChars(string) has one argument and retains both letters and digits. To retain ASCII letters only, use a regex replacement:

string lettersOnly = replace($in.0.label, "[^A-Za-z]", "");

The pattern matches every character that is not a letter.
```

**Variant `akmrx-4330`** (index 4329, 33 words)

```
Yes. `getAlphanumericChars($in.0.label, true, false)` is the direct built-in for letters only. A regex replacement is an alternative:

string lettersOnly = replace($in.0.label, "[^A-Za-z]", "");

The pattern matches every character that is not a letter.
```

---

### 17. `CTL_LoRA_training_data.json` — 2 variants

**Prompt**

```
Can getAlphanumericChars(input, "[0-9]") select just the digits from an invoice code?
```

**Variant `akmrx-4333`** (index 4332, 53 words)

```
No. getAlphanumericChars() does not accept a regex or selector; its one-argument form keeps letters and digits; the three-argument overload selects alpha and numeric characters independently. For digits only, remove non-digits:

string digits = replace($in.0.invoiceCode, "[^0-9]", "");

Do not use this to prepare a decimal amount because it removes the decimal separator and sign.
```

**Variant `akmrx-4350`** (index 4349, 44 words)

```
No. getAlphanumericChars() does not accept a regex or selector; its one-argument form keeps letters and digits. For digits only, remove non-digits:

string digits = replace($in.0.invoiceCode, "[^0-9]", "");

Do not use this to prepare a decimal amount because it removes the decimal separator and sign.
```

---

### 18. `CTL_LoRA_training_data.json` — 2 variants  ·  **2.8× length spread**

**Prompt**

```
What are sequences in CloverDX?
```

**Variant `akmrx-4880`** (index 4879, 122 words)

```
Sequences in CloverDX generate unique sequential values, typically used for creating primary keys or unique identifiers.

**Types of sequences:**

**1. SimpleSequence** - Simple counter, persisted on diskxml
<Sequence id="OrderSeq" name="OrdersSequence" type="SIMPLE_SEQUENCE"
  start="1"
  step="1"
  fileURL="${DATAIN_DIR}/setquence.dat"
  cached="100"/>
**Using sequences in CTL2:**

```ctl
//#CTL2
function integer transform() {
    // Get next value from sequence
    $out.0.order_id = sequence(OrderSeq).next();
    $out.0.customer_name = $in.0.name;
    return ALL;
}
```

**Sequence functions:**
- `sequence(SeqId).next()` - Get next value and increment
- `sequence(SeqId).current()` - Get current value without incrementing
- `sequence(SeqId).reset()` - Reset to start value

**Properties:**
- **start**: Initial value
- **step**: Increment amount
- **cached**: Number of values to cache (performance)

**Use cases:**
- Generating surrogate keys
- Creating unique transaction IDs
- Batch numbering
- Row numbering within transformations
```

**Variant `akmrx-9421`** (index 9420, 43 words)

```
Sequences in CloverDX are graph objects designed to generate numbers, for example for record numbering or unique identifiers. In CTL2 you do not define sequences inline in code; you access an existing graph sequence through `sequence(name)` and then call `current()`, `next()`, or `reset()`.
```

---

### 19. `CTL_LoRA_training_data.json` — 2 variants

**Prompt**

```
I am using a Rollup to aggregate shipments by route. Each input has:

- route_id: string (not null)
- metrics_json: string (nullable)   // JSON object of metrics like { "weight": 5000, "boxes": 120 }

The group accumulator record `RouteAgg` has:
- route_id: string (not null)
- last_metrics: variant (nullable)

In the Rollup `finishGroup` I want to convert `last_metrics` (a JSON string copied from input) into a map and keep it as a variant for output. Can you show the Rollup functions to do that using `toMap`? Assume the output port has fields `route_id` and `metrics_map: variant`.
```

**Variant `akmrx-8206`** (index 8205, 109 words)

```
`toMap()` cannot convert a parsed JSON variant. Use `cast()` and store the resulting map in the accumulator's `variant` field during `finishGroup()`.

```ctl
//#CTL2
function void initGroup(RouteAgg groupAccumulator) {
    groupAccumulator.route_id = "";
    groupAccumulator.last_metrics = null;
}

function boolean updateGroup(RouteAgg groupAccumulator) {
    groupAccumulator.route_id = $in.0.route_id;

    if (!isnull($in.0.metrics_json)) {
        groupAccumulator.last_metrics = $in.0.metrics_json;
    }

    return false;
}

function boolean finishGroup(RouteAgg groupAccumulator) {
    if (!isnull(groupAccumulator.last_metrics)) {
        variant parsed = parseJson(cast(groupAccumulator.last_metrics, string));
        groupAccumulator.last_metrics = cast(parsed, map, string, variant);
    }

    return true;
}

function integer updateTransform(integer counter, RouteAgg groupAccumulator) {
    return SKIP;
}

function integer transform(integer counter, RouteAgg groupAccumulator) {
    if (counter > 0) return SKIP;

    $out.0.route_id = groupAccumulator.route_id;
    $out.0.metrics_map = groupAccumulator.last_metrics;
    return ALL;
}
```
```

**Variant `akmrx-8209`** (index 8208, 107 words)

```
Use `cast()`, not `toMap()`. `toMap()` builds a map from key/value lists; it does not convert a parsed JSON `variant`.

```ctl
//#CTL2
function void initGroup(RouteAgg groupAccumulator) {
    groupAccumulator.route_id = "";
    groupAccumulator.last_metrics = null;
}

function boolean updateGroup(RouteAgg groupAccumulator) {
    groupAccumulator.route_id = $in.0.route_id;

    if (!isnull($in.0.metrics_json)) {
        groupAccumulator.last_metrics = $in.0.metrics_json;
    }

    return false;
}

function boolean finishGroup(RouteAgg groupAccumulator) {
    if (!isnull(groupAccumulator.last_metrics)) {
        variant parsed = parseJson(cast(groupAccumulator.last_metrics, string));
        groupAccumulator.last_metrics = cast(parsed, map, string, variant);
    }

    return true;
}

function integer updateTransform(integer counter, RouteAgg groupAccumulator) {
    return SKIP;
}

function integer transform(integer counter, RouteAgg groupAccumulator) {
    if (counter > 0) return SKIP;

    $out.0.route_id = groupAccumulator.route_id;
    $out.0.metrics_map = groupAccumulator.last_metrics;
    return ALL;
}
```
```

---

### 20. `CTL_LoRA_training_data.json` — 2 variants

**Prompt**

```
Given Input Metadata on Port 0:
<Metadata id="InLogs">
<Record name="LogEntry" fieldDelimiter="|" recordDelimiter="\n" type="delimited">
    <Field name="timestamp" type="date"/>
    <Field name="level" type="string"/>
    <Field name="message" type="string"/>
</Record>
</Metadata>

Write a Filter expression that passes log entries where message contains the word "timeout".
```

**Variant `akmrx-11644`** (index 11643, 52 words)

```
```ctl
//#CTL2
!isnull($in.0.message) && $in.0.message ?= "\\btimeout\\b"
```

`?=` searches for a regex match anywhere in the message. The `\\b` word boundaries ensure that `timeout` is matched as a word rather than as part of a longer token such as `timeouts`.

For case-insensitive matching:

```ctl
//#CTL2
!isnull($in.0.message) && $in.0.message ?= "(?i)\\btimeout\\b"
```
```

**Variant `akmrx-11685`** (index 11684, 41 words)

```
A Filter uses a bare boolean expression. Because `?=` uses regex containment, use word boundaries to avoid matching a larger word such as `timeouts`.

```ctl
//#CTL2
nvl($in.0.message, "") ?= "\\btimeout\\b"
```

This is case-sensitive. For case-insensitive matching, use the pattern `"(?i)\\btimeout\\b"`.
```

---

### 21. `CTL_LoRA_training_data.json` — 2 variants

**Prompt**

```
What are all the comparison and string operators available in CTL2?
```

**Variant `akmrx-11647`** (index 11646, 148 words)

```
CTL2 comparison and pattern operators are:

| Purpose | Operators |
|---|---|
| Equal | `==`, `.eq.` |
| Not equal | `!=`, `<>`, `.ne.` |
| Less than | `<`, `.lt.` |
| Greater than | `>`, `.gt.` |
| Less than or equal | `<=`, `=<`, `.le.` |
| Greater than or equal | `>=`, `=>`, `.ge.` |
| Regex full match | `~=`, `.regex.` |
| Regex contains | `?=` |
| String concatenation | `+` |

Related logical operators are `&&` / `and`, `||` / `or`, and `!` / `not`.

```ctl
boolean adult = !isnull($in.0.age) && $in.0.age >= 18;
boolean fullId = $in.0.code ~= "[A-Z]{3}";
boolean hasError = $in.0.log ?= "(?i)error";
string fullName = nvl($in.0.first, "") + " " + nvl($in.0.last, "");
```

Equality and inequality are null-safe. Ordered comparisons such as `<` and `>=` must be guarded when either operand can be null.
```

**Variant `akmrx-11686`** (index 11685, 136 words)

```
**Comparison operators**

- Equality: `==` or `.eq.`
- Inequality: `!=`, `<>`, or `.ne.`
- Less than: `<` or `.lt.`
- Greater than: `>` or `.gt.`
- Less than or equal: `<=`, `=<`, or `.le.`
- Greater than or equal: `>=`, `=>`, or `.ge.`

Equality and inequality are null-safe. Ordered comparisons require non-null operands.

**String and pattern operators**

- `+` concatenates strings.
- `~=` or `.regex.` performs a whole-string regex match.
- `?=` performs a regex-contains match.

Related logical operators are `&&` / `and`, `||` / `or`, and `!` / `not`.

Membership is not an operator: use `in(value, collection)`. For maps, it tests keys; use `containsValue(map, value)` to test values.

```ctl
!isnull($in.0.age) && $in.0.age >= 18;
$in.0.email ~= "[a-z]+@[a-z]+\\.[a-z]+";
$in.0.log ?= "(?i)error";
$out.0.name = nvl($in.0.first, "") + " " + nvl($in.0.last, "");
in($in.0.country, ["US", "CA", "MX"]);
```
```

---

### 22. `CTL_LoRA_training_data_think.json` — 2 variants

**Prompt**

```
In MAP/REFORMAT, parse a JSON string constant and write name (string), age (integer), and city (string) to output fields.
```

**Variant `jdixp-658`** (index 657, 50 words)

```
Parse the constant JSON and cast every variant property to its destination field type.

```ctl
//#CTL2
function integer transform() {
    string jsonText = "{\"name\":\"Marta\",\"age\":18,\"city\":\"London\"}";
    variant v = parseJson(jsonText);

    $out.0.name = cast(v["name"], string) : null;
    $out.0.age = cast(v["age"], integer) : null;
    $out.0.city = cast(v["city"], string) : null;
    return ALL;
}
```
```

**Variant `jdixp-649`** (index 648, 48 words)

```
Use `parseJson()` and explicitly cast the resulting properties to the output types.

```ctl
//#CTL2
function integer transform() {
    string jsonText = "{\"name\":\"Zoe\",\"age\":42,\"city\":\"Tokyo\"}";
    variant v = parseJson(jsonText);

    $out.0.name = cast(v["name"], string) : null;
    $out.0.age = cast(v["age"], integer) : null;
    $out.0.city = cast(v["city"], string) : null;
    return ALL;
}
```
```

---

### 23. `CTL_LoRA_training_data_think.json` — 2 variants

**Prompt**

```
Given metadata record PersonRec(name:string, age:integer, city:string) on output port 0, parse JSON and assign the filled record directly to $out.0.
```

**Variant `jdixp-656`** (index 655, 61 words)

```
Declare the local record using the supplied metadata name, fill it from JSON, and assign it to output port 0.

```ctl
//#CTL2
function integer transform() {
    string jsonText = "{\"name\":\"Bob\",\"age\":25,\"city\":\"London\"}";
    variant v = parseJson(jsonText);
    PersonRec p;

    p.name = cast(v["name"], string) : null;
    p.age = cast(v["age"], integer) : null;
    p.city = cast(v["city"], string) : null;
    $out.0 = p;
    return ALL;
}
```
```

**Variant `jdixp-657`** (index 656, 58 words)

```
Use the provided `PersonRec` metadata for the local record and assign the matching record to port 0.

```ctl
//#CTL2
function integer transform() {
    string jsonText = "{\"name\":\"Eve\",\"age\":46,\"city\":\"Berlin\"}";
    variant v = parseJson(jsonText);
    PersonRec p;

    p.name = cast(v["name"], string) : null;
    p.age = cast(v["age"], integer) : null;
    p.city = cast(v["city"], string) : null;
    $out.0 = p;
    return ALL;
}
```
```

---

### 24. `CTL_LoRA_training_data_think.json` — 2 variants

**Prompt**

```
Validate the proposed CTL2 implementation against the original request. Focus on CTL2 syntax and whether the implementation satisfies the requested business logic.

ORIGINAL REQUEST:
Given Output Metadata on Port 0:
<Metadata id="OutAuditSchedule">
<Record name="AuditScheduleRecord" fieldDelimiter="," recordDelimiter="\n" type="delimited">
    <Field name="control_run_id" type="long"/>
    <Field name="review_date" type="date" format="yyyy-MM-dd"/>
    <Field name="compliance_year" type="integer" nullable="false"/>
    <Field name="compliance_month" type="integer"/>
    <Field name="iso_week_number" type="integer" nullable="true"/>
    <Field name="weekday_code" type="integer"/>
    <Field name="season_window" type="string" nullable="false"/>
    <Field name="site_visit_required" type="boolean"/>
</Record>
</Metadata>

Write a DataGenerator that creates a Nordics energy and utilities com
… [truncated, 304 words total]
```

**Variant `jdixp-979`** (index 978, 166 words)

```
ISSUES:
  [ERROR] `getWeekNumber()` is not a CTL2 function, so the assignment to `iso_week_number` cannot compile.
  [ERROR] `generate()` uses `return STOP;` to stop after the range and `return SKIP;` for nonmatching dates. DataGenerator configuration must control invocation count, while every `generate()` call must emit one record.
  [WARNING] `getDayOfWeek()` numbers Monday as 1, so `dayOfWeek == 2` selects Tuesday rather than Monday.
  [WARNING] The `isLastDayOfMonth` comparison is true for ordinary dates because tomorrow is almost always later than a date one month earlier, so non-Mondays are selected incorrectly.

SUGGESTIONS:
  - Use a supported CTL2 week extraction such as `date2num(currentDate, week)` when it matches the graph's required week-number convention.
  - Configure the component for the required number of output invocations. Keep the date cursor at module scope, advance it inside each call until the next Monday or month-end, emit that record, and return `OK`.
  - Detect month end by comparing the next day's month with the current month; `month` and `year` do not need to be renamed.

VERDICT: FAIL
```

**Variant `jdixp-975`** (index 974, 130 words)

```
ISSUES:
  [ERROR] `getWeekNumber()` is not a CTL2 function, so the assignment to `iso_week_number` cannot compile.
  [ERROR] `generate()` returns `STOP` after the range and `SKIP` for nonmatching dates. DataGenerator configuration must control invocation count, and each `generate()` call must emit one row.
  [WARNING] `getDayOfWeek()` numbers Monday as 1, so `dayOfWeek == 2` selects Tuesdays rather than Mondays.
  [WARNING] The last-day test compares tomorrow with a date one month earlier and is effectively true for ordinary dates, so it does not identify month ends.

SUGGESTIONS:
  - Use a supported CTL2 week extraction such as `date2num(currentDate, week)` when it matches the graph's required week-number convention.
  - Configure the required output count, advance the module-level date cursor until the next Monday or month-end, emit that row, and return a normal output code.

VERDICT: FAIL
```

---
