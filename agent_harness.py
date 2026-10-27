#!/home/pavlisd/venv/bin/python
"""agent_harness — the agentic generate loop, scored by execution.

What an agent with the CloverDX MCP sees: prompt -> model -> ctl_validate -> graph run -> error text fed back -> retry.
The verdict is whether the graph produced exactly the expected rows, never a judge. Adapted from mut_validate.py (the
loop and the --tweak prompt rewriting) and data/suite_v5/exec_retry.py (the feedback turn and the execution scorer).

Three subcommands:

  pool     build a task pool: prompts with a fixture-backed acceptance graph.
             --suite               the 11 suite-v5 gap tests (data/suite_v5/run_graphs manifests + generate_rw.json)
             --corpus SFT FIXTURES corpus SFT records joined to the authors' fixture cases by id (several pairs allowed);
                                   the fixture's own reference is run first and the task is kept only if it passes
             --tweak SFT [SFT ...] the generate prompts of these files rewritten by the tweak LLM into a new domain
                                   (mut_validate --tweak; --seed picks the domains, --tweak-n caps the count), with a
                                   fixture and reference written by the same LLM; kept only if the reference produces the
                                   LLM's own expected rows (two derivations must agree)
  run      run the loop on a pool: --model on a vLLM server, both thinking modes, --runs samples per task, --rounds
           feedback rounds. Results are appended per (task, run, mode) and a rerun resumes.
  summary  pass@1 / pass after each round, final status mix, compile-error causes, by mode, source and component.

    python agent_harness.py pool --suite --corpus ctl_lora_training/sft_training_data/CTL_LoRA_scd2_sft.json \
        ctl_lora_training/sft_training_data/logs/scd2_runtime/round2/fixtures.json --out data/agent_harness/pool1.jsonl
    python agent_harness.py run data/agent_harness/pool1.jsonl --model c13c_r015 --url http://127.0.0.1:3012 \
        --modes on off --runs 3 --rounds 2 --out results/agent_harness/c13c_pool1.jsonl
    python agent_harness.py summary results/agent_harness/c13c_pool1.jsonl

Needs the CloverDX server on :8083 (sandbox MiscExamples, everything under suite_v5/agent/) and, for run, the model on
vLLM (--load-adapter PATH hot-loads a LoRA adapter under the --model name first).
"""
import argparse, asyncio, collections, hashlib, json, random, re, sys, time, xml.etree.ElementTree as E
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT / "data/suite_v5"), str(ROOT / "data/suite_v5/round2")]
import graph_harness as H      # noqa: E402
import exec_score as X         # noqa: E402

H.R = X.R = H.D / "agent_harness" / "graphs"      # under data/suite_v5 so the harness's relative paths work
H.R.mkdir(parents=True, exist_ok=True)
H.ANCHOR.setdefault("EXT_HASH_JOIN", "transform")
SANDBOX = X.SANDBOX
PREFIX = "suite_v5/agent/"
MCP_URL = "http://localhost:8083/clover/mcp/mcp"
SYSTEM = ("You are a CloverDX ETL expert specializing in transformation graphs, components, and CTL2. CTL and CTL2 mean "
          "the same language.\nHelp users write, debug, and explain CTL2 code and related concepts. Provide working code, "
          "explanation, or both as needed.\nPrefer correct, practical, minimal solutions.")
FEEDBACK = ("I ran this in a CloverDX graph and it failed:\n\n{error}\n\n"
            "Fix the code and give the complete corrected version.")
ROWS_FEEDBACK = ("I ran this in a CloverDX graph. It finished, but the output is wrong:\n\n{error}\n\n"
                 "Fix the code and give the complete corrected version.")
SAMPLING = dict(temperature=0.4, top_p=0.95, top_k=20)
TOOL_TYPE = {"REFORMAT": "reformat", "ROLLUP": "rollup", "NORMALIZER": "normalizer", "DENORMALIZER": "denormalizer",
             "PARTITION": "partition", "DATA_INTERSECTION": "joiner", "EXT_MERGE_JOIN": "joiner", "EXT_HASH_JOIN": "joiner"}
# the compile-failure causes of findings §3.29, matched on the server's message
CAUSES = [("out_port", r"Cannot write to output port|output port '[12]'"),
          ("unknown_field", r"Field '[^']+' does not exist|does not exist in record"),
          ("regex_negation", r"Syntax error on token '!'|Operator '!' is not defined for type 'string'"),
          ("reserved_time_unit", r"Syntax error on token '(integer|long|string|decimal|number|date|boolean)'"),
          ("unknown_function", r"Function '[^']+' is not declared"),
          ("wrong_arguments", r"is not applicable for the arguments"),
          ("undeclared_variable", r"Variable '[^']+' is not declared"),
          ("invalid_escape", r"Invalid escape sequence"),
          ("ternary_constant", r"Syntax error on token '\?'"),
          ("type_mismatch", r"Type mismatch|cannot convert|Cannot convert"),
          ("dictionary", r"[Dd]ictionary")]


NO_CONTEXT_RE = re.compile(r"resolve lookup table|Unknown variable type or metadata name|resolve sequence|dictionary", re.I)


def cause_of(msg):
    for name, pat in CAUSES:
        if re.search(pat, msg or ""):
            return name
    return "other"


# ----------------------------------------------------------------------------------------------------------- pool
def rec_xml(meta):
    """Corpus metadata dict -> the <Record> XML graph_harness expects."""
    name = re.sub(r"\W", "_", meta["name"]) or "rec"       # LLM-written fixtures use names like "Middle result"
    out = [f'<Record name="{name}" type="delimited" fieldDelimiter="|" recordDelimiter="\\n" nullValue="__NULL__">']
    for f in meta["fields"]:
        a = f'name="{f["name"]}" type="{f["type"]}" nullable="{str(f.get("nullable", True)).lower()}"'
        for k in ("length", "scale"):
            if f.get(k) is not None:
                a += f' {k}="{f[k]}"'
        if f["type"] == "date":
            a += ' format="yyyy-MM-dd HH:mm:ss" timeZone="UTC"'
        out.append(f"  <Field {a}/>")
    out.append("</Record>")
    return "\n".join(out)


def fix_rows(rows, meta):
    """Fill omitted fields with null; epoch-int dates -> text."""
    names = [f["name"] for f in meta["fields"]]
    dates = {f["name"] for f in meta["fields"] if f["type"] == "date"}
    fixed = []
    for r in rows:
        r = {n: r.get(n) for n in names}
        for d in dates:
            if isinstance(r[d], int):
                r[d] = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(r[d] / 1000))
        fixed.append(r)
    return fixed


def case_to_spec(c):
    """A corpus fixture case (scd2 / syntax / rollup_acc / normalizer format) -> a graph_harness spec."""
    comp = c["component"]
    ins, outs = c["input_metadata"], list(c["output_metadata"])
    exp = c["expected"]
    key = lambda i: exp.get(f"OUTPUT_{i}", exp.get(str(i), []))  # noqa: E731
    if comp == "DATA_INTERSECTION":          # the corpus case lists only the matched output; the graph has A-only, matched, B-only
        outs = [ins[0], outs[0], ins[1]]
    expected = {str(i): fix_rows(key(i), m) for i, m in enumerate(outs)}
    spec = dict(component=comp, inputMetadata=[rec_xml(m) for m in ins], outputMetadata=[rec_xml(m) for m in outs],
                settings=dict(c.get("attributes") or {}), resources={},
                fixture=dict(inputs=[fix_rows(rows, m) for rows, m in zip(c["inputs"], ins)], expected=expected))
    if c.get("accumulator_metadata"):
        spec["accumulatorMetadata"] = rec_xml(c["accumulator_metadata"])
    return spec


def build_manifest(label, spec, reference, description="agent harness task"):
    test = dict(test_id=label, reference=reference, rubric=dict(description=description))
    return H.build(test, spec)


VALIDATE_RE = re.compile(r"\b(Validate|Review|Audit) (this|the whole|the following|the)\b"
                         r"|\bexplain the\b(?![^.]*\b(correction|change|fix))|\bISSUES:|\bVERDICT\b", re.I | re.M)


def task_kind(prompt):
    """generate | fix | validate (validate and explanation answers are prose, not code, so the pool leaves them out)."""
    prose = re.sub(r"```.*?```", "", prompt, flags=re.S)
    if VALIDATE_RE.search(prose):
        return "validate"
    return "fix" if "```" in prompt or re.search(r"^\s*(Fix|Repair|Correct)\b", prompt) else "generate"


def load_sft(path):
    recs = json.loads(Path(path).read_text())
    out = {}
    for r in recs:
        msgs = r.get("messages") or []
        user = next((m["content"] for m in msgs if m["role"] == "user"), None)
        if user and r.get("id"):
            out[r["id"]] = user
    return out


async def pool_cmd(a):
    tasks = []
    if a.suite:
        rw = {t["test_id"]: t for t in json.loads((ROOT / "data/suite_v5/generate_rw.json").read_text())}
        for tid, ms in sorted(X.MANIFESTS.items()):
            t = rw[tid]
            tasks.append(dict(id=f"suite_{tid}", source="suite_v5", component=t["component"], task="generate",
                              prompt=t["user_message"], system=t.get("system_prompt") or SYSTEM, manifests=ms))
    corpus = list(zip(a.corpus[0::2], a.corpus[1::2])) if a.corpus else []
    rejected = collections.Counter()
    async with X.streamablehttp_client(MCP_URL, timeout=180) as (rd, wr, _):
        async with X.ClientSession(rd, wr) as s:
            await s.initialize()
            await s.call_tool("task_workflow_get", {"task": "validate_and_run"})

            async def call(n, args):
                guard(n, args)
                return X.payload(await s.call_tool(n, args))

            for sft_path, fx_path in corpus:
                prompts = load_sft(sft_path)
                cases = json.loads(Path(fx_path).read_text())
                src = Path(fx_path).parts[-3] if Path(fx_path).parent.name in ("round2", "r1_3", "r4_6", "r7_8") else Path(fx_path).parent.name
                for c in cases:
                    cid = c.get("id")
                    if cid not in prompts or not c.get("code") or c.get("code_provenance") == "user_candidate":
                        rejected["no_prompt_or_code"] += 1
                        continue
                    if task_kind(prompts[cid]) == "validate":
                        rejected["validate_prompt"] += 1
                        continue
                    if c.get("expected_outcome") not in (None, "match") or c.get("expected_runtime") not in (None, "PASS", "FINISHED_OK"):
                        rejected["expected_failure_case"] += 1
                        continue
                    label = f"AH_{cid}"
                    try:
                        spec = case_to_spec(c)
                        m = build_manifest(label, spec, c["code"])
                    except Exception as exc:  # noqa: BLE001
                        rejected[f"build_error"] += 1
                        print("  build error", cid, str(exc)[:160], flush=True)
                        continue
                    st, det = await verify(call, m, c["code"])
                    if st != "pass":
                        rejected[f"reference_{st}"] += 1
                        print("  reference fails", cid, st, det[:160], flush=True)
                        continue
                    tasks.append(dict(id=f"{src}_{cid}", source=src, component=c["component"], task=task_kind(prompts[cid]),
                                      prompt=prompts[cid], system=SYSTEM, manifests=[m]))
                    print("  kept", cid, flush=True)
            if a.tweak:
                tasks += await tweak_pool(call, a, rejected)
    out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as fh:
        for t in tasks:
            fh.write(json.dumps(t, ensure_ascii=False) + "\n")
    report = dict(tasks=len(tasks), by_source=collections.Counter(t["source"] for t in tasks),
                  by_component=collections.Counter(t["component"] for t in tasks),
                  by_task=collections.Counter(t["task"] for t in tasks), by_set=collections.Counter(t.get("set") for t in tasks if t.get("set")),
                  rejected=rejected)
    out.with_suffix(".report.json").write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps(report, indent=1))


# ----------------------------------------------------------------------------------------------- tweak (LLM-made tasks)
# The ROLLUP and reserved-word rules were added after seed 101 (spec/harness_measurement_findings.md): every Rollup
# reference failed to compile ($acc.x, missing lifecycle functions, `record`/`input`/`trace` as names, server-verified).
FIXTURE_SYSTEM = """\
You are a CloverDX / CTL2 test author. You get a CTL2 code-generation task. Write an acceptance fixture for it and a
reference solution, as ONE JSON object and nothing else:

{
  "component": "REFORMAT" | "ROLLUP" | "NORMALIZER" | "DENORMALIZER" | "PARTITION" | "DATA_INTERSECTION" | "EXT_MERGE_JOIN" | "EXT_HASH_JOIN",
  "input_metadata": [{"name": "...", "fields": [{"name": "...", "type": "string|integer|long|decimal|number|boolean|date", "nullable": true|false, "length": 18, "scale": 2}]}],
  "output_metadata": [ ...same shape, one entry per output port... ],
  "accumulator_metadata": { ...same shape... } | null,
  "attributes": { "groupKeyFields": "a;b" | "joinKey": "$k=$k" | ... } ,
  "inputs": [ [ {row}, ... ] , ... one list per input port ],
  "expected": { "OUTPUT_0": [ {row}, ... ], ... },
  "reference_code": "//#CTL2\\n..."
}

Rules:
- The metadata must be exactly the metadata the task states (same names, types, nullability, order).
- 8 to 15 input rows per port, covering every rule and edge in the task (nulls where a field is nullable, boundary
  values, at least one group with one record for grouping components). Inputs must already be sorted by the group or
  join key where the component requires it.
- Work out the expected rows BY HAND from the task's rules, in output order. Do not derive them by mentally running your
  reference code; the two are compared and must agree.
- Dates are strings "yyyy-MM-dd HH:mm:ss" (UTC). Decimals are strings with the field's scale ("12.50"). Nulls are null.
- For DATA_INTERSECTION, output_metadata has ONE entry (the matched output) and "expected" has OUTPUT_0 (A-only rows,
  input-0 metadata), OUTPUT_1 (matched rows) and OUTPUT_2 (B-only rows, input-1 metadata).
- The reference solution must be complete, correct CTL2 for that component, using only the declared fields.
- ROLLUP references define all five functions, with the accumulator record as a typed parameter (the name is the
  accumulator_metadata name; fields are read and written as acc.field, never $acc.field or $out.0 in updateGroup):
    function void initGroup(AccName acc) { ... }
    function boolean updateGroup(AccName acc) { ...; return false; }
    function boolean finishGroup(AccName acc) { ...; return true; }
    function integer updateTransform(integer counter, AccName acc) { return SKIP; }
    function integer transform(integer counter, AccName acc) { if (counter != 0) return SKIP; $out.0.x = ...; return ALL; }
- Do not use record, input, line, trace, or a date unit (day, month, year, hour, ...) as a variable or
  parameter name; they are reserved in CTL2.
"""


def parse_json_object(raw):
    raw = raw.split("</think>")[-1]
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.S) or re.search(r"(\{.*\})", raw, re.S)
    return json.loads(m.group(1)) if m else None


TWEAK_COMPONENT = [(r"\bDataIntersection\b|\bdata\s*intersection\b", "DATA_INTERSECTION"),
                   (r"\bExtHashJoin\b|\bhash\s*join\b", "EXT_HASH_JOIN"), (r"\bExtMergeJoin\b|\bmerge\s*join\b", "EXT_MERGE_JOIN")]


def tweak_component(prompt):
    """The component named to the tweak LLM: review_judge's bucket, but the joiners by name (its bucket is just JOIN)."""
    from dpo_forge.review_judge import infer_component_type_from_prompt
    for pat, name in TWEAK_COMPONENT:
        if re.search(pat, prompt, re.I):
            return name
    return infer_component_type_from_prompt(prompt)


async def tweak_pool(call, a, rejected):
    """mut_validate --tweak: rewrite SFT prompts into new domains; then let the same LLM write fixture + reference.

    Every generate prompt of the --tweak SFT files (shuffled by --seed, the first --tweak-n if given) is rewritten once,
    --tweak-concurrency at a time. Each rejection is appended to <out>.rejected.jsonl with its reason and the raw
    fixture, so the rejection causes can be read."""
    import yaml
    sys.path.insert(0, str(ROOT))
    from dpo_forge.review_judge import ReviewJudgeClient, pick_business_domain
    cfg = yaml.safe_load(Path(a.tweak_config).read_text())
    llm = ReviewJudgeClient(cfg["tweak_llm"], log_file=None)
    # the fixture answer (3 ports x up to 15 rows + reference) and its reasoning do not fit tweak_llm's 8k budget
    fixture_llm = ReviewJudgeClient(dict(cfg["tweak_llm"], max_completion_tokens=a.fixture_tokens), log_file=None)
    items = []
    for sft_path in a.tweak:
        prompts = load_sft(sft_path)
        items += [(Path(sft_path).stem, i, prompts[i]) for i in sorted(prompts) if task_kind(prompts[i]) == "generate"]
    random.Random(a.seed).shuffle(items)
    items = items[:a.tweak_n] if a.tweak_n else items
    rej_path = Path(a.out).with_suffix(".rejected.jsonl")
    rej_path.unlink(missing_ok=True)
    sem, lock = asyncio.Semaphore(a.tweak_concurrency), asyncio.Lock()
    tasks = []

    async def locked(n, args):
        async with lock:
            return await call(n, args)

    async def one(sft, i, prompt):
        async with sem:
            comp = tweak_component(prompt)
            domain = pick_business_domain(random.Random(i + str(a.seed)))
            rec = dict(set=sft, origin=i, seed=a.seed, component_hint=comp, domain=domain)

            def reject(reason, detail="", **kw):
                rejected[f"tweak_{reason}"] += 1
                rec.update(reason=reason, detail=detail[:3000], **kw)
                with open(rej_path, "a") as fh:
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                print(f"  tweak {reason:24s} {i} {detail[:140]}", flush=True)

            try:
                new_prompt = await asyncio.to_thread(llm.tweak, prompt, comp, business_domain=domain)
            except Exception as exc:  # noqa: BLE001
                return reject("llm_error", str(exc))
            if not new_prompt or len(new_prompt) < 100:
                return reject("no_prompt", new_prompt or "")
            try:
                raw = await asyncio.to_thread(fixture_llm._call, FIXTURE_SYSTEM, "## Task\n\n" + new_prompt, "tweak")
            except Exception as exc:  # noqa: BLE001
                return reject("llm_error", str(exc), prompt=new_prompt)
            try:
                c = parse_json_object(raw)
            except Exception:  # noqa: BLE001
                c = None
            if not (c and c.get("reference_code") and c.get("inputs") and c.get("expected")):
                return reject("no_json", raw[-1500:], prompt=new_prompt)
            c["code"] = c.pop("reference_code")
            c["component"] = str(c.get("component", "")).upper()
            label = f"AH_tweak_{hashlib.sha256(new_prompt.encode()).hexdigest()[:10]}"
            try:
                m = build_manifest(label, case_to_spec(c), c["code"])
            except Exception as exc:  # noqa: BLE001
                return reject("build_error", f"{type(exc).__name__}: {exc}", prompt=new_prompt, fixture=c)
            try:
                st, det = await verify(locked, m, c["code"])
            except Exception as exc:  # noqa: BLE001
                st, det = "harness_error", str(exc)
            if st != "pass":
                return reject(f"reference_{st}", det, prompt=new_prompt, fixture=c)
            tasks.append(dict(id=label[3:], source="tweak", set=sft, origin=i, seed=a.seed, domain=domain,
                              component=c["component"], task="generate", prompt=new_prompt, system=SYSTEM, manifests=[m]))
            rejected["tweak_kept"] += 1
            print(f"  tweak kept {i} -> {label} ({c['component']})", flush=True)

    await asyncio.gather(*(one(*x) for x in items))
    return tasks


# -------------------------------------------------------------------------------------------------- server side
def guard(name, args):
    assert name in X.TOOLS | {"ctl_validate"}, name
    if "sandboxCode" in args:
        p = args["sandboxPath"]
        assert args["sandboxCode"] == SANDBOX and p.startswith("suite_v5/") and ".." not in Path(p).parts, args


async def upload_inputs(call, m, uploaded):
    for x in m["files"]:
        if "/data-in/" in x["local"] and x["remote"] not in uploaded:
            await call("sandbox_write_file", dict(sandboxCode=SANDBOX, sandboxPath=x["remote"],
                                                  content=(H.D / x["local"]).read_text()))
            uploaded.add(x["remote"])


def graph_path(m):
    """Suite manifests live in data/suite_v5/run_graphs, pool-built ones under agent_harness/graphs."""
    for base in (H.R, X.D / "run_graphs"):
        p = base / m["label"] / "graph" / Path(m["graph_file"]).name
        if p.exists():
            return p
    raise FileNotFoundError(m["label"])


def candidate_graph(m, code, key):
    """The acceptance graph with the Test node's CTL replaced and outputs redirected under suite_v5/agent/out/."""
    root = E.parse(graph_path(m)).getroot()
    test = root.find(".//Node[@id='Test']")
    attrs = [a for a in test.findall("attr") if (a.text or "").lstrip().startswith("//#CTL2")]
    assert len(attrs) == 1, (m["label"], [a.get("name") for a in test.findall("attr")])
    attrs[0].text = code
    outs = {}
    for a in root.iter("attr"):
        if a.get("name") == "fileURL" and (a.text or "").startswith("suite_v5/data-out/"):
            new = f"{PREFIX}out/{key}_{Path(a.text).name}"
            outs[a.text] = new
            a.text = new
    return E.tostring(root, encoding="unicode"), outs


async def score(call, m, code, key):
    """exec_score.score_one with the graph and outputs under suite_v5/agent/ and a row-level detail for wrong rows."""
    xml, outs = candidate_graph(m, code, key)
    gpath = f"{PREFIX}graph/{key}.grf"
    await call("sandbox_write_file", dict(sandboxCode=SANDBOX, sandboxPath=gpath,
                                          content='<?xml version="1.0" encoding="UTF-8"?>\n' + xml))
    valid = await call("job_validate", dict(sandboxCode=SANDBOX, sandboxPath=gpath, timeoutSeconds=60))
    if valid.get("overall") != "PASS":
        probs = [p.get("message", "") for p in valid.get("problems", []) if p.get("severity") == "ERROR"] or [json.dumps(valid)[:1500]]
        return "invalid", "Graph validation failed: " + "\n".join(probs)[:3000]
    run = await call("job_run", dict(sandboxCode=SANDBOX, sandboxPath=gpath, params=m.get("parameters", {})))
    rid = run["runId"]
    done = await call("job_await", dict(runId=rid, timeoutSeconds=90))
    err = done.get("error") or {}
    if m["expected_failure"]:
        ok = done.get("status") == "ERROR" and err.get("componentId") == "Test" and "initialization failed" not in err.get("message", "").lower()
        return ("pass" if ok else "wrong_rows"), f"expected a failure, got {done.get('status')} {str(err.get('message'))[:300]}"
    if done.get("status") != "FINISHED_OK":
        msg = str(err.get("message", ""))
        st = "init_error" if "initialization failed" in msg.lower() else "runtime_error"
        return st, f"Component {err.get('componentId')}: {msg[:3000]}"
    bad = []
    for port, path in m["output_paths"].items():
        content = await call("sandbox_read_file", dict(sandboxCode=SANDBOX, sandboxPath=outs.get(path, path)))
        text = content if isinstance(content, str) else content.get("content", content.get("text", ""))
        meta = m["output_metadata"][int(port)]
        try:
            actual = H.parse_actual(text, meta)
        except Exception as exc:  # noqa: BLE001
            bad.append(f"output port {port}: unparsable output ({exc})"); continue
        expected = H.normalized_rows(m["fixture"]["expected"].get(port, []), meta)
        if actual != expected:
            i = next((i for i in range(max(len(actual), len(expected)))
                      if i >= len(actual) or i >= len(expected) or actual[i] != expected[i]), 0)
            bad.append(f"output port {port}: {len(actual)} rows, expected {len(expected)}; first difference at row {i}: "
                       f"expected {json.dumps(expected[i] if i < len(expected) else None, ensure_ascii=False)}, "
                       f"got {json.dumps(actual[i] if i < len(actual) else None, ensure_ascii=False)}")
    return ("wrong_rows" if bad else "pass"), ("; ".join(bad) or "rows match")


async def verify(call, m, code):
    uploaded = set()
    await upload_inputs(call, m, uploaded)
    return await score(call, m, code, f"ref_{m['label']}")


# ------------------------------------------------------------------------------------------------------------ run
async def ask(client, url, model, messages, think):
    body = dict(model=model, messages=messages, **SAMPLING,
                chat_template_kwargs={"enable_thinking": think, "reasoning_effort": "medium"})
    r = await client.post(f"{url}/v1/chat/completions", json=body, timeout=900)
    r.raise_for_status()
    j = r.json()
    msg = j["choices"][0]["message"]
    text = msg.get("content") or ""
    think_text = msg.get("reasoning_content") or (text.split("</think>")[0] if "</think>" in text else "")
    return text, think_text, j.get("usage", {}).get("completion_tokens")


def spec_metadata(task):
    """The port metadata of the task's first manifest, for ctl_validate."""
    m = task["manifests"][0]
    g = E.parse(graph_path(m)).getroot()
    metas = {x.get("id"): E.tostring(x[0], encoding="unicode") for x in g.find("Global").findall("Metadata")}
    ins = [metas[k] for k in sorted(metas) if re.fullmatch(r"In\d+", k)]
    outs = [metas[k] for k in sorted(metas) if re.fullmatch(r"Out\d+", k)]
    if "INTERSECTION" in task["component"].upper().replace(" ", "_"):
        outs = outs[1:2]     # the CTL's $out.0 is the matched output (physical port 1); ports 0 and 2 are pass-through
    return ins, outs, metas.get("Accumulator")


async def run_cmd(a):
    import httpx
    tasks = [json.loads(l) for l in Path(a.pool).read_text().splitlines() if l.strip()]
    if a.limit:
        tasks = tasks[:a.limit]
    out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if out.exists():
        done = {(r["task_id"], r["run"], r["mode"]) for r in map(json.loads, out.read_text().splitlines()) if r.get("final")}
    todo = [(t, run, mode) for t in tasks for mode in a.modes for run in range(1, a.runs + 1) if (t["id"], run, mode) not in done]
    print(len(todo), "runs to do,", len(done), "already done", flush=True)
    sem = asyncio.Semaphore(a.concurrency)
    lock = asyncio.Lock()
    async with X.streamablehttp_client(MCP_URL, timeout=180) as (rd, wr, _), httpx.AsyncClient() as client:
        if a.load_adapter:
            r = await client.post(f"{a.url}/v1/load_lora_adapter", json=dict(lora_name=a.model, lora_path=str(Path(a.load_adapter).resolve())), timeout=300)
            print("load adapter:", r.status_code, r.text[:100], flush=True)
        async with X.ClientSession(rd, wr) as s:
            await s.initialize()
            await s.call_tool("task_workflow_get", {"task": "validate_and_run"})

            async def call(n, args):
                guard(n, args)
                async with lock:
                    return X.payload(await s.call_tool(n, args))

            uploaded = set()
            for t in tasks:
                for m in t["manifests"]:
                    await upload_inputs(call, m, uploaded)
            metas = {t["id"]: spec_metadata(t) for t in tasks}

            async def one(t, run, mode):
                async with sem:
                    think = mode == "on"
                    msgs = [{"role": "system", "content": t.get("system") or SYSTEM}, {"role": "user", "content": t["prompt"]}]
                    rec = dict(task_id=t["id"], source=t["source"], component=t["component"], task=t["task"], run=run, mode=mode,
                               model=a.model, attempts=[])
                    t0 = time.monotonic()
                    for rnd in range(0, a.rounds + 1):
                        try:
                            text, think_text, ntok = await ask(client, a.url, a.model, msgs, think)
                        except Exception as exc:  # noqa: BLE001
                            rec["attempts"].append(dict(round=rnd, status="model_error", detail=str(exc)[:300])); break
                        answer = text.split("</think>")[-1]
                        msgs.append({"role": "assistant", "content": answer})
                        code = X.extract_code(text)
                        att = dict(round=rnd, think_chars=len(think_text or ""), completion_tokens=ntok, answer=answer)
                        if code is None:
                            att.update(status="no_code", detail="no CTL code block in the answer"); rec["attempts"].append(att); break
                        att["code_sha"] = hashlib.sha256(code.encode()).hexdigest()[:12]
                        feedback = None
                        if a.precompile:
                            ins, outs, acc = metas[t["id"]]
                            args = dict(componentType=TOOL_TYPE.get(t["component"].upper().replace(" ", "_"), "generic"), code=code,
                                        inputMetadata=ins, outputMetadata=outs)
                            if acc:
                                args["accumulatorMetadata"] = acc
                            try:
                                d = await call("ctl_validate", args)
                                errs = [p.get("message", "") for p in d.get("problems", []) if p.get("severity") == "ERROR"]
                                att["compile"] = d.get("overall")
                                # ctl_validate has no graph context: lookups, sequences and dictionary entries cannot resolve
                                # there, so such a FAIL is not evidence; the graph run compiles the code for real.
                                if any(NO_CONTEXT_RE.search(e) for e in errs):
                                    att["compile"] = "SKIPPED (needs graph context)"
                                    errs = []
                                if d.get("overall") != "PASS" and errs:
                                    att.update(status="compile_error", detail="\n".join(errs)[:3000])
                                    feedback = FEEDBACK.format(error="ctl_validate reported:\n" + att["detail"])
                            except Exception as exc:  # noqa: BLE001
                                att["compile"] = f"error: {str(exc)[:100]}"
                        if feedback is None:
                            worst, det = "pass", "rows match"
                            order = ["harness_error", "invalid", "init_error", "runtime_error", "wrong_rows", "pass"]
                            for m in t["manifests"]:
                                key = f"{m['label']}_{run}{mode}_r{rnd}_{att['code_sha']}"
                                try:
                                    st, d = await score(call, m, code, key)
                                except Exception as exc:  # noqa: BLE001
                                    st, d = "harness_error", str(exc)[:400]
                                if order.index(st) < order.index(worst):
                                    worst, det = st, d
                            att.update(status=worst, detail=det)
                            if worst in ("init_error", "runtime_error", "invalid"):
                                feedback = FEEDBACK.format(error=det)
                            elif worst == "wrong_rows" and a.rows_feedback:
                                feedback = ROWS_FEEDBACK.format(error=det)
                        if att["status"] in ("compile_error", "init_error", "invalid"):
                            att["cause"] = cause_of(att["detail"])
                        rec["attempts"].append(att)
                        if feedback is None or rnd == a.rounds:
                            break
                        msgs.append({"role": "user", "content": feedback})
                    rec["final"] = rec["attempts"][-1]["status"] if rec["attempts"] else "model_error"
                    rec["first"] = rec["attempts"][0]["status"] if rec["attempts"] else "model_error"
                    rec["rounds_used"] = max(0, len(rec["attempts"]) - 1)
                    rec["seconds"] = round(time.monotonic() - t0, 1)
                    async with lock:
                        with open(out, "a") as fh:
                            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    print(f"{t['id']:40s} {mode:3s} run{run} {rec['first']:13s} -> {[x['status'] for x in rec['attempts'][1:]]}", flush=True)

            await asyncio.gather(*(one(t, r, m) for t, r, m in todo))
    summary_cmd(argparse.Namespace(results=str(out), by=["source", "component"]))


# ---------------------------------------------------------------------------------------------------------- summary
def summary_cmd(a):
    recs = [json.loads(l) for l in Path(a.results).read_text().splitlines() if l.strip()]
    rounds = max((len(r["attempts"]) for r in recs), default=1)
    lines = []

    def block(title, rs):
        if not rs:
            return
        lines.append(f"\n### {title} (n={len(rs)})\n")
        lines.append("| mode | n | pass@first | " + " | ".join(f"pass≤round {k}" for k in range(1, rounds)) + " | final mix | mean rounds | median think chars |")
        lines.append("|---|---|---|" + "---|" * (rounds - 1) + "---|---|---|")
        for mode in ("off", "on"):
            ms = [r for r in rs if r["mode"] == mode]
            if not ms:
                continue
            n = len(ms)
            def passed_by(k):
                return sum(any(x["status"] == "pass" for x in r["attempts"][:k + 1]) for r in ms)
            cum = " | ".join(f"{passed_by(k) / n:.2f}" for k in range(1, rounds))
            mix = collections.Counter(r["final"] for r in ms)
            mixs = ", ".join(f"{k} {v}" for k, v in mix.most_common())
            think = sorted(x.get("think_chars", 0) for r in ms for x in r["attempts"][:1])
            med = think[len(think) // 2] if think else 0
            lines.append(f"| {mode} | {n} | {passed_by(0) / n:.2f} | {cum} | {mixs} | {sum(r['rounds_used'] for r in ms) / n:.2f} | {med} |")

    block("All tasks", recs)
    for by in a.by or []:
        for v in sorted({r[by] for r in recs}):
            block(f"{by} = {v}", [r for r in recs if r[by] == v])
    causes = collections.Counter()
    for r in recs:
        for x in r["attempts"]:
            if x.get("cause"):
                causes[(r["mode"], x["cause"])] += 1
    if causes:
        lines.append("\n### Compile / init error causes (all attempts)\n\n| cause | off | on |\n|---|---|---|")
        for c in sorted({c for _, c in causes}):
            lines.append(f"| {c} | {causes[('off', c)]} | {causes[('on', c)]} |")
    unfixed = collections.Counter()
    for r in recs:
        if r["final"] != "pass" and len(r["attempts"]) > 1:
            unfixed[(r["mode"], r["attempts"][0]["status"], r["final"])] += 1
    if unfixed:
        lines.append("\n### Retried but not fixed (first status -> final)\n\n| mode | first | final | n |\n|---|---|---|---|")
        for (mode, f, l), n in unfixed.most_common():
            lines.append(f"| {mode} | {f} | {l} | {n} |")
    text = "\n".join(lines)
    print(text)
    Path(a.results).with_suffix(".summary.md").write_text(text + "\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pool")
    p.add_argument("--suite", action="store_true")
    p.add_argument("--corpus", nargs="*", metavar="SFT_JSON FIXTURES_JSON", help="pairs: SFT file then its fixtures file")
    p.add_argument("--tweak", nargs="+", metavar="SFT_JSON", help="rewrite the generate prompts of these SFT files")
    p.add_argument("--tweak-n", type=int, help="only the first N of the shuffled prompts")
    p.add_argument("--tweak-concurrency", type=int, default=6)
    p.add_argument("--fixture-tokens", type=int, default=32768, help="completion budget of the fixture call (with reasoning)")
    p.add_argument("--tweak-config", default="configs/mut_validate_qwen38.yaml")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--out", required=True)
    r = sub.add_parser("run")
    r.add_argument("pool")
    r.add_argument("--model", required=True)
    r.add_argument("--url", default="http://127.0.0.1:3012")
    r.add_argument("--load-adapter")
    r.add_argument("--modes", nargs="+", default=["off", "on"])
    r.add_argument("--runs", type=int, default=1)
    r.add_argument("--rounds", type=int, default=2, help="feedback rounds after the first answer")
    r.add_argument("--precompile", action=argparse.BooleanOptionalAction, default=True, help="ctl_validate before the run")
    r.add_argument("--rows-feedback", action="store_true", help="also feed back wrong rows (an agent that sees the test output)")
    r.add_argument("--concurrency", type=int, default=8)
    r.add_argument("--limit", type=int)
    r.add_argument("--out", required=True)
    s = sub.add_parser("summary")
    s.add_argument("results")
    s.add_argument("--by", nargs="*", default=["source", "component"])
    a = ap.parse_args()
    if a.cmd == "pool":
        asyncio.run(pool_cmd(a))
    elif a.cmd == "run":
        asyncio.run(run_cmd(a))
    else:
        summary_cmd(a)
