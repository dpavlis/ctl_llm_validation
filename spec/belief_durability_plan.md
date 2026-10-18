# Making the declaration-default fix durable

**Problem.** The fix for the declaration-default belief exists only in an OPCD adapter. The belief: a declared but
uninitialised variable starts null, so it gets a guard or a "fix".

**Status.**

| | |
|---|---|
| Fixed in | c13c (findings §3.25) |
| T40 / T42 traps (n20) | 0 / 6 |
| Hard-set belief | 0% on all three sets |

Two things undo the fix:

1. **Every base rebuild resets it.** rb1009 came back at:
   - T40 / T42 traps: 20/20 and 20/20;
   - hard-set belief: 74% (set 1) and 92% (set 2).

   So each rebuild needs the full OPCD sequence again: c13, c13b, c13c, about 9 h of training plus evaluations.
2. **Every OPCD run that adds other prompts dilutes it.** Hard set 2 moved:

   | c10 | c11 | c12 | c13 |
   |---|---|---|---|
   | 5% | 17% | 22% | 18% |

## What the corpus has and has not done

**The corpus does not teach the belief.**
- Of the 464 self-distilled traces in the rb1009 SFT, the belief regex hits one.
- Of the 12,185 answer-only records, it hits six. All six are correct statements that `variant`, `byte` and `cbyte`
  start null.

The belief comes from pretraining (Java/C# field semantics, findings §3.16).

**Corpus attempts to counter it have all failed so far** (findings §3.16):

| attempt | data | belief (T40 / T42) | side effect |
|---|---|---|---|
| rb1007 | 80 answer-only records that name the declaration | 20/20, 20/20 | `roundHalfUp()` hallucination |
| rb1008 | 184 own correct fix thinking traces ×2 (30 of them repaired), ~10% of tokens, up to 4 per prompt | 20/20, 20/20 | **thinking-off validate WRONG 3.5% → 13–15%** |
| dpodef2b | 48 own-voice context-distillation DPO pairs | 19/20, 20/20 | thinking-off validate WRONG 3.2% → 11.1% |

So "fold the fix into the corpus" has a weak prior. Expect partial reduction at best, and watch thinking-off validate.

## Plan

Two parts:
- **Part A** makes the fix reliable with what is proven, so a rebuild costs one known OPCD stage.
- **Part B** is a bounded experiment to see whether the corpus can carry part of it, which would shorten that stage.

### Part A: a canonical belief stage and a belief anchor (proven; do this regardless)

**A1. One reproducible Stage 3** for any new base, so we do not re-derive the c13 → c13b → c13c sequence each time.
- **`configs/opcd_stage3a.yaml`:**
  - c13's mix (belief prompts, gap prompts with the guide teachers, DI prompts);
  - teacher **rulev6** from the start (c13 used rulev3; rulev6 passes T42 and gave fix 0.967 vs 0.870 in its teacher
    check);
  - fresh adapter, 40 rounds.
- **`configs/opcd_stage3b.yaml`:** the belief-focused continuation (c13b/c13c mix, rulev6), 16 rounds.
- **Templating:** the base model path is the only per-base setting. `scripts/opcd_gaps_run.sh` runs both stages and the
  gates with `EVAL_SERVE` for that base.
- **Cost per rebuild:** about 8.5 h of training plus 3 h of evaluation, on 2 GPUs.

**A2. A belief anchor in every OPCD run.**
- **Weight:** at least 30% of the non-replay prompts are belief prompts, scored by rulev6:
  - dpodef1 train;
  - dpodef3b;
  - hard sets 1–2;
  - contrast prompts.
- **Gate:** T40/T42 at n20 and hard sets 1–3 are gates for every run, as they are now in the run script.
- **Why:** c11, c12 and c13 each lost ground because their new prompt groups crowded the belief prompts out.

### Part B: fold the belief-free behaviour into the next rebuild (experiment)

**Why it might work where rb1008 failed:**
- **Source.** rb1008's traces came from rb1006, a model that stated the belief in 48% of its thinking on those prompts.
  They were the minority of samples that came out right, 30 of them repaired by hand. c13c's traces are its natural
  output: it does not hold the belief, and it reasons about declared variables correctly without a rule in its prompt.
- **Dose.** rb1008 used ~10% of tokens and up to 4 traces per prompt on a narrow set. Part B uses one trace per prompt
  on a wider set, ×1, ~3% of tokens.

**B1. Prompt pool.** `data/build_belief_traces.py select` builds it, all with the plain system prompt. Every prompt
carries the corpus or run-verified reference answer the self-distill judge compares against.

Measured on corpus `d80aaa5`:

| source | prompts kept |
|---|---|
| dpodef1 train (belief-prone fix / validate) | 206 |
| dpodef3b (declaration contrast) | 53 |
| contrast prompts (something really is null; reference looked up by record id) | 55 |
| `CTL_LoRA_fix_to_spec_explained.json` (not already in dpodef1) | 44 |
| **belief pool (arm a)** | **358** (232 fix, 84 validate, 42 generate) |
| + c9 gap prompts (c9 holdouts excluded) | 68 |
| + revised DataIntersection prompts (c12 holdouts excluded) | 50 |
| **arm b pool** | **476** |

- Most of `fix_defaults_explained` (80) and `declaration_defaults_contrast` (55) are already in dpodef1/dpodef3b; 184
  duplicates are dropped.
- Validate prompts get a second entry sampled thinking off: 84 for arm a, 94 for arm b.
- **Excluded:** eval data, suites v2–v5 and the frozen v5 snapshot, the 50 probe prompts, and **every hard-case set**. The
  hard sets have no reference answers. They stay OPCD prompts and measures, so set 2 and T42 stay clean.
- **Contrast prompts stay in on purpose.** They keep "really null" cases in the data, so the model does not overshoot
  into "nothing is null". That overshoot was c2's T22 failure and the c13 line's T41 explanation.

**B2. Sample c13c** on vLLM: rb1009 plus the `c13c_r015` adapter.
- Plain system prompt (no rule), eval sampling (T = 0.4, top-p 0.95).
- Thinking on, k = 4 per prompt.
- Thinking off, k = 2 for the validate prompts. Thinking-off validate is what rb1008 and dpodef2b damaged, so it also
  gets clean examples.

**B3. Filter.** `build_belief_traces.py sample` drops samples that hit the OPCD belief scan. Then the unchanged
`self_distill.py filter` and `assemble` run, rejecting a sample on any of:
- the belief regex (`opcd.scan_belief`) on thinking + answer;
- the hard-case LLM judge (`data/opcd/eval_hard_cases.py` JUDGE_SYS, gpt-6.1-sol): any false claim about a declared
  variable, or a guard/initialiser added to avoid a null;
- for real nullable fields: missing a guard where one is needed (the overshoot check);
- where a reference answer exists, the self-distill reference judge plus the compile check, as in `self_distill.py`
  filter;
- more than 4,096 tokens (the SFT cutoff), or an unclosed `<think>`.

Smoke test (8 samples, 2026-10-18): the pipeline runs end to end. The judge is strict: 1 of 8 was accepted. It rejected
false side-claims in otherwise correct fixes, and a DataIntersection answer with invented per-port callbacks. Expect
roughly 150–300 accepted traces, not 400–500.

Keep one accepted sample per prompt; `assemble` picks among the accepted. Prompts with no accepted sample are
dropped, never repaired: repairs are off-policy, which was rb1008's and dpodef1's failure.

**B4. Build two arms of rb1010** on 2 GPUs in parallel, about 5 h each. Both use corpus HEAD with the same exclusions
as rb1009.

| arm | adds | purpose |
|---|---|---|
| **rb1010a** | the B3 belief traces, ×1 (`--sd=c13c_belief:1`) | does the corpus carry the belief fix? |
| **rb1010b** | the belief traces plus a second run on the gap and DI prompts (`select --gaps-only`; `--sd=c13c_belief:1 --sd=c13c_gaps:1`) | does it also carry the generate gains of c10/c13? |

`data/build_sft_rebuild.py` takes the new trace runs as extra inputs, as it already takes `full1` and `gen2full`.

**B5. Gates on each arm,** before any OPCD, against rb1009 (`scripts/rb1009_eval.sh` with the base swapped).

| measure | rb1009 | success | kill (drop the traces) |
|---|---|---|---|
| T40 / T42 traps (n20, on) | 20 / 20 | ≤ 10 / 20 each | — |
| hard sets 1 / 2 belief | 74% / 92% | ≤ 30% / 50% | — |
| validate WRONG, thinking off (9 reps) | 5.7% | ≤ 7.0% | ≥ 9% (the rb1008 pattern) |
| generate v4 / gap tests | 0.966 / 0.676 off | within noise | drop > 0.03 |
| T41 (accumulator explanation, n20) | — | no worse than c13c (0.815) | — |

**Outcomes:**
- **Success:** the belief is largely in the base. Stage 3b (A1) may become unnecessary, or shorter.
- **Partial:** run the full Stage 3 as usual, which then starts closer and has less to fix.
- **Kill:** the result is still informative, and Part A stands.

## Cost and order

| step | GPU time | wall time |
|---|---|---|
| A1 configs (no run needed until the next base) | — | 1 h of work |
| B1–B3 prompt pool, sampling, filter | ~1 h on 2 GPUs + judge | ~3 h |
| B4 two rebuild arms | 2 × 5 h, in parallel | ~5.5 h |
| B5 gates | ~1.5 h | ~1.5 h |

**Suggested order:**
1. Write the A1 configs now. They need no GPU.
2. Run B1–B5 when the GPUs are free of harness work.
3. Feed the B5 outcome into the rebuild after harness feedback (gap 1), so that rebuild carries harness-derived data
   too.

## New code needed

- **`data/build_belief_traces.py`:**
  - prompt-pool assembly with the exclusions;
  - sampling through the OPCD vLLM sampler with an adapter;
  - the B3 filter, reusing `opcd.scan_belief`, the `eval_hard_cases` judge and the `self_distill` reference judge;
  - output in the self-distill train format, written to `data/self_distill/c13c_belief/`.
- **`data/build_sft_rebuild.py`:** an option to add trace runs beyond `full1` and `gen2full`, at a chosen repeat count.
- **`configs/opcd_stage3a.yaml`, `configs/opcd_stage3b.yaml`,** and a small wrapper that runs both on a given base.
