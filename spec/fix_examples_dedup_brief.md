# Fix-to-spec explained set: replace templated near-duplicates

**`sft_training_data/CTL_LoRA_fix_to_spec_explained.json` (120 records) contains only 56 distinct
records.** Many records reuse the same broken code with different names: a new domain, new
field names, a new title, while the logic, the defects, the traps and often the explanation text
are the same. In training, 15 renamed copies teach one example 15 times. That overweights it,
invites memorisation, and adds nothing the first copy didn't. Everything else about the set is
good: compiler-verified fixes, correct explanations, traps left alone. Keep that quality.

## The near-duplicate groups

Groups are measured as broken-code similarity `difflib.SequenceMatcher(None, a, b,
autojunk=False).ratio() > 0.85` (check below):

| component | group size | ids |
|---|---:|---|
| NORMALIZER | 15 | fixexpl_046 – fixexpl_060 (all) |
| DENORMALIZER | 15 | fixexpl_061 – fixexpl_075 (all) |
| ROLLUP | 15 | fixexpl_091 – fixexpl_105 (all) |
| DATA_GENERATOR | 10 | 076, 078, 079, 081, 082, 084, 085, 087, 088, 090 |
| DATA_GENERATOR | 5 | 077, 080, 083, 086, 089 |
| JOIN | 4 | 108, 114, 119, 120 |
| JOIN | 3 | 106, 112, 118 |
| PARTITION | 2 | 032, 042 |
| PARTITION | 2 | 036, 044 |
| JOIN | 2 | 109, 115 |
| JOIN | 2 | 111, 117 |

Reformat (001–015), Filter (016–030) and the rest of Partition and Join are fine.

## What to do

1. **Keep one record per group** (the best one) and **rewrite the others as genuinely different
   records**, so each component still has about 15 distinct records.
2. **"Different" means different code and logic, not new names.** A rewritten record must
   differ in at least two of:
   - **the specification:** what the transform computes, its rules and their order, its outputs;
   - **the code structure:** other lifecycle functions in use, other control flow (loops, early
     returns, routing), other data structures (list, map, accumulator fields, lookups);
   - **the defect set:** other planted defects from the brief's themes, or the same theme in a
     different construct (membership via `containsValue` against `in()` against `x.in(list)`;
     regex `?=` against `~=` against `matches()`; null via arithmetic against an ordered
     comparison against date functions);
   - **the trap set:** other correct-but-suspicious constructs left unchanged.
3. **Use each component's own variety.** For example:
   - **Normalizer:** `count()` from a list, a map, `split`, or a computed number; `transform(idx)`
     indexing; `countOnError` with logging; output counts of 0.
   - **Denormalizer:** first-record against last-record values (ruling 2); collecting into a
     list against a map against counters; `clean()` reset; `appendOnError` with logging; group
     key read in `transform()`.
   - **Rollup:** summary-only against per-record (`updateGroup` returning `true` /
     `updateTransform`); accumulator initialisation (unassigned fields are null each group);
     several output ports; `finishGroup` gating.
   - **DataGenerator:** sequences against counters; random against deterministic values;
     `generate()` returning `OK` / `ALL` (ruling 1: never `STOP`); several output ports.
   - **Join:** inner against left outer; unmatched slave fields read as null; the slave key
     against master-only fields; `transform` against `transformOnError`.
4. **Don't reuse explanation text.** Each record's problem list must be written for that
   record's own code and values. No identical sentences across records, apart from short
   formulaic phrases.
5. **Keep the rules of the original brief** (`spec/fix_examples_brief.md` in llama_train):
   - 2–4 real defects and at least one silent trap per record;
   - exact mechanisms and concrete wrong values;
   - owner rulings 1–6;
   - no benchmark scenarios;
   - compiler-verified corrected code;
   - compile errors confirmed by the compiler;
   - and the compiler findings you already recorded: `list.length()`, `str.isEmpty()` and
     `x.in(list)` are valid.

## Check before committing

There must be no pair of broken-code blocks above 0.85 similarity, and no repeated
problem-list text:

```python
import json, re, difflib
d = json.load(open("sft_training_data/CTL_LoRA_fix_to_spec_explained.json"))
def code(r):
    u = next(m["content"] for m in r["messages"] if m["role"] == "user")
    b = re.findall(r"```ctl\n(.*?)```", u, re.S)
    return b[-1] if b else ""
def plist(r):
    a = next(m["content"] for m in r["messages"] if m["role"] == "assistant")
    return a[:a.find("```")]
C = [code(r) for r in d]; P = [plist(r) for r in d]
bad = [(d[i]["id"], d[j]["id"], round(x, 3)) for i in range(len(d)) for j in range(i + 1, len(d))
       if (x := difflib.SequenceMatcher(None, C[i], C[j], autojunk=False).ratio()) > 0.85]
same = [(d[i]["id"], d[j]["id"]) for i in range(len(d)) for j in range(i + 1, len(d)) if P[i] == P[j]]
print("code pairs > 0.85:", len(bad), bad[:10]); print("identical problem lists:", len(same))
```

Keep the record ids `fixexpl_001` to `fixexpl_120`, so rewritten records take over their slots.
Update the validation log in `sft_training_data/logs/` for the rewritten records, covering the
compile evidence and the coverage counts. Commit and push.
