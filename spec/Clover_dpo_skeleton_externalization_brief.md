# Mini-Spec — Externalize Metadata & CTL in the DPOForge Skeletons

> Audience: the assistant that built the 8 skeletons in `DPOForge/graph/skeletons/`.
> Goal: refactor each skeleton so that **every per-example-variable piece loads from
> an external file**, and the graph XML itself becomes **immutable** — the DPO harness
> and the judge LLM should only ever write small `.fmt` / `.ctl` files and pass run
> parameters, never edit a `.grf`.
>
> Do **not** change the structure established earlier: component-under-test ids,
> port topology, TRASH terminals with `debugPrint="true"`, generator→component→TRASH
> shape, and record-count behaviour all stay exactly as they are and must still
> validate PASS / run FINISHED_OK after this refactor.

---

## 1. The principle: parameterized work tree + external files

Introduce one graph parameter per skeleton, `WORK_DIR`, that points at a **working
tree** holding the swappable pieces, organized by asset kind and component type:

```
${WORK_DIR}/meta/<COMPONENT_TYPE>/<file>.fmt     external metadata
${WORK_DIR}/ctl/<COMPONENT_TYPE>/<file>.ctl      external CTL (generator + under-test)
```

`<COMPONENT_TYPE>` is the canonical type string of the skeleton's component under
test (`REFORMAT`, `ROLLUP`, `EXT_FILTER`, `DATA_GENERATOR`, `EXT_HASH_JOIN`,
`PARTITION`, `NORMALIZER`, `DENORMALIZER`). Because each skeleton tests exactly one
component, it **bakes its own type into every path** — e.g. the REFORMAT skeleton
only ever references `…/meta/REFORMAT/…` and `…/ctl/REFORMAT/…`. This keeps all eight
components' assets cleanly separated within one shared tree, so a run overwrites only
its component's subtree and never disturbs the others.

```xml
<GraphParameters>
  <GraphParameterFile fileURL="workspace.prm"/>
  <GraphParameter name="WORK_DIR" value="${DATATMP_DIR}/forge/ref"/>
  <GraphParameter name="RECORDS_NUMBER" value="50"/>
  <!-- component-specific key params, see §4 -->
</GraphParameters>
```

- The committed default `WORK_DIR` points at a **pristine reference tree** (`…/forge/ref`)
  that you populate with known-good `.fmt` + `.ctl` files for all eight components, so
  every skeleton validates and runs standalone with no params supplied.
- At execution time the harness passes a **different `WORK_DIR`** (the live working
  tree `…/forge/work`, or a per-worker tree) via `job_run` params. CloverDX resolves
  `${WORK_DIR}` inside every `fileURL` / `transformURL` / etc. The pristine `ref` tree
  is never overwritten, so standalone validation always holds.

`meta` and `ctl` may be lifted to their own params (`META_DIR`, `CTL_DIR`) if you want
the second-level names configurable; default to the literal `meta` / `ctl` subdirs.
This relies only on standard CloverDX param substitution in attributes (same mechanism
`${DATAIN_DIR}`, `${INPUT_FILE}` already use).

---

## 2. Externalize the metadata → `.fmt` files

Replace every inline `<Metadata><Record>…</Record></Metadata>` block with an external
reference under the component's meta subdir:

```xml
<!-- before -->
<Metadata id="InMeta"><Record name="InMeta" type="delimited"> … </Record></Metadata>

<!-- after (REFORMAT skeleton) -->
<Metadata id="InMeta"  fileURL="${WORK_DIR}/meta/REFORMAT/in_meta.fmt"/>
<Metadata id="OutMeta" fileURL="${WORK_DIR}/meta/REFORMAT/out_meta.fmt"/>
```

- The `.fmt` file contains exactly the `<Record …> … </Record>` XML that was inline.
- Keep the **metadata id** stable (`InMeta`, `OutMeta`, …) — edges still reference the
  id, only the definition moves to the file.
- Standard per-component metadata files:
  `in_meta.fmt`, `out_meta.fmt`; plus `acc_meta.fmt` for ROLLUP (accumulator) and
  `slave_in_meta.fmt` for EXT_HASH_JOIN.

---

## 3. Externalize the CTL → `.ctl` files (per-component attribute)

Each component-under-test and each generator moves its CTL body to an external file
under the component's ctl subdir, via the **URL-form attribute**. These are the
verified attribute names — use exactly these:

| Skeleton (component) | Inline attr today | External attr to use | External file |
|---|---|---|---|
| Generator (all skeletons) | `attr name="generate"` | `generateURL` | `${WORK_DIR}/ctl/<TYPE>/generate.ctl` |
| REFORMAT (`TRANSFORMER`) | `transform` | `transformURL` | `${WORK_DIR}/ctl/REFORMAT/transform.ctl` |
| ROLLUP (`ROLLUP0`) | `transform` | `transformURL` | `${WORK_DIR}/ctl/ROLLUP/transform.ctl` |
| PARTITION (`PARTITION0`) | `transform` | `transformURL` | `${WORK_DIR}/ctl/PARTITION/transform.ctl` |
| EXT_HASH_JOIN (`EXT_HASH_JOIN0`) | `transform` | `transformURL` | `${WORK_DIR}/ctl/EXT_HASH_JOIN/transform.ctl` |
| NORMALIZER (`NORMALIZER0`) | `normalize` | `normalizeURL` | `${WORK_DIR}/ctl/NORMALIZER/transform.ctl` |
| DENORMALIZER (`DENORMALIZER0`) | `denormalize` | `denormalizeURL` | `${WORK_DIR}/ctl/DENORMALIZER/transform.ctl` |

The URL form is written as an **attribute on the `<Node>`**, replacing the
`<attr name="…">` child element, e.g.:

```xml
<Node id="TRANSFORMER" type="REFORMAT"
      transformURL="${WORK_DIR}/ctl/REFORMAT/transform.ctl" .../>
<Node id="GENERATOR" type="DATA_GENERATOR" recordsNumber="${RECORDS_NUMBER}"
      generateURL="${WORK_DIR}/ctl/REFORMAT/generate.ctl" .../>
```

Conventions the harness relies on:
- The **component under test always uses the filename `transform.ctl`** — even
  NORMALIZER/DENORMALIZER (whose attribute differs) and even the DATAGEN skeleton
  (where `transform.ctl` is wired to `generateURL` because the generator *is* the
  thing under test). One predictable filename regardless of component.
- The **input generator always uses `generate.ctl`**. For EXT_HASH_JOIN's two
  generators use `generate_driver.ctl` and `generate_slave.ctl`.
- Note the generator for, say, the REFORMAT skeleton lives under `ctl/REFORMAT/`
  (it is part of the REFORMAT test bundle) — `<TYPE>` always means *this skeleton's*
  component, not the type of the node the file feeds.

### 3.1 EXCEPTION — EXT_FILTER has no URL form

`EXT_FILTER` exposes only `filterExpression` (inline). There is **no `filterExpressionURL`**.
So this one skeleton cannot externalize its CTL the same way. Handle it as follows,
in order of preference:

1. **Parameter substitution (try first):** set
   `filterExpression="${FILTER_EXPR}"` and pass the boolean as a run parameter. Verify
   during build that a multi-line `//#CTL2` value passed via `job_run` params resolves
   correctly. If it does, EXT_FILTER joins the uniform no-edit model (and needs no
   `ctl/EXT_FILTER/transform.ctl`).
2. **Fallback (if param substitution mangles the CTL):** the harness performs a single
   mechanical attribute write into a per-run *clone* of the graph (`graph_edit_properties`
   on `filterExpression`), reading the boolean from `ctl/EXT_FILTER/transform.ctl`.
   Flag this clearly so the utility-builder knows EXT_FILTER is the lone graph-editing
   case.

Record which option works in the manifest (§5).

---

## 4. Externalize / parameterize the grouping & join keys

Some attributes reference **field names**, which vary per example, but live in the
graph XML (not in CTL or metadata). Parameterize them so the graph stays immutable:

| Skeleton | Attribute | Make it | Run param |
|---|---|---|---|
| Generator (all) | `recordsNumber` | `recordsNumber="${RECORDS_NUMBER}"` | `RECORDS_NUMBER` |
| ROLLUP | `groupKey` | `groupKey="${GROUP_KEY}"` | `GROUP_KEY` (e.g. `region;category`) |
| ROLLUP | `groupAccumulator` | keep id; externalize accumulator metadata as `${WORK_DIR}/meta/ROLLUP/acc_meta.fmt` | — |
| ROLLUP | `sortedInput` | `sortedInput="${SORTED_INPUT}"` (default `true`) | `SORTED_INPUT` |
| DENORMALIZER | `key` | `key="${GROUP_KEY}"` | `GROUP_KEY` |
| EXT_HASH_JOIN | `joinKey` | `joinKey="${JOIN_KEY}"` | `JOIN_KEY` (e.g. `$id=$id`) |
| EXT_HASH_JOIN | `joinType` | `joinType="${JOIN_TYPE}"` (default `inner`) | `JOIN_TYPE` |

Give every parameter a sensible default in the committed skeleton (matching the
current reference instantiation) so it still validates/runs with no params supplied.

> Note on the current EXT_HASH_JOIN skeleton: it emits 30 records from a 30-row driver,
> i.e. it is wired `leftOuter`. Set the default `JOIN_TYPE=leftOuter` to preserve
> today's behaviour, or `inner` for matched-only — pick one and record it.

---

## 5. Output: tree layout, defaults, and a manifest

```
graph/skeletons/REFORMAT_skeleton.grf          (immutable, parameterized; default WORK_DIR=…/forge/ref)
graph/skeletons/…  (all 8, refactored)

data-tmp/forge/ref/                             PRISTINE reference tree — never overwritten
  meta/REFORMAT/in_meta.fmt, out_meta.fmt
  ctl/REFORMAT/generate.ctl, transform.ctl
  meta/ROLLUP/in_meta.fmt, out_meta.fmt, acc_meta.fmt
  ctl/ROLLUP/generate.ctl, transform.ctl
  meta/EXT_HASH_JOIN/in_meta.fmt, slave_in_meta.fmt, out_meta.fmt
  ctl/EXT_HASH_JOIN/generate_driver.ctl, generate_slave.ctl, transform.ctl
  …  (one meta/<TYPE> + ctl/<TYPE> per component)

data-tmp/forge/work/                            LIVE area the harness overwrites (see Section 18)
```

You only need to provision the `ref` tree; the harness creates `work` at runtime.
Write a **manifest** as a project-knowledge entry (`knowledge_project_store`,
project `dpo-forge`) with one row per skeleton listing: skeleton path; default
`WORK_DIR`; the external files it expects (relative paths under `meta/<TYPE>` and
`ctl/<TYPE>`, and which metadata id each `.fmt` backs); the run parameters it accepts
(names + defaults); and for EXT_FILTER, which CTL-binding option (§3.1) was adopted.
Also record, **per output edge, the diff comparison mode** the harness must use
(`ordered` for deterministic-order components like REFORMAT / PARTITION-per-port /
NORMALIZER; `keyed_multiset` + the key field for EXT_HASH_JOIN and unsorted ROLLUP whose
output order isn't guaranteed — see §18.5.1).
The harness reads this manifest to know exactly which files to write and which params
to pass per skeleton.

---

## 6. Acceptance criteria (per skeleton)

- [ ] No inline `<Metadata><Record>` blocks remain — all via `fileURL="${WORK_DIR}/meta/<TYPE>/…"`.
- [ ] Component-under-test CTL and generator CTL load via URL attributes from
      `${WORK_DIR}/ctl/<TYPE>/…` (or, for EXT_FILTER, via the §3.1 option chosen).
- [ ] Grouping/join keys and record counts are graph parameters with defaults.
- [ ] Pristine `ref` tree populated so the skeleton, **as committed and with no
      params**, still `job_validate` → PASS and `job_run` → FINISHED_OK with the same
      record counts as before this refactor.
- [ ] Running the skeleton with `WORK_DIR` pointed at a **copy of `ref`** (passed via
      `job_run` params) produces identical results — proving the indirection works.
- [ ] Structure unchanged: ids, ports, TRASH terminals, topology identical.
- [ ] Manifest entry written, including per-output-edge diff comparison mode (§18.5.1).
