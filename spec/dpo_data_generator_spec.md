# Specification — CTL2 DPO Example Generator

**Component name (working):** `dpo-forge`
**Purpose:** Convert existing SFT examples into on-policy DPO preference pairs by sampling completions from the locally trained CTL2 model, validating them, and judging them with a stronger reference LLM that has the full CTL2 reference in context.
**Status:** Draft v0.1
**Owner:** DavidP

---

## 1. Goal and rationale

The current SFT eval-loss floor (~0.151–0.155) is data-limited; further SFT yields nothing. DPO is the lever, but the DPO dataset is small and its rewards margin has collapsed (~0.024 → ~0.007) as the set shrank. The cheapest path to a larger, *more informative* DPO set is to mine the model's own mistakes.

This utility takes SFT prompts (for which a ground-truth answer already exists), generates candidate completions from the **current trained checkpoint**, and turns the failures into `rejected` samples paired against a known-good `chosen`. Because the rejected samples come from the policy model itself, the resulting pairs are on-policy and target exactly the failure modes the model still exhibits.

### Non-goals
- Not a training harness (output feeds LLaMA Factory unchanged).
- Not a replacement for the deterministic CTL2 validator — it wraps it.
- Not an RLHF/online loop — this is offline batch generation.

---

## 2. High-level pipeline

```
SFT examples (prompt + reference answer)
        │
        ▼
[1] Prompt extraction & dedup
        │
        ▼
[2] Local generation  ── PyTorch / transformers, N samples/prompt
        │                 (exported safetensors checkpoint)
        ▼
[3] Tier-1 filter  ── deterministic CTL2 validator (compile/parse)
        │
        ▼
[4] Tier-2 judge   ── stronger LLM (OpenAI/Anthropic) + FULL CTL2 reference
        │
        ▼
[5] Pair construction & filtering
        │
        ▼
[6] Output writer  ── LLaMA Factory DPO format + run report
        │
        ▼
   W&B run log (counts, accept rate, cost, failure taxonomy)
```

Two-tier validation is deliberate: the deterministic validator is free and catches the bulk of obviously-broken candidates before any paid judge call is made. The judge only adjudicates candidates that *compile* but may be semantically wrong, plus borderline cases.

---

## 3. Input

### 3.1 SFT source format
Accept LLaMA Factory ShareGPT-style and Alpaca-style JSON/JSONL. The loader normalizes both into an internal record:

```python
@dataclass
class SourceExample:
    id: str                 # stable hash of prompt
    system: str | None      # system prompt if present
    prompt: str             # the "user" turn (the task)
    reference: str          # ground-truth assistant answer (chosen candidate)
    meta: dict              # passthrough: failure_mode tag, source file, etc.
```

Notes:
- Only single-turn task→answer examples are in scope for v0.1. Multi-turn rows are skipped with a warning (logged count).
- `reference` is required. Prompts without a known-good answer are out of scope here (they belong to a separate "hard prompt mining" tool).
- Dedup on normalized `prompt` (strip whitespace, collapse). Keep first occurrence.

### 3.2 Selection
- Optional filter by `meta.failure_mode` so a run can target a specific weakness (e.g. only `rollup_lifecycle` prompts).
- Optional `--limit N` and `--shuffle --seed S` for sampling subsets.

### 3.3 Prompt ingestion & normalization

Turning a raw SFT example into structured inputs is its own step — in practice the
example embeds everything in the prompt (the Join example names the component type in
prose, carries three `<Metadata>` blocks as CloverDX XML, and states port roles). The
loader must extract, not guess:

- **Component-type routing.** Classify the prompt to one of the supported skeleton
  types (REFORMAT, ROLLUP, EXT_FILTER, DATA_GENERATOR, EXT_HASH_JOIN, PARTITION,
  NORMALIZER, DENORMALIZER) from the prose ("a Join component (like ExtHashJoin)",
  "rollup", "Reformat/Map"). Attach a confidence; below threshold or ambiguous →
  route to **static-validate-only** (Tier-1 compile check, no execution oracle) rather
  than forcing a wrong skeleton.
- **Unsupported / mismatched components.** If the example targets a component with no
  skeleton (Dedup, DataIntersection, custom Java, a multi-output Reformat whose port
  count differs from the skeleton), do not force-fit — mark `oracle=static_only` or
  skip, and log. Port count and roles must match the skeleton or the oracle is invalid.
- **Lossless metadata transcription.** Extract each `<Metadata>`/`<Record>` block
  verbatim into the `.fmt` bundle preserving **every** field attribute — `decimal`
  length/scale, date/datetime `format`, `nullable`, `default`, delimiters, record type.
  The prompt's metadata *ids* are irrelevant (CTL resolves by port index + field name);
  only the `<Record>` body matters. This is mechanical parsing, not an LLM task.
- **CTL normalization.** Both the reference answer and every model candidate arrive
  wrapped in markdown fences (```` ```ctl ````) and may include prose. Before writing
  any `transform.ctl`: strip fences, drop non-CTL prose, and guarantee the first line is
  `//#CTL2` (CloverDX requires the header). A correct candidate that keeps its fences
  otherwise fails to compile — a false L1.
- **System prompt** is taken from the example itself (the `system` turn), not a static
  config, so candidate generation matches training exactly.

---

## 4. Stage 2 — Local generation (PyTorch / transformers)

Load the exported checkpoint directly with `transformers`; no external serving layer.

### 4.1 Loading

```python
from transformers import AutoModelForCausalLM, AutoTokenizer
import torch

tok = AutoTokenizer.from_pretrained(CKPT_DIR)
model = AutoModelForCausalLM.from_pretrained(
    CKPT_DIR,
    torch_dtype=torch.bfloat16,
    device_map="auto",            # single Blackwell GPU is plenty for a 9B
    attn_implementation="flash_attention_2",  # fall back to "sdpa" if FA2 unavailable on the Blackwell build
)
model.eval()
```

- Checkpoint is the merged/exported safetensors dir (post-LoRA-merge), so this is a normal dense load — no PEFT adapter handling required. If a run wants to test an unmerged adapter, support an optional `--adapter-dir` that applies `PeftModel.from_pretrained` on top.
- Chat template comes from the tokenizer (`tok.apply_chat_template`). The system prompt must match what was used in SFT/serving — make it a config field, do not hardcode.

### 4.2 Sampling

Generate `N` candidates per prompt (default `N=4`) with temperature sampling for diversity. Diversity is the point — identical greedy completions give no contrast.

```python
gen_cfg = dict(
    do_sample=True,
    temperature=0.8,
    top_p=0.95,
    max_new_tokens=1024,
    num_return_sequences=N,
    pad_token_id=tok.eos_token_id,
)
```

- **Batching:** batch across prompts (left-padding) for throughput, not just `num_return_sequences`. Target a configurable token budget per batch to avoid OOM. A simple length-bucketed batcher is sufficient.
- **Sampling for contrast (DPO-specific).** The goal is *informative wrong* candidates, not just diversity. Prefer a temperature spread (one greedy + several at 0.7–1.0) over a single temperature — this surfaces both the confident-but-wrong mode and tail errors. **Dedup candidates by normalized text** before any validation/judge call; never pay to judge identical outputs. If all N candidates pass, the prompt yields no signal — optionally resample once with higher N/temperature before discarding. Optionally harvest extra failures from an earlier (pre-DPO) checkpoint to enrich the rejected pool.
- Decode, strip the prompt, and trim at the first stop sequence / EOS. Apply the §3.3 CTL normalization (strip fences, ensure `//#CTL2`) to each candidate before it leaves this stage.
- Record per-candidate metadata: sampling params, token count, generation latency.
- Determinism: log the global seed; note that exact reproducibility across PyTorch/CUDA versions is best-effort, not guaranteed.

### 4.3 Output of this stage

```python
@dataclass
class Candidate:
    source_id: str
    index: int              # 0..N-1
    text: str
    gen_meta: dict
```

---

## 5. Stage 3 — Tier-1 deterministic validator

Wrap the existing CTL2 validator (the `DataRecordMetadataXMLReaderWriter` + `validate` path used by the `ctl_assistant` / `CTLAuthorAgentTool` suite). This stage is purely mechanical: does the candidate parse/compile against the supplied port metadata?

```python
@dataclass
class ValidationResult:
    ok: bool
    errors: list[ValidationError]   # severity, message, line/col if available
    raw: str                        # raw validator output for the report
```

Decision logic:
- `ok == False` → candidate is a **hard reject** (compile failure). No judge call needed. Tag with the validator's error category for the failure taxonomy.
- `ok == True` → candidate is *syntactically* valid but may be semantically wrong → forward to the judge.

The validator needs the same record metadata / port context the original task assumed. Carry that context in `SourceExample.meta` (input/output field schemas) so validation is faithful to the task. If a prompt has no associated metadata, fall back to syntax-only validation and flag it in the report.

---

## 6. Stage 4 — Tier-2 LLM judge

A stronger model (configurable: an OpenAI or Anthropic model) adjudicates semantic correctness, **with the full CTL2 reference in context**. This is the part the local model cannot do reliably itself.

### 6.1 Judge inputs
- The original task (`prompt`, system context).
- The **full CTL2 reference** (the authoritative `cloverdx://reference/ctl2` content), injected verbatim into the judge's context/system block. Cache it; it's the same every call.
- The candidate completion(s).
- The ground-truth `reference` answer (optional — see modes below).

### 6.2 Judge modes
Support two, selectable per run:

**(a) Pointwise grade (default).** Judge each compiling candidate independently: is it a correct, idiomatic CTL2 solution to the task? Returns a verdict and structured reasons. The ground-truth `reference` is *not* shown, so the judge isn't biased into demanding a verbatim match — many tasks have multiple valid solutions.

**(b) Pairwise preference.** Judge is shown `reference` (A) vs candidate (B) and asked which better solves the task and why. Useful when you want the judge, not the dataset's fixed answer, to pick `chosen`.

### 6.3 Structured output contract
Force JSON (no prose), parsed defensively:

```json
{
  "verdict": "correct | incorrect | partially_correct",
  "confidence": 0.0,
  "failure_modes": ["date_format_token", "rollup_lifecycle"],
  "explanation": "<= 60 words, concrete",
  "minimal_fix": "optional: shortest change that would make it correct"
}
```

- `failure_modes` must come from a **fixed enum** (your existing CTL2 failure taxonomy) so the report aggregates cleanly. Free-text modes are coerced to `other` and logged.
- Reject/retry on malformed JSON (max 2 retries, then drop candidate and count it).
- Temperature 0 for the judge.

### 6.4 Judge reliability guards
- Self-consistency option: call the judge `k` times (default 1; 3 for high-stakes runs) and take majority verdict; log disagreement rate.
- Spot-check sink: write a configurable fraction (e.g. 2%) of judged candidates to a `review/` file for manual audit. Judge quality is the single biggest risk to dataset quality — make auditing trivial.

---

## 7. Stage 5 — Pair construction and filtering

For each `source_id`, you now have: one `reference` (ground truth) + up to `N` graded candidates.

### 7.1 Labeling
- A candidate is a **valid rejected** if: Tier-1 `ok == False`, OR judge verdict ∈ {`incorrect`, `partially_correct`} with `confidence ≥ τ` (default τ=0.6).
- `chosen` = the `reference` answer (mode a), or the judge-preferred option (mode b).

### 7.2 Pairing strategy (configurable)
- `best_vs_worst` (default): one pair per prompt — `chosen` vs the *most informative* rejected. "Most informative" = the highest-confidence incorrect candidate that still **compiles** (compiling-but-wrong is a harder, more useful contrast than garbage that fails to parse). If no compiling-wrong candidate exists, fall back to a compile-fail rejected.
- `all_pairs`: emit `chosen` paired with every distinct rejected (dedup rejected by normalized text). Inflates dataset but adds gradient diversity. Cap per prompt with `--max-pairs-per-prompt`.

### 7.3 Discard rules (no training signal)
- **All candidates correct** → discard prompt (model already solved it). Count toward "model already competent."
- **All candidates fail to compile / all identical** → keep at most one pair, but flag; a prompt the model *never* gets even close on may be too hard and add noise.
- **chosen ≈ rejected** (normalized text near-identical) → drop the pair.
- **Correct via a different valid output** → a candidate that executes to a *different* output than the reference but is ruled correct (judge, or an alternate-accepted oracle) carries no contrast — **drop it from pairing**, never label it `rejected`. When this path is hit the judge must be given both executed outputs plus the task; log the rate, since a high rate suggests the oracle diff is too strict (see §18.5.1).
- Length-ratio guard: drop pairs where rejected is trivially short/empty (degenerate generation), to avoid teaching "shorter = worse."

---

## 8. Stage 6 — Output

### 8.1 DPO file (LLaMA Factory)
Emit ShareGPT-style preference JSON:

```json
{
  "conversations": [
    {"from": "system", "value": "<system prompt used in training>"},
    {"from": "human", "value": "<task prompt>"}
  ],
  "chosen":   {"from": "gpt", "value": "<reference / preferred>"},
  "rejected": {"from": "gpt", "value": "<model failure>"}
}
```

- Make the exact schema a pluggable writer; LLaMA Factory's `dataset_info.json` expectations change between versions, so keep the key names (`conversations`/`chosen`/`rejected` vs `prompt`/`chosen`/`rejected`) configurable.
- Also emit the matching `dataset_info.json` snippet so the file drops straight into a training run.

### 8.2 Sidecar provenance file
For every emitted pair, write a parallel JSONL record (not used for training) capturing: `source_id`, sampling params, validator output, **execution evidence** (`exec_level_reached`, tracking counts, log excerpt, output diff — see §18.6), judge verdict + reasons + failure_modes, pairing strategy, and the **oracle bundle version** (skeleton revision + generator/setup-bundle hash + `server_deployment`). The bundle version matters because this feeds an iterative SFT+DPO loop: an oracle that drifts between rounds makes pair sets incomparable. This makes the dataset auditable and lets you slice DPO results by failure mode later.

### 8.3 Run report (markdown + W&B)
Log to W&B (same project/entity as training) as a run tagged `dpo-forge`:
- Counts: prompts in, candidates generated, Tier-1 reject rate, judge verdict distribution, pairs emitted, prompts discarded (by reason).
- **Failure-mode histogram** — the most useful output for deciding what to target next.
- Judge cost (tokens × price) and wall-clock.
- Self-consistency disagreement rate (if k>1).

### 8.4 Dataset composition control (not just reporting)

The whole motivation is the collapsed rewards margin, and an unbalanced output set won't
fix it broadly. Treat composition as an active control, not a post-hoc chart:

- **Per-component and per-failure-mode caps / targets.** Cap how many pairs any single
  component type or failure mode contributes (e.g. no mode > 25% of the set) so DPO
  doesn't overfit the most common error. Optionally drive toward a target distribution.
- **Cap easy L1 (compile-fail) rejecteds.** L1 contrasts are weak; if they dominate, the
  model learns "produce parseable output" rather than "produce correct output". Set a
  maximum L1 share (e.g. ≤20%) and prefer L3_mismatch > L2_fail rejecteds (§18.6).
- **Report the realized mix** — per-component counts, failure-mode histogram, and the
  L1/L2/L3 ratio — and warn or fail the run if the mix violates the configured caps.

---

## 9. Configuration

Single YAML, env-overridable. Sketch:

```yaml
input:
  sft_files: ["data/sft/*.jsonl"]
  failure_mode_filter: null        # or e.g. "rollup_lifecycle"
  limit: null
  shuffle: {enabled: true, seed: 42}

model:
  checkpoint_dir: "/models/qwen3.5-9b-ctl-merged"
  adapter_dir: null
  dtype: "bfloat16"
  attn_impl: "flash_attention_2"
  system_prompt_file: "prompts/ctl_system.txt"

generation:
  n_samples: 4
  temperatures: [0.0, 0.7, 0.9, 1.0]   # spread for contrast; length may differ from n_samples
  top_p: 0.95
  max_new_tokens: 1024
  batch_token_budget: 16384
  seed: 42
  dedup_candidates: true               # drop identical normalized outputs before judging
  resample_if_all_pass: true           # one extra higher-temp round before discarding a no-signal prompt
  harvest_checkpoint_dir: null         # optional earlier (pre-DPO) checkpoint to mine extra failures

validator:
  endpoint: "<how the CTL2 validator is invoked>"   # in-proc call or local service
  require_metadata: true

judge:
  provider: "anthropic"            # or "openai"
  model: "<judge model id>"
  mode: "pointwise"                # pointwise | pairwise
  reference_doc: "ctl2_reference.md"   # full CTL2 reference, cached
  temperature: 0.0
  self_consistency_k: 1
  confidence_threshold: 0.6
  max_json_retries: 2
  audit_sample_rate: 0.02

pairing:
  strategy: "best_vs_worst"        # best_vs_worst | all_pairs
  max_pairs_per_prompt: 3
  drop_if_all_correct: true
  drop_correct_via_alt_output: true   # candidate correct with a different output → no contrast, drop

balance:
  max_share_per_failure_mode: 0.25
  max_share_per_component: 0.40
  max_share_l1_rejected: 0.20
  enforce: "warn"                  # warn | fail  when caps are violated

output:
  dpo_file: "data/dpo/forged.jsonl"
  provenance_file: "data/dpo/forged.provenance.jsonl"
  schema: "sharegpt"
  wandb: {enabled: true, project: "llamafactory", entity: "david-pavlis-cloverdx"}
```

---

## 10. CLI

```
dpo-forge run --config configs/forge.yaml
dpo-forge run --config ... --limit 200 --judge.mode pairwise   # overrides
dpo-forge audit data/dpo/forged.provenance.jsonl               # open the review sink
dpo-forge stats data/dpo/forged.provenance.jsonl               # print failure-mode histogram
```

Exit non-zero if accept rate is below a configurable floor (catches a broken checkpoint or judge early).

---

## 11. Error handling & edge cases

| Case | Behavior |
|------|----------|
| Multi-turn SFT row | Skip, count, warn |
| Missing reference answer | Skip (out of scope for v0.1) |
| Generation OOM | Halve batch, retry once; then skip prompt, log |
| Validator throws / times out | Treat candidate as `unvalidated`; route to judge syntax-aware; flag |
| Judge malformed JSON | Retry ≤2, then drop candidate, count |
| Judge API error / rate limit | Exponential backoff; checkpoint progress so a run resumes |
| All candidates correct | Discard prompt (logged) |
| Empty / truncated generation | Drop candidate (length guard) |

**Resumability:** persist per-prompt progress (e.g. a `.state` file or sqlite) so a long run survives interruption and avoids re-paying judge calls. This matters at scale.

---

## 12. Cost & throughput notes

- Tier-1 (validator) is free and removes most candidates before any paid call — keep it first.
- Judge cost dominates. Levers: only judge compiling candidates; cache the CTL2 reference; batch where the provider allows; keep `self_consistency_k=1` for routine runs.
- With `N=4` and a healthy SFT pool, expect the judge to see roughly (compiling fraction × 4 × prompts) candidates. Estimate and print projected cost before a full run (`--dry-run` does generation + Tier-1 only, then extrapolates judge cost).

---

## 13. Quality risks (ranked)

1. **Judge is wrong.** A bad judge silently poisons the dataset. Mitigate: full reference in context, structured output, audit sink, optional self-consistency, periodic manual spot-check.
2. **Rejected too easy.** Compile-failures are weak contrasts. Mitigate: prefer compiling-but-wrong as rejected (`best_vs_worst`).
3. **Degenerate rejected** (empty/short) teaching length bias. Mitigate: length-ratio guard.
4. **Distribution skew** — over-mining one failure mode. Mitigate: composition caps (§8.4).
5. **Stale checkpoint** — generating from the wrong export. Mitigate: log checkpoint hash + path in the W&B run.
6. **False mismatch from naive diffing** — unordered output (hash join), decimal scale, or null serialization compared as text. Mitigate: component-aware diff (§18.5.1). This produces confidently-wrong `rejected` labels, so in practice it ranks near the top.
7. **Silently-wrong oracle setup** — setup LLM mis-infers `JOIN_KEY`/`JOIN_TYPE`/`GROUP_KEY`, so a runnable reference produces the wrong golden. Mitigate: the oracle sanity assertion (§18.4) — the reference must exhibit the task's stated edge-case behavior before any candidate is judged.

---

## 14. Open decisions

- Judge mode default: pointwise (multiple valid CTL2 solutions exist) vs pairwise (lets judge override the fixed reference). Leaning pointwise.
- Whether to also keep *correct* model candidates as alternative `chosen` answers (would let you build pairs where ground truth isn't the only acceptable solution). Out of scope v0.1, worth revisiting.
- How metadata/port context is threaded to the validator for prompts that lack it — partially syntax-only for now.
- Single merged checkpoint only, or support comparing two checkpoints' failures in one run.

---

## 15. Milestones

1. Loader + normalizer for SFT formats; dedup.
2. transformers generation with batching + sampling.
3. Validator wrapper (Tier-1) + failure tagging.
4. Judge client (provider-agnostic), reference injection, structured parse.
5. Pair construction + filters + writers (DPO + provenance).
6. W&B reporting + `stats`/`audit` subcommands.
7. `--dry-run` cost estimation + resumability.
