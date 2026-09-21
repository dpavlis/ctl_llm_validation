# Fix the reasoning length in `CTL_LoRA_reasoning_v2.json`

## What is wrong

The 300 records are structurally correct — delimiters right, no code fences, no nested
tags, 164 validate / 136 generate. **Only the reasoning length is wrong, and by ~3.3x.**

| | required | delivered |
|---|---|---|
| median | 180–320 tok | **72** |
| p10 | ≥ 120 | 47 |
| p90 | ≤ 450 | 89 |
| max | — | **116** |
| records ≥ 120 tok | 300 / 300 | **0 / 300** |

Both task types are equally short: validate median 70, generate median 73.

The target median is **240 tokens**, so most records need roughly **3x their current
length**. This is not a stylistic preference — see below.

## Why length, specifically

The existing 452-trace training set has a median of 82 tokens, and a dose curve shows the
model gets monotonically terser and loses validation accuracy as that set is applied harder.
This new set exists to test whether *longer, grounded* traces invert that. At median 72 it
is a second copy of the suspected problem and tests nothing.

## The actual defect: conclusions without grounding

Length is the symptom. The cause is that each trace states its verdict rather than reaching
it. A real record (`reasonin96_0`), currently **57 tokens**:

> Five callbacks use the configured accumulator. updateGroup suppresses update output;
> finishGroup starts final output. Counter zero returns ALL and counter one SKIP, yielding
> one row. Nullable inputs have typed zero fallbacks and all required outputs are assigned.
> Clean, PASS.

Every clause is an assertion. Nothing is checked against the prompt, no alternative is
weighed, no candidate defect is raised and dismissed. Rewritten with grounding — same
verdict, ~210 tokens:

> The component must emit one summary row per (region, category) group. Input metadata
> declares quantity and amount both nullable="true"; output declares order_count and the
> totals nullable="false", so every accumulator read has to survive a null input.
>
> Checking the five callbacks against the Rollup contract: initGroup, updateGroup,
> finishGroup, updateTransform and transform are all defined. initGroup sets the counters to
> typed zeros — 0 for the integer, 0D for the decimals — so no field is read uninitialised.
> updateGroup wraps each input read in nvl(), which covers the nullable quantity and amount.
>
> updateGroup returns false, which suppresses the per-record output loop. That is worth
> flagging only if per-record output were requested; the prompt asks for one summary row per
> group, so returning false is correct here, not a defect.
>
> transform returns ALL at counter zero and SKIP at counter one. The SKIP is what ends the
> output loop, so exactly one row is emitted per group — the guard is present, so the
> "unguarded output loop" defect does not apply. All four output fields are assigned.
>
> No compile-blocking or semantic defect. PASS.

The extra ~150 tokens are: the metadata quoted before being relied on, the contract
enumerated rather than asserted, and **two candidate defects raised and explicitly rejected**
(`updateGroup` returning false; the missing counter guard). That last behaviour is the one
with no coverage in the existing set and the one the model most needs.

## What to do

Rewrite the `<think>` body of each of the 300 records. Keep everything else byte-identical —
the `content` after `\n</think>\n\n`, the `id`, the message structure, the delimiters.

Per record, make **two or three** of these visibly present in the text. A trace that only
announces conclusions is rejected regardless of its token count:

1. **Quote the prompt before relying on it** — field name, nullability, type, port.
2. **Justify a built-in against the catalog** — why that function and not a neighbour.
   Never name a function absent from `resources/ctl-function-library.json`.
3. **Decide severity explicitly** (validate records) — does this stop compilation?
4. **Raise a candidate defect and reject it** — name the rule, check the code, drop it.
   Required in **at least a third** of the 300.
5. **Read spec ordering** where it matters — round before comparing, group key before init.

Do not pad. If a record genuinely has two decisions, write two and let it land near 180
rather than inflating to 300. Prose, no bullet lists, no headings, no code fences.

## Verify before returning

```python
import json, statistics as st
from transformers import AutoTokenizer
tok = AutoTokenizer.from_pretrained("Qwen/Qwen3.8-27B", trust_remote_code=True)
D = json.load(open("CTL_LoRA_reasoning_v2.json"))
th = []
for r in D:
    c = [m["content"] for m in r["messages"] if m["role"] == "assistant"][0]
    assert c.startswith("<think>\n") and "\n</think>\n\n" in c, "delimiters"
    body, ans = c.split("<think>\n", 1)[1].split("\n</think>\n\n", 1)
    assert "```" not in body and "<think>" not in body, "fence or nested tag"
    th.append(len(tok.encode(body)))
s = sorted(th)
print("records :", len(D), "(want 300)")
print("tokens  : median", st.median(th), "p10", s[len(s)//10], "p90", s[9*len(s)//10])
print("          want median 180-320, p10 >= 120, p90 <= 450")
print("under120:", sum(1 for x in th if x < 120), "(want 0)")
print("over450 :", sum(1 for x in th if x > 450), "(want 0)")
```

**This block fails on the current file** (`under120 = 300`). Run it — it was the check that
would have caught this before delivery.

Also confirm every answer body after `\n</think>\n\n` is unchanged from the current file.
