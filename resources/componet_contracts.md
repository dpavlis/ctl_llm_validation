
# Component CTL Contracts

## Reformat / Map component
	
(a) Entry-point signature(s) - verbatim, exact
- function integer transform()
- Return ALL / OK / output port index / SKIP.

(b) Lifecycle / call order
- transform() is called once per input record.

(c) Port model
- One input ($in.0) and one or more outputs ($out.N).
- Typical mapping pattern: copy from $in.0 to $out.N and override selected fields.

(d) Keep in mind
- Use $out.0.* = $in.0.* for bulk copy, then override specific fields.
- Do not use ++ on record fields ($in/$out). ++ is for local/module vars only.
- Ordered comparisons on nullable values (<, >, <=, >=) require null guards.
- Equality operators == and != are null-safe.

(e) Minimal correct skeleton
```ctl
//#CTL2
function integer transform() {
    $out.0.* = $in.0.*;
    return ALL;
}
```

(f) Minimal correct skeleton - with multiple outputs and skip
```ctl
//#CTL2
function integer transform() {			    
    if ($in.0.value > 1000) {
        $out.0.* = $in.0.*;
        $out.0.status = "high";
        return 0; //send to output port 0
    } else if ($in.0.value > 100) {
        $out.1.* = $in.0.*;
        $out.1.status = "low";
        return 1; //send to output port 1
    }else {
        // skip record
        return SKIP;
    }
}
```

(g) Canonical mistake
- Wrong: ++$out.0.count
- Correct: use a local variable and assign the final value into $out.0.count

## Filter component

(a) Entry-point signature(s) - verbatim, exact
- FILTER CTL is a bare boolean expression at module level.
- No function wrapper, no return statement.

(b) Lifecycle / call order
- Expression is evaluated once per input record.
- true -> record passes; false -> record is rejected.

(c) Port model
- One input port only in CTL context.
- No $out writes in FILTER CTL.

(d) Keep in mind
- Convert "return SKIP" style logic to a negated boolean condition.
- Ordered comparisons on nullable values need guards.
- Equality operators == and != are null-safe.

(e) Minimal correct skeleton
```ctl
//#CTL2
!isnull($in.0.amount) && $in.0.amount > 0
```

(f) Canonical mistake
- Wrong: function integer transform() { ... }
- Correct: single top-level boolean expression.
			
## Partition component
	
(a) Entry-point signature(s) - verbatim, exact
- function integer getOutputPort()
- Not transform().

(b) Lifecycle / call order
- getOutputPort() is called once per input record.
- Return value decides target output port.

(c) Port model
- One input port ($in.0), multiple output ports.
- Routing only; records are not transformed in PARTITION CTL.

(d) Keep in mind
- Return valid zero-based port index.
- Do not write $out fields in PARTITION CTL.
- Ordered comparisons on nullable values need guards.
- Equality operators == and != are null-safe.

(e) Minimal correct skeleton
```ctl
//#CTL2
function integer getOutputPort() {
    if ($in.0.score >= 90) return 0;
    if ($in.0.score >= 50) return 1;
    return 2;
}
```

(f) Canonical mistake
- Wrong: function integer transform()
- Correct: function integer getOutputPort()

## Rollup component		

(a) Entry-point signature patterns - exact shapes
- function void initGroup(<accumulator>)
- function boolean updateGroup(<accumulator>)
- function boolean finishGroup(<accumulator>)
- function integer updateTransform(integer counter, <accumulator>)
- function integer transform(integer counter, <accumulator>)
- Important: <accumulator> is a placeholder for the real accumulator metadata type, for example Acc or GroupAcc.
- Important: transform() has no trailing boolean parameter.
- Important: updateTransform() and transform() are output-generation loops, not single-shot callbacks.

(b) Lifecycle / call order
- initGroup once at the start of each group.
- updateGroup once for each input record in the group.
- After each updateGroup(<accumulator>):
    - if it returns true, CloverDX starts the updateTransform(counter, <accumulator>) loop for that input record
    - if it returns false, no per-record output is generated for that input record
- After the whole group is consumed, finishGroup(<accumulator>) is called once.
- After finishGroup(<accumulator>):
    - if it returns true, CloverDX starts the transform(counter, <accumulator>) loop for the group-final output
    - if it returns false, no final group output is generated
- For both updateTransform and transform:
    - counter starts at 0
    - CloverDX calls the function repeatedly with counter = 0, 1, 2, ...
    - the loop stops only when the function returns SKIP
    
(c) Port model
- One input ($in.0), one or more outputs ($out.N), and one accumulator argument.
- Read $in.0 only in updateGroup.
- Write $out only in updateTransform / transform.
- Do not write $out in initGroup, updateGroup, or finishGroup.

(d) Critical return semantics
- updateGroup(<accumulator>) return value:
    - true = start per-record output loop for this input record
    - false = do not run updateTransform for this input record
- finishGroup(<accumulator>) return value:
    - true = start final group output loop
    - false = do not run transform for this group
- updateTransform(counter, <accumulator>) / transform(counter, <accumulator>) return value:
    - SKIP = stop the current loop immediately
    - ALL = emit the current output record to all connected output ports for this invocation, then CloverDX calls the function again with counter + 1
    - output port number (for example 0, 1, ...) = emit to that one port for this invocation, then CloverDX calls the function again with counter + 1
- Therefore:
    - ALL does not end the loop
    - returning 0 does not end the loop
    - only SKIP ends the loop
- This is the main source of infinite output bugs:
    - if updateTransform() or transform() returns ALL unconditionally, CloverDX keeps calling it forever with counter = 0, 1, 2, ...
    
(e) Output-generation patterns you must follow
- Exactly one detail row per input record:
    - updateGroup(<accumulator>) must return true
    - updateTransform(counter, <accumulator>) must:
    - emit on counter == 0
    - return SKIP for counter > 0
- No detail rows for input records:
    - updateGroup(<accumulator>) must return false
    - updateTransform() may still exist, but will never be entered
- Exactly one summary row per group:
    - finishGroup(<accumulator>) must return true
    - transform(counter, <accumulator>) must:
    - emit on counter == 0
    - return SKIP for counter > 0
- No summary row for a group:
    - finishGroup(<accumulator>) must return false
    
(f) Counter meaning
- counter is not a row number from input data.
- counter is the ordinal number of generated output rows within the current loop.
- updateTransform(counter, <accumulator>):
    - counter counts rows generated for the current input record
- transform(counter, <accumulator>):
    - counter counts rows generated for the final group phase
- If you want one output row only, always guard with:
    - if (counter > 0) return SKIP;
    
(g) Accumulator guidance
- Initialize every accumulator field in initGroup.
- Null arithmetic throws, so never rely on implicit initialization.
- Store any values needed later for output in accumulator fields.
- If final output needs a group key, keep it in the accumulator during updateGroup.
- Do not rely on $in.0 inside transform / updateTransform.

(h) Divide-by-zero / null safety
- Guard divide-by-zero before computing averages or ratios.
- Guard nullable numeric fields before arithmetic, or normalize them before accumulating.
- Typical safe pattern:
    - acc.total = acc.total + nvl($in.0.amount, 0.0);
    - acc.avg = acc.count == 0 ? 0.0 : acc.total / acc.count;
    
(i) Minimal correct skeleton: one detail row per input record + one summary row per group
```ctl
//#CTL2
function void initGroup(acc_type acc) {
    acc.count = 0;
    acc.total = 0.0;
    acc.cur_amount = 0.0;
}
function boolean updateGroup(acc_type acc) {
    acc.count = acc.count + 1;
    acc.cur_amount = $in.0.amount;
    acc.total = acc.total + $in.0.amount;
    return true;
}
function boolean finishGroup(acc_type acc) {
    acc.avg = acc.count == 0 ? 0.0 : acc.total / acc.count;
    return true;
}
function integer updateTransform(integer counter, acc_type acc) {
    if (counter > 0) return SKIP;
    $out.0.record_type = "DETAIL";
    $out.0.amount = acc.cur_amount;
    return ALL;
}
function integer transform(integer counter, acc_type acc) {
    if (counter > 0) return SKIP;
    $out.0.record_type = "SUMMARY";
    $out.0.count = acc.count;
    $out.0.total = acc.total;
    $out.0.avg = acc.avg;
    return ALL;
}
```

(j) Minimal correct skeleton: summary only, no per-record detail rows
```ctl
//#CTL2
function void initGroup(acc_type acc) {
    acc.count = 0;
    acc.total = 0.0;
}
function boolean updateGroup(acc_type acc) {
    acc.count = acc.count + 1;
    acc.total = acc.total + $in.0.amount;
    return false;
}
function boolean finishGroup(acc_type acc) {
    acc.avg = acc.count == 0 ? 0.0 : acc.total / acc.count;
    return true;
}
function integer updateTransform(integer counter, acc_type acc) {
    return SKIP;
}
function integer transform(integer counter, acc_type acc) {
    if (counter > 0) return SKIP;
    $out.0.count = acc.count;
    $out.0.total = acc.total;
    $out.0.avg = acc.avg;
    return ALL;
}
```

(k) Why the generated code loops forever
- This is wrong:
    - function integer updateTransform(integer counter, Acc acc) {
        ...
        return ALL;
    }
- Because:
    - counter = 0 -> emit row, return ALL
    - counter = 1 -> emit row again, return ALL
    - counter = 2 -> emit row again, return ALL
    - and so on forever
- Correct one-detail-row pattern:
    - function integer updateTransform(integer counter, Acc acc) {
        if (counter > 0) return SKIP;
        ...
        return ALL;
    }
    
(l) Canonical mistakes
- Wrong: function integer transform(integer counter, acc_type acc, boolean last)
- Correct: function integer transform(integer counter, acc_type acc)
- Wrong: unconditional return ALL in updateTransform/transform
- Correct: emit for the needed counter values, then return SKIP
- Wrong: using $in.0 in transform
- Correct: store needed values in the accumulator during updateGroup
- Wrong: writing $out in updateGroup
- Correct: write $out only in updateTransform/transform

(m) Short rule the model should memorize
- updateGroup / finishGroup decide whether an output loop starts.
- updateTransform / transform decide how many rows are produced.
- SKIP stops the loop.
- If you want exactly one output row, emit at counter == 0 and return SKIP for counter > 0.

## Denormalizer component
	
(a) Entry-point signature patterns - exact shapes
- function integer append()
- function integer transform()
- function void clean()
- Important: append() and transform() take no parameters.
- Important: clean() returns void, not integer.

(b) Lifecycle / call order
- append() is called once for each input record in the current group.
- append() is the accumulation phase for the group.
- After the whole group is consumed, transform() is called once to produce the final output row for that group.
- After transform() finishes, clean() is called once to reset module-level state before the next group starts.
- Then the same append() -> transform() -> clean() cycle repeats for the next group.

(c) Port model
- One input ($in.0) and one output ($out.0).
- Read $in.0 only in append().
- Write $out.0 only in transform().
- Do not read $out.0 in append().
- Do not read $in.0 in transform().
- clean() should only reset module-level state; it should not read $in.0 or write $out.0.

(d) Critical return semantics
- append() return value:
    - OK = accept this input record into the current group accumulation
    - SKIP = ignore this input record for accumulation
- transform() return value:
    - OK = emit the final output record for the group
    - SKIP = suppress output for the group
- Denormalizer does not use counter-based output loops like Rollup.
- Therefore:
    - transform() is a single-shot finalization callback, not a repeated output loop
    - there is no counter parameter and no need for counter guards
    
(e) State model
- Keep all group state in module-level variables.
- Typical state includes:
    - current group key
    - running totals
    - counts
    - collected lists or concatenated strings
    - first/last values needed later in transform()
- Every module-level accumulator used for one group must be reset in clean().
- If you forget to reset state, values bleed into the next group.

(f) Input/output access rules the model must memorize
- append():
    - read $in.0
    - update module-level accumulators
    - do not write $out.0
- transform():
    - read module-level accumulators
    - write $out.0
    - do not read $in.0
- clean():
    - reset module-level accumulators
    - do not depend on current input/output records
    
(g) Grouping assumptions
- Denormalizer depends on upstream grouping.
- Records for one logical group must arrive together.
- Ensure upstream sorting/grouping assumptions match the component configuration, for example key fields or fixed group size.
- If the upstream order/grouping is wrong, the Denormalizer logic may still compile but produce logically wrong output.

(h) Null-safety / initialization
- Initialize or guard every accumulator before first use.
- Null arithmetic throws.
- Safe numeric accumulation pattern:
    - total = isnull(total) ? nvl($in.0.amount, 0.0) : total + nvl($in.0.amount, 0.0);
- Safe first-key capture pattern:
    - if (isnull(groupKey)) groupKey = $in.0.key;
- Safe string/list accumulation should also consider first-use initialization.

(i) Output-suppression patterns
- If a group should produce no row, return SKIP from transform().
- If some input rows should not contribute to the group, return SKIP from append() for those rows.
- If every input row should contribute, return OK from append().

(j) Minimal correct skeleton
```ctl
//#CTL2
string groupKey;
string[] values;
function integer append() {
    if (isnull(groupKey)) {
        groupKey = $in.0.key;
    }
    append(values, $in.0.value);
    return OK;
}
function integer transform() {
    $out.0.key = groupKey;
    $out.0.values = join(",", values);
    return OK;
}
function void clean() {
    groupKey = null;
    clear(values);
}
```

(k) Minimal correct skeleton with numeric aggregation
```ctl
//#CTL2
string customerId;
decimal totalAmount;
integer count;
function integer append() {
    if (isnull(customerId)) {
        customerId = $in.0.customer_id;
    }
    totalAmount = isnull(totalAmount)
        ? nvl($in.0.amount, 0.0)
        : totalAmount + nvl($in.0.amount, 0.0);
    count = isnull(count) ? 1 : count + 1;
    return OK;
}
function integer transform() {
    $out.0.customer_id = customerId;
    $out.0.total_amount = totalAmount;
    $out.0.count = count;
    return OK;
}
function void clean() {
    customerId = null;
    totalAmount = null;
    count = null;
}
```

(l) Canonical mistakes
- Wrong: using $out.0 in append()
- Correct: only update module-level variables in append()
- Wrong: using $in.0 in transform()
- Correct: store what you need during append(), then emit from saved state in transform()
- Wrong: forgetting to reset accumulators in clean()
- Correct: reset every module-level variable used by the group
- Wrong: assuming numeric/string accumulators start safely
- Correct: initialize or guard first use explicitly

(m) Short rule the model should memorize
- append() reads input and accumulates group state.
- transform() emits exactly one final row for the group from saved state.
- clean() resets everything for the next group.
- Never read $in.0 in transform().
- Never write $out.0 in append().			

## Normalizer component

(a) Entry-point signature patterns - exact shapes
- function integer count()
- function integer transform(integer idx)
- function void clean()
- Optional on-error hooks:
    - function integer countOnError(string errorMessage, string stackTrace)
    - function integer transformOnError(string errorMessage, string stackTrace, integer idx)
- Important: transform() takes exactly one integer idx parameter.
- Important: if transformOnError() is implemented for Normalizer, it must include idx.

(b) Lifecycle / call order
- count() is called once for each input record.
- count() decides how many output rows will be generated for the current input record.
- If count() returns N:
    - transform(0), transform(1), ..., transform(N - 1) are called for that input record
- If count() returns 0:
    - no transform(idx) calls happen for that input record
- After the last transform(idx) call for that input record, clean() is called once.
- Then the same count() -> transform(idx) -> clean() cycle repeats for the next input record.

(c) Port model
- One input ($in.0) expands into zero, one, or many output rows on $out.0.
- Read $in.0 in count() and/or transform(idx).
- Write $out.0 only in transform(idx).
- Do not write $out.0 in count().
- clean() should only reset module-level state; it should not depend on $in.0 or $out.0.

(d) Critical return semantics
- count() return value:
    - non-negative integer N = how many times transform(idx) will be called for the current input record
    - 0 = skip the current input record entirely
- transform(idx) return value:
    - OK = emit the current output row for this idx
    - SKIP = suppress output for this idx
- countOnError(errorMessage, stackTrace) return value:
    - fallback row count for the current input record if count() throws
    - returning 0 is the usual safe choice when count() fails
- transformOnError(errorMessage, stackTrace, idx) return value:
    - fallback result for the current idx if transform(idx) throws
    - returning SKIP is the usual safe choice when a particular output row cannot be produced
- Normalizer does not use repeated output loops like Rollup.
- transform(idx) is called exactly once for each idx chosen by count().

(e) idx meaning
- idx is zero-based.
- idx runs from 0 to count() - 1.
- idx is the ordinal number of the output row being produced for the current input record.
- idx must stay within the bounds of any prepared arrays/lists used by transform(idx).

(f) State model
- Prepare split/list/temporary state in count().
- Consume that prepared state in transform(idx).
- Reset all module-level state in clean().
- If you compute arrays/lists in count(), transform(idx) should read from those arrays/lists rather than recomputing them repeatedly.

(g) Input/output access rules the model must memorize
- count():
    - may read $in.0
    - may prepare module-level arrays/lists/temporary values
    - must not write $out.0
- transform(idx):
    - may read $in.0
    - may read prepared module-level state
    - writes $out.0 for the current output row
- clean():
    - resets module-level state for the next input record
    - should not depend on current input/output records
    
(h) Common output-count patterns
- Zero rows for blank input:
    - if the source string is null/blank, return 0 from count()
- One row per split token:
    - split the string in count()
    - return length(parts)
    - in transform(idx), use parts[idx]
- Exactly one output row per input record:
    - count() returns 1
    - transform(0) writes the one output row
    
(i) Null-safety / preparation guidance
- Guard nullable inputs before split() or parsing.
- If the source field can be null or blank, handle that in count() and return 0 when appropriate.
- Reset prepared arrays/lists in clean() to avoid stale state leaking into the next input record.
- If transform(idx) reads prepared state, make sure count() always initializes that state consistently.

(j) Minimal correct skeleton
```ctl
//#CTL2
string[] parts;
function integer count() {
    if (isBlank($in.0.csv_values)) {
        parts = [];
        return 0;
    }
    parts = split($in.0.csv_values, ";");
    return length(parts);
}
function integer transform(integer idx) {
    $out.0.id = $in.0.id;
    $out.0.value = trim(parts[idx]);
    return OK;
}
function void clean() {
    clear(parts);
}
```

(k) Minimal correct skeleton with optional on-error hooks
```ctl
//#CTL2
string[] parts;
function integer count() {
    if (isBlank($in.0.csv_values)) {
        parts = [];
        return 0;
    }
    parts = split($in.0.csv_values, ";");
    return length(parts);
}
function integer countOnError(string errorMessage, string stackTrace) {
    parts = [];
    return 0;
}
function integer transform(integer idx) {
    $out.0.id = $in.0.id;
    $out.0.value = trim(parts[idx]);
    return OK;
}
function integer transformOnError(string errorMessage, string stackTrace, integer idx) {
    return SKIP;
}
function void clean() {
    clear(parts);
}
```

(l) Canonical mistakes
- Wrong: transformOnError(string errorMessage, string stackTrace)
- Correct: transformOnError(string errorMessage, string stackTrace, integer idx)
- Wrong: returning a boolean from count()
- Correct: count() returns the number of output rows as integer
- Wrong: accessing parts[idx] when count() did not prepare parts consistently
- Correct: prepare state in count(), then consume the same state in transform(idx)
- Wrong: forgetting clean() reset so data from one input record leaks into the next
- Correct: clear/reset all module-level prepared state in clean()
- Wrong: writing $out.0 in count()
- Correct: write $out.0 only in transform(idx)

(m) Short rule the model should memorize
- count() decides how many output rows the current input record expands into.
- transform(idx) emits one output row for one zero-based idx.
- clean() resets prepared state for the next input record.
- If count() returns 0, the current input record produces no rows.
- If transformOnError() exists for Normalizer, it must include idx.
			
## Join / Data Intersection / Cross Join / Combine / Ext Hash Join / Ext Merge Join components

(a) Entry-point signature(s) - verbatim, exact
- function integer transform()

(b) Lifecycle / call order
- transform() runs for each produced joined row.
- Physical join strategy differs by component, CTL contract is the same.

(c) Port model
- Port 0 is master/driver ($in.0).
- Port 1+ are slave/lookup records ($in.1, $in.2, ...).
- Output is written to $out.N from transform().

(d) Keep in mind
- For LEFT_OUTER/FULL_OUTER, guard slave-field reads with field-level null checks.
- Do not use whole-record checks like isnull($in.1).
- Use fields from the correct port; slave-only fields on $in.0 cause field errors.
- Equality operators == and != are null-safe.

(e) Minimal correct skeleton
```ctl
//#CTL2
function integer transform() {
    $out.0.master_id = $in.0.id;
    if (!isnull($in.1.lookup_key)) {
        $out.0.lookup_value = $in.1.value;
    }
    return ALL;
}
```

(f) Canonical mistake
- Wrong: isnull($in.1) or sentinels like -1/NONE for missing slave row.
- Correct: check a concrete slave key field, e.g. isnull($in.1.lookup_key).
			
## DataGenerator component

(a) Entry-point signature(s) - verbatim, exact
- function integer generate()

(b) Lifecycle / call order
- generate() is called repeatedly, number of calls determined by component configuration.

(c) Port model
- No input port.
- Writes generated records to one or more output ports.

(d) Keep in mind
- Module-level counters/state are expected here.
- ++ is valid on module/local variables.
- Don't use STOP or SKIP return constatns. STOP means ABORT.
- For sequence values, use internal counter or sequence(Name).next().

(e) Minimal correct skeleton
```ctl
//#CTL2
integer i = 0;
function integer generate() {			    
    $out.0.id = i;
    i++;
    return ALL;
}
```

(f) Canonical mistake
- Wrong: expecting $in.0 in DATAGENERATOR.
- Correct: no input; generate from module state and constants.

## AI OpenAIClient component

(a) Entry-point signature(s) - verbatim, exact
- function boolean newChat()
- function string prepareQuery(list[ChatMessage] chatContext, integer iterationIndex)
- function integer processResponse(list[ChatMessage] chatContext, integer iterationIndex, string assistantResponse)
- Optional error handlers:
    - function boolean newChatOnError(string errorMessage, string stackTrace)
    - function string prepareQueryOnError(string errorMessage, string stackTrace, list[ChatMessage] chatContext, integer iterationIndex)
    - function integer sendRequestOnError(string errorMessage, string stackTrace, list[ChatMessage] chatContext, integer iterationIndex)
    - function integer processResponseOnError(string errorMessage, string stackTrace, list[ChatMessage] chatContext, integer iterationIndex)

(b) Lifecycle / call order
- Per input record: newChat() -> prepareQuery(...,0) -> request -> processResponse(...,0,...).
- If processResponse returns CONTINUE (-3), the cycle repeats with iterationIndex+1.
- When processResponse returns OK, output row is emitted and processing moves to next input row.

(c) Port model
- Input 0 carries query source data.
- Output 0 carries response and pass-through fields.
- In CTL access rules: prepareQuery can read $in.0, processResponse can read $in.0 and write $out.0.

(d) Keep in mind
- Define CONTINUE constant explicitly: const integer CONTINUE = -3.
- Guard continuation loops with iteration limits to avoid infinite retries.
- Build/append follow-up prompts using chatContext for multi-turn refinement.
- Write output fields only in processResponse (not in prepareQuery).

(e) Minimal correct skeleton
```ctl
//#CTL2
const integer CONTINUE = -3;
function boolean newChat() {
    return true;
}
function string prepareQuery(list[ChatMessage] chatContext, integer iterationIndex) {
    return $in.0.prompt;
}
function integer processResponse(list[ChatMessage] chatContext, integer iterationIndex, string assistantResponse) {
    $out.0.response = assistantResponse;
    return OK;
}
```

(f) Canonical mistake
- Wrong: return CONTINUE without an iteration cap.
- Correct: cap retries with an iterationIndex threshold before CONTINUE.

## REST Connector component

(a) Entry-point signature(s) - verbatim, exact
- Input mapping CTL entry point: function integer transform()
- Default output mapping CTL entry point: function integer transform()
- (Both are distinct mapping contexts but share the same signature.)

(b) Lifecycle / call order
- Input mapping transform() runs before sending each HTTP request.
- REST call executes.
- If status code is not handled by responseMapping (or on transport error), default output mapping transform() runs.

(c) Port model
- Input mapping context:
    - $in.0 = graph input record
    - $out.0.requestContent = request body payload
    - $out.2.<paramName> = request path/query/header parameters
- Default output mapping context:
    - $in.0 has response fields (content, statusCode, errorMessage, etc.)
    - $in.2 carries pass-through original input record
    - $out.N writes graph output ports

(d) Keep in mind
- Do not confuse REST_CONNECTOR virtual mapping ports with graph port numbering.
- For request parameter assignment, use $out.2.<parameterName> in input mapping.
- For JSON request body, assign serialized payload to $out.0.requestContent.
- In default output mapping, consume statusCode/errorMessage from $in.0 and pass-through fields from $in.2.

(e) Minimal correct skeleton
Input mapping:
```ctl
//#CTL2
function integer transform() {
    $out.2.code = $in.0.code;
    variant payload = {"id" -> $in.0.id};
    $out.0.requestContent = writeJson(payload);
    return ALL;
}
```
Default output mapping:
```ctl
//#CTL2
function integer transform() {
    $out.0.response = $in.0.content;
    $out.0.statusCode = $in.0.statusCode;
    $out.0.errorMessage = $in.0.errorMessage;
    return ALL;
}
```

(f) Canonical mistake
- Wrong: use $out.0.<param> for request parameters.
- Correct: set request parameters on $out.2.<param> in input mapping.