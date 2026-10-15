# SCD-2 training set, round 2: rebalance around the full CloverDX SCD-2 flow, remove hints, add validation

**Revise `CTL_LoRA_scd2_sft.json` (60) and `CTL_LoRA_DPO_scd2.jsonl` (40)** in
`ctl_lora_training/sft_training_data/`. Keep the counts and the format. `spec/scd2_training_set_brief.md` still
applies; this file says what to change.

DPO pairs are referred to by their **line number in the file, counting from 1**.

## Why

The review found **nothing false**:
- 18 of 20 sampled SFT examples and 37 of 40 DPO pairs are correct; the rest are minor or doubtful;
- every chosen answer compiles (apart from "unable to resolve sequence", which is expected outside a graph);
- the DPO pairs are minimal and the rejected answers are wrong in the intended way.

Keep all of that. Five things need to change.

### 1. The set covers only one of the three steps of an SCD-2 load

In CloverDX, SCD-2 against a snapshot is built around DataIntersection:

```
new snapshot (A) ─┐                     port 0: A only  → new keys      → OPEN rows (new surrogate key)
                  ├─ DataIntersection ─ port 1: matched → CTL compares  → changed → CLOSE old + OPEN new
current dim (B) ──┘                     port 2: B only  → deleted keys  → CLOSE (retire) rows
```

1. **Change detection (DataIntersection).** The matched-pair CTL decides changed vs unchanged (null-safe, which
   attributes count, `SKIP` for unchanged) and writes `$out.0`.
2. **One changed pair → two dimension writes.** The matched output carries one record per pair, but a changed key needs
   a CLOSE row and an OPEN row:
   - the CLOSE row is the old version's surrogate key and `valid_from`, with `valid_to` set and `is_current=false`;
   - the OPEN row has the new values, a new key from `sequence(…, long).next()` and `valid_from`.

   This is done downstream, either by a **Normalizer** (`count()` 2 for changed, 1 for new; CLOSE at idx 0, OPEN at
   idx 1) or by a **two-output Reformat** (CLOSE to the UPDATE writer, OPEN to the INSERT writer, routed by return
   value). `valid_to` = "the day before" is computed in UTC here. **Suite T60 tests this step** and is the weakest
   test for every model.
3. **Versions from a change log.** When the source delivers change events (audit trail, CDC log, historical backfill:
   several rows per key, sorted by key and time), there is no snapshot pair to compare. A **Reformat** (or a Denormalizer
   or Rollup per key) carries the current version across consecutive records:
   - detect the first event of a key by a key change or a flag, never by testing a declared variable for null;
   - close the carried version when a tracked attribute changes;
   - reset the carried state at a key change.

   **Suite T61 tests this step.**

Plus the two simple ends:
- the retire path: port 2 (B only) → a Reformat building CLOSE rows;
- the new-key path: port 0 (A only) → OPEN rows with a new key.

**Now:** 36 SFT and 24 DPO are step 1, about 11 cover step 2 and about 4 cover step 3. The set must teach the whole
flow, with DataIntersection as the anchor.

**Target mix:**

| step | SFT | DPO |
|---|---|---|
| 1. change detection in DataIntersection | ~20 | ~12 |
| 2. changed pair → CLOSE + OPEN (Normalizer or two-output Reformat), sequence keys, UTC `valid_to` | ~20 | ~15 |
| 3. versions from a change log (Reformat over consecutive records) | ~12 | ~8 |
| retire (port 2 → CLOSE) and new-key (port 0 → OPEN) paths | ~8 | ~5 |

- **Task mix across the SFT:** about 10 explanation, 25 generate, 13 validate and 12 fix tasks. The set now has about
  27 explanations and 9 generate tasks.
- **Where it fits, the prompt says where the component sits** ("the matched output of a DataIntersection feeds this
  Normalizer"; "the CDC log arrives sorted by customer and change time").

**Which examples to rewrite** (repurpose rather than add, so the counts stay at 60 and 40). You may swap an id for a
similar one if the target mix is met.
- **SFT:** rewrite these 16 DataIntersection explanations into step 2, step 3 and the retire/new-key paths, mostly as
  generate and fix tasks:
  - scd2_sft_004, 005, 009, 010, 012, 013, 016, 018;
  - scd2_sft_019, 025, 038, 039, 040, 041, 045, 058.

  Keep the other DataIntersection examples, for example 001, 002, 003, 006–008, 011, 014, 015, 017, 020, 021, 028,
  037, 047, 050, 052, 054, 055 and 059.
- **DPO:** rewrite these 12 DataIntersection pairs (lines 2, 3, 4, 6, 9, 10, 12, 13, 14, 18, 19, 29) into step 2,
  step 3 and the end paths. Each targets one typical mistake:
  - a sequence value taken for CLOSE rows;
  - a CLOSE row carrying the new values;
  - OPEN emitted before CLOSE;
  - `transform(idx)` in a Reformat;
  - `ALL` sending CLOSE to both writers;
  - `dateAdd(…, day)` for `valid_to`;
  - a null test on a declared variable for the first event of a key;
  - state not reset at a key change;
  - a deleted key not closed;
  - an unchanged key re-versioned.

### 2. Mechanism hints in user turns

The user turn states the business requirement and the graph context, never how to write the CTL. These prompts say
how:

| item | hint to remove |
|---|---|
| scd2_sft_017, 021, 022, 027, 047, 055, 059 | "local output" / "one local output record" (the `$out.0` answer) |
| scd2_sft_040 | names `transform(integer idx)` |
| scd2_sft_049 | "millisecond" (the DST answer) |
| DPO line 1 | "$out.0", "local output" |
| DPO lines 15, 16, 17, 28 | "local output" |
| DPO line 5 | "rather than replacing" (the `valid_from` answer) |
| DPO lines 7, 37 | "long range", "long-key … without truncation" (the `long` sequence answer) |
| DPO lines 8, 21 | "must not advance the sequence" |
| DPO line 11 | "the transform exposes one matched record schema" |
| DPO line 32 | names `return SKIP` |

Check every other prompt against the same rule. A port number in the graph description is fine ("physical output 1
feeds the change writer"); the CTL record or return value is not.

### 3. Glued words

Put the spaces back. The list:
- `input0` / `input1` should read "input 0" / "input 1";
- `output0`, `outputs0 and2`, `physical1`, `port0` / `port1`;
- `step1`, `starting3000000000`, `at09:00` / `at12:00`, `by1`, `from1`.

Affected:
- **SFT:** 001–004, 006–008, 010–015, 017, 022, 026–028, 044, 047, 048, 054, 055, 059;
- **DPO lines:** 2–5, 7–11, 14–19, 21, 26, 28, 29, 31–34, 36–38.

Use a regex pass, then re-read.

### 4. Doubtful items

- **DPO line 38:** the rejected answer uses `isnull($in.1)` to detect a missing slave record in a left-outer
  ExtMergeJoin. If that works at runtime, the pair teaches the model to reject correct code. **Probe it on the server.**
  If it works, replace the rejected answer with a clearly wrong slave test.
- **DPO line 13:** "disabling duplicate-key allowance uses the first encountered record" has no probe and is not in
  `ctl2-basics.md`. Probe it, or drop the claim. This pair is also in the rewrite list.
- **SFT 022:** say whether a null label counts as blank ("null and blank labels are the same").
- **SFT 052:** add that the natural fix is to leave output 2 unconnected or remove the retirement writer; the
  `SKIP`-only Reformat is the in-CTL alternative.

### 5. Validation evidence is missing

There is no `logs/CTL_LoRA_scd2_validation.json` and no `logs/scd2_runtime/`, so none of the round-1 brief's runtime
checks can be confirmed. Deliver both, as for the DataIntersection set:
- compiler results for every CTL block;
- a real graph run in `MiscExamples/scd2/` (never `DPOForge`) for every generate and fix answer, with 8–15 input
  records, expected outputs derived from the spec by hand, and runIds;
- a DST-crossing case for every example that computes `valid_to`;
- probe runs for the two doubtful DPO claims;
- the overlap checks: 5-gram Jaccard < 0.30 against suite v5 T59–T61, `llama_train/data/opcd/generate_gaps.jsonl` and
  the hard cases, and within the set with field names masked.

## Form

- **Answers stay short and answer-only.** Generate answers are code plus 1–3 sentences. 13 SFT answers are code only
  and need a sentence: scd2_sft_021, 023, 026, 028, 029, 031, 033, 035, 039, 046, 051, 054, 056.
- **Each DPO pair still differs in one point only.**

---

## Internal tracking (not part of the brief)

- **c11 = c10's recipe plus a DataIntersection group** (prompts from the 60 DataIntersection SFT user turns) **and an
  SCD-2 group** (prompts from this set's user turns, once revised). Hold out about 10 per group. Teacher: rb1006 +
  rulev3 + the component guide (DataIntersection / Normalizer / Reformat) + `ctl2-basics.md` §8.9 / §13.3. Teacher
  check first.
- **Gates:** as for c9/c10, plus T53/T54 and T60/T61 at n10 in both modes.
