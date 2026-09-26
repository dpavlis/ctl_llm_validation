# Rebuilding the two training-time eval sets

**Target: ~200 records for phase 1, ~120 for phase 3.** Everything above the
"Internal tracking" section at the end is a self-contained brief. It assumes CTL2
knowledge (the language, the CloverDX component model, and the `ISSUES:` /
`SUGGESTIONS:` / `VERDICT:` review format) but no other context.

These are the held-out sets used to compute `eval_loss` while training, not the
benchmark the finished model is judged on. Two files:

| file | used by | now | target |
|---|---|---|---|
| `CTL_LoRA_eval_data.json` | phase 1 (SFT, answers only) | 155 | ~200 |
| `CTL_LoRA_eval_data_think.json` | phase 3 (SFT on reasoning) | 60 | ~120 |

## What these sets are for

`eval_loss` is a **diagnostic**, not a scoring metric. It answers "is this phase still
learning the distribution it is being trained on, or has it started to diverge?" It does
not predict downstream quality and must not be used to pick a checkpoint.

That gives one governing rule: **each eval set should look like a held-out sample of the
data its own phase trains on.** Loss measured on a distribution the phase is not training
on is noise. Today neither set does this, which is the whole reason for the rebuild.

## Rule 1 — match the task mix of the phase you evaluate

The single biggest defect. Validate-format records (answers in the
`ISSUES:` / `SUGGESTIONS:` / `VERDICT:` shape) are far rarer in eval than in training:

| | training validate share | eval validate share now | eval target |
|---|---|---|---|
| phase 1 | 12.6% | 3.9% (6 of 155) | **~13%** (~26 of 200) |
| phase 3 | **41.8%** | **5.0%** (3 of 60) | **~40%** (~48 of 120) |

Phase 3 is the severe case: it trains on 42% validate content and is evaluated on three
validate records, two of which have a single finding. Its loss is effectively blind to
the review behaviour the phase mostly teaches.

## Rule 2 — cover multi-defect reviews

Phase-3 training contains **47 validate reviews with four or more findings**; the phase-3
eval set contains **one**. Multi-defect reviews are long, structurally distinctive, and a
known failure mode, so their absence from eval hides exactly the regressions worth
catching.

Of the ~48 phase-3 validate records, aim for roughly:

- **20** with 1 finding
- **12** with 2-3 findings
- **16** with 4-6 findings

Give phase 1 a smaller version of the same shape: of its ~26 validate records, at least
**8** with four or more findings.

## Rule 3 — fix the component skew

Both sets over-weight bare expressions and Map work and under-weight the components where
the model actually struggles.

Phase-1 eval today, against a rough sense of where difficulty lies:

| component | now (of 155) | target share |
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
one-line expressions are a third of the set and are the easiest thing in it. Apply the
same proportions to phase 3.

Within Rollup specifically, include **both** lifecycle shapes: the summary-only pattern
(`updateGroup` returns false, output only from `transform()`) and the per-record output
loop (`updateGroup` returns true, `updateTransform` writes output and returns a port
number, both loops bounded by a `counter` guard). The second is the one that has caused
repeated trouble and it should be no less than a third of the Rollup records.

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

## Rule 5 — never overlap the judged suite

No eval prompt may duplicate a prompt in `resources/ctl2_test_suite_v4.json`. This holds
today (0 overlap in both sets) and must be preserved: the suite is the independent
measure, and leaking it into training-time evaluation would quietly destroy that.

Also keep both eval sets disjoint from the training corpora — verified today, must stay.

## Format

Each record is `{"messages": [...]}` with a `system`, a `user` and an `assistant` turn,
matching the training corpora. Also carry `id`, `difficulty`, `tags`, and `component`
where one applies.

**Phase-1 eval (`CTL_LoRA_eval_data.json`)** — answers only, no reasoning, no `<think>`
tags anywhere.

**Phase-3 eval (`CTL_LoRA_eval_data_think.json`)** — every record carries reasoning. Write
it the way the training corpora do: a separate `reasoning_content` field on the assistant
message, with `content` holding the answer, then let `convert_think.py` merge them. Never
hand-write `<think>` tags; the merge needs an exact literal spelling and a hand-typed
variant fails silently. All 60 current records are correctly tagged — preserve that.

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

Every answer must be **correct CTL2**. The current sets are clean on this and the bar
should not drop: no invented functions, correct arity, `//#CTL2` header on every fenced
block.

## Verification

```python
import json, re, collections, statistics as st, os
D = os.path.expanduser('~/LlamaFactory/data')
THINK = re.compile(r'^<think>\n.*?\n</think>\n\n', re.S)
def asst(e): return THINK.sub('', ''.join(m.get('content','') or '' for m in e['messages'] if m['role']=='assistant'))
def user(e): return ' '.join(next(m['content'] for m in e['messages'] if m['role']=='user').split())
def lines(s):
    if 'ISSUES:' not in s: return []
    b = s.split('ISSUES:',1)[1].split('SUGGESTIONS:')[0].split('VERDICT:')[0]
    return [l for l in b.splitlines() if re.match(r'\s*\[(ERROR|WARNING|INFO)\]', l) and 'No issues found' not in l]

suite = json.load(open('/home/pavlisd/llama_train/resources/ctl2_test_suite_v4.json'))
suite = suite['tests'] if isinstance(suite, dict) else suite
sp = {' '.join(t['user_message'].split()) for t in suite}

for ev, tr, lab, tgt in [('CTL_LoRA_eval_data.json','CTL_LoRA_training_data.json','phase 1',0.126),
                         ('CTL_LoRA_eval_data_think.json','CTL_LoRA_training_data_think.json','phase 3',0.418)]:
    E = json.load(open(f'{D}/{ev}')); T = json.load(open(f'{D}/{tr}'))
    v = [e for e in E if 'ISSUES:' in asst(e)]
    print(f'{lab}: {len(E)} eval records')
    print(f'   validate share {100*len(v)/len(E):.1f}%   (training {100*tgt:.1f}%, want within ~3 pts)')
    print(f'   median answer  {st.median([len(asst(e).split()) for e in E]):.0f}w  '
          f'(training {st.median([len(asst(e).split()) for e in T]):.0f}w, want within ~10%)')
    print(f'   validate records with >=4 findings: {sum(1 for e in v if len(lines(asst(e)))>=4)}')
    print(f'   duplicate prompts (want 0): {sum(1 for k,n in collections.Counter(user(e) for e in E).items() if n>1)}')
    print(f'   overlap with judged suite (want 0): {sum(1 for e in E if user(e) in sp)}')
    trp = {user(e) for e in T}
    print(f'   overlap with training corpus (want 0): {sum(1 for e in E if user(e) in trp)}')
    print(f'   missing difficulty tag (want 0): {sum(1 for e in E if not e.get("difficulty"))}')
    print(f'   fenced answers missing //#CTL2 (want 0): '
          f'{sum(1 for e in E if "```ctl" in asst(e) and "//#CTL2" not in asst(e))}')
    print()
```

For the phase-3 set additionally confirm the tagging after `convert_think.py`:

```python
import json, os
B = json.load(open(os.path.expanduser('~/LlamaFactory/data/CTL_LoRA_eval_data_think.json')))
a = lambda e: ''.join(m.get('content','') or '' for m in e['messages'] if m['role']=='assistant')
print('records:', len(B))
print('wrong thought-word spelling (want 0):',
      sum(1 for e in B if not ('<think>\n' in a(e) and '\n</think>\n\n' in a(e))))
print('unmerged reasoning_content (want 0):',
      sum(1 for e in B for m in e['messages'] if 'reasoning_content' in m))
```

---

## Internal tracking (not part of the generation brief above)

Evidence is in `spec/ctl2_training_findings.md` §4.4, measured 2026-09-26.

**Priority is lower than it looks.** `load_best_model_at_end` was disabled on all three
phases the same day, so `eval_loss` no longer selects checkpoints — which was the acute
harm. What remains is the diagnostic value: had the phase-3 eval set been 42% validate,
fix4's validate collapse (0.8462 → 0.5538) would likely have shown as rising eval_loss
during the run instead of surfacing three hours later in the suite eval. That is worth
having, but it is not blocking any training.

**Do not re-enable checkpoint selection on eval_loss even after this rebuild.** A
representative eval set makes the metric meaningful as a trend; it does not make it
predictive of suite score, which §2.1 measured directly. The flatness that made selection
arbitrary (16 of 39 checkpoints within 0.002) is a property of the loss surface, not only
of the eval set.

**What is already fine and should not be "fixed":** both sets are clean on validity — no
duplicate prompts, no overlap with the judged suite or the training corpora, no missing
`//#CTL2` headers, no invalid CTL2. A function-library scan flagged 20 records and all 20
are false positives (`lookup()` and `sequence()` are syntax constructs, `freq()` is a
helper the prompt asks the model to define, `toDecimal()` appears in a validate record
that correctly flags it as not existing). Generate-side composition is also reasonable —
70% and 65% full component transforms against a judged suite that is 62% generate.

**Sizing rationale.** Phase 3's 60 records give a noisy loss estimate on a set that is
41.8% validate in training terms; doubling to ~120 costs little and halves the noise.
Phase 1 at 155 → ~200 is a smaller relative change, justified mainly by needing room for
the Rollup and Partition records without dropping other coverage.

**The suite has a `fix` test type** (T39, T40, added 2026-09-24) that neither eval set
represents. Left out of the brief deliberately — the training corpora barely contain that
task shape either, so adding it to eval would reintroduce the same train/eval mismatch in
a new place. Revisit if `fix` records are ever added to training in volume.
