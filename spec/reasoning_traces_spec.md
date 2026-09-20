# Spec — author a second set of CTL2 reasoning traces

## Why

Phase 3 trains on 452 traces with a **median of 82 tokens**. A dose curve at fixed batch
size (`spec/ctl2_training_findings.md` §2.3) shows that applying them harder makes the model
monotonically worse, and that validate score tracks thinking length:

| post-SFT | suite | validate | model's thinking at inference |
|---|---|---|---|
| none | 0.8658 | 0.7179 | 314 tok |
| 0.66 ep | 0.8799 | **0.7500** | — |
| 1.3 ep | 0.8585 | 0.6667 | — |
| 2.6 ep | 0.8374 | 0.6581 | 110 tok |

The working hypothesis is that this is a property of the **traces**, not the dose: 82-token
traces summarise a finished answer instead of demonstrating verification, so training on
them compresses reasoning, and compressed reasoning loses validation accuracy.

This set tests that hypothesis. Author traces that are longer and that *verify*, and the
relationship should invert rather than merely shift.

## Deliverable

A **separate** dataset, not an edit to the existing 452 — so the two can be trained alone or
combined and the hypothesis can actually be A/B'd.

| | |
|---|---|
| Write | `CTL_LoRA_reasoning_v2.json` (same shape as the existing SFT files: `id`, `messages`) |
| Records | **300**, drawn from the existing corpus (see *Coverage*) |
| Then | `python convert_think.py CTL_LoRA_reasoning_v2.json -o <combined>_v2.json` |

**Emit `reasoning_content` on the assistant message; do not write `<think>` tags.**
`convert_think.py` owns the exact delimiter spelling LlamaFactory requires, and getting it
wrong silently breaks both the thinking and the non-thinking phases.

```json
{"role": "assistant", "reasoning_content": "...", "content": "<unchanged, byte for byte>"}
```

The `content` of every assistant turn is preserved exactly. These are existing, reviewed
answers; only reasoning is being added.

## Length

**Target 180–320 tokens, median ~240. Hard floor 120, hard ceiling 450.**

That is roughly **3× the existing traces** and is calibrated on what the models actually
produce:

| model | thinking at inference |
|---|---|
| no phase 3 | 314 tok (median) — untrained, rambles, sometimes never terminates |
| **best model (0.8961)** | **243 tok** |
| over-trained on the 82-tok traces (0.8374) | 110 tok |

240 tokens is where the best-performing model already sits. The goal is to make that
behaviour deliberate and consistent, not to push length for its own sake.

Do **not** scale length with answer size. A 500-token component transform gets about the
same reasoning as a one-line format question, because what the trace records is the
*decisions*, and the decision count barely moves with how much code they imply. If a task
genuinely has two decisions, write two — do not pad to reach the band.

## What the reasoning must do

Five behaviours. Each exists because the model currently fails at it; the failing test is
named so you can see the shape of the error.

1. **Ground every claim in the prompt before relying on it.** Quote the metadata.
   *(T22: the model asserted "accumulator records ARE reset between groups, and numeric
   fields default to zero", reasoned from that invented rule to "technically safe", and
   missed the real bug.)*

2. **Justify each built-in against the catalog.** Name why that function and not another.
   Never use a name absent from `resources/ctl-function-library.json`.
   *(T29 invented `randomElement`, T18 invented `lookup(PriceLookup, key)`, T27 invented
   `remainingL.isNegative()`.)*

3. **Decide severity explicitly** on validate-type records — does this stop compilation?
   *(T24: the corpus teaches WARNING for syntactically valid date letters; the model emits
   ERROR anyway. 0.25–0.75 in every model measured.)*

4. **Reject at least one candidate finding.** Raise the memorised rule, re-read the code,
   drop it when it does not apply.
   *(T22: the model flagged `transform()` returning ALL without noticing the
   `counter > 0 → SKIP` guard on line 1. 115 corpus examples show that guarded form being
   accepted; zero flag it.)*

5. **Read the spec in order** where ordering matters — round before comparing to a
   threshold, group key before accumulator init.
   *(T29 evaluated a 6.00 threshold on unrounded wear.)*

Not every trace needs all five. Aim for **two or three per trace**, chosen by what the task
actually requires, and ensure behaviour 4 appears in at least a third of the set — it is the
one with no coverage at all today.

## Example — the target

This is a real trace from the best model, on a task it got right (T37, Rollup with two
output ports). Note what it does: enumerates decisions, checks the accumulator metadata
before assuming a field exists, self-corrects, and assigns each lifecycle function a role.

> The user wants a Rollup CTL2 with two output ports. Port 1 emits per-piece progress
> (running seq and cumulative glaze), port 0 emits the firing summary after all pieces are
> consumed.
>
> Accumulator FiringAcc has piece_count, glaze_total, rework_total. I need to also store the
> group key firing_id somewhere — but the accumulator metadata only has those 3 fields. I'll
> capture firing_id in a module-level variable when initGroup is called, since the group key
> is available via `$in.0.firing_id`.
>
> updateGroup returns true to start the per-record output loop on port 1. updateTransform is
> called once per input row and returns a route constant, so it emits one progress record
> and returns 1; counter 1 returns SKIP to end that row's loop. finishGroup returns true so
> transform runs for the group, and transform emits the summary on port 0 with the same
> counter guard.

≈200 tokens. Grounded, decisive, no narration of intent.

## Example — what to avoid

Also real, from a failing T22 run:

> initGroup only initializes acc.total to 0D but not acc.count. The accumulator fields are
> declared as integer and decimal, so they default to zero on first use per group — but only
> if the accumulator record is fresh for each group. In CloverDX, accumulator records ARE
> reset between groups, and numeric fields default to zero. So acc.count starts at 0 even
> without explicit initialization.

Three faults: it states a CTL2 rule it cannot support, it treats its own restatement as
confirmation, and it reasons from the invented premise to the wrong conclusion. Length alone
would not have saved it — **grounding** is the point, and length is what grounding costs.

Also avoid: restating the prompt wholesale; narrating intent ("I will now write the
transform"); hedging without resolving ("maybe X, or possibly Y"); `<think>` tags, markdown
headings or code fences inside `reasoning_content`; any mention of CloverDX documentation,
this spec, or the training process.

Style: plain declarative sentences, CTL2 identifiers spelled as in the code, no bullet lists
in the final text, no first-person narration of intent.

## Coverage

Draw the 300 source records from the existing corpus, weighted toward where the model is
weakest. Candidate pools, measured in the phase-1 corpus:

| topic | failing test | best score seen | pool | take |
|---|---|---|---|---|
| Rollup lifecycle / output loops | T22, T37, T38 | 0.69 | 375 | **70** |
| `lookup(X).get(k)` | T18 | 0.83 | 192 | **45** |
| date-pattern severity | T24 | 0.75 | 138 | **40** |
| JOIN slave sentinel | T12 | 1.00 | 110 | **30** |
| DataGenerator random idioms | T29 | 1.00 | 118 | **30** |
| type conversions `str2*` | T26 | 1.00 | 682 | **25** |
| validate schema generally | — | — | 1157 | **60** |

Roughly 55% validate-type and 45% generate-type, matching the suite. Do not draw records
that already carry `reasoning_content`, and do not draw any record whose user message
appears in `resources/ctl2_test_suite_v4.json` — eight suite tests already have near-verbatim
twins in the corpus (`results/training_data_gaps_20260918.md` §2.5) and adding reasoning to
them would deepen the leak.

## Verification

```python
import json, statistics as st
from transformers import AutoTokenizer
tok = AutoTokenizer.from_pretrained("Qwen/Qwen3.8-27B", trust_remote_code=True)
D = json.load(open("CTL_LoRA_reasoning_v2.json"))
th = []
for r in D:
    for m in r["messages"]:
        if m["role"] != "assistant":
            continue
        rc = m.get("reasoning_content", "")
        assert rc.strip(),        "empty reasoning_content"
        assert "<think>" not in rc, "raw tags in reasoning_content"
        assert "```" not in rc,     "code fence in reasoning_content"
        th.append(len(tok.encode(rc)))
s = sorted(th)
print("records      :", len(D), "(want 300)")
print("tokens       : median", st.median(th), "p10", s[len(s)//10], "p90", s[9*len(s)//10])
print("             : (want median 180-320, p10 >= 120, p90 <= 450)")
print("under 120    :", sum(1 for x in th if x < 120), "(want 0)")
```

Also assert every `content` still matches its source record byte for byte, and report any
that does not rather than silently fixing it.

## How it will be evaluated

Trained as phase 3 in place of the existing 452, then again combined with them, both at
`--runs 3` against the six preserved exports. The hypothesis is confirmed if the new set
tolerates more epochs without the validate decline in §2.3 — not merely if the suite score
rises, which at these sample sizes could be noise (suite sd is 0.02–0.05).
