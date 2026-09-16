# Specification — Section 17: Skeleton Graph Definitions

> Extends the CTL2 DPO Example Generator spec. This section is the build brief for
> the eight skeleton graphs referenced in Section 16. Hand it to the transformation
> authoring assistant; each subsection is a self-contained spec for one skeleton.
>
> Target sandbox: `DPOForge`. Skeletons live in `graph/skeletons/` (read-only
> source). Execution clones go to `graph/runtime/`. See `graph/README.md`.

---

## 17.0 Shared requirements for every skeleton

Apply these to all eight graphs unless a subsection overrides them.

1. **Shape:** `DATA_GENERATOR (deterministic) → <COMPONENT UNDER TEST> → TRASH`.
   Multi-input or multi-output components add generators / TRASH terminals per port.
2. **Deterministic input only.** The generator uses fixed arrays + index arithmetic
   (`recordIndex % N`, `dateAdd(base, i*kL, day)` etc.) — never `random*`. The known
   input is what makes the §16.5 oracle possible. Follow the proven pattern in the
   existing `PersonGeneratorToTrash.grf` generator.
3. **Self-contained.** No DATA_READER, no DATA_WRITER, no DB connection, no `.fmt` /
   `.lkp` / `.cfg` / input file. Inputs are generated; outputs go to TRASH. The
   sandbox must run with zero external files so it can move server-to-server.
4. **Terminal = TRASH with `debugPrint="true"`** on every output port, so records are
   inspectable via edge debug (`job_get_edge_debug_data`) without writing files.
5. **Fixed injection target id.** The component under test keeps the exact `id` named
   in each subsection — this is where the judge injects candidate CTL. Do not rename.
6. **Stable edge ids.** Name the output edge(s) of the component under test
   predictably (`EdgeOut`, `EdgeOut0`, `EdgeOut1`, …) so the manifest can point the
   judge at the right edge to inspect.
7. **Explicit small metadata** covering string, integer, decimal, and date so
   type-sensitive failure modes (date-format tokens, decimal/integer upcasting)
   actually surface. Define metadata inline in `<Global>`.
8. **Each skeleton must pass `job_validate` (overall PASS) and one clean
   `job_run` (FINISHED_OK)** with the *reference* CTL in place before being committed
   as a skeleton. The committed skeleton ships with correct placeholder CTL so it is
   runnable as-is; the judge overwrites that CTL per candidate.
9. **RichTextNote** on each graph briefly stating it is a DPO validation skeleton for
   component X and must not be edited in place.

**Manifest:** after building, record one row per skeleton (component type, skeleton
path, injection node id, CTL attribute name, required entry points, output edge id(s),
generator row count, oracle notes) in the project knowledge manifest so the judge
agent can look it up rather than hardcoding.

---

## 17.1 REFORMAT skeleton — `REFORMAT_skeleton.grf`

- **Component under test id:** `TRANSFORMER` (type `REFORMAT`).
- **Inject into:** `attr:transform`. Entry point: `function integer transform()`.
- **Generator output (input to REFORMAT):** 50 records.
  Fields: `id:integer` (1..50), `first_name:string`, `last_name:string`,
  `amount:decimal(12,2)` (deterministic, e.g. `(i+1)*1.25`), `order_date:date`
  (`dateAdd(2025-01-01, i, day)`).
- **Output metadata:** include at least one concatenated string
  (`full_name`), one numeric passthrough/derivation, one reformatted date string
  (`order_month:string`, format `yyyy-MM`) — chosen to expose the common REFORMAT
  failure modes.
- **Ports to inspect:** `EdgeOut` = REFORMAT Port 0 (out) → TRASH.
- **Failure modes this targets:** wrong `$out` field assignment, decimal↔integer
  upcasting, date-format tokens, dropped records (wrong return value), null
  propagation.
- **Reference (placeholder) CTL:** straightforward correct mapping
  (`full_name = first_name + " " + last_name`, copy numerics, `order_month =
  date2str(order_date, "yyyy-MM")`, `return ALL;`).

## 17.2 ROLLUP skeleton — `ROLLUP_skeleton.grf`

- **Component under test id:** `ROLLUP0` (type `ROLLUP`).
- **Inject into:** `attr:transform`. Entry points (all five required):
  `initGroup(acc)`, `updateGroup(acc)`, `updateTransform(counter, acc)`,
  `finishGroup(acc)`, `transform(counter, acc)`.
- **Accumulator:** define `groupAccumulatorMetadataId` pointing to an accumulator
  `<Record>`; the placeholder CTL references it by its record name. Note the gotcha:
  accumulator metadata-name mismatch fails the graph at load with
  `"Error loading job file"` — keep name and reference identical.
- **Generator output:** 60 records **emitted already sorted by group key**
  (`region`, `category`) so `inputSorted` can be handled without a SORT component.
  Document in the build `risks[]` that sorting is guaranteed by the generator, so the
  `job_plan` missing-sort warning is a false positive. Fields:
  `region:string`, `category:string`, `order_date:date`, `quantity:integer`,
  `amount:decimal(12,2)`. Use a small fixed set of regions × categories so groups are
  predictable (e.g. 3 regions × 2 categories = 6 groups, 10 rows each).
- **Output metadata:** one summary row per group — `region`, `category`,
  `order_count:integer`, `total_quantity:integer`, `total_amount:decimal(12,2)`.
- **Ports to inspect:** `EdgeOut` = ROLLUP Port 0 (out) → TRASH. Oracle: one row per
  group, correct count/sum.
- **Failure modes this targets (high value):** accumulator metadata-name mismatch,
  missing `updateTransform`, per-record emission instead of per-group, group state
  not initialised in `initGroup`.
- **Reference (placeholder) CTL:** reuse the proven group-accumulator pattern (init
  to zero, accumulate in `updateGroup`, `updateTransform` returns `SKIP`,
  `finishGroup` returns `true`, `transform` emits once per group returning `ALL`).

## 17.3 EXT_FILTER skeleton — `EXT_FILTER_skeleton.grf`

- **Note:** there is no `FILTER` component — use `EXT_FILTER`.
- **Component under test id:** `EXT_FILTER0` (type `EXT_FILTER`).
- **Inject into:** the filter expression attribute. The injected CTL is a **bare
  boolean expression** (no `function`, no `return`, no `//#CTL2` header) — confirm
  the exact attribute name and syntax with `component_get_info` / `component_get_guide`.
- **Generator output:** 100 records, `amount:integer` spanning a known range (e.g.
  0..99 via `recordIndex`), with a handful of deliberate nulls in a nullable field to
  exercise null handling.
- **Ports to inspect:** `EdgeOut0` = Port 0 (accepted), `EdgeOut1` = Port 1 (rejected),
  each → its own TRASH. Oracle: accepted + rejected = 100, and the accepted set
  exactly matches the predicate over the known input.
- **Failure modes this targets:** inverted condition, missing null guard, off-by-one
  boundary, wrong field referenced.
- **Reference (placeholder) CTL:** a simple correct predicate, e.g. `$in.0.amount >= 50`.

## 17.4 DATA_GENERATOR skeleton — `DATAGEN_skeleton.grf`

- **Special case:** here the candidate CTL *is* the generator. The skeleton is just
  `DATA_GENERATOR0 → TRASH`.
- **Component under test id:** `DATA_GENERATOR0` (type `DATA_GENERATOR`).
- **Inject into:** `attr:generate`. Entry point: `function integer generate()`
  (return `OK` to continue, `STOP` to end). Set `recordsNumber` per the task being
  evaluated (the judge sets it when known; default a fixed value such as 100).
- **Output metadata:** a small mixed-type record (`id:integer`, `name:string`,
  `created:date`, `value:decimal(12,2)`).
- **Ports to inspect:** `EdgeOut` = Port 0 (out) → TRASH. Oracle: row count equals the
  requested count and each field follows the task's generation rule.
- **Failure modes this targets:** never returning `STOP` (over/under count vs
  `recordsNumber`), date-token errors, off-by-one indices, wrong field types.
- **Reference (placeholder) CTL:** the deterministic generator already proven in
  `PersonGeneratorToTrash.grf`, trimmed to this metadata.

## 17.5 EXT_HASH_JOIN skeleton — `EXT_HASH_JOIN_skeleton.grf`

- **Component under test id:** `EXT_HASH_JOIN0` (type `EXT_HASH_JOIN`; unsorted,
  in-memory — the common join case).
- **Inputs:** two generators.
  - Master → Port 0: 30 records, `id:integer` 1..30, plus a master attribute.
  - Slave → Port 1: ~20 records whose keys are a **subset** of 1..30 plus a few
    non-matching keys, plus a slave attribute, to exercise matched / unmatched paths.
- **Inject into:** `attr:transform`. Entry point: `function integer transform()`.
  Fix `joinKey` in the skeleton (e.g. `$0.id=$1.id`) so only the CTL varies.
- **Output metadata:** merged record combining master + slave fields.
- **Ports to inspect:** `EdgeOut` = Port 0 (out) → TRASH. Oracle: matched-record count
  and merged field values. **Deliberately include the "0 matched records" trap** by
  keeping key types identical in the reference skeleton (so the correct case matches),
  letting candidates that mishandle keys collapse to 0.
- **Failure modes this targets:** sourcing a field from `$in.0` vs `$in.1` incorrectly,
  key-type-mismatch blindness, null handling on the unmatched outer side.
- **Reference (placeholder) CTL:** map master + slave fields straight through,
  `return ALL;`.

## 17.6 PARTITION skeleton — `PARTITION_skeleton.grf`

- **Component under test id:** `PARTITION0` (type `PARTITION`).
- **Inject into:** `attr:partitionSource`. Entry point:
  `function integer getOutputPort()`.
- **Generator output:** 90 records with a field designed to route cleanly into **3
  buckets** (e.g. `recordIndex % 3`).
- **Ports to inspect:** `EdgeOut0`, `EdgeOut1`, `EdgeOut2` = Ports 0/1/2 → three TRASH
  terminals. Oracle: sum across the three ports = 90, and each bucket's membership
  matches the routing rule over the known input.
- **Failure modes this targets:** returning an out-of-range port index, wrong
  modulus/branch logic, records silently dropped.
- **Reference (placeholder) CTL:** `return $in.0.<field> % 3;` (or equivalent matching
  the routing field).

## 17.7 NORMALIZER skeleton — `NORMALIZER_skeleton.grf`

- **Component under test id:** `NORMALIZER0` (type `NORMALIZER`; 1 record → N records).
- **Inject into:** `attr:normalize`. Entry points: `function integer count()` and
  `function integer transform(integer idx)`.
- **Generator output:** 20 records, each carrying a field to explode — e.g. a
  delimited string `tags:string` with a deterministic, known number of items per
  record (vary 1..4 so totals are non-trivial).
- **Output metadata:** the exploded shape — one row per item (e.g. `id:integer`,
  `tag:string`).
- **Ports to inspect:** `EdgeOut` = Port 0 (out) → TRASH. Oracle: total output rows =
  sum of per-record `count()`, and exploded values are correct.
- **Failure modes this targets:** `count()` / `transform(idx)` disagreement, `idx`
  off-by-one, wrong control-code return.
- **Reference (placeholder) CTL:** `count()` returns the item count;
  `transform(idx)` emits the idx-th item.

## 17.8 DENORMALIZER skeleton — `DENORMALIZER_skeleton.grf`

- **Component under test id:** `DENORMALIZER0` (type `DENORMALIZER`; N records → 1 per
  group; requires sorted input).
- **Inject into:** `attr:denormalize`. Entry points: `function integer append()`,
  `function integer transform()`, `function void clean()`.
- **Generator output:** 60 records emitted **already sorted by group key** (so no SORT
  component is needed; document the false-positive `job_plan` sort warning in
  `risks[]`). Use a known group layout (e.g. 12 groups of 5).
- **Output metadata:** one aggregated row per group (e.g. group key + a concatenated or
  summed field).
- **Ports to inspect:** `EdgeOut` = Port 0 (out) → TRASH. Oracle: one output row per
  group, aggregated fields correct.
- **Failure modes this targets:** group state not reset in `clean()`, wrong group
  boundary handling, emitting from `append()` instead of `transform()`.
- **Reference (placeholder) CTL:** accumulate in `append()`, emit the aggregate in
  `transform()`, reset state in `clean()`.

---

## 17.9 Build checklist (per skeleton)

- [ ] Self-contained: no reader/writer/connection/external file
- [ ] Deterministic generator (no `random*`)
- [ ] Component-under-test id matches the spec exactly
- [ ] Output edge id(s) named per spec
- [ ] TRASH terminal(s) with `debugPrint="true"` on every output port
- [ ] Metadata spans string/integer/decimal/date as required
- [ ] Reference (placeholder) CTL present and correct
- [ ] `job_validate` → overall PASS
- [ ] `job_run` → FINISHED_OK, `job_get_tracking` counts as expected
- [ ] Committed to `graph/skeletons/`, never to `graph/runtime/`
- [ ] Manifest row added to project knowledge
