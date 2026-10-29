# Brief: validate-precision OPCD, round 2 (valprec2)

Background: `spec/validate_precision_findings.md` (valprec1, findings §3.37); the round-1 brief
`spec/validate_precision_brief.md`, whose rules (exclusions, fact sources, run hygiene) all still apply. Follow the
shared-machine, git and correctness rules in `CLAUDE.md`.

## Why

valprec1 trained c13c on 1426 server-verdict-conditioned validate reviews.
- **Thinking on, it is the best reviewer so far:** B1 false alarm 0.14 → 0.01, lifecycle recall 0.35 → 0.83.
- **Thinking off:**
  - lifecycle recall rose 0.18 → 0.67;
  - the false-alarm rate with the output format did not move (B1 0.41 → 0.35, B1-tweak 0.24 → 0.23);
  - without the format (the test.py path) it **doubled** (0.30 → 0.61), with new false claims: DataIntersection `$out.0`
    is the "wrong port", getDayOfWeek and getMinute signatures, an "unreachable return";
  - the judge's thinking-off WRONG share rose 2.2% → 3.8%.

Three features of round 1 explain most of that:

1. **Imbalance.** Clean code was 22% of the review prompts. The one training slot whose teacher–student KL never
   converged is clean / plain / thinking off: 0.190 → 0.095, while every other slot fell to ≤ 0.03. It had 160 samples
   against about 550 per planted slot.
2. **The compile-type mutants dominate the planted half** (unconnected port and unknown field are 57%). Their recall
   was already ≈ 1.0 before training. They teach "there is a port or field problem", not judgement.
3. **The severity sentence did nothing.** Null-comparison findings stayed ERROR (0 WARNINGs). The teacher was never told
   what form to use for a data-dependent null on the very code it saw.

The fact sheet worked where it applied: the decimal / integer claims and "null assigned to a local throws" disappeared.

**Hypothesis:** with clean reviews at ≥ 50% of the review weight (clean / plain / thinking off over-sampled), the
compile-type mutants down-sampled, and the teacher context naming the WARNING form and ruling out compile claims on code
that compiled:
- the thinking-off false-alarm rate falls in both conditions (B1-tweak with the format 0.24 → ≤ 0.16; B1 plain no
  higher than c13c's 0.30);
- valprec1's thinking-on and lifecycle gains are kept;
- generate and belief do not move.

## Data

Same source and exclusions as round 1. The 160 exec-RFT references (the exec-RFT pool minus the pool-1 / B1 references;
the holdout unread) and their 553 server-confirmed planted defects, `data/validate_precision/review_mutants.jsonl`, are
reused unchanged.

- **Clean reviews:** every reference in **both** conditions (format and plain) in **both** modes: 640 rows, against
  320 in round 1.
  - Row weights: clean / plain / thinking off ×2.
  - **Claim controls** ×2 more, in every condition: clean code that holds a construct the round-1 model falsely flagged.
    - DataIntersection transforms writing `$out.0`;
    - Rollup code that counts or resets state in `initGroup`;
    - millisecond date arithmetic (`date2long`, `86400000`);
    - ordered comparisons (`<`, `>`, `<=`, `>=`) on nullable input fields;
    - calls to getDayOfWeek, getMinute or getHour with a time zone.

    The selection is a regex over the code and metadata; record the count per construct.
- **Planted reviews:** unconnected port and unknown field down-sampled to 30 each (stratified by component, seed 13).
  Missing lifecycle (51), wrong `return SKIP` (92), inverted condition (42) and null guard removed (54) are kept whole.
  That is 299 prompts × 2 modes = 598 rows, the format alternating within each kind as in round 1.
- **Target share:** clean reviews ≥ 50% of the review weight; reviews 60–65% of the non-replay weight, with anchors as
  in valprec1 (c13c's ×2).
- **Not used:** the retry-distill tweak pool (`pool_retry_tweak.jsonl`). Its tasks are rewrites of the same corpus
  records as pool_tweak (81 shared origins with B1-tweak), so training on their references would make B1-tweak less
  held out. Only 45 tasks have origins outside B1-tweak's.

## Teacher context

The round-1 verdict lines plus these changes:

- **clean:** after the existing sentence add: "It compiled, so nothing in it is a compile error, an undeclared function
  or a wrong signature. A null in a nullable field that neither the fixture nor the requirements mention is at most a
  [WARNING], never an [ERROR]." That is a restatement of the §7 severity ruling applied to code that passed.
- **planted:** unchanged.
- **fact sheet:** round 1's, plus server-probed lines for the new false claims, written only after the probes run:
  - `getDayOfWeek` numbering (expected 1 = Monday … 7 = Sunday, ctl2-basics);
  - `getMinute(date, "UTC")` and `getHour(date, "UTC")` compile;
  - a `return` after an `if / else if (true)` chain compiles.

  Add them to `scripts/validate_precision/probe_facts.py` and run them on the server; a line goes in only if the probe
  confirms it.

## Run

- `valprec2`, initialised from **c13c** (round 015), not from valprec1. The result is one recipe stage on the ship
  candidate, and the comparison with valprec1 isolates the data change.
- c13c's per-step hyperparameters, the same guards (quote guard, context guard), and the round-1 anchors.
- Rounds: enough to draw the review weight about once, computed from the prepared weights.
- GPUs: training on one free GPU, the sampler (:3011, served as `rb1009_vp`) on another, both checked with
  `nvidia-smi` first.
- `opcd.py` needs per-row weights in hard files (a `row_weight` field multiplied with the file weight).

## Gates (against c13c and valprec1, same vLLM path)

| gate | how | pass |
|---|---|---|
| **B1-tweak**, with the format, thinking off: false alarm | as round 1 | c13c 0.24 → ≤ 0.16 (down by > 0.08) |
| **B1 plain**, thinking off: false alarm | `gen_answers.py` without `--format` | ≤ c13c's 0.30 + 0.08 and ≤ the format condition + 0.08 |
| B1 / B1-tweak, with the format, thinking off: lifecycle recall | as round 1 | ≥ 0.6 |
| B1 / B1-tweak, with the format, thinking on: false alarm / recall | as round 1 | false alarm ≤ c13c's; recall not below c13c's by > 0.05 |
| **B1 plain, thinking on** (new) | without `--format` | false alarm ≤ c13c's 0.04 + 0.08 |
| judge validate off ×9, WRONG share excluding T18/T22 | as round 1 | ≤ 2.5% (c13c 2.2%, valprec1 3.8%) |
| gap tests execution pass rate | 3 × n10, both modes | within ±0.06 of c13c (0.403 / 0.761) |
| harness pool 1 first attempt | `--rounds 0 --runs 2`, both modes | within the CI of c13c (0.65 / 0.82) |
| T40/T42, hard sets 1–3 by direction, T54 off | as round 1 | as c13c; T54 `$out.1` ≤ 1/20 |
| thinking-on full v4 n5 | as round 1 | within noise |

Report every number with n and a 95% CI, and every comparison against both c13c and valprec1.

## Deliverables

1. `spec/validate_precision2_findings.md` with:
   - data stats, including the claim-control counts per construct;
   - the probe results;
   - training per-slot KL;
   - the gate table;
   - for the 10 B1 plain thinking-off controls valprec1 flagged, valprec2's answers next to it (quote the changed
     sentence), and the claim table by category for c13c, valprec1 and valprec2;
   - **Indications:**
     1. did the thinking-off false alarm fall in both conditions;
     2. were valprec1's thinking-on and lifecycle gains kept;
     3. did the null-comparison findings move to WARNING;
     4. generate / belief regressions;
     5. verdict: adopt as c13c's successor, or stop and leave thinking-off precision to the system prompt or retry
        loop.
2. Configs and scripts in the repo; run data under `data/opcd/valprec2/`, `data/validate_precision/`, `results/`;
   a WORKLOG entry and a findings §3.38.

## Do not

- Train on pool 1, pool_tweak, the retry-distill tweak pool, B1, B1-tweak, the suite, the hard sets or the exec-RFT
  holdout.
- Reuse a run folder.
- Change rubrics, references or `ctl2-basics.md`.
- Put a fact in the teacher that is not in §7 or server-verified.
- Touch `~/venv`, other users' processes or GPUs, or other sessions' uncommitted files.
