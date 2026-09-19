# Spec — add `reasoning_content` to the CTL2 eval set

## Goal

Produce `CTL_LoRA_think_eval_data.json`: a held-out eval set carrying the same
`<think>` supervision as the phase-3 training data, so that `eval_loss` during
the thinking SFT round measures the distribution the model is actually being
trained on.

Today `CTL_LoRA_eval_data.json` has **0 of 155** assistant turns with reasoning.
With `enable_thinking: true`, LlamaFactory injects an *empty* `<think>\n\n</think>\n\n`
into every eval target, so `eval_loss` scores a format the model is being taught
not to produce, and `load_best_model_at_end` selects on it.

## Inputs / outputs

| | |
|---|---|
| Read | `~/LlamaFactory/data/CTL_LoRA_eval_data.json` (155 records) |
| Write | `~/llama_train/data/sft_input/CTL_LoRA_think_eval.json` |
| Then | `python convert_think.py data/sft_input/CTL_LoRA_think_eval.json -o ~/LlamaFactory/data/CTL_LoRA_think_eval_data.json` |
| Consumed by | `post_dpo_sft` stage in `configs/qwen38.yaml`, as `clover_ctl_think_eval_data` |

**Do not modify `CTL_LoRA_eval_data.json`.** Phases 1 and 2 still use it.

**Do not write `<think>` tags yourself.** Emit a `reasoning_content` string on the
assistant message and let `convert_think.py` wrap it — it owns the exact
delimiter spelling that LlamaFactory's `thought_words` requires, and getting that
wrong silently breaks both the thinking and the non-thinking phases.

```json
{"role": "assistant", "reasoning_content": "...", "content": "<unchanged>"}
```

The `content` of every assistant turn must be preserved **byte for byte**. This
is an eval set; changing the targets invalidates comparison with earlier runs.

## Which records

Select **60** of the 155, stratified so the mix matches the eval set as a whole.
Answer-length buckets, measured in Qwen3.8 tokens on the assistant `content`:

| bucket | in the 155 | take |
|---|---|---|
| tiny, <100 tok | 80 | 30 |
| small, 100–250 | 59 | 22 |
| medium, 250–500 | 14 | 6 |
| large, 500+ | 2 | 2 |

Within each bucket spread across task kinds (Reformat/Map, Rollup, Normalizer,
Denormalizer, Join, Partition, Filter, DataGenerator, lookups/sequences, date and
type conversion, prose-only answers). 143 of 155 answers contain a ```ctl block
and 12 do not — keep roughly that proportion, because the prose answers are the
ones where reasoning is most likely to go off the rails.

Verify no selected record's user message appears in `CTL_LoRA_think_data.json`
(the phase-3 training set) before writing.

## Length calibration

This is the part to get right, and the answer is counter-intuitive.

Measured over the 452 existing reasoning traces:

| answer size | n | median thinking | median think:answer ratio |
|---|---|---|---|
| <100 tok | 109 | **68 tok** | 0.94 |
| 100–250 tok | 160 | **76 tok** | 0.45 |
| 250+ tok | 183 | **93 tok** | 0.20 |

**Thinking length is near-constant at ~70–95 tokens regardless of answer size.**
Do not scale it with the answer. A full 500-token component transform gets about
as much reasoning as a one-line date-format question, because what the trace
records is the *decisions*, and the number of real decisions barely moves with
how much code they imply.

Rules:
- Target **60–110 tokens** of reasoning per assistant turn. Hard ceiling 160.
- Never exceed the answer's own token count on answers above 150 tokens.
- A trivial answer (a single function name, a one-line format string) gets the
  shortest form: one or two sentences naming the fact being applied. Do not pad
  to reach the band — if there is genuinely one decision, write one decision.
- Aim for an overall ratio near **0.4** across the 60 records, which keeps the
  thinking at ~24% of eval loss tokens and leaves `eval_loss` a mostly
  answer-quality signal.

## What the reasoning must do

Write the decisions that produce the answer, in the order they are made, as the
model would reach them — not a summary of the finished answer, and not a
restatement of the prompt.

Required behaviours, each of which exists because the model currently fails at it
(see `results/training_data_gaps_20260918.md`):

1. **Ground claims in the prompt.** Quote the metadata before relying on it —
   `slave port 1: customer_id nullable="false" -> usable sentinel; email
   nullable="true" -> not usable`.
2. **Name the function before using it.** Where a built-in is chosen, say why
   that one — `str2decimal for a string field; cast() is variant-only`. Never
   invent a function: every name must exist in `resources/ctl-function-library.json`.
3. **Decide severity explicitly** on validate-type records — `does this stop
   compilation? no -> WARNING, verdict stays PASS`.
4. **Reject at least one candidate.** Where the answer does *not* flag something
   a pattern-matcher would, say so and why — `transform() returns ALL; is the
   counter guarded? line 1 is if (counter > 0) return SKIP. Guarded. Not a finding.`
5. **Read the spec in order** where the prompt's ordering matters — rounding
   before a threshold comparison, group key before accumulator init.

Must not:
- restate the prompt or the metadata wholesale;
- narrate the answer after the fact ("I will now write the transform");
- hedge without resolving ("maybe X, or possibly Y") — a trace that raises an
  alternative must settle it;
- contain `<think>` tags, markdown headings, or code fences;
- mention CloverDX documentation, this spec, or the training process.

Style: plain declarative sentences, lower-case CTL2 identifiers as they appear in
the code, no bullet lists, no first-person narration of intent.

## Verification before handing back

```bash
python - <<'EOF'
import json, statistics as st
from transformers import AutoTokenizer
tok = AutoTokenizer.from_pretrained("Qwen/Qwen3.8-27B", trust_remote_code=True)
src = {json.dumps(r["messages"]): r for r in
       json.load(open("/home/pavlisd/LlamaFactory/data/CTL_LoRA_eval_data.json"))}
out = json.load(open("data/sft_input/CTL_LoRA_think_eval.json"))
th, an = [], []
for r in out:
    for m in r["messages"]:
        if m["role"] != "assistant":
            continue
        assert "<think>" not in m.get("reasoning_content", ""), "raw tags in reasoning_content"
        assert m.get("reasoning_content", "").strip(), "empty reasoning_content"
        th.append(len(tok.encode(m["reasoning_content"])))
        an.append(len(tok.encode(m["content"])))
print("records      :", len(out), "(want 60)")
print("think tokens : median", st.median(th), " max", max(th), "(want median 60-110, max <=160)")
print("overall ratio:", round(sum(th) / sum(an), 2), "(want ~0.4)")
EOF
```

Also assert that every `content` string still matches the corresponding record in
`CTL_LoRA_eval_data.json` exactly, and report any record where it does not
rather than silently fixing it.
