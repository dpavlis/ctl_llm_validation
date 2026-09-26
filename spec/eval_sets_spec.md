# Rebuilding the two training-time eval sets

**Target: ~200 records for phase 1, ~120 for phase 3.** Everything above the
"Internal tracking" section at the end is a self-contained brief. It assumes CTL2
knowledge (the language, the CloverDX component model, and the `ISSUES:` /
`SUGGESTIONS:` / `VERDICT:` review format) but no other context.

## Where you are working

Everything is inside the `ctl_lora_training` repo. Paths below are relative to its root.

| path | what it is |
|---|---|
| `sft_eval_data/CTL_LoRA_eval_data.json` | **phase-1 eval — edit this** |
| `sft_eval_data/CTL_LoRA_eval_data_think_src.json` | **phase-3 eval source — edit this** |
| `sft_eval_data/CTL_LoRA_DPO_eval.jsonl` | DPO eval — **leave alone**, see below |
| `sft_training_data/*.json` | the training corpora these sets are held out from |
| `references/CTL2_Reference_for_LLM_compact.md` | the CTL2 language reference |
| `references/ctl-function-library.json` | every built-in, with signatures and overloads |
| `references/componet_contracts.md` | per-component lifecycle rules (Rollup, Denormalizer, …) |
| `references/CTL2_Example_Generation_Playbook.md` | house style for writing examples |
| `references/CTL2_SFT_Validation_Playbook.md` | house style for validate-format answers |
| `references/CTL2_Reasoning_Trace_Playbook.md` | house style for reasoning traces |
| `utils/convert_think.py` | merges `reasoning_content` into the tagged form |

The `_think_src.json` suffix matters: that file holds `reasoning_content` as a separate
field and **no** `<think>` tags. `utils/convert_think.py` turns it into the merged
`CTL_LoRA_eval_data_think.json` that training consumes. Edit the `_src` file only.

**Do not touch `sft_training_data/`.** These sets are held out from it; changing training
data here would defeat the purpose.

## How eval examples differ from training examples

You may have guidance on writing *training* examples. Most of it applies — same CTL2, same
formats, same correctness bar — but the goal is different in three ways, and where they
conflict, these win.

1. **Representative, not exemplary.** A training example is chosen to teach something well.
   An eval record exists to measure whether the model has learned the distribution it was
   trained on, so it should look like a *typical* member of that distribution, including
   the ordinary and unremarkable cases. Do not curate for pedagogical value, and do not
   prefer the cleanest or most instructive phrasing — prefer the usual one.
2. **The mix matters more than any single record.** For training data, one excellent
   example earns its place. Here, a record is only useful insofar as the set as a whole
   matches the training distribution in task type, component, and difficulty. The rules
   below are mostly about proportions for that reason.
3. **Held out means held out.** No eval prompt may duplicate a training prompt or a
   benchmark prompt (Rule 5). A training-example workflow has no reason to check this; here
   it is the one thing that invalidates the whole set if you get it wrong.

Everything else — CTL2 correctness, `//#CTL2` headers, the `ISSUES:`/`VERDICT:` shape,
reasoning written as `reasoning_content` — follows the normal house style in `references/`.

## What these sets are for

`eval_loss` is a **diagnostic**, not a scoring metric. It answers "is this phase still
learning the distribution it is being trained on, or has it started to diverge?" It does
not predict downstream quality and is not used to pick a checkpoint.

That gives one governing rule: **each eval set should look like a held-out sample of the
data its own phase trains on.** Loss measured on a distribution the phase is not training
on is noise. Today neither set does this, which is the reason for the rebuild.

| file | used by | now | target |
|---|---|---|---|
| `CTL_LoRA_eval_data.json` | phase 1 (SFT, answers only) | 155 | ~200 |
| `CTL_LoRA_eval_data_think_src.json` | phase 3 (SFT on reasoning) | 60 | ~120 |

## Rule 1 — match the task mix of the phase you evaluate

The single biggest defect. Validate-format records are far rarer in eval than in training:

| | training validate share | eval validate share now | eval target |
|---|---|---|---|
| phase 1 | 12.6% | 3.9% (6 of 155) | **~13%** (~26 of 200) |
| phase 3 | **41.8%** | **5.0%** (3 of 60) | **~40%** (~48 of 120) |

Phase 3 is the severe case: it trains on 42% validate content and is evaluated on three
validate records, two of which have a single finding. Its loss is effectively blind to the
review behaviour the phase mostly teaches.

## Rule 2 — cover multi-defect reviews

Phase-3 training contains **47 validate reviews with four or more findings**; the phase-3
eval set contains **one**. Multi-defect reviews are long, structurally distinctive, and a
known failure mode, so their absence hides exactly the regressions worth catching.

Of the ~48 phase-3 validate records, aim for roughly:

- **20** with 1 finding
- **12** with 2-3 findings
- **16** with 4-6 findings

Give phase 1 a smaller version of the same shape: of its ~26 validate records, at least
**8** with four or more findings.

## Rule 3 — fix the component skew

Both sets over-weight bare expressions and Map work and under-weight the components where
the model actually struggles.

| component | phase-1 eval now (of 155) | target share |
|---|---|---|
| bare expression, no component | 51 (33%) | **~15%** |
| Map / Reformat+Lookup | 24 (15%) | ~8% |
| Reformat | 23 (15%) | ~20% |
| Filter | 15 (10%) | ~8% |
| Denormalizer | 10 | ~8% |
| Join (ExtHash / ExtMerge) | 9 | ~8% |
| Normalizer | 7 | ~8% |
| **Rollup** | **6 (4%)** | **~12%** |
| **Partition** | **4 (3%)** | **~10%** |
| DataGenerator | 4 | ~5% |

Rollup and Partition are the two most under-represented and among the hardest; bare
one-line expressions are a third of the set and the easiest thing in it. Apply the same
proportions to phase 3.

Within Rollup, include **both** lifecycle shapes: the summary-only pattern (`updateGroup`
returns false, output only from `transform()`) and the per-record output loop
(`updateGroup` returns true, `updateTransform` writes output and returns a port number,
both loops bounded by a `counter` guard). The second has caused repeated trouble and
should be no less than a third of the Rollup records. `references/componet_contracts.md`
has the authoritative rules.

## Rule 4 — match the difficulty, not just the topic

Eval answers are systematically shorter than training answers, which saturates the loss
and flattens the curve:

| | median training answer | median eval answer now |
|---|---|---|
| phase 1 | 51 words | 35 words |
| phase 3 | 62 words | 38 words |

Bring the eval medians within about 10% of the training medians. The lever is task
difficulty — full component transforms with real metadata rather than one-line
expressions — not padding the answers.

Keep the existing `difficulty` tag (`easy` / `medium` / `hard`) and put it on **every**
record; it is currently missing on 97 of 155 and 40 of 60. Aim for roughly 30% easy,
50% medium, 20% hard.

## Rule 5 — never overlap the benchmark or the training corpora

No eval prompt may duplicate a prompt in the judged benchmark suite, and none may
duplicate a prompt in `sft_training_data/`. Both hold today (0 overlap on all counts) and
must be preserved: the benchmark is the independent measure, and leaking it into
training-time evaluation would quietly destroy that.

The benchmark lives outside this repo at
`/home/pavlisd/llama_train/resources/ctl2_test_suite_v4.json`. If it is not reachable,
say so rather than skipping the check.

## Format

Each record is `{"messages": [...]}` with a `system`, a `user` and an `assistant` turn,
matching the training corpora. Also carry `id`, `difficulty`, `tags`, and `component`
where one applies.

**Phase-1 eval (`CTL_LoRA_eval_data.json`)** — answers only, no reasoning, no `<think>`
tags anywhere.

**Phase-3 eval (`CTL_LoRA_eval_data_think_src.json`)** — every record carries reasoning as
a separate `reasoning_content` field on the assistant message, with `content` holding the
answer. **Never hand-write `<think>` tags**; `utils/convert_think.py` merges them, and it
needs an exact literal spelling that a hand-typed variant gets wrong silently. All 60
current records follow this correctly — preserve it.

Generate answers are a `//#CTL2` fenced block. Validate answers use:

```
ISSUES:
  [ERROR] <construct, mechanism with its qualifier, concrete consequence>
  [WARNING] <construct, why it is suspicious, why it still runs>
SUGGESTIONS:
  - <the fix>
VERDICT: FAIL
```

with `ISSUES:\n  [INFO] No issues found.` and `VERDICT: PASS` for clean code.

Every answer must be **correct CTL2** — check against
`references/ctl-function-library.json` for arity and existence. The current sets are clean
on this and the bar should not drop.

## Verification

Run from the repo root. It compares each eval set against the training corpus it is held
out from, reading `sft_training_data/` directly.

```python
import json, re, glob, collections, statistics as st

THINK = re.compile(r'^<think>\n.*?\n</think>\n\n', re.S)
def asst(e): return THINK.sub('', ''.join(m.get('content','') or '' for m in e['messages'] if m['role']=='assistant'))
def user(e): return ' '.join(next(m['content'] for m in e['messages'] if m['role']=='user').split())
def lines(s):
    if 'ISSUES:' not in s: return []
    b = s.split('ISSUES:',1)[1].split('SUGGESTIONS:')[0].split('VERDICT:')[0]
    return [l for l in b.splitlines() if re.match(r'\s*\[(ERROR|WARNING|INFO)\]', l) and 'No issues found' not in l]

# every training prompt, and the validate share of each phase's training data
train_prompts, tr_p1, tr_p3 = set(), [], []
for f in glob.glob('sft_training_data/*.json'):
    try: data = json.load(open(f))
    except Exception: continue
    if isinstance(data, dict): data = data.get('examples') or data.get('records') or []
    for r in data:
        if not isinstance(r, dict) or not r.get('messages'): continue
        train_prompts.add(user(r))
        tr_p1.append(r)
        if any('reasoning_content' in m for m in r['messages']): tr_p3.append(r)

SUITE = '/home/pavlisd/llama_train/resources/ctl2_test_suite_v4.json'
try:
    s = json.load(open(SUITE)); s = s['tests'] if isinstance(s, dict) else s
    suite_prompts = {' '.join(t['user_message'].split()) for t in s}
except Exception:
    suite_prompts = None
    print('WARNING: benchmark suite not reachable — Rule 5 only half checked')

for ev, tr, lab in [('sft_eval_data/CTL_LoRA_eval_data.json', tr_p1, 'phase 1'),
                    ('sft_eval_data/CTL_LoRA_eval_data_think_src.json', tr_p3, 'phase 3')]:
    E = json.load(open(ev))
    v = [e for e in E if 'ISSUES:' in asst(e)]
    tv = sum(1 for e in tr if 'ISSUES:' in asst(e))
    print(f'{lab}: {len(E)} eval records')
    print(f'   validate share {100*len(v)/len(E):.1f}%   (training {100*tv/len(tr):.1f}%, want within ~3 pts)')
    print(f'   median answer  {st.median([len(asst(e).split()) for e in E]):.0f}w  '
          f'(training {st.median([len(asst(e).split()) for e in tr]):.0f}w, want within ~10%)')
    print(f'   validate records with >=4 findings: {sum(1 for e in v if len(lines(asst(e)))>=4)}')
    print(f'   duplicate prompts (want 0): {sum(1 for k,n in collections.Counter(user(e) for e in E).items() if n>1)}')
    print(f'   overlap with training corpora (want 0): {sum(1 for e in E if user(e) in train_prompts)}')
    if suite_prompts is not None:
        print(f'   overlap with benchmark suite (want 0): {sum(1 for e in E if user(e) in suite_prompts)}')
    print(f'   missing difficulty tag (want 0): {sum(1 for e in E if not e.get("difficulty"))}')
    print(f'   fenced answers missing //#CTL2 (want 0): '
          f'{sum(1 for e in E if "```ctl" in asst(e) and "//#CTL2" not in asst(e))}')
    print()

src = json.load(open('sft_eval_data/CTL_LoRA_eval_data_think_src.json'))
print('phase-3 src: records with reasoning_content (want all):',
      sum(1 for e in src if any('reasoning_content' in m for m in e['messages'])), 'of', len(src))
print('phase-3 src: hand-written <think> tags (want 0):',
      sum(1 for e in src if '<think>' in asst(e)))
```

Then convert and confirm the tagging:

```bash
python3 utils/convert_think.py sft_eval_data/CTL_LoRA_eval_data_think_src.json -o sft_eval_data/CTL_LoRA_eval_data_think.json
```

---

## Should the DPO eval set be updated too?

**No — leave `sft_eval_data/CTL_LoRA_DPO_eval.jsonl` alone.** Measured 2026-09-26, it does
not have either problem the SFT sets have.

**Its composition already matches its training data:**

| | DPO train (1189 pairs) | DPO eval (49 pairs) |
|---|---|---|
| validate-format chosen | 22% | 29% |
| median chosen length | 16 words | 18 words |

A 7-point validate gap against phase 1's 8.7 and phase 3's 36.8, and the lengths are
within two words. 49 held out of 1189 is a sane ~4%.

**And its loss curve actually discriminates.** The DPO metric has roughly four times the
dynamic range of the SFT one and a far narrower flat region:

| | eval span (worst − best) | checkpoints within 0.002 of best |
|---|---|---|
| SFT (fix4) | 0.145 | **16 of 39** |
| DPO (fix3) | 0.580 | 4 of 18 |
| DPO (fix4) | 0.585 | 4 of 18 |
| DPO (fix5) | 0.605 | 3 of 18 |

Those 3-4 near-best checkpoints are consecutive and at the end (375-450 of 472), so
selection landed at 425-450 every run — 90-95% through, consistently. There was never the
2× dose swing that broke SFT checkpoint selection.

So the SFT/postSFT diagnosis does not generalise to DPO, and rewriting a healthy eval set
would only risk breaking it.

---

## Internal tracking (not part of the generation brief above)

Evidence is in `spec/ctl2_training_findings.md` §4.4, measured 2026-09-26.

**Priority is lower than it looks.** `load_best_model_at_end` was disabled on all three
phases the same day, so `eval_loss` no longer selects checkpoints — which was the acute
harm. What remains is diagnostic value: had the phase-3 eval set been 42% validate, fix4's
validate collapse (0.8462 → 0.5538) would likely have shown as rising eval_loss during the
run instead of surfacing three hours later in the benchmark eval. Worth having, not
blocking any training.

**Do not re-enable checkpoint selection on eval_loss even after this rebuild.** A
representative eval set makes the metric meaningful as a trend; it does not make it
predictive of suite score, which §2.1 measured directly. The flatness that made selection
arbitrary is a property of the loss surface, not only of the eval set.

**One cost of that change, for the record.** DPO selection was working (see above), so
pinning it to the last checkpoint is the one place where disabling selection loses a
little. DPO now takes checkpoint-472 rather than the 425-450 the metric preferred; 472 is
22 steps past the end of the flat band and unevaluated, so the loss there is unmeasured
but very unlikely to be materially worse. Kept for chain determinism. Revisit only with
evidence.

**What is already fine and should not be "fixed":** both SFT sets are clean on validity —
no duplicate prompts, no overlap with the benchmark or the training corpora, no missing
`//#CTL2` headers, no invalid CTL2. A function-library scan flagged 20 records and all 20
are false positives (`lookup()` and `sequence()` are syntax constructs, `freq()` is a
helper the prompt asks the model to define, `toDecimal()` appears in a validate record that
correctly flags it as not existing). Generate-side composition is also reasonable — 70% and
65% full component transforms against a benchmark that is 62% generate.

**Sizing rationale.** Phase 3's 60 records give a noisy loss estimate on a set that should
be ~40% validate; doubling to ~120 costs little and halves the noise. Phase 1 at 155 → ~200
is a smaller relative change, justified mainly by needing room for the Rollup and Partition
records without dropping other coverage.

**The benchmark has a `fix` test type** (T39, T40, added 2026-09-24) that neither eval set
represents. Left out of the brief deliberately — the training corpora barely contain that
task shape either, so adding it to eval would reintroduce the same train/eval mismatch in a
new place. Revisit if `fix` records are ever added to training in volume.
