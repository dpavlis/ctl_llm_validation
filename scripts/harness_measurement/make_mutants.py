#!/home/pavlisd/venv/bin/python
"""Part B1 of spec/harness_measurement_brief.md: validate prompts with planted, server-confirmed defects.

Each pool-1 task's reference CTL (the Test node of its acceptance graph, which passes) gets one defect of a known kind.
The mutant is run in the task's acceptance graph(s) and kept only if it fails there: graph validation / init error for
the compile-type defects, a runtime error or wrong rows against the fixture for the semantic ones. Equivalent mutants
(still pass) are dropped and the next site is tried. Unchanged references are the controls.

  kind                  mutation                                             anchor                severity (§7)
  missing_lifecycle     delete one Rollup lifecycle function                 the function name     ERROR
  unconnected_port      one `$out.0.f =` -> `$out.K.f =` (K = first unconnected port; DataIntersection's CTL sees one)
                                                                             `$out.K`               ERROR
  unknown_field         rename one output assignment's field                 the new field name    ERROR
  wrong_return          the emitting `return ALL|OK` of transform -> SKIP    SKIP                  ERROR (stated requirement)
  inverted_condition    a boundary comparison with a literal: >= <-> >, <= <-> <
                                                                             the compared operand  ERROR or WARNING
  null_guard_removed    `nvl(F, d)` -> F, or an `!isnull(F) &&` / `F != null &&` conjunct dropped
                                                                             the field             WARNING
  control               reference unchanged                                  -                     no ERROR, PASS

The prompt is "Validate this <component> against its metadata and requirements." + the task text with the original
instruction sentences and code blocks removed + the code; no hint about the defect.

    ~/venv/bin/python scripts/harness_measurement/make_mutants.py --out data/agent_harness/validate_mutants.jsonl

--exec-rft: the source tasks are exec-RFT pool records (data/exec_rft/pool.jsonl: one `manifest`, graphs under
data/exec_rft/graphs/), minus every task whose reference is a pool-1 reference (B1) — the training set of the
validate-precision OPCD run (spec/validate_precision_brief.md). --per-kind 0 / --controls -1 keep every confirmed
mutant / every reference.
"""
import argparse, asyncio, collections, json, random, re, sys, xml.etree.ElementTree as E
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import agent_harness as AH   # noqa: E402  (read-only use: graph paths, scorer, MCP guard)

LIFECYCLE = ["finishGroup", "updateTransform", "initGroup", "updateGroup"]
COMP_NAME = {"REFORMAT": "Reformat", "ROLLUP": "Rollup", "NORMALIZER": "Normalizer", "DENORMALIZER": "Denormalizer",
             "PARTITION": "Partition", "DATA_INTERSECTION": "DataIntersection", "DATAINTERSECTION": "DataIntersection",
             "EXT_MERGE_JOIN": "ExtMergeJoin", "EXTMERGEJOIN": "ExtMergeJoin", "EXT_HASH_JOIN": "ExtHashJoin",
             "EXTHASHJOIN": "ExtHashJoin", "DATAGENERATOR": "DataGenerator"}
SEVERITY = dict(missing_lifecycle="ERROR", unconnected_port="ERROR", unknown_field="ERROR", wrong_return="ERROR",
                inverted_condition="ERROR|WARNING", null_guard_removed="WARNING")


def comp_key(c):
    return re.sub(r"\W", "", c.split("(")[0]).upper()


def comp_name(c):
    k = comp_key(c)
    return COMP_NAME.get(k, c.split("(")[0].strip())


def reference(m):
    root = E.parse(AH.graph_path(m)).getroot()
    test = root.find(".//Node[@id='Test']")
    return next(a.text for a in test.findall("attr") if (a.text or "").lstrip().startswith("//#CTL2"))


# --------------------------------------------------------------------------------------------- CTL text helpers
def mask(code):
    """Same-length copy with string literals and comments blanked, so regexes and brace matching see only code."""
    out, i, n = list(code), 0, len(code)
    while i < n:
        c = code[i]
        if code.startswith("//", i):
            j = code.find("\n", i); j = n if j < 0 else j
            out[i:j] = " " * (j - i); i = j
        elif code.startswith("/*", i):
            j = code.find("*/", i + 2); j = n if j < 0 else j + 2
            out[i:j] = re.sub(r"[^\n]", " ", code[i:j]); i = j
        elif c in "\"'":
            j = i + 1
            while j < n and code[j] != c:
                j += 2 if code[j] == "\\" else 1
            out[i + 1:j] = " " * (j - i - 1); i = j + 1
        else:
            i += 1
    return "".join(out)


def functions(code):
    """name -> (start, end) of each top-level `function T name(...) {...}`, end past the closing brace and newline."""
    mk, out = mask(code), {}
    for m in re.finditer(r"(?m)^[ \t]*function\s+[\w\[\]<>, ]+?\s+(\w+)\s*\(", mk):
        i = mk.index("{", m.end()); depth = 0
        for j in range(i, len(mk)):
            depth += {"{": 1, "}": -1}.get(mk[j], 0)
            if depth == 0:
                break
        end = j + 1
        if end < len(code) and code[end] == "\n":
            end += 1
        out[m.group(1)] = (m.start(), end)
    return out


def balanced_arg_end(mk, i):
    """Index of the ',' or ')' closing the argument that starts at i (depth 0)."""
    depth = 0
    for j in range(i, len(mk)):
        if mk[j] in "([{":
            depth += 1
        elif mk[j] in ")]}":
            if depth == 0:
                return j
            depth -= 1
        elif mk[j] == "," and depth == 0:
            return j
    return -1


def anchor_re(name):
    return r"(?<!\w)\$?" + re.escape(name) + r"(?!\w)" if not name.startswith("$") else re.escape(name) + r"(?!\w)"


# ------------------------------------------------------------------------------------------------- mutations
def m_missing_lifecycle(code, task, meta):
    if comp_key(task["component"]) != "ROLLUP":
        return []
    fs = functions(code)
    out = []
    for f in LIFECYCLE:
        if f in fs:
            s, e = fs[f]
            out.append(dict(code=code[:s] + code[e:], anchor=f, anchor_res=[anchor_re(f)], site=f))
    return out


def m_unconnected_port(code, task, meta):
    k = 1 if "INTERSECTION" in comp_key(task["component"]) else meta["n_out"]
    mk, out = mask(code), []
    for m in re.finditer(r"\$out\.0\.(\w+)\s*=(?!=)", mk):
        new = code[:m.start()] + f"$out.{k}." + code[m.start() + 7:]
        out.append(dict(code=new, anchor=f"$out.{k}",
                        anchor_res=[rf"\$?out\.{k}(?!\d)", rf"\b(output|port)\s*'?{k}'?(?!\d)"], site=m.group(1)))
    return out


def m_unknown_field(code, task, meta):
    mk, out = mask(code), []
    for m in re.finditer(r"\$out\.(\d+)\.(\w+)\s*=(?!=)", mk):
        port, f = int(m.group(1)), m.group(2)
        if f == "*":
            continue
        new_name = f.replace("_", "", 1) if "_" in f else f + "s"
        if new_name in meta["out_fields"].get(port, set()) | {f}:
            continue
        s = m.start(2)
        out.append(dict(code=code[:s] + new_name + code[m.end(2):], anchor=new_name, anchor_res=[anchor_re(new_name)],
                        site=f"{port}.{f}"))
    return out


def m_wrong_return(code, task, meta):
    if re.search(r"\bSKIP\b", mask(code)):
        return []          # SKIP already used legitimately: a finding naming SKIP would be ambiguous
    fs = functions(code)
    if "transform" not in fs:
        return []
    s, e = fs["transform"]
    body = mask(code)[s:e]
    rets = list(re.finditer(r"\breturn\s+(ALL|OK)\s*;", body))
    if not rets:
        return []
    r = rets[-1]
    a, b = s + r.start(), s + r.end()
    return [dict(code=code[:a] + "return SKIP;" + code[b:], anchor="SKIP", anchor_res=[r"\bSKIP\b"], site=r.group(1))]


FLIP = {">=": ">", ">": ">=", "<=": "<", "<": "<="}
OPERAND = r"(\$?[A-Za-z_][\w.]*(?:\([^()]*\))?)"


def m_inverted_condition(code, task, meta):
    mk, out = mask(code), []
    pats = [re.compile(OPERAND + r"\s*(>=|<=|>|<)(?!=)\s*(-?\d+(?:\.\d+)?[DdLl]?)\b"),
            re.compile(r"(-?\d+(?:\.\d+)?[DdLl]?)\s*(>=|<=|>|<)(?!=)\s*" + OPERAND)]
    for pi, p in enumerate(pats):
        for m in p.finditer(mk):
            ident = m.group(1) if pi == 0 else m.group(3)
            if re.match(r"(counter|i|j|k|idx|n)$", ident) or ident.startswith(("length(", "size(")) or "->" in ident:
                continue
            if re.search(r"\bfor\s*\([^)]*$", mk[max(0, m.start() - 80):m.start()]):
                continue      # loop bounds
            op_start = m.start(2)
            op = m.group(2)
            new = code[:op_start] + FLIP[op] + code[op_start + len(op):]
            last = re.sub(r"\(.*", "", ident).split(".")[-1]
            res = [anchor_re(last)] if len(last) > 2 else []
            res.append(re.escape(code[m.start():m.end()]).replace(r"\ ", r"\s*"))
            out.append(dict(code=new, anchor=last if len(last) > 2 else code[m.start():m.end()], anchor_res=res,
                            site=code[m.start():m.end()]))
    return out


def m_null_guard_removed(code, task, meta):
    mk, out = mask(code), []
    for m in re.finditer(r"\bnvl\s*\(\s*(\$in\.\d+\.(\w+))\s*,", mk):
        f = m.group(2)
        if f not in meta["nullable_in"]:
            continue
        end = balanced_arg_end(mk, m.end())
        if end < 0 or mk[end] != ")":
            continue
        out.append(dict(code=code[:m.start()] + code[m.start(1):m.end(1)] + code[end + 1:], anchor=f,
                        anchor_res=[anchor_re(f)], site=f"nvl {f}"))
    for p in (r"!\s*isnull\s*\(\s*(\$in\.\d+\.(\w+))\s*\)\s*&&\s*", r"(\$in\.\d+\.(\w+))\s*!=\s*null\s*&&\s*"):
        for m in re.finditer(p, mk):
            f = m.group(2)
            if f not in meta["nullable_in"]:
                continue
            out.append(dict(code=code[:m.start()] + code[m.end():], anchor=f, anchor_res=[anchor_re(f)], site=f"guard {f}"))
    return out


MUTATORS = dict(missing_lifecycle=m_missing_lifecycle, unconnected_port=m_unconnected_port, unknown_field=m_unknown_field,
                wrong_return=m_wrong_return, inverted_condition=m_inverted_condition, null_guard_removed=m_null_guard_removed)


# ------------------------------------------------------------------------------------------------------ prompt
def requirements(prompt):
    """The task text without the generate/fix instruction and without CTL code blocks."""
    t = re.sub(r"```[^\n]*\n(.*?)```", lambda m: "" if re.search(r"//#CTL2|\bfunction\s+\w+", m.group(1)) else m.group(0),
               prompt, flags=re.S)
    # instructions about a (now absent) faulty version: they would point the reviewer at a defect that is not there
    t = re.sub(r"(?m)^Current code:\s*$", "", t)
    # pool_tweak prompts carry a "Component type:" header copied from the source set, 19 of 165 contradicting the task
    # (§3.36); the validate prompt already names the component, so the header is dropped
    t = re.sub(r"(?im)^Component type:[^\n]*\n?", "", t)
    for s in [r"The only reported defect[^.\n]*\.", r"Review and fix this[^.\n]*\.", r"(?m)(^|(?<=\. ))(Fix|Repair|Correct)\b(?! (this|the)\b)[^.\n]*\.",
              r"Repair its CTL[^.\n]*\.", r"(List|Give|Justify)\b[^.\n]*\b(change|correction|repair|reason)s?\b[^.\n]*\."]:
        t = re.sub(s, "", t)
    t = re.sub(r": write (a|an) ", r": \1 ", t)
    for p in [r"Write (the )?complete\b[^.]*\.", r"List every problem[^.]*\.", r"Correct this component implementation[^.]*\.",
              r"[^.\n]*\b(provide|give|return|output)s? (the |a )?(complete|full|corrected)[^.\n]*\.", r"Explain every (correction|fix)[^.\n]*\.",
              r"(?m)^(Correct|Fix|Repair)\b[^.\n]*\bcode\b[^.\n]*\."]:
        t = re.sub(p, "", t, flags=re.I)
    t = re.sub(r"\b(Fix|Repair|Correct)\s+(this|the)\s+", "This is the ", t)
    t = re.sub(r"This is the (\w+( below)?|[^.\n]*\b(so that|to satisfy|to meet|against its metadata)\b[^.\n]*)\.\s*", "", t)
    t = re.sub(r"\bWrite (a|an|the)\s+", lambda m: m.group(1).capitalize() + " ", t)
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    return t[0].upper() + t[1:] if t else t


def build_prompt(task, code):
    what = "CTL2 code" if task["component"].startswith("Standalone") else f"{comp_name(task['component'])} transform"
    return (f"Validate this {what} against its metadata and requirements.\n\n"
            f"{requirements(task['prompt'])}\n\n```ctl\n{code.strip()}\n```")


def load_exec_rft(path, exclude_pools):
    """exec-RFT records in the pool-1 shape (manifests list, source = corpus set), with the graph harness pointed at
    data/exec_rft/. Tasks whose reference hash is in an excluded pool (pool 1 = B1's references) are dropped."""
    AH.H.D = ROOT / "data/exec_rft"
    AH.H.R = AH.X.R = AH.H.D / "graphs"
    excl = {m["reference_sha256"] for f in exclude_pools for l in Path(f).read_text().splitlines() if l.strip()
            for m in json.loads(l)["manifests"]}
    tasks, dropped = [], 0
    for l in Path(path).read_text().splitlines():
        if not l.strip():
            continue
        r = json.loads(l)
        if r["manifest"]["reference_sha256"] in excl:
            dropped += 1; continue
        tasks.append(dict(r, manifests=[r["manifest"]], source=r["set"]))
    print(f"exec-RFT: {len(tasks)} tasks, {dropped} dropped (reference in {', '.join(map(str, exclude_pools))})", flush=True)
    return tasks


def fixture_rows(t):
    return sum(len(x) for x in t["manifests"][0]["fixture"]["inputs"])


def task_meta(task):
    m = task["manifests"][0]
    root = E.parse(AH.graph_path(m)).getroot()
    metas = {x.get("id"): x[0] for x in root.find("Global").findall("Metadata")}
    outs = sorted(k for k in metas if re.fullmatch(r"Out\d+", k))
    ins = sorted(k for k in metas if re.fullmatch(r"In\d+", k))
    nullable_in = {f.get("name") for k in ins for f in metas[k].findall("Field") if f.get("nullable", "true") == "true"}
    out_fields = {int(k[3:]): {f.get("name") for f in metas[k].findall("Field")} for k in outs}
    return dict(n_out=len(outs), nullable_in=nullable_in, out_fields=out_fields)


# ------------------------------------------------------------------------------------------------------- main
async def main(a):
    tasks = load_exec_rft(a.pool, a.exclude) if a.exec_rft else \
        [json.loads(l) for l in Path(a.pool).read_text().splitlines() if l.strip()]
    rng = random.Random(a.seed)
    todo = []        # (task, kind, [candidates]) — candidates tried in shuffled order until one fails on the server
    for t in tasks:
        refs = {reference(m) for m in t["manifests"]}
        if len(refs) != 1:
            print("skip (manifests disagree on the reference)", t["id"]); continue
        code = refs.pop()
        meta = task_meta(t)
        t["_code"], t["_meta"] = code, meta
        if t["component"].startswith("Standalone"):
            continue        # a function library: its transform is the harness wrapper, not the specified code
        for kind, fn in MUTATORS.items():
            cands = [c for c in fn(code, t, meta) if c["code"] != code]
            if cands:
                rng.shuffle(cands)
                todo.append((t, kind, cands[:a.tries]))
    print(len(todo), "(task, kind) pairs with a mutation site", collections.Counter(k for _, k, _ in todo), flush=True)
    out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    results, stats = [], collections.Counter()
    q = asyncio.Queue()
    for x in todo:
        q.put_nowait(x)

    async def worker(w):
        async with AH.X.streamablehttp_client(AH.MCP_URL, timeout=180) as (rd, wr, _):
            async with AH.X.ClientSession(rd, wr) as s:
                await s.initialize()
                await s.call_tool("task_workflow_get", {"task": "validate_and_run"})

                async def call(n, args):
                    AH.guard(n, args)
                    return AH.X.payload(await s.call_tool(n, args))
                uploaded = set()
                while not q.empty():
                    t, kind, cands = q.get_nowait()
                    for m in t["manifests"]:
                        await AH.upload_inputs(call, m, uploaded)
                    for ci, c in enumerate(cands):
                        worst, det = "pass", ""
                        order = ["harness_error", "invalid", "init_error", "runtime_error", "wrong_rows", "pass"]
                        for m in t["manifests"]:
                            key = f"mut_{m['label']}_{kind}_{ci}"
                            try:
                                st, d = await AH.score(call, m, c["code"], key)
                            except Exception as exc:  # noqa: BLE001
                                st, d = "harness_error", str(exc)[:400]
                            if order.index(st) < order.index(worst):
                                worst, det = st, d
                        stats[(kind, worst)] += 1
                        print(f"[w{w}] {t['id']:45s} {kind:20s} {c['site'][:30]:30s} {worst}", flush=True)
                        if worst not in ("pass", "harness_error"):
                            results.append(dict(id=f"{t['id']}__{kind}", task_id=t["id"], source=t["source"],
                                                component=comp_name(t["component"]), kind=kind, truth="FAIL",
                                                anchor=c["anchor"], anchor_res=c["anchor_res"], site=c["site"],
                                                severity=SEVERITY[kind], server_status=worst, server_detail=det[:600],
                                                input_rows=fixture_rows(t), task=t.get("task"),
                                                prompt=build_prompt(t, c["code"]), code=c["code"]))
                            break

    await asyncio.gather(*(worker(w) for w in range(a.workers)))
    # sample: up to --per-kind mutants per kind, spread over components; controls from tasks across components
    by_kind = collections.defaultdict(list)
    for r in sorted(results, key=lambda r: r["id"]):
        by_kind[r["kind"]].append(r)
    kept = []
    for kind, rs in by_kind.items():
        rng.shuffle(rs)
        rs.sort(key=lambda r: sum(x["component"] == r["component"] for x in rs))   # rarer components first
        kept += rs[:a.per_kind] if a.per_kind > 0 else rs
    ctl_tasks = [t for t in tasks if "_code" in t]
    rng.shuffle(ctl_tasks)
    seen = collections.Counter()
    ctl_tasks.sort(key=lambda t: seen.update([comp_name(t["component"])]) or seen[comp_name(t["component"])])
    for t in ctl_tasks[:a.controls] if a.controls >= 0 else ctl_tasks:
        kept.append(dict(id=f"{t['id']}__control", task_id=t["id"], source=t["source"], component=comp_name(t["component"]),
                         kind="control", truth="PASS", anchor=None, anchor_res=[], site="", severity=None,
                         server_status="pass", server_detail="reference passes its acceptance graph",
                         input_rows=fixture_rows(t), task=t.get("task"),
                         prompt=build_prompt(t, t["_code"]), code=t["_code"]))
    with open(out, "w") as fh:
        for r in kept:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    report = dict(records=len(kept), by_kind=collections.Counter(r["kind"] for r in kept),
                  by_kind_component={k: collections.Counter(r["component"] for r in kept if r["kind"] == k) for k in
                                     sorted({r["kind"] for r in kept})},
                  by_server_status=collections.Counter(f"{r['kind']}:{r['server_status']}" for r in kept),
                  verified_before_sampling=collections.Counter(r["kind"] for r in results),
                  tries={f"{k}:{s}": n for (k, s), n in sorted(stats.items())},
                  candidate_pairs=collections.Counter(k for _, k, _ in todo))
    out.with_suffix(".report.json").write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", default=str(ROOT / "data/agent_harness/pool1.jsonl"))
    ap.add_argument("--out", default=str(ROOT / "data/agent_harness/validate_mutants.jsonl"))
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--tries", type=int, default=4, help="sites tried per (task, kind) until one fails on the server")
    ap.add_argument("--per-kind", type=int, default=30)
    ap.add_argument("--controls", type=int, default=50)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--exec-rft", action="store_true", help="--pool is an exec-RFT pool (one manifest per record)")
    ap.add_argument("--exclude", nargs="*", default=[str(ROOT / "data/agent_harness/pool1.jsonl")],
                    help="--exec-rft: drop tasks whose reference hash is in these pools")
    ap.add_argument("--dry", action="store_true", help="only list the mutation sites and print sample prompts")
    a = ap.parse_args()
    if a.dry:
        tasks = load_exec_rft(a.pool, a.exclude) if a.exec_rft else \
            [json.loads(l) for l in Path(a.pool).read_text().splitlines() if l.strip()]
        c = collections.Counter()
        for t in tasks:
            code = reference(t["manifests"][0]); meta = task_meta(t)
            for kind, fn in MUTATORS.items():
                n = len(fn(code, t, meta)); c[kind] += bool(n)
        print(c)
    else:
        asyncio.run(main(a))
