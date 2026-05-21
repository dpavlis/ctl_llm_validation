description: Dense CTL2 language reference for CloverDX transformations: valid syntax, typing and conversion rules, record and port access semantics, null handling, control flow, built-in function surface, and hard constraints needed to generate, lint, and repair executable CTL2 without inventing unsupported constructs.

# CTL2 (Clover Transformation Language) — Reference

> Authoritative CTL2 reference for CloverDX ETL. Use to generate, validate, review CTL2 code. Anything not documented here does NOT exist in CTL2.

## LLM Rules (hard constraints)

- This document is the only valid source. Unlisted construct → propose closest valid alternative.
- Prefer simple, explicit CTL2: named field access, explicit conversions.
- Records are NOT objects: no `.get()`, `.set()`, `.fields()`. Use record functions (**11.6**).
- Null checks: `isnull(expr)` (1 arg, lowercase) and `expr == null` / `expr != null` are interchangeable for any type including records. `isNull(record, integer|string)` (2 args, camelCase) is a separate function for dynamic field access by index/name. `""` ≠ null. See **11.8**.
- Output records: prefer `$out.<port>.* = $in.<port>.*;`. Full-record assignment is valid only when metadata is identical (e.g., `$out.1 = $out.0;`, `$out.0 = $in.0;`).
- No implicit conversions except numeric upcasting. Use documented conversion functions.
- Prefer **native literals** over conversion functions:
  - Use `date d = 2025-01-01;` instead of `str2date(...)`
  - Use `10.5D` instead of string-based decimal parsing
  - Use `123L` for long values

## Fix CTL2: steps
1. Braces, semicolons, function boundaries (see **1**, **4**).
2. Port/record access — `$in`/`$out` syntax (see **6**).
3. Every function call must exist in **10** with correct args/return type.
4. Types & conversions — **2**, **3**. No implicit conversions.
5. Null-safety — `isnull()`/`isNull()`; `nvl()` for fallbacks; `isBlank()` for null+empty. See **11.8**.
6. No records/variants mixing (see **11.6**, **11**).

## Generate CTL2: steps
1. State assumptions — ports, field names/types.
2. Component context — lifecycle functions (see **8**).
3. Bulk copy `.*`, then override fields explicitly.
4. Documented operators and functions only.
5. `isnull()`, `nvl()`, explicit checks for required fields.

---

## 1. Program Structure

```
//#CTL2              — interpreted mode (default)
//#CTL2:COMPILE      — compiled mode (faster; no conditional-fail expr, no DB lookups)
```

Script order: imports → variable declarations → function declarations → statements/mappings.
Declarations and statements can be interspersed. Variables/functions must be declared before use.

```ctl
import "trans/filterFunctions.ctl";
import '${TRANS_DIR}/utils.ctl';
import metadata "meta/Customer.fmt";
import metadata "${META_DIR}/Order.fmt" MyOrderAlias;
```

- Double-quoted paths: support escape sequences. Single-quoted: only `\'`.
- Graph parameters (`${PARAM}`) allowed in paths.
- `import metadata` (since CloverDX 5.6) makes external metadata available for record variables.

```ctl
// Single-line comment
/* Multi-line comment */
```

---

## 2. Data Types

### 2.1 Primitive Types

### 2.1.1 Literal Usage (Important for LLMs)

CTL2 provides **native literals** for several types. Prefer literals over conversion functions whenever possible.

#### Date / Date-time literals

Formats: `yyyy-MM-dd` (date) or `yyyy-MM-dd HH:mm:ss` (date-time).

```ctl
date date1 = 2025-01-01; // date only
date datetime1 = 2023-06-15 08:45:00; // date + time
```

Equivalent (but unnecessary):

```ctl
date d = str2date("2025-01-01", "yyyy-MM-dd");
```

**Rule:**  
Use date/date-time literals for constants instead of `str2date()`.

---

#### Decimal literals

```ctl
decimal price = 10.50D;
```

---

#### Long literals

```ctl
long id = 1234567890123L;
```

---

#### Summary

| Type | Preferred |
|------|----------|
| date | `date d = 2025-01-01;` |
| decimal | `10.5D` |
| long | `123L` |


| Type | Default | Literal Examples | Notes |
|---|---|---|---|
| `boolean` | `false` | `true`, `false` | |
| `integer` | `0` | `123`, `0xA7B0`, `0644` | 32-bit signed. |
| `long` | `0` | `257L`, `9562307813123123L` | 64-bit signed. **`L` suffix required**. Use long literals instead of implicit integer widening when value exceeds integer range. |
| `number` (alias `double`) | `0.0` | `123.45`, `1.5e2` | 64-bit IEEE 754 double-precision. Default floating-point type. |
| `decimal` | `0` | `123.45D`, `10.50D` | Fixed-precision. **`D` suffix required on literals**. Prefer decimal literals for precise arithmetic instead of `number`. |
| `date` | `1970-01-01 00:00:00 GMT` | `2025-01-01`, `2023-06-15 08:45:00` | Holds both date AND time. **CTL2 supports date and date-time literals**, which can be directly assigned to `date` variables or used as function parameters. No need for `str2date()` when using literal values. |
| `string` | `""` | | |
| `byte` | `null` | (use `hex2byte()`) | Raw byte array. |
| `cbyte` | `null` | | Compressed byte array. |

### 2.2 String Literals

| Syntax | Escape sequences |
|---|---|
| `"double quoted"` | `\n \r \t \\ \" \b` |
| `'single quoted'` | Only `\'` — backslash-n is literal |
| `"""triple quoted"""` | None — real newlines preserved |

### 2.3 Complex Types

```ctl
string[] myList;                        // list short syntax
list[string] myList2;                   // list verbose syntax
integer[] nums = [10, 17, 31];
list[list[string]] nested;
list[map[string, integer]] listOfMaps;
// 0-based indexing; assigning beyond bounds auto-fills preceding with null

map[string, integer] scores = {"Alice" -> 95, "Bob" -> 87};
// Key types: boolean, date, decimal, integer, long, number, string only
// myMap["key"] returns null if key missing
```

**Variant:**
```ctl
variant v;                    // default: null
variant vMap = {};
variant vList = [];
```
- Holds any type. No compile-time type checking.
- **Must cast before typed operations**: `integer i = cast(myVariant, integer);`
- `cast()` is for variant→strong type ONLY. Never `cast(decimal, integer)` — use `decimal2integer()`.
- Check type: `typeof` operator or `getType()`.
- Access: `v["key"]` (map), `v[0]` (list).
- Most container functions work with variant if it contains the proper container type.

**Record:**
```ctl
import metadata "meta/Customer.fmt" Customer;
Customer myRecord;
myRecord.firstName = "John";
// or registered at graph level — definition auto-propagated to CTL
Order myOrder;
```
- Defined by metadata. Fields by name or index. Deep-copied on assignment.

### 2.4 Variable Declaration

```ctl
integer count;
integer count = 0;
const integer MAX = 100;
const string[] TAGS = ["a", "b", "c"];
```
- `const` prevents reassignment.
- Outside functions: **global** (persists across records). Inside functions: **local**.

---

## 3. Operators

### 3.1 Arithmetic

| Operator | Notes |
|---|---|
| `+` | `numeric+(numeric,numeric)` / `string+(string,string)` (concat) / `list+(list,list)` (concat) / `map+(map,map)` (union) |
| `+=` | compound assignment: `x += y` ≡ `x = x + y`; same type rules as `+` (numeric, string concat, list concat, map union) |
| `-` `*` `%` | numeric; `%` works on float/decimal too (e.g., `6.25 % 2.5` → `1.25`) |
| `-=` `*=` `/=` `%=` | compound assignment (numeric only): `x -= y` ≡ `x = x - y`; same division/modulus rules as `/` and `%` |
| `/` | both-integer → truncates (`7/2`→`3`); float operand → float; decimal → decimal; ÷0 → exception for integer/long/decimal, Infinity for number |
| `++` `--` | pre/post; **cannot use on**: literals, record fields, map/list values |

**Numeric type promotion** (automatic, per expression): `integer < long < number(double) < decimal`.
Rules: int+long→long; int/long+number→number (⚠ long→number may lose precision); int/long+decimal→decimal.
⚠ **`number` is contagious**: if any operand is `number` (or an unsuffixed float literal like `0.15`, which is `number`), the entire expression is floating-point — decimal precision is lost. Use `D`-suffixed literals throughout to stay in decimal math.
No implicit downcast on assignment — result type must match target or use explicit conversion (`decimal2double()`, `decimal2long()`, `double2long()`, etc.).
Overflow: integer/long overflow silently (no error). Null operand → runtime exception.

### 3.2 Relational

| Operator | Alternative | Notes |
|---|---|---|
| `==` | `.eq.` | All types. Strings by value. |
| `!=` | `<>`, `.ne.` | |
| `<` | `.lt.` | Numeric, date, string. |
| `>` | `.gt.` | |
| `<=` | `=<`, `.le.` | |
| `>=` | `=>`, `.ge.` | |
| `~=` | `.regex.` | Regex **whole-string** match. `"bookcase" ~= "book"` → false. |
| `?=` | | Regex **contains**. `"miredo" ?= "redo"` → true. |

Dotted alternatives must be surrounded by spaces.

**Null behavior:**
- `==`, `!=`, `<>`: safe with null. `null == null` → true; `null == nonNull` → false. Never throw.
- `<`, `>`, `<=`, `>=`: **throw runtime exception if either operand is null.** Guard first:
```ctl
if (!isnull($in.0.amount) && !isnull($in.0.threshold) && $in.0.amount > $in.0.threshold) { ... }
// or: nvl($in.0.amount, 0) > nvl($in.0.threshold, 0)
```

### 3.3 Type Check

```ctl
value typeof type   // returns boolean; false if null; does NOT check element types
```
Valid types: `integer`, `long`, `number`, `decimal`, `string`, `boolean`, `date`, `byte`, `cbyte`, `list`, `map`, `record`, `variant`, any metadata name.

### 3.4 Logical

| Operator | Alternative | Notes |
|---|---|---|
| `&&` | `and`, `.and.` | Short-circuit |
| `\|\|` | `or`, `.or.` | Short-circuit |
| `!` | `not`, `.not.` | |

### 3.5 Assignment

| Operator | Notes |
|---|---|
| `=` | Deep copy for lists, maps, records, dates. |
| `+=` | If left side null: uses type default (0, "", [], {}). |
| `-=` `*=` `/=` `%=` | |

**`+=` vs `+` with null strings:**
```ctl
string s = null;
s += "hello";      // s = "hello"   (null treated as "")
s = s + "hello";   // s = "nullhello" (null concatenated as "null")
```

### 3.6 Ternary

```ctl
result = condition ? valueIfTrue : valueIfFalse;   // both branches must be same type
```

### 3.7 Conditional Fail Expression (interpreted mode only, NOT compiled)

```ctl
expr1 : expr2 : ... : exprN;
```

- `//#CTL2` only (not `//#CTL2:COMPILE`).
- Evaluate left → right; first non-throwing expression wins; rest are skipped.
- If all expressions throw, graph fails.
- Usable in assignment, output mapping, and function arguments.
- Can return `null`; use `nvl()` when non-null fallback is required.

```ctl
date d = str2date($in.0.text, "yyyy-MM-dd") : str2date($in.0.text, "dd.MM.yyyy") : null;   // assignment/mapping/arg contexts
```

---

## 4. Control Flow

```ctl
if (cond) { ... } else if (cond2) { ... } else { ... }

switch (expr) {          // expr: integer, string, boolean, double, decimal, date; labels must be unique literals; null expr is allowed (no runtime error) — default branch is taken if present
    case "v1": ...; break;
    case "v2":
    case "v3": ...; break;  // fall-through
    default: ...;
}

for (integer i = 0; i < 10; i++) { ... }
while (cond) { ... }
do { ... } while (cond);
foreach (string item : myStringList) { ... }
// foreach: list→elements, map→values (use getKeys() for keys), record→field values
break; continue; return; return expression;
```

---

## 5. Functions

```ctl
function returnType functionName(type1 arg1, type2 arg2) {
    return value;
}
```
- Return type: any type or `void`. Can be nested. Must be declared before use.

**Calling conventions:**
```ctl
result = upperCase(substring($in.0.name, 0, 5));   // standard
result = $in.0.name.substring(0, 5).upperCase();   // object notation (not for Misc functions)
```

---

## 6. Record and Port Access

```ctl
$in.0.fieldName    $out.0.fieldName     // by name
$in.0.2            $out.1.0             // by index (0-based)
$in.0.*            $out.0.*             // wildcard
```
`$` prefix: only for `$in`/`$out`. Record variables never use `$`.

**Bulk copying:**
```ctl
$out.0.* = $in.0.*;           // copy matching fields by name+type
$out.1 = $out.0;              // full record assignment (identical metadata)
$out.0 = $in.0;               // no wildcard needed if metadata is identical
copyByName($out.0, $in.0);
copyByPosition($out.0, $in.0);
```

**Record variables:**
```ctl
import metadata "meta/Customer.fmt" Customer;
Customer myCustomer;
myCustomer.firstName = "John";
$out.0.* = myCustomer.*;
```
Record assignment = deep copy. For dynamic access by index/name at runtime use record functions (**11.6**).

---

## 7. Error Handling

```ctl
try {
    c = a / b;
} catch (CTLException ex) {
    printLog(warn, "Error: " + ex.message);
    c = -1;
}
```
**CTLException** fields (properties, NOT methods — `ex.message` not `ex.getMessage()`):
`sourceRow`, `sourceColumn`, `message`, `cause`, `stackTrace` (list[string]), `exceptionTrace` (list[string]).

Limitations: one `catch` block, only `CTLException`, no `finally`.

```ctl
raiseError("Fatal: invalid data");   // aborts graph unless caught

printLog(debug|info|warn|error|fatal, "message");
printLog(info, "myLogger", "message with custom logger");
printErr("message");
printErr("message", true);   // with source location
```

---

## 8. Component CTL Patterns

### 8.1 Return Constants

| Constant | Value | Meaning |
|---|---|---|
| `OK` | `0` | Success, send to port 0. |
| `ALL` | special | Send to all connected output ports. |
| `SKIP` | `-1` | Skip record. |
| `STOP` | `-2` | Stop processing (DataGenerator: normal termination). |
| `0`, `1`, `2`... | port index | Send to specific port. |

### 8.2 Map / Reformat (transformer)

```ctl
//#CTL2
function integer transform() {
    $out.0.name = upperCase($in.0.name);
    return ALL;
}
function integer transformOnError(string errorMessage, string stackTrace) {
    return SKIP;
}
```

### 8.3 DataGenerator

```ctl
//#CTL2
integer counter = 0;
function integer generate() {
    counter++;
    $out.0.id = counter;
    return OK;
}
function integer generateOnError(string errorMessage, string stackTrace) { return SKIP; }
```

### 8.4 Denormalizer

```ctl
//#CTL2
integer count;
decimal total;
function integer append() {
    count++;
    total += $in.0.amount;
    return OK;
}
function integer appendOnError(string errorMessage, string stackTrace) { return OK; }
function integer transform() {
    $out.0.count = count;
    $out.0.total = total;
    $out.0.average = total / count;
    return OK;
}
function integer transformOnError(string errorMessage, string stackTrace) { return SKIP; }
function void clean() { count = 0; total = 0.0D; }
```

### 8.5 Normalizer

```ctl
//#CTL2
string[] parts;
function integer count() {
    parts = split($in.0.csvField, ",");
    return length(parts);
}
function integer countOnError(string errorMessage, string stackTrace) { return 0; }
function integer transform(integer idx) {
    $out.0.parentId = $in.0.id;
    $out.0.part = trim(parts[idx]);
    return OK;
}
function integer transformOnError(string errorMessage, string stackTrace, integer idx) { return SKIP; }
function void clean() { clear(parts); }
```

### 8.6 Partition

```ctl
//#CTL2
function integer getOutputPort() {
    if ($in.0.region == "EMEA") return 0;
    if ($in.0.region == "AMER") return 1;
    return 2;
}
function integer getOutputPortOnError(string errorMessage, string stackTrace) { return 0; }
```

### 8.7 Rollup

Accumulator metadata is set on the Rollup component; `GroupAccMeta` and `groupAccumulator` are examples only, actual type/name come from graph metadata.

```ctl
//#CTL2
// First record in each group.
function void initGroup(GroupAccMeta groupAccumulator) {
    groupAccumulator.count = 0;
    groupAccumulator.total = 0D;
}
// Every record in group (first..last).
function boolean updateGroup(GroupAccMeta groupAccumulator) {
    groupAccumulator.count++;
    groupAccumulator.total += $in.0.amount;
    return true;
}
// Last record in each group.
function boolean finishGroup(GroupAccMeta groupAccumulator) {
    groupAccumulator.avg = groupAccumulator.total / groupAccumulator.count;
    return true;
}
// After finishGroup=true; emit group-level outputs.
function integer transform(integer counter, GroupAccMeta groupAccumulator) {
    if (counter > 0) return SKIP;
    $out.0.count = groupAccumulator.count;
    $out.0.average = groupAccumulator.avg;
    return ALL;
}
```

### 8.8 Optional init()

```ctl
function boolean init() {
    return true;   // return false to abort graph; runs once before processing
}
```

---

## 9. Graph Parameters, Lookup Tables, Sequences, Dictionary

```ctl
string path = "${DATAIN_DIR}/input.csv";      // inline — resolved before execution
string value = getParamValue("MY_PARAM");      // runtime
string raw = getRawParamValue("MY_PARAM");     // unresolved
```

Standard parameters: `${DATAIN_DIR}`, `${DATAOUT_DIR}`, `${DATATMP_DIR}`, `${CONN_DIR}`, `${TRANS_DIR}`, `${LOOKUP_DIR}`, `${SEQ_DIR}`, `${META_DIR}`, `${GRAPH_DIR}`, `${SUBGRAPH_DIR}`, `${JOBFLOW_DIR}`, `${LIB_DIR}`.

Lookup table functions: `count`, `get`, `next`, `put`. Access via `lookup(<name>)` where name is unquoted identifier.
Only one query per lookup table at a time (single internal state for next record).
Do NOT use lookup functions in `init()`, `preExecute()`, or `postExecute()`.

- **get(keyValue)** — returns first matching record or `null`. Access fields: `.fieldName` or `.*`.
- **next()** — returns next record with same key (after `get`), or `null` when exhausted.
- **count(keyValue)** — returns number of matching records. DB lookups may return `-1` if `Max cached size` is 0.
- **put(record)** — stores record in lookup; returns `boolean`. Record metadata must match. Not supported by DB lookups. Stored records may not be available for reading in the same phase.

DB lookups require interpreted mode (`//#CTL2`), not compiled (`//#CTL2:COMPILE`).

```ctl
// get — single-key and multi-key
UsersMetadata rec = lookup(UsersLookup).get("searchKey");
rec = lookup(MyLookup).get(key1, key2);
string phone = lookup(users).get("John", "Smith").phone; //read field from lookup record

// iterate duplicates
UsersMetadata u = lookup(UsersLookup).get($in.0.key);
while (u != null) {
    // process u
    u = lookup(UsersLookup).next();
}

// count and put
integer cnt = lookup(MyLookup).count("key");
lookup(MyLookup).put(myRecord);  // returns boolean
```

```ctl
integer id = sequence(MySequence).next();
integer id2 = sequence(MySequence).current();
long idL = sequence(MySequence, long).next();
string idS = sequence(MySequence, string).next();
// Do NOT use sequences in init(), preExecute(), postExecute().

string val = dictionary.myEntry;
dictionary.myEntry = "some value";
```

---

## 10. Metadata (XML Format)

Metadata defines the structure of records flowing between components. Fields in CTL2 are typed by their metadata definition.

### 10.1 Type Mapping

| Metadata `type` | CTL2 type | Notes |
|---|---|---|
| `string` | `string` | |
| `integer` | `integer` | 32-bit signed |
| `long` | `0` | `257L`, `9562307813123123L` | 64-bit signed. **`L` suffix required**. Use long literals instead of implicit integer widening when value exceeds integer range. |
| `number` (alias `double`) | `0.0` | `123.45`, `1.5e2` | 64-bit IEEE 754 double-precision. Default floating-point type. |
| `decimal` | `0` | `123.45D`, `10.50D` | Fixed-precision. **`D` suffix required on literals**. Prefer decimal literals for precise arithmetic instead of `number`. |
| `number` | `number` (`double`) | Floating-point |
| `boolean` | `boolean` | |
| `date` | `1970-01-01 00:00:00 GMT` | `2025-01-01`, `2023-06-15 08:45:00` | Holds both date AND time. **CTL2 supports date and date-time literals**, which can be directly assigned to `date` variables or used as function parameters. No need for `str2date()` when using literal values. |
| `byte` | `byte` | Raw bytes |
| `cbyte` | `cbyte` | Compressed bytes |
| `variant` | `variant` | Dynamic type |

### 10.2 Container Fields

`containerType` attribute on `<Field>` makes it a list or map:
- `containerType="list"` — `type` = element type; CTL2 type is `type[]`.
- `containerType="map"` — `type` = value type; key is always `string`; CTL2 type is `map[string, type]`.

### 10.3 Key Field Attributes

| Attribute | Default | Meaning |
|---|---|---|
| `nullable` | `true` | `false` → graph fails at runtime if null flows through. Compiler does NOT enforce. |
| `nullValue` | (not set) | Which source string(s) map to null on read. Default (not set): `""` → null. Custom value (e.g. `"N/A"`): only that string → null; `""` is no longer null. Multiple: `"NULL\|N/A\|none"` (pipe-separated). |
| `default` | (not set) | Default value if field is null/missing. Applied at read time. |
| `format` | (not set) | For `date` fields: Java SimpleDateFormat pattern used during parsing/formatting. |
| `length` | type-dependent | Max length for `string`/`decimal`. |
| `scale` | `0` | Decimal places for `decimal`. |

### 10.4 Example Metadata XML

```xml
<Metadata id="Metadata0">
  <Record name="CustomerRecord" type="delimited" fieldDelimiter="," recordDelimiter="\n"
          nullValue="N/A">  <!-- record-level nullValue; field-level overrides this -->
    <Field name="customer_id" type="integer" nullable="false"/>
    <Field name="name" type="string"/>
    <Field name="balance" type="decimal" length="10" scale="2"/>
    <Field name="created" type="date" format="yyyy-MM-dd"/>
    <Field name="status" type="string" nullValue="NULL|N/A|none"/>
    <Field name="score" type="number" default="0.0" nullable="false"/>
    <Field name="tags" type="string" containerType="list"/>
    <Field name="properties" type="string" containerType="map"/>
    <Field name="extra_data" type="variant"/>
  </Record>
</Metadata>
```

**Key nullability rules for CTL2:**
- Unset record fields are `null` by default (not the type's zero value).
- `nullable="false"` is a runtime data-quality constraint — the CTL2 compiler allows null assignment regardless.
- `nullValue` affects only what is read from source data; within CTL2 the field behaves as a normal nullable field.
- `""` is null only if no custom `nullValue` is set on the field or its record. Once a custom `nullValue` is configured, `""` stays as `""`.

---

## 11. Built-in Functions — Complete Reference

> If a function is not listed here, it does NOT exist in CTL2.

### 11.1 Conversion Functions

**Important:** Conversion functions (e.g., `str2date`, `str2decimal`) are intended for parsing external string input. Do NOT use them for constant values — use CTL2 literals instead.

**Locale format:** `"language.COUNTRY"` e.g. `"en.US"`, `"de.DE"`.


| Function | Signature(s) | Description |
|---|---|---|
| `base64byte` | `byte base64byte(string)` | Base64 string → byte array. |
| `bits2str` | `string bits2str(byte)` | Byte array → binary string. |
| `bool2num` | `integer bool2num(boolean)` | true→1, false→0. |
| `byte2base64` | `string byte2base64(byte)` | Byte array → base64. |
| | `string byte2base64(byte, boolean wrap)` | With line-wrapping. |
| `byte2hex` | `string byte2hex(byte)` | Byte array → hex string. |
| | `string byte2hex(byte, string escapeChars)` | With per-byte prefix. |
| `byte2str` | `string byte2str(byte, string charset)` | Byte array → string. |
| `cast` | `<type> cast(variant, <type>)` | Cast variant to strong type. **Only for variant → strong type. NEVER between strong types.** Three forms: (1) scalar: `cast(v, string)` → `string`; (2) list: `cast(v, list, elemType)` → e.g. `cast(v, list, string)` → `list[string]`; (3) map: `cast(v, map, keyType, valueType)` → e.g. `cast(v, map, string, long)` → `map[string,long]`. Map requires BOTH key and value types. |
| `date2long` | `long date2long(date)` | Date → ms since epoch. |
| `date2num` | `integer date2num(date, unit)` | Extract component. Units: `year`, `month`, `week`, `day`, `hour`, `minute`, `second`, `millisec`. |
| | `integer date2num(date, unit, string locale)` | |
| `date2str` | `string date2str(date, string pattern)` | Date → string. Java SimpleDateFormat. |
| | `string date2str(date, string pattern, string locale)` | |
| | `string date2str(date, string pattern, string locale, string timeZone)` | |
| `decimal2double` | `number decimal2double(decimal)` | |
| `decimal2integer` | `integer decimal2integer(decimal)` | |
| `decimal2long` | `long decimal2long(decimal)` | |
| `double2integer` | `integer double2integer(number)` | |
| `double2long` | `long double2long(number)` | |
| `hex2byte` | `byte hex2byte(string)` | Hex string → byte array. |
| `json2xml` | `string json2xml(string)` | JSON → XML string. |
| `long2date` | `date long2date(long)` | ms since epoch → date. |
| `long2integer` | `integer long2integer(long)` | |
| `long2packDecimal` | `byte long2packDecimal(long)` | Long → packed decimal bytes. |
| `num2bool` | `boolean num2bool(integer\|long\|number\|decimal)` | 0→false, nonzero→true. |
| `num2str` | `string num2str(numeric)` | Number → string. |
| | `string num2str(integer\|long\|double, integer radix)` | Base 2–36. |
| | `string num2str(numeric, string format)` | Java DecimalFormat. |
| | `string num2str(numeric, string format, string locale)` | |
| `packDecimal2long` | `long packDecimal2long(byte)` | |
| `parseBson` | `variant parseBson(byte)` | BSON → variant. |
| `parseJson` | `variant parseJson(string)` | JSON → variant; null→null; whole numbers→`integer`/`long` (size-based), decimals→`number` (`double`). |
| `parseAvro` | `variant parseAvro(byte, string schema)` | Avro → variant. |
| `record2map` | `variant record2map(record)` | Record → map variant. |
| `str2bits` | `byte str2bits(string)` | Binary string → byte array. |
| `str2bool` | `boolean str2bool(string)` | Accepts TRUE/FALSE, T/F, YES/NO, Y/N, 1/0 (upper or lower case); null -> null. |
| `str2byte` | `byte str2byte(string, string charset)` | |
| `str2date` | `date str2date(string, string pattern)` | Java SimpleDateFormat. `locale`: `"en.US"` (dot-separated). `timeZone`: `"GMT-5"`, `"UTC"`, etc. |
| | `date str2date(string, string pattern, boolean strict)` | |
| | `date str2date(string, string pattern, string locale)` | |
| | `date str2date(string, string pattern, string locale, boolean strict)` | |
| | `date str2date(string, string pattern, string locale, string timeZone)` | |
| | `date str2date(string, string pattern, string locale, string timeZone, boolean strict)` | |
| `str2decimal` | `decimal str2decimal(string)` | null → null. |
| | `decimal str2decimal(string, string format)` | Numeric format pattern; null/`""` = default locale format. |
| | `decimal str2decimal(string, string format, string locale)` | locale: see Locale; default locale if omitted. |
| `str2double` | `number str2double(string)` | |
| | `number str2double(string, string format)` | |
| | `number str2double(string, string format, string locale)` | |
| `str2integer` | `integer str2integer(string)` | |
| | `integer str2integer(string, integer radix)` | |
| | `integer str2integer(string, string format)` | |
| | `integer str2integer(string, string format, string locale)` | |
| `str2long` | `long str2long(string)` | |
| | `long str2long(string, integer radix)` | |
| | `long str2long(string, string format)` | |
| | `long str2long(string, string format, string locale)` | |
| `str2timeUnit` | `unit str2timeUnit(string)` | String → time unit constant. |
| `toString` | `string toString(any)` | Any → string. Null → "null". Debug only. |
| `writeAvro` | `byte writeAvro(variant, string schema)` | |
| `writeBson` | `byte writeBson(variant)` | Variant → BSON. Top-level must be map. |
| | `byte writeBson(map)` | |
| `writeJson` | `string writeJson(variant)` | Variant → JSON. Dates: ISO-8601 UTC. |
| `xml2json` | `string xml2json(string)` | |

### 11.2 String Functions

| Function | Signature(s) | Description |
|---|---|---|
| `charAt` | `string charAt(string, integer index)` | Char at index (0-based). |
| `chop` | `string chop(string)` | Remove trailing newline/CR. |
| | `string chop(string, string regex)` | Remove trailing chars matching regex. |
| `codePointAt` | `integer codePointAt(string, integer index)` | Unicode code point at index. |
| `codePointLength` | `integer codePointLength(integer code)` | Char count for code point (1 or 2). |
| `codePointToChar` | `string codePointToChar(integer code)` | Code point → character. |
| `concat` | `string concat(string, string, ...)` | Concatenate. Null args → "null". Faster than `+` for 3+. |
| `concatWithSeparator` | `string concatWithSeparator(string sep, string, string, ...)` | Join with separator. |
| `contains` | `boolean contains(string, string substring)` | Contains substring? **input null → false. substring null → fails.** |
| `countChar` | `integer countChar(string, string char)` | Count occurrences of char. |
| `cut` | `string[] cut(string, integer[] indices)` | Returns substrings by `indices` position/length pairs `[pos1,len1,pos2,len2,...]` (even count required; `null`/`""` input fails). Example: `cut("somestringasanexample",[2,3,1,5]) = ["mes","omest"]`. |
| `editDistance` | `integer editDistance(string, string)` | Levenshtein distance. Defaults: strength=4, locale=system, maxDifference=3; null/empty args fail. |
| | `integer editDistance(string, string, string locale)` | |
| | `integer editDistance(string, string, integer strength)` | |
| | `integer editDistance(string, string, integer strength, string locale)` | |
| | `integer editDistance(string, string, integer strength, integer maxDifference)` | |
| | `integer editDistance(string, string, integer strength, string locale, integer maxDifference)` | Returns `maxDifference + 1` once cutoff is reached. |
| `endsWith` | `boolean endsWith(string, string suffix)` | **str null → false. suffix null → fails.** |
| `escapeUrl` | `string escapeUrl(string)` | URL-encode. |
| `unescapeUrl` | `string unescapeUrl(string)` | Decodes %-encoded sequences (e.g. %20→space). Requires valid URL; empty/null/invalid → error. |
| `escapeUrlFragment` | `string escapeUrlFragment(string)\|string escapeUrlFragment(string, string encoding)` | Default encoding: UTF-8; null encoding fails. |
| `unescapeUrlFragment` | `string unescapeUrlFragment(string)\|string unescapeUrlFragment(string, string encoding)` | Inverse of escapeUrlFragment; null input → null; null encoding → fails. |
| `escapeXML` | `string escapeXML(string)` | Escape &, <, >, ", '. |
| `unescapeXML` | `string unescapeXML(string input)` | Unescape XML entities to original chars (' , ", &, <, >); inverse of `escapeXML`. |
| `find` | `string[] find(string, string regex)` | All regex matches. |
| `formatMessage` | `string formatMessage(string template, variant ..., variant)` | Template `{0}`, `{1}`. Format: `{index[,type[,style]]}`. Types: `number`, `date`, `time`, `choice`. Styles: `short`, `medium`, `long`, `full`, `integer`, `currency`, `percent`, custom. Example: `formatMessage("Date: {0,date,short}, Cost: {1,number,currency}", myDate, price)`. |
| `formatMessageWithLocale` | `string formatMessageWithLocale(string locale, string template, variant ..., variant)` | |
| `getAlphanumericChars` | `string getAlphanumericChars(string)` | Keep alphanumeric only. |
| | `string getAlphanumericChars(string, boolean takeAlpha, boolean takeNumeric)` | |
| `getFileExtension` | `string getFileExtension(string)` | |
| `getFileName` | `string getFileName(string)` | |
| `getFileNameWithoutExtension` | `string getFileNameWithoutExtension(string)` | |
| `getFilePath` | `string getFilePath(string)` | Extract directory path. |
| `getUrlHost` | `string getUrlHost(string)` | |
| `getUrlPath` | `string getUrlPath(string)` | |
| `getUrlPort` | `integer getUrlPort(string)` | |
| `getUrlProtocol` | `string getUrlProtocol(string)` | |
| `getUrlQuery` | `string getUrlQuery(string)` | |
| `getUrlRef` | `string getUrlRef(string)` | |
| `getUrlUserInfo` | `string getUrlUserInfo(string)` | |
| `indexOf` | `integer indexOf(string, string substring)` | First index (−1 if not found). **string null → −1. substring null → fails; substring `""` → 0.** |
| | `integer indexOf(string, string substring, integer fromIndex)` | Search from index. |
| `isAscii` | `boolean isAscii(string)` | |
| `isBlank` | `boolean isBlank(string)` | Null, empty, or whitespace-only? |
| `isDate` | `boolean isDate(string, string pattern)` | `pattern`: Java SimpleDateFormat. `locale`: `"en.US"` (dot-separated). `timeZone`: `"GMT-5"`, `"UTC"`, etc. |
| | `boolean isDate(string, string pattern, boolean strict)` | |
| | `boolean isDate(string, string pattern, string locale)` | |
| | `boolean isDate(string, string pattern, string locale, boolean strict)` | |
| | `boolean isDate(string, string pattern, string locale, string timeZone)` | |
| | `boolean isDate(string, string pattern, string locale, string timeZone, boolean strict)` | Examples: `isDate("2014-03-30 2:30 +1000","yyyy-MM-dd H:m Z","en.US")=true`; `isDate("2014-03-30 2:30","yyyy-MM-dd H:m","en.US","GMT-5")=true`. |
| `isDecimal` | `boolean isDecimal(string)` | |
| | `boolean isDecimal(string, string format)` | |
| | `boolean isDecimal(string, string format, string locale)` | |
| `isEmpty` | `boolean isEmpty(string)` | Null or empty? |
| `isInteger` | `boolean isInteger(string)` | |
| | `boolean isInteger(string, string format)` | |
| | `boolean isInteger(string, string format, string locale)` | |
| `isLong` | `boolean isLong(string)` | |
| | `boolean isLong(string, string format)` | |
| | `boolean isLong(string, string format, string locale)` | |
| `isNumber` | `boolean isNumber(string)` | |
| | `boolean isNumber(string, string format)` | |
| | `boolean isNumber(string, string format, string locale)` | |
| `isUrl` | `boolean isUrl(string)` | |
| `join` | `string join(string delimiter, type[] array)` | Join array with delimiter. |
| `lastIndexOf` | `integer lastIndexOf(string input, string substr)` | Last occurrence. `input` null → `-1`; `substr` null → fail. |
| | `integer lastIndexOf(string input, string substr, integer index)` | Search backward from `index`. `index` null/`substr` null → fail; `index < 0` → `-1`. |
| `left` | `string left(string, integer length)` | Leftmost N chars. |
| `length` | `integer length(string)` | Also works on lists, maps, records. **null or `""` → 0.** |
| `lowerCase` | `string lowerCase(string)` | **null → null.** |
| `lpad` | `string lpad(string, integer length)` | Left-pad with spaces. |
| | `string lpad(string input, integer length, string filler)` | Left-pad using filler. |
| `matches` | `boolean matches(string, string regex)` | Whole-string match. |
| `matchGroups` | `string[] matchGroups(string, string regex)` | Capture groups. |
| `metaphone` | `string metaphone(string)` | Phonetic code. |
| `normalizeDecimal` | `string normalizeDecimal(string arg)` | Normalize decimal-like strings by stripping non-numeric chars and using the rightmost `,` or `.` as decimal separator. Heuristic only. **null → null.** |
| `normalizeWhitespaces` | `string normalizeWhitespaces(string)` | Trim + collapse internal whitespace. |
| `normalizePath` | `string normalizePath(string arg)` | Normalize path/URL: remove `.` and resolvable `..`, convert `\` to `/`. Unresolvable `..` or null input → null. |
| `properCase` | `string properCase(string)` | Title Case. **null → null.** |
| | `string properCase(string, string locale)` | Locale-aware (e.g. Dutch "ij" digraph). locale null or `""` → default locale. **string null → null.** |
| `randomString` | `string randomString(integer minLen, integer maxLen)` | |
| `randomUUID` | `string randomUUID()` | |
| `removeBlankSpace` | `string removeBlankSpace(string)` | Remove all whitespace. |
| `removeDiacritic` | `string removeDiacritic(string)` | |
| `removeNonAscii` | `string removeNonAscii(string)` | |
| `removeNonPrintable` | `string removeNonPrintable(string)` | |
| `replace` | `string replace(string, string regex, string replacement)` | Replace regex matches. **Pattern arg is always regex — escape special chars: `replace(s, "\\.", "_")`** |
| `reverse` | `string reverse(string)` | |
| `right` | `string right(string, integer length)` | Rightmost N chars. |
| `rpad` | `string rpad(string, integer length)` | Right-pad with spaces. |
| | `string rpad(string input, integer length, string filler)` | Right-pad using filler. |
| `soundex` | `string soundex(string)` | Phonetic code. |
| `split` | `string[] split(string, string regex)` | Split on regex. **Pattern is always regex.** |
| `startsWith` | `boolean startsWith(string, string prefix)` | **str null → false. prefix null → fails.** |
| `substring` | `string substring(string, integer fromIndex)` | From index to end. Returns null if arg null; fails if fromIndex negative/null. |
| | `string substring(string, integer fromIndex, integer length)` | **`length` = max chars, NOT end index.** Fails if length negative/null. |
| `trim` | `string trim(string)` | Remove leading/trailing whitespace. **null → null; `""` → `""`.** |
| `upperCase` | `string upperCase(string)` | **null → null.** |

### 11.3 Date Functions

| Function | Signature(s) | Description |
|---|---|---|
| `createDate` | `date createDate(integer year, integer month, integer day)` | Construct date. **Month is 1-based** (1=January). |
| | `date createDate(integer year, integer month, integer day, string timeZone)` | |
| | `date createDate(integer year, integer month, integer day, integer hour, integer minute, integer second)` | |
| | `date createDate(integer year, integer month, integer day, integer hour, integer minute, integer second, string timeZone)` | |
| | `date createDate(integer year, integer month, integer day, integer hour, integer minute, integer second, integer millisecond)` | |
| | `date createDate(integer year, integer month, integer day, integer hour, integer minute, integer second, integer millisecond, string timeZone)` | |
| `dateAdd` | `date dateAdd(date, long amount, unit)` | Units: `year`, `month`, `week`, `day`, `hour`, `minute`, `second`, `millisec`. |
| `dateDiff` | `long dateDiff(date later, date earlier, unit)` | Difference in units (truncated). |
| `extractDate` | `date extractDate(date)` | Zero out time part. |
| `extractTime` | `date extractTime(date)` | Zero out date part. |
| `getDay` | `integer getDay(date)` | Day of month. |
| | `integer getDay(date, string timeZone)` | |
| `getDayOfWeek` | `integer getDayOfWeek(date)` | 1=Monday … 7=Sunday. |
| | `integer getDayOfWeek(date, string timeZone)` | |
| `getHour` | `integer getHour(date)` | 0–23. |
| | `integer getHour(date, string timeZone)` | |
| `getMillisecond` | `integer getMillisecond(date)` | |
| | `integer getMillisecond(date, string timeZone)` | |
| `getMinute` | `integer getMinute(date)` | 0–59. |
| | `integer getMinute(date, string timeZone)` | |
| `getMonth` | `integer getMonth(date)` | **1-based** (January=1). |
| | `integer getMonth(date, string timeZone)` | |
| `getSecond` | `integer getSecond(date)` | 0–59. |
| | `integer getSecond(date, string timeZone)` | |
| `getYear` | `integer getYear(date)` | |
| | `integer getYear(date, string timeZone)` | |
| `randomDate` | `date randomDate(date from, date to)` | Random date in range (inclusive). |
| | `date randomDate(long from, long to)` | Epoch millis. |
| | `date randomDate(string from, string to, string format)` | |
| | `date randomDate(string from, string to, string fmt, string locale)` | |
| | `date randomDate(string from, string to, string fmt, string locale, string tz)` | |
| `today` | `date today()` | Current date and time. |
| `zeroDate` | `date zeroDate()` | 1970-01-01 00:00:00 GMT. |

Date format patterns: Java SimpleDateFormat — `yyyy`, `MM`, `dd`, `HH`, `mm`, `ss`, `SSS`, `EEE`, `MMM`, `z`/`Z`.

**Dates are immutable.** No setters. To change a component: `createDate(2025, getMonth(d), getDay(d), ...)`.

### 11.4 Mathematical Functions

| Function | Signature(s) | Description |
|---|---|---|
| `abs` | `T abs(T)` — T: integer\|long\|number\|decimal | Absolute value. |
| `acos` | `number acos(number\|decimal)` | Arc cosine (radians). |
| `addNoise` | `T addNoise(T value, T noise)` | Add random noise ±noise. Use for anonymization. |
| | `date addNoise(date, long noise)` | Noise in ms. |
| | `date addNoise(date, long noise, unit)` | |
| `asin` | `number asin(number\|decimal)` | |
| `atan` | `number atan(number\|decimal)` | |
| `bitAnd` | `T bitAnd(T, T)` — T: integer\|long\|byte | |
| `bitIsSet` | `boolean bitIsSet(integer\|long, integer index)` | |
| `bitLShift` | `T bitLShift(T, T)` | |
| `bitNegate` | `T bitNegate(T)` | |
| `bitOr` | `T bitOr(T, T)` | |
| `bitRShift` | `T bitRShift(T, T)` | |
| `bitSet` | `T bitSet(T, integer index, boolean value)` | |
| `bitXor` | `T bitXor(T, T)` | |
| `ceil` | `number ceil(number)`, `decimal ceil(decimal)` | |
| `cos` | `number cos(number\|decimal)` | |
| `e` | `number e()` | 2.71828… |
| `exp` | `number exp(integer\|long\|number\|decimal)` | e^x. |
| `floor` | `number floor(number)`, `decimal floor(decimal)` | |
| `log` | `number log(number\|decimal)` | Natural log. |
| `log10` | `number log10(number\|decimal)` | |
| `max` | `T max(T, T)` | |
| | `T max(T[])` | Max in list. |
| `min` | `T min(T, T)` | |
| | `T min(T[])` | |
| `pi` | `number pi()` | 3.14159… |
| `pow` | `number pow(number, number)`, `decimal pow(decimal, decimal)` | |
| `random` | `number random()` | [0.0, 1.0). |
| | `number random(number min, number max)` | |
| `randomBoolean` | `boolean randomBoolean()` | |
| `randomDecimal` | `decimal randomDecimal()` | |
| | `decimal randomDecimal(decimal min, decimal max)` | |
| `randomGaussian` | `number randomGaussian()` | mean=0, stddev=1. |
| `randomInteger` | `integer randomInteger()` | |
| | `integer randomInteger(integer min, integer max)` | |
| `randomLong` | `long randomLong()` | |
| | `long randomLong(long min, long max)` | |
| `round` | `long round(number)`, `decimal round(decimal)` | Half-up. |
| | `T round(T, integer precision)` | Negative precision rounds before decimal. |
| `roundHalfToEven` | `decimal roundHalfToEven(decimal)` | Banker's rounding. |
| | `decimal roundHalfToEven(decimal, integer precision)` | |
| `setRandomSeed` | `void setRandomSeed(long)` | Seed RNG. Use in `init()`. |
| `signum` | `integer signum(integer\|long\|decimal)`, `number signum(number)` | −1, 0, or 1. |
| `sin` | `number sin(number\|decimal)` | |
| `sqrt` | `number sqrt(number\|decimal)` | |
| `tan` | `number tan(number\|decimal)` | |
| `toDegrees` | `number toDegrees(number\|decimal)` | |
| `toRadians` | `number toRadians(number\|decimal)` | |

### 11.5 Container Functions (List, Map, Variant)

> **Variant compatibility:** list/map funcs also accept `variant` containers; typed and `variant` overloads are equivalent. `append()` and `push()` are interchangeable. `append()`/`push()`/`insert()` mutate and return the same container; `pop()`/`poll()`/`remove()` mutate and return removed value.

| Function | Signature(s) | Description |
|---|---|---|
| `append` | `T[] append(T[], T element)` | Append to end. Returns modified list. `append(nullList, x)` throws error. |
| | `variant append(variant, variant)` | variant must contain list. |
| `appendAll` | `list[E] appendAll(list[E] target, list[E] source)` | Append `source` to `target`; returns mutated `target`. `target==null` fails. Since 6.4.0. |
| | `map[K,V] appendAll(map[K,V] target, map[K,V] source)` | Merge into `target`; existing keys in `target` are preserved (left wins). `target==null` or `source==null` fails. Since 6.4.0. |
| | `variant appendAll(variant target, variant source)` | Same semantics for list/map variants; fails on non-container, mixed types, or null-invalid cases. Since 6.4.0. |
| `binarySearch` | `integer binarySearch(T[], T)` | Binary search on **pre-sorted** list. Returns 0-based index if found; negative value `-(insertionPoint+1)` if not found. |
| `clear` | `void clear(list\|map\|variant)` | Remove all elements. |
| `containsAll` | `boolean containsAll(T[], T[])` | List contains all from another? |
| `containsKey` | `boolean containsKey(map, key)` | Map contains key? **map null → fails.** |
| | `boolean containsKey(variant, variant key)` | variant must contain map. |
| `containsValue` | `boolean containsValue(map\|list, value)` | Map/list contains value? **first arg null → fails.** |
| | `boolean containsValue(variant, variant value)` | variant must contain map or list. |
| `in` | `boolean in(any element, list\|map\|variant collection)` | True if collection contains element. For maps: checks keys. Object notation: `element.in(collection)`. |
| `copy` | `T[] copy(T[] to, T[] from)` | Copy elements. |
| | `map[K,V] copy(map[K,V] to, map[K,V] from)` | Merge `from` into `to` (overwrite duplicate keys); returns mutated `to`; null arg fails. |
| `findAllValues` | `variant findAllValues(variant container, variant key)` | Find all values for key in nested. |
| `getKeys` | `keyType[] getKeys(map)` | All keys as list. |
| | `variant getKeys(variant)` | variant must contain map. |
| `getValues` | `valueType[] getValues(map)` | All values as list. |
| | `variant getValues(variant)` | variant must contain map. |
| `insert` | `list[T] insert(list[T], integer index, T element)` | Insert at position. |
| | `list[T] insert(list[T], integer index, list[T] elements)` | |
| | `variant insert(variant, integer index, variant)` | |
| `isEmpty` | `boolean isEmpty(list\|map)` | |
| `length` | `integer length(list\|map\|string\|record\|variant)` | Elements/chars/fields. For maps: key-value pair count; nested list: top-level size only. **null → 0.** |
| `poll` | `T poll(T[])` | Remove and return first element. **Empty list → fails.** |
| | `variant poll(variant)` | variant must contain list. |
| `pop` | `T pop(T[])` | Remove and return last element. **Empty list → fails.** |
| | `variant pop(variant)` | variant must contain list. |
| `push` | `list[T] push(list[T], T element)` | Add to end (alias of `append`). |
| | `variant push(variant, variant)` | variant must contain list. |
| `remove` | `T remove(T[], integer index)` | Remove at index (0-based). Mutates list. Returns removed. **null → fails.** |
| | `V remove(map[K,V], K key)` | Remove by key from map. Mutates map. Returns removed value. **null → fails.** |
| | `variant remove(variant, variant)` | variant must contain list or map. Mutates. Returns removed. **null → fails.** |
| `reverse` | `T[] reverse(T[])` | Reverse list. Returns modified list. **null → fails.** |
| | `variant reverse(variant)` | variant must contain list, else fails. |
| `sort` | `T[] sort(T[])` | Ascending. |
| | `variant sort(variant)` | variant must contain list. |
| `toMap` | `map toMap(variant)` | Convert variant containing map to typed map. |
| | `map[K,V] toMap(K[] keys, V[] values)` | Build map from equal-length key and value lists. **keys null → fails. values null → fails.** |
| | `map[K,V] toMap(K[] keys, V value)` | Build map: all keys map to same value. **keys null → fails. value null → all keys map to null.** |

Variant access: `v["key"]`, `v[0]`, `v["key"] = val`, `v[0] = val`.

### 11.6 Record Functions (Dynamic Field Access)

Dynamic field access in CTL2 is **function-based**. Do not use object-style access such as `record.get(...)` or `record.set(...)`. For dynamic access by field name or index, use the functions below.

| Function | Signature(s) | Description |
|---|---|---|
| `compare` | `integer compare(record, integer idx1, record, integer idx2)` | Compare by field index. Returns `<0`, `0`, `>0`. |
| | `integer compare(record, string fieldName1, record, string fieldName2)` | Compare by field name. |
| `copyByName` | `void copyByName(record to, record from)` | Copy matching field names. |
| `copyByPosition` | `void copyByPosition(record to, record from)` | Copy matching field positions. |
| `getBoolValue` | `boolean getBoolValue(record, integer fieldIndex)` | |
| | `boolean getBoolValue(record, string fieldName)` | |
| `getByteValue` | `byte getByteValue(record, integer fieldIndex)` | |
| | `byte getByteValue(record, string fieldName)` | |
| `getDateValue` | `date getDateValue(record, integer fieldIndex)` | |
| | `date getDateValue(record, string fieldName)` | |
| `getDecimalValue` | `decimal getDecimalValue(record, integer fieldIndex)` | |
| | `decimal getDecimalValue(record, string fieldName)` | |
| `getFieldIndex` | `integer getFieldIndex(record, string fieldName)` | Returns zero-based index, or `-1` if not found. |
| `getFieldLabel` | `string getFieldLabel(record, integer fieldIndex)` | |
| `getFieldName` | `string getFieldName(record, integer fieldIndex)` | |
| `getFieldProperties` | `map[string,string] getFieldProperties(record, integer fieldIndex)` | Unmodifiable metadata-property map for field. |
| | `map[string,string] getFieldProperties(record, string fieldName)` | |
| `getFieldType` | `string getFieldType(record, integer fieldIndex)` | |
| `getIntValue` | `integer getIntValue(record, integer fieldIndex)` | |
| | `integer getIntValue(record, string fieldName)` | |
| `getLongValue` | `long getLongValue(record, integer fieldIndex)` | |
| | `long getLongValue(record, string fieldName)` | |
| `getNumValue` | `number getNumValue(record, integer fieldIndex)` | |
| | `number getNumValue(record, string fieldName)` | |
| `getRecordProperties` | `map[string,string] getRecordProperties(record)` | Unmodifiable metadata-property map for record. |
| `getStringValue` | `string getStringValue(record, integer fieldIndex)` | |
| | `string getStringValue(record, string fieldName)` | |
| `getValue` | `variant getValue(record, integer fieldIndex)` | |
| | `variant getValue(record, string fieldName)` | |
| `getValueAsString` | `string getValueAsString(record, integer fieldIndex)` | |
| | `string getValueAsString(record, string fieldName)` | |
| `isNull` | `boolean isNull(record, integer fieldIndex)` | **camelCase — NOT `isnull`** |
| `isNull` | `boolean isNull(record, string fieldName)` | **camelCase — NOT `isnull`** |
| `length` | `integer length(record)` | Number of fields. `null` record → `0`. |
| `resetRecord` | `void resetRecord(record)` | Reset all fields to null/default. |
| `setBoolValue` | `void setBoolValue(record, integer idx, boolean val)` | |
| | `void setBoolValue(record, string fieldName, boolean val)` | |
| `setByteValue` | `void setByteValue(record, integer idx, byte val)` | |
| | `void setByteValue(record, string fieldName, byte val)` | |
| `setDateValue` | `void setDateValue(record, integer idx, date val)` | |
| | `void setDateValue(record, string fieldName, date val)` | |
| `setDecimalValue` | `void setDecimalValue(record, integer idx, decimal val)` | |
| | `void setDecimalValue(record, string fieldName, decimal val)` | |
| `setIntValue` | `void setIntValue(record, integer idx, integer val)` | |
| | `void setIntValue(record, string fieldName, integer val)` | |
| `setLongValue` | `void setLongValue(record, integer idx, long val)` | |
| | `void setLongValue(record, string fieldName, long val)` | |
| `setNumValue` | `void setNumValue(record, integer idx, number val)` | |
| | `void setNumValue(record, string fieldName, number val)` | |
| `setStringValue` | `void setStringValue(record, integer idx, string val)` | |
| | `void setStringValue(record, string fieldName, string val)` | |
| `setValue` | `void setValue(record, integer idx, variant val)` | |
| | `void setValue(record, string fieldName, variant val)` | |

Record metadata helpers return `map[string,string]`, not `variant`.

### 11.7 Hash and Crypto Functions

| Function | Signature(s) | Description |
|---|---|---|
| `md5` | `byte md5(byte\|string)` | |
| `md5HexString` | `string md5HexString(byte\|string)` | |
| `sha1` | `string sha1(byte\|string)` | |
| `sha1HexString` | `string sha1HexString(byte\|string)` | |
| `sha256` | `byte sha256(byte\|string)` | |
| `sha256HexString` | `string sha256HexString(byte\|string)` | |
| `hashCode` | `integer hashCode(integer\|long\|number\|decimal\|boolean\|date\|string\|record\|map\|variant)` | Java-style hash. |

### 11.8 Null Handling

**Fundamentals:**
- Every type can be null. `null` ≠ `""` — `isnull("")` = false.
- Local var defaults: primitives NOT null (see **2.1**). `byte`/`cbyte`/`variant` default null.
- Unset record fields are null (not type default) unless metadata defines a Default.
- `isnull(expr)` and `expr == null` / `expr != null` are **interchangeable** for all types (scalars, records, lookup results, etc.).
- In joins, do NOT test missing slave as `isnull($in.1)`; test a slave field, e.g. `isnull($in.1.region_name)`.

**Two different null check functions:**

| Function | Casing | Args | Signature | Use case |
|---|---|---|---|---|
| `isnull` | lowercase | 1 | `boolean isnull(any expr)` | Any value, variable, named field. |
| `isNull` | camelCase | 2 | `boolean isNull(record, integer index)` | Dynamic field by index. |
| `isNull` | camelCase | 2 | `boolean isNull(record, string fieldName)` | Dynamic field by name. |

```ctl
isnull(null)             // true
isnull("")               // false — "" NOT null
isnull($in.0.name)       // true if field null
isNull($in.0, 0)         // field at index 0 null?
isNull($in.0, "field2")  // field "field2" null?
// INVALID: isnull($in.0, 0)   — 1 arg only
// INVALID: isNull($in.0.name) — needs 2 args
// INVALID: $in.0.name == NULL — uppercase NULL invalid
```

**Metadata `Null value` property** — which source strings map to null on read:
- Default (not set): `""` → null.
- Custom set (e.g. `"N/A"`): only that string → null; `""` no longer null.
- Multiple: `nullValue="NULL\|N/A\|none"` (pipe-separated).
- `nullable="false"` on `<Field>`: runtime fail on null. Compiler doesn't enforce it.

**Local var null behavior:**

| Type | `isnull()` on unset local var |
|---|---|
| `string` | false (default `""`) |
| `integer`/`long`/`decimal` | false (default `0`) |
| `number`/`double` | false (default `0.0`) |
| `boolean` | false (default `false`) |
| `date` | `1970-01-01 00:00:00 GMT` | `2025-01-01`, `2023-06-15 08:45:00` | Holds both date AND time. **CTL2 supports date and date-time literals**, which can be directly assigned to `date` variables or used as function parameters. No need for `str2date()` when using literal values. |
| `byte`/`cbyte`/`variant` | true |
| record field (unset) | true |

**Null functions:**

| Function | Signature | Description |
|---|---|---|
| `isnull` | `boolean isnull(any expr)` | 1 arg, lowercase. |
| `isNull` | `boolean isNull(record, integer\|string)` | 2 args, camelCase. |
| `nvl` | `T nvl(T value, T default)` | Non-null or default. Types must match. |
| `nvl2` | `T nvl2(<any> value, T ifNotNull, T ifNull)` | Returns `ifNotNull` if value is non-null, else `ifNull`. First arg can be any type; second and third must match. |
| `isBlank` | `boolean isBlank(string)` | Null, `""`, or whitespace. |
| `isEmpty` | `boolean isEmpty(string)` | Null or `""`. No whitespace check. |
| `iif` | `T iif(boolean, T, T)` | Inline conditional (prefer `? :`). |

`isnull(expr)` and `expr == null` are interchangeable for any expression. For dynamic field access by index/name use `isNull(record, idx)` / `isNull(record, "name")`. Fallback: `nvl()`; null+empty: `isBlank()`.

**Common null mistakes:**
- `isnull($in.0, 0)` INVALID — use `isNull($in.0, 0)`.
- `isNull($in.0.name)` INVALID — use `isnull($in.0.name)`.
- `null + "text"` = `"nulltext"` — guard with `nvl()`.
- `nvl()` type mismatch — both args must be same type.
- Local `integer x;` starts at `0`, not null. Unset `$in.0.count` is null.
- Custom `Null value` metadata disables empty-as-null.
- `nullable="false"` is runtime-only.
- **`<`, `>`, `<=`, `>=` throw runtime exception if either operand is null.** `==`/`!=` are null-safe. Guard: `!isnull(x) && x > y` or `nvl(x, default) > nvl(y, default)`.

### 11.9 Miscellaneous / Utility Functions

| Function | Signature(s) | Description |
|---|---|---|
| `evalExpression` | `variant evalExpression(string expr)` | Evaluate a CTL expression string at runtime. Result is always `variant` — cast before use. Expensive; avoid in per-record loops. |
| `getComponentProperty` | `string getComponentProperty(string name)` | Component config property. |
| `getEnvironmentVariables` | `map getEnvironmentVariables()` | System env vars. |
| `getJavaProperties` | `map getJavaProperties()` | Java system properties. |
| `getParamValue` | `string getParamValue(string paramName)` | Resolved graph param. |
| `getParamValues` | `map getParamValues()` | All graph params. |
| `getRawParamValue` | `string getRawParamValue(string paramName)` | Unresolved param. |
| `getRawParamValues` | `map getRawParamValues()` | All unresolved params. |
| `getType` | `string getType(variant)` | Type name string. Returns `"double"` for `number`/`double` values. |
| `getCurrentTimeMillis` | `long getCurrentTimeMillis()` | Epoch ms. |
| `getOAuth2Token` | `string getOAuth2Token(string connName)` | |
| `parseProperties` | `map parseProperties(string)` | Parse properties format. |
| `printErr` | `void printErr(any message)` | |
| | `void printErr(any message, boolean printLocation)` | With source location. |
| `printLog` | `void printLog(level, any message)` | Levels: `debug`, `info`, `warn`, `error`, `fatal`. |
| | `void printLog(level, string logger, any message)` | |
| `raiseError` | `void raiseError(string message)` | Abort processing. |
| `resolveParams` | `string resolveParams(string)` | Resolve `${PARAM}` in string. |
| `sleep` | `void sleep(long millis)` | |
| `toAbsolutePath` | `string toAbsolutePath(string path)` | Path/URL -> OS absolute path; relative input resolves against graph context URL; server `sandbox://` works only for local files on current node; conversion fail -> `null`; `path=null` -> error. |
| `toProjectUrl` | `string toProjectUrl(string path)` | Relative path -> `sandbox://<sandbox>/...`; `null` -> `null`; `""`/`"."` -> sandbox root; `"/"` -> `file:/`;|

### 11.10 Validation Functions

| Function | Signature(s) | Description |
|---|---|---|
| `isUnicodeNormalized` | `boolean isUnicodeNormalized(string, string form)` | |
| `isValidCodePoint` | `boolean isValidCodePoint(integer)` | |
| `unicodeNormalize` | `string unicodeNormalize(string, string form)` | |
| `validateCreditCard` | `string validateCreditCard(string, boolean acceptEmpty)` | Null if valid. |
| `validateEmail` | `string validateEmail(string, boolean acceptEmpty)` | Null if valid. |
| `validatePhoneNumber` | `string validatePhoneNumber(string, string region, boolean acceptEmpty)` | Null if valid. |

### 11.11 Data Service / HTTP Functions (Data Service components only)

| Function | Description |
|---|---|
| `getRequestBody()` | HTTP request body (string). |
| `getRequestMethod()` | HTTP method. |
| `getRequestParameter(string)` | Query/form parameter. |
| `getRequestParameterNames()` | All parameter names. |
| `getRequestParameters(string)` | All values for parameter. |
| `getRequestHeader(string)` | Request header value. |
| `getRequestHeaderNames()` | All header names. |
| `getRequestContentType()` | |
| `getRequestEncoding()` | |
| `getRequestClientIPAddress()` | |
| `getRequestPartFilename(string)` | Multipart filename. |
| `setResponseBody(string)` | |
| `setResponseStatus(integer)` | |
| `setResponseContentType(string)` | |
| `setResponseEncoding(string)` | |
| `setResponseHeader(string, string)` | |
| `addResponseHeader(string, string)` | |
| `containsResponseHeader(string)` | |
| `getResponseContentType()` | |
| `getResponseEncoding()` | |
| `setRequestEncoding(string)` | |

### 11.12 Subgraph Functions

| Function | Description |
|---|---|
| `getSubgraphInputPortsCount()` | Number of input ports. |
| `getSubgraphOutputPortsCount()` | Number of output ports. |
| `isSubgraphInputPortConnected(integer)` | |
| `isSubgraphOutputPortConnected(integer)` | |

---

## 12. Regular Expressions

Java regex (`java.util.regex.Pattern`):

| Token | Meaning |
|---|---|
| `.` | Any character |
| `?` `*` `+` | 0-or-1, 0+, 1+ |
| `\|` | Alternation |
| `()` `[]` `[^...]` | Grouping, class, negated class |
| `{n}` `{n,}` `{n,m}` | Exact, min, range |
| `\s\S` `\d\D` `\w\W` | Whitespace, digit, word (and negations) |
| `^` `$` | Start/end of string |

Flags: `(?i)` case-insensitive, `(?s)` dotall, `(?m)` multiline.

Functions using regex: `replace()`, `split()`, `find()`, `matches()`, `matchGroups()`, `chop()`, `~=`, `?=`.
In `replace(str, regex, repl)` and `split(str, regex)`: pattern is always regex. Escape specials: `replace(s, "\\.", "_")`.

---

## 13. CTL2 Constraints, Pitfalls, and Invalid Patterns

### 13.1 Things CTL2 Does NOT Have

- No classes/objects — procedural only.
- No lambdas, closures, arrow functions, anonymous functions.
- No generics — type specified at declaration.
- Only `CTLException` in catch — no exception hierarchy, no `finally`.
- No `interface`, `abstract`, `enum`, `this`/`self`.
- No Java class imports — only CTL files and metadata.
- No `??` — use `nvl()`. No `?.` optional chaining.
- No `in` operator syntax — use `in()` function: `in(x, list)` or `x.in(list)`.
- **No `size()` / `.size()`** — use `length()`. #1 hallucinated method.
- **No `if(cond, a, b)` as function** — use `iif(cond, a, b)`. `if` is control-flow only.
- **No `toInteger()`, `toDouble()`, `toDecimal()`** — use `str2integer()`, `str2double()`, `str2decimal()`. Most common hallucination.
- **No `parseDate()`, `parseInt()`, `parseDecimal()`** — use `str2date()`, `str2integer()`, `str2decimal()`.
- **No `now()`** — use `today()` for current date-time.
- No `asc()` — use `codePointAt(string, index)`.
- No `catch(Exception)` — only `catch(CTLException)`. Properties: `ex.message` NOT `ex.getMessage()`.
- No `foreach (x in list)` — use colon: `foreach (type x : list)`. No tuple unpacking.
- No `.keys()`, `.contains()` on lists, `.firstKey()`, `.nextKey()`, `removeAt()` — use `getKeys()`, `containsValue()`/`in()`, `remove()`.
- No record reflection: no `.getField("x")`, `.set("x", v)`, `.fields()` — use **11.6**.
- No JSON-style access on records (`rec["field"]`) — bracket syntax for variant only.
- No `printJson` — use `writeJson()`.
- No `containerSize` — use `length()`.
- No `decode` — CTL1 only, does not exist in CTL2.
- No `$variable` for local vars — `$` only for `$in`/`$out`.
- No `format` — use `formatMessage`.
- No `toUpperCase`/`toLowerCase` — use `upperCase()`/`lowerCase()`.
- No `strip` — use `trim()`.
- No `len` — use `length()`.
- No `print` — use `printLog()`/`printErr()`.
- No `range` — use for loop.
- No `map`/`filter`/`reduce` — use foreach.
- No `JSON.parse`/`JSON.stringify` — use `parseJson()`/`writeJson()`.


### 13.2 Common Pitfalls

1. **Decimal without `D`**: `123.45` is `number`, not `decimal`. Use `123.45D`. Mixing a `number` literal into a `decimal` expression silently degrades to floating-point math.
2. **Long without `L`**: `9999999999` overflows integer. Use `9999999999L`.
3. **`replace()` regex**: `replace(s, ".", "_")` replaces EVERY char. Use `replace(s, "\\.", "_")`.
4. **`split()` regex**: `split(s, ".")` splits every char. Use `split(s, "\\.")`.
5. **`~=` whole string**: `"bookcase" ~= "book"` is FALSE. Use `?=` or `".*book.*"`.
6. **`getMonth()` 1-based**: January = 1.
7. **`substring()` out-of-bounds throws**: unlike Python slicing.
8. **`null + "text"` = `"nulltext"`**: use `nvl()` first.
9. **Variant requires cast**: `integer i = myVariant;` INVALID. Use `cast(myVariant, integer)`.
10. **No date setters**: use `createDate()` to reconstruct.
11. **`++` on record fields**: `$out.0.count++` INVALID. Use `$out.0.count = $out.0.count + 1;`.
12. **Map foreach yields values**: use `getKeys(myMap)` for keys.
13. **`iif()` not `if()`**: `if(cond, a, b)` INVALID — #1 LLM error (37×).
14. **Conversion naming**: `str2integer()` not `toInteger()`/`parseInt()`.
15. **`foreach` colon not `in`**: `foreach (string s : myList)`. No tuple unpacking.
16. **Exception**: `catch(CTLException e)` only. `e.message` property, not `e.getMessage()`.
17. **Port syntax**: `$in.0.field` — NOT `$in0.field`, NOT `$field`.
18. **`lastIndexOf()`** has 2 forms; optional `index` searches backward from `index`. `input` null → `-1`; `substr`/`index` null → fail; `index < 0` → `-1`.
19. **`date2num()` needs unit**: `date2num(date, day)` — not bare `date2num(date)`.
20. **`double` is valid alias** for `number`. `double x = 1.5;` is valid.
21. **`cast()` strong-type conversion INVALID**: `cast(decimal, integer)` is wrong. Use `decimal2integer()`.
22. **Null function confusion**: `isnull(expr)` (1 arg, lowercase) and `expr == null` are interchangeable. `isNull(record, idx/name)` (2 args, camelCase) is a different function for dynamic field access. `isnull("")` = false. Local primitive vars NOT null. See **11.8**.
23. **Null in ordering comparisons throws**: `<`, `>`, `<=`, `>=` throw `CTLException` if either operand is null. `==`/`!=` are null-safe. Use `isnull()` guards or `nvl()` fallbacks.
24. **Numeric promotion one-way**: `integer→long→number(double)→decimal`; assigning result to lower type is a compile error — use explicit conversion. long→number may lose precision. integer/long overflow silently.

---

## 14. Validation Checklist

1. Header `//#CTL2` or `//#CTL2:COMPILE` (optional).
2. Imports at top. Syntax: `import "path";` or `import metadata "path";`.
3. Types: only from **2**. No `int`, `float`, `str`, `char`, `object`, `HashMap`, `ArrayList`.
4. Literals: `D` suffix for decimal, `L` for long. No `f`/`F`.
5. String literals: `"..."`, `'...'`, `"""..."""` only. No backticks.
6. Operators: only **3**. No `===`, `>>>`, `instanceof`, `is`, `not in`, `in` as operator.
7. Control flow: only `if/else`, `switch/case`, `for`, `while`, `do-while`, `foreach`, `break`, `continue`, `return`. No `for-in`, `for-of`, `yield`, `async/await`, `try-finally`.
8. Functions: `function returnType name(args)`. No `def`, `fun`, `fn`, arrow, anonymous.
9. Built-in functions: only **10**. Top hallucinations: `size()`→`length()`, `toInteger()`→`str2integer()`, `if(cond,a,b)`→`iif()`, `parseDate()`→`str2date()`, `parseInt()`→`str2integer()`, `now()`→`today()`, `toDouble()`→`str2double()`, `toDecimal()`→`str2decimal()`, `asc()`→`codePointAt()`, `parseDecimal()`→`str2decimal()`, `removeAt()`→`remove()`, `addDays()`→`dateAdd()`, `number2decimal()`→DNE (auto numeric upcast), `double2decimal()`→DNE (`double`=`number`; auto upcast), `regexReplace()`→`replace()`, `printJson`→`writeJson`, `containerSize`→`length`, `format`→`formatMessage`, `toUpperCase`→`upperCase`, `toLowerCase`→`lowerCase`, `strip`→`trim`, `len`→`length`, `print`→`printLog`/`printErr`, `JSON.parse`→`parseJson`, `JSON.stringify`→`writeJson`.
10. Port access: `$in.N.field` / `$out.N.field`. No `input[0]`, `record.get()`.
11. Type casting: `cast(variant, type)` for variants ONLY. No C-style `(int)x`, no `as`.
12. Null: `isnull(expr)` and `expr == null` interchangeable for all types. `isNull(record, int/string)` (2 args, camelCase) is separate — dynamic field access only. No `??`, `?.`, `== NULL`. `""` ≠ null. Ordering operators throw on null.
13. Collections: `type[]` or `list[type]`; `map[keyType, valueType]`. No `List<>`, `Map<>`, `Dictionary`, `Array`, `Set`.
14. Semicolons: all statements end with `;`. Blocks `{}` do NOT.
15. Component functions match expected signatures for component type.
16. Return values: `OK`, `ALL`, `SKIP`, `STOP`, or port number.



### Sequence Functions (complete)

Sequences generate ordered values stored in CloverDX sequence objects.

Basic usage:
```ctl
integer id = sequence(MySequence).next();
integer currentId = sequence(MySequence).current();
sequence(MySequence).reset();
```

Typed access — default is `integer`; specify `long` or `string` as second arg:
```ctl
long idL = sequence(MySequence, long).next();
string idS = sequence(MySequence, string).next();
long curL = sequence(MySequence, long).current();
string curS = sequence(MySequence, string).current();
```

Function semantics:

| Function | Description |
|---|---|
| `next()` | Returns the next sequence value and advances the sequence. The **first call returns the initial value** of the sequence. |
| `current()` | Returns the current sequence value **without advancing** the sequence. **Do not call before the first `next()`** because the sequence may not yet be initialized. |
| `reset()` | Resets the sequence to its initial value. |

Important constraints:

- Sequence functions **must not be used in** `init()`, `preExecute()`, or `postExecute()` lifecycle functions.
- Sequences may be **internal (defined in the graph)** or **external/shared** via a sequence file.
- In clustered execution environments, sequences are **not automatically synchronized across nodes** unless configured as a shared external sequence.
