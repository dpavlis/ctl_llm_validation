# Brief: thinking-off validate false alarms at inference (review rules, escalation, verification)

> **Closed 2026-11-01, not run (owner ruling).** A thinking-off review call will not ship; the deployment validate call is
> valprec2 thinking on (clean-code false alarm 0.02–0.03, recall 0.96, §3.38), so the thinking-off false alarms this brief
> targets are not a deployment problem. What was learned in the meantime also argues against arm R: a seven-line CTL2 fact
> list in the system prompt raised the B1-tweak thinking-off false alarm 0.15 → 0.38 and the thinking-on one 0.02 → 0.08
> (`spec/sysprompt_rules_findings.md`, "Deployment recipe check"), and this brief's R3 line explains DataIntersection in port
> numbers, the framing the 2026-11-01 ruling replaced (`spec/di_section_8_9_rewrite.md`). Arms E and V stay unrun; E could
> be simulated offline from the stored B1 answers of both modes if a cheap review call ever becomes a target. The text
> below is kept as written.


Background:
- `spec/validate_precision2_findings.md` and findings §3.38: valprec2 is the ship candidate.
- `spec/validate_precision_findings.md` (§3.37), the method and the claim analysis.
- §4.8, the validate gate.

Follow the shared-machine, git, measurement and correctness rules in `CLAUDE.md`. **No training in this brief.**
Everything here is a change to how the shipped model is called.

## Why

valprec2 is the best reviewer measured.
- **Thinking on, it is near-perfect:** false alarm 0.02–0.03, recall 0.96.
- **Thinking off, it still flags clean code with an [ERROR]:**
  - B1 with the format 0.25 (100 control answers);
  - B1-tweak with the format 0.15;
  - B1 plain (the test.py path) 0.31.

Two training rounds removed the requirement misreadings and the invented compile claims. What is left is a short,
stable list of claims (valprec2 thinking off, B1, [ERROR] lines on controls, keyword-classified):

| claim | format | plain | what is true (source) |
|---|---|---|---|
| a nullable field compared with `<`/`>` or used in arithmetic "throws" | 10 | 9 | It throws only if the value is null, so it is a data-dependent risk. **WARNING**, not ERROR (§7 review severity; server probes §3.37). The planted null-guard mutants expect WARNING too. |
| Rollup group state "not reset", "leaks into the next group", initGroup numbering | 8 | 8 | initGroup runs once per group, before updateGroup sees the group's first record; the accumulator is reset from its metadata before each group (§7 Rollup accumulator; probes §3.37). |
| DataIntersection writing `$out.0` is "the removal / A-only port" | 3 | 3 | CTL writes `$out.0`, which the component sends out on port 1 (matches) (§7 DataIntersection). |
| requirement misreadings (rule order, SCD-2 boundaries) | 9 | 7 | not a fact problem |
| DST / millisecond date arithmetic, time-zone signatures, getDayOfWeek "Sunday = 1" | 2–3 | 2–3 | getDayOfWeek returns 1 = Monday … 7 = Sunday; date parts take a time zone (server probes, `fact_probes_v2.json`) |

The OPCD route has run its course. valprec2 had 22 DataIntersection and 40 initGroup claim controls plus the facts in
the teacher's context, and the claims stayed. §3.38 decided to try the two inference-time levers instead.

## Hypotheses

1. **Review rules in the system prompt (arm R).** A short block of the facts above, added to the system prompt of
   validate requests, removes the fact-based claims (null severity, Rollup state, DataIntersection port, getDayOfWeek)
   thinking off without lowering recall. It does not touch the misreadings.
2. **Escalate on ERROR (arm E).** Re-review with thinking on only when the thinking-off review reports an [ERROR]. Final
   answer: the thinking-on review. This gives thinking-on precision at a fraction of thinking-on cost, because a clean
   answer from the fast pass is accepted as is.
3. **Verify each ERROR (arm V).** A second thinking-off call per [ERROR] finding sees the code and that one finding and
   answers CONFIRMED or REJECTED with a reason. Rejected findings are dropped, or downgraded to WARNING if the verifier
   says so. Compile claims ("does not compile", "undeclared", "no such function / signature") are checked with
   `ctl_validate` on the server instead and dropped if the code compiles.

R is the cheapest. E and V add calls. Each arm must report what it costs: extra requests, tokens, and p50 / p95
latency per review.

## Arms

All arms use **valprec2** (`data/opcd/valprec2/round_155` on rb1009, served on vLLM with the adapter hot-loaded),
**thinking off for the first pass**, the suite's sampling settings (temperature 0.4), and 2 runs per record.

| arm | system prompt | second step | conditions |
|---|---|---|---|
| **0** baseline | suite prompt | — | format, plain (reuse valprec2's stored answers if the serving path is unchanged; otherwise regenerate) |
| **R** rules | suite prompt + review-rules block | — | format, plain |
| **R1–R4** one rule each | suite prompt + one line of the block | — | format |
| **E** escalate | suite prompt (+ rules if R passes) | if the pass-1 answer has any [ERROR]: the same request with thinking on; the final answer is the thinking-on one | format |
| **V** verify | suite prompt (+ rules if R passes) | per [ERROR] finding: compile claims → `ctl_validate`; others → one thinking-off verifier call (prompt below) | format |
| **T** thinking on, reference | suite prompt | — | format (valprec2's stored answers) |

E and V need the format so that findings can be parsed. They run on the format condition only. Report the share of
plain answers that lose the layout under R, because §3.38 saw 26% of thinking-off plain answers drop it.

### Review-rules block (arm R)

It is one block and one fact per line. Every fact comes from §7 or a server probe. Lines:

- **R1 (severity):** "Severity: [ERROR] is a compile failure, a certain runtime failure, or a violation of a stated
  requirement. A nullable field used in a comparison or arithmetic without a null check fails only when the value is
  null; report it as [WARNING] unless the requirements or the data say the value can be null on that path."
- **R2 (Rollup):** "Rollup: initGroup runs once per group, before updateGroup sees the group's first record, and the
  accumulator is reset from its metadata before each group. State kept in the accumulator does not leak into the next
  group."
- **R3 (DataIntersection):** "DataIntersection: the transform writes `$out.0`, which the component sends to output port
  1 (matched pairs); ports 0 and 2 are pass-through."
- **R4 (dates):** "getDayOfWeek returns 1 for Monday through 7 for Sunday; getDayOfWeek, getHour and getMinute accept an
  optional time-zone argument."

Use the wording exactly as given, or change it only if a server probe or §7 requires it. Record the final block in the
findings. Do not tune the wording on B1-tweak or C3 answers (see Sets).

**Read R2 carefully.** Global (non-accumulator) variables do persist across groups. A clean control that resets a
global in initGroup is correct, and a missing reset of a global *is* a real bug. R2 speaks only about the accumulator.
Check, in the hand check, that R2 does not make the model accept a missing global reset.

### Verifier prompt (arm V)

- **System:** the suite prompt + the rules block (if R passes).
- **User:** the original review request (requirements + code); then "A reviewer reported this finding:"; then the one
  [ERROR] line; then "Is this finding correct for this code and these requirements? Answer on the first line
  CONFIRMED, REJECTED, or WARNING (a real but data-dependent risk), then one sentence why."
- **Mode:** thinking off.
- **Parsing:** an unparseable verifier answer keeps the finding.

The compile route uses the `ctl_validate` MCP tool (localhost:8083), the same one `agent_harness.py` and `exec_score.py`
use. It is not a graph run, so no sandbox writes. The verdict is merged back into the answer: drop or downgrade the
finding, and recompute the VERDICT line as FAIL if any [ERROR] is left, else PASS.

## Sets

| set | records | role |
|---|---|---|
| **B1-tweak** | 146 mutants + 50 controls (`data/agent_harness/validate_mutants_tweak.jsonl`) | **primary**: nobody trained on it, and the rules were not written from its answers |
| B1 | 169 mutants + 50 controls (`validate_mutants.jsonl`) | secondary: the claim table above comes from its answers, so it is the development set |
| **C3: fresh clean controls** | the references of `data/agent_harness/pool_retry_tweak.jsonl` (190 LLM-rewritten tasks). Keep only references that pass on the server (`exec_score.py`) | false-alarm rate on unseen clean code. valprec2 never trained on these; retry1 did, but retry1 is not the model here. 81 origins are shared with B1-tweak; report C3 with and without them. |
| judge suite | validate off ×9 (excl. T18/T22) | WRONG share, and that the rules do not hurt multi-finding explanations |

Do not use `pool_retry.jsonl` as C3: its 160 prompts are the exec-RFT references valprec2 trained on.

## Gates

Report every number with n and a 95% CI, paired-bootstrap differences against arm 0, and the noise bands from
`CLAUDE.md`: recall ±0.05, false alarm ±0.08, one kind ±0.15.

| gate | pass |
|---|---|
| **B1-tweak format, false alarm** | below arm 0's 0.15 by more than the band, i.e. ≤ 0.07 |
| **B1 plain, false alarm** (arm R only) | ≤ 0.20 (arm 0: 0.31) |
| **C3 false alarm** | below arm 0 by more than the band |
| **defect recall**, B1-tweak and B1 | not below arm 0 by more than 0.05 |
| **recall per kind:** null_guard_removed, missing_lifecycle, DataIntersection mutants (by component) | not below arm 0 by more than 0.15 |
| **severity ok** (the parser's column) | not below arm 0 |
| **judge validate off ×9, WRONG share** | ≤ arm 0 |
| **cost** (E, V) | report extra requests, completion tokens and p50 / p95 latency per review against arm 0 and arm T |
| **generate** | only if the rules block is put into a system prompt that generate requests share: gap tests 3 × n10 both modes, within ±0.06 of valprec2 |

## Hand check

For 10 controls the rules or the verifier fixed and 10 mutants whose defect they suppressed, if there are any, quote
the before / after sentence and say which line or step did it. Include every case where R2 or R1 removed a true defect,
i.e. a mutant recall loss.

## Deliverables

1. **Code:**
   - `scripts/harness_measurement/gen_answers.py`: `--system-append FILE` (adds a block to the system prompt) and
     `--escalate` (the arm-E second pass, recorded per answer);
   - `scripts/validate_falsealarm/verify.py`: arm V, reading a gen_answers file and writing a file `score_validate.py`
     can score;
   - the C3 control builder.

   Configs and scripts in the repo. Results under `results/validate_falsealarm/`.
2. **`spec/validate_falsealarm_findings.md`** with:
   - the final rules block;
   - the C3 construction and server pass counts;
   - the gate table for every arm;
   - the per-rule ablation (R1–R4: which claims each line removes, and what it costs in recall);
   - the claim table by category for arms 0, R, E and V;
   - the cost table;
   - the hand check.
   - **Indications:**
     1. Which arm meets the false-alarm gate on B1-tweak and C3?
     2. Did any rule suppress true defects?
     3. What does E or V cost per review against plain thinking on?
     4. **Recommendation:** the deployment's validate call. Choose rules only, rules + escalate, rules + verify, or simply
        thinking on for validate, and write the system prompt text to ship.
3. A WORKLOG entry and a findings §3.x.

## Do not

- Train anything.
- Tune the rules block or the verifier prompt on B1-tweak or C3 answers. B1 is the development set.
- Put a fact in the rules block that is not in §7 or server-verified. When a claim is unclear, probe the server
  (`scripts/validate_precision/probe_facts.py`, sandbox MiscExamples under `suite_v5/`).
- Change rubrics, references, `ctl2-basics.md` or the B1 / B1-tweak sets.
- Touch `~/venv`, other users' processes or GPUs, or other sessions' uncommitted files. Use fresh output names.
