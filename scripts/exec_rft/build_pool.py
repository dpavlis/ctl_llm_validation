"""Step 1 of the exec-RFT pilot: an executable prompt pool from the corpus runtime harnesses, not the evaluation suite.

For every generate / fix-to-spec record of the server-verified corpus sets (SCD-2, DataIntersection, Rollup accumulator,
Rollup lifecycle, Normalizer multi-row, syntax pitfalls, zeroDate), the record's gold answer is linked to a corpus
fixture (same CTL code, else the same record id) and rebuilt as a graph_harness graph with the fixture's inputs:
  - corpus_harness: the gold answer reproduces the corpus's expected rows in our graph;
  - reference_run:  no usable corpus expectation (no expected rows, the gold code was revised after the fixture, or our
                    graph's row normalization differs): the expected rows are the gold answer's own output on the
                    fixture inputs (source 2 of the brief). A gold answer that does not run is dropped.
Every kept manifest is re-run with the gold answer and must pass. Prompts with 5-gram Jaccard >= 0.30 (field names
masked) against the suite v5 prompts, generate_rw.json or the hard-case sets are dropped; fixtures with no expected
row at all are dropped (any answer that outputs nothing would pass). 40 prompts are held out, stratified by component.

    ~/venv/bin/python scripts/exec_rft/build_pool.py [--dry]
"""
import argparse, asyncio, collections, json, random, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

CORPUS = C.ROOT / "ctl_lora_training/sft_training_data"
LOGS = CORPUS / "logs"
DPO = {"scd2": "CTL_LoRA_DPO_scd2.jsonl", "dataintersection": "CTL_LoRA_DPO_dataintersection.jsonl",
       "rollup_accumulator": "CTL_LoRA_DPO_rollup_accumulator.jsonl", "normalizer_multirow": "CTL_LoRA_DPO_normalizer_multirow.jsonl",
       "syntax_pitfalls": "CTL_LoRA_DPO_syntax_pitfalls.jsonl", "zerodate": "CTL_LoRA_DPO_zerodate.jsonl"}
SETS = {   # set -> (SFT file, fixture files in the common fixtures.json format)
    "scd2": ("CTL_LoRA_scd2_sft.json", ["scd2_runtime/round2/fixtures.json"]),
    "dataintersection": ("CTL_LoRA_dataintersection_sft.json", ["dataintersection_runtime/round2/fixtures.json"]),
    "rollup_accumulator": ("CTL_LoRA_rollup_accumulator_sft.json", ["rollup_acc_runtime/fixtures.json"]),
    "normalizer_multirow": ("CTL_LoRA_normalizer_multirow_sft.json", ["normalizer_multi_runtime/fixtures.json"]),
    "syntax_pitfalls": ("CTL_LoRA_syntax_pitfalls_sft.json", ["syntax_pitfalls_runtime/r1_3/fixtures.json",
                                                              "syntax_pitfalls_runtime/r4_6/fixtures.json",
                                                              "syntax_pitfalls_runtime/r7_8/fixtures.json"]),
    "rollup_lifecycle": ("CTL_LoRA_rollup_lifecycle_validate_sft.json", []),   # cases.json + fixtures/<id>.json
    "zerodate": ("CTL_LoRA_zerodate_sft.json", []),                            # data/corpus_authoring/zerodate_records.CHECKS
}
N_HOLDOUT = 40


# ----------------------------------------------------------------------------- records

def task_of(user, answer):
    if "VERDICT:" in answer:
        return "validate"
    if re.search(r"```[^\n]*\n[\s\S]*?\bfunction\s+\w+[\s\S]*?```", user) or "//#CTL2" in user:
        return "fix"
    return "generate"


def records():
    """SFT records, then DPO prompts with the chosen answer as gold (a prompt seen twice is used once)."""
    seen = set()
    for set_name, (fname, _) in SETS.items():
        for r in json.loads((CORPUS / fname).read_text()):
            user, answer = r["messages"][0]["content"], r["messages"][-1]["content"]
            seen.add(user.strip())
            yield dict(set=set_name, source_file=f"sft_training_data/{fname}", source_id=r["id"], prompt=user,
                       task=task_of(user, answer), gold=C.extract_code(answer))
    for set_name, fname in DPO.items():
        for i, r in enumerate(C.read_jsonl(CORPUS / fname), 1):
            if r["prompt"].strip() in seen:
                continue
            seen.add(r["prompt"].strip())
            yield dict(set=set_name, source_file=f"sft_training_data/{fname}", source_id=f"{set_name}_dpo_{i:03d}",
                       prompt=r["prompt"], task=task_of(r["prompt"], r["chosen"]), gold=C.extract_code(r["chosen"]))


# ----------------------------------------------------------------------------- fixtures

def meta_xml(m):
    """Corpus JSON metadata -> CloverDX Record XML in the graph harness's delimited form."""
    if isinstance(m, str):
        return m
    out = [f'<Record name="{m["name"]}" type="delimited" fieldDelimiter="|" recordDelimiter="\\n" nullValue="__NULL__">']
    for f in m["fields"]:
        t = {"double": "number", "int": "integer"}.get(f["type"], f["type"])
        a = f'name="{f["name"]}" type="{t}" nullable="{str(f.get("nullable", True)).lower()}"'
        for k in ("containerType", "length", "scale", "default"):
            if f.get(k) is not None:
                a += f' {k}="{f[k]}"'
        out.append(f"  <Field {a}/>")
    return "\n".join(out + ["</Record>"])


def norm_code(code):
    return "\n".join(l.strip() for l in (code or "").replace("//#CTL2", "").splitlines() if l.strip())


def expected_ports(exp):
    if exp is None:
        return None
    if isinstance(exp, list):
        return {"0": exp}
    out = {re.sub(r"^OUTPUT_", "", k): v for k, v in exp.items() if re.fullmatch(r"(OUTPUT_)?\d+", k)}
    return out or None


def corpus_fixtures():
    """Every fixture as {fid, set, component, code, ins, outs, acc, settings, resources, inputs, expected}."""
    fx = []
    for set_name, (_, files) in SETS.items():
        for fn in files:
            for f in json.loads((LOGS / fn).read_text()):
                if f.get("expected_status") or str(f.get("expected_outcome", "")).lower().startswith(("error", "init", "fail")):
                    continue   # fixtures of intentionally failing code
                ins = [meta_xml(m) for m in f["input_metadata"]]
                outs = [meta_xml(m) for m in f["output_metadata"]]
                exp = expected_ports(f.get("expected"))
                if f["component"] == "DATA_INTERSECTION" and len(outs) == 1:
                    outs = [ins[0], outs[0], ins[1]]   # out 0 = A-only, 1 = both (the CTL's $out.0), 2 = B-only
                res = {}
                if f.get("sequences"):
                    res["sequences"] = [dict(name=s["name"], start=s.get("start", 1), step=s.get("step", 1)) for s in f["sequences"]]
                fx.append(dict(fid=f["id"], set=set_name, component=f["component"], code=f.get("code"), ins=ins, outs=outs,
                               acc=meta_xml(f["accumulator_metadata"]) if f.get("accumulator_metadata") else None,
                               settings=dict(f.get("attributes") or {}), resources=res, inputs=f["inputs"], expected=exp,
                               rows_count=f.get("configured_records")))
    for c in json.loads((LOGS / "rollup_lifecycle_runtime/cases.json").read_text()):
        if c.get("task") not in ("fix", "fix-to-spec") or c.get("variant", "candidate") != "candidate":
            continue
        fx.append(dict(fid=c["id"], set="rollup_lifecycle", component="ROLLUP", code=c.get("corrected_code"),
                       ins=[meta_xml(m) for m in c["inputMetadata"]], outs=[meta_xml(m) for m in c["outputMetadata"]],
                       acc=meta_xml(c["accumulatorMetadata"]), settings={"groupKeyFields": ";".join(c["group_keys"])},
                       resources={}, inputs=[c["fixture"]],
                       expected={"0": c["expected_output"]} if c.get("expected_output_applies_to") == "corrected_code" else None))
    sys.path.insert(0, str(C.ROOT / "data/corpus_authoring"))
    import zerodate_records as Z
    for r in Z.RECORDS:
        for code, exp, chk in r["blocks"]:
            if chk and not chk.endswith("!") and exp == "PASS":
                c = Z.CHECKS[chk]
                fx.append(dict(fid=r["id"], set="zerodate", component=c["component"], code=code, ins=c["ins"], outs=c["outs"],
                               acc=c.get("acc"), settings=dict(c.get("settings", {})), resources={}, inputs=c["inputs"],
                               expected=c["expected"]))
    return fx


def link(rec, fixtures):
    """The fixture for a record: same gold code (corpus expectation usable), else same record id (inputs only)."""
    same_set = [f for f in fixtures if f["set"] == rec["set"]]
    g = norm_code(rec["gold"])
    by_code = [f for f in same_set if f["code"] and norm_code(f["code"]) == g]
    if by_code:
        return by_code[0], True
    by_id = [f for f in same_set if f["fid"] in (rec["source_id"], rec["source_id"] + "_chosen")]
    return (by_id[0], False) if by_id else (None, False)


def manifest(label, rec, f, expected):
    fixture = dict(inputs=[[{k: row.get(k) for k in [x.get("name") for x in C.H.fields(m)]} for row in rows]
                           for rows, m in zip(f["inputs"], f["ins"])],
                   expected={p: [{k: row.get(k) for k in [x.get("name") for x in C.H.fields(f["outs"][int(p)])]} for row in rows]
                             for p, rows in expected.items() if int(p) < len(f["outs"])})
    if f.get("rows_count"):
        fixture["rows_count"] = f["rows_count"]
    test = dict(test_id=label, reference=rec["gold"], rubric=dict(description=f"exec-RFT pool {rec['source_id']}"))
    spec = dict(component=f["component"], inputMetadata=f["ins"], outputMetadata=f["outs"], settings=f["settings"],
                resources=f["resources"], fixture=fixture)
    if f.get("acc"):
        spec["accumulatorMetadata"] = f["acc"]
    return C.H.build(test, spec)


# ----------------------------------------------------------------------------- overlap

def protected_prompts():
    out = []
    for t in json.loads((C.ROOT / "resources/ctl2_test_suite_v5.json").read_text())["tests"]:
        out.append(("suite_v5:" + t["test_id"], t["user_message"]))
    for t in json.loads((C.ROOT / "data/suite_v5/generate_rw.json").read_text()):
        out.append(("generate_rw:" + t["test_id"], t["user_message"]))
    for p in sorted((C.ROOT / "data/opcd").glob("hard_cases*.jsonl")):
        for h in C.read_jsonl(p):
            out.append((f"{p.name}:{h['id']}", h["user"]))
    return [(k, C.grams(v)) for k, v in out]


# ----------------------------------------------------------------------------- main

async def verify(cands, report):
    keep = []
    async with C.Server(6) as srv:
        async def one(rec, f, code_match):
            label = "rft_" + rec["source_id"]
            if code_match and f["expected"]:
                m = manifest(label, rec, f, f["expected"])
                st, det = await srv.score(m, rec["gold"], label + "_ref")
                if st == "pass":
                    return rec | dict(fixture_source="corpus_harness", manifest=m, ref_detail=det)
                rec["corpus_mismatch"] = f"{st}: {det[:200]}"
            m = manifest(label, rec, f, {str(i): [] for i in range(len(f["outs"]))})
            st, det, rows = await srv.run_rows(m, rec["gold"], label + "_refrows")
            if st != "ok":
                return rec | dict(drop=f"reference does not run ({st}: {det[:200]})")
            if not any(rows.values()):
                return rec | dict(drop="reference output is empty")
            m = manifest(label, rec, f, rows)
            st, det = await srv.score(m, rec["gold"], label + "_ref")
            if st != "pass":
                return rec | dict(drop=f"reference-run fixture does not re-pass ({st}: {det[:200]})")
            return rec | dict(fixture_source="reference_run", manifest=m, ref_detail=det)

        sem = asyncio.Semaphore(6)
        async def guarded(c):
            async with sem:
                try:
                    r = await one(*c)
                except Exception as exc:  # noqa: BLE001 — a fixture the harness cannot build is dropped, with the reason
                    r = c[0] | dict(drop=f"harness error ({type(exc).__name__}: {str(exc)[:200]})")
                print(r["source_id"], r.get("fixture_source") or r.get("drop"), flush=True)
                return r
        for r in await asyncio.gather(*(guarded(c) for c in cands)):
            if "drop" in r:
                report["dropped"][r["drop"].split(" (")[0]] += 1
                report["dropped_ids"].append([r["source_id"], r["drop"]])
            else:
                keep.append(r)
    return keep


def split_holdout(rows, report):
    """40 held-out prompts, stratified by component. Near-duplicates (5-gram Jaccard >= 0.30 with field names masked, or
    the same gold code, e.g. an SFT record and a DPO pair on one scenario) form clusters that go to one side whole, so
    no held-out prompt has a near-copy in the training pool."""
    parent = list(range(len(rows)))
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]; i = parent[i]
        return i
    g = [C.grams(r["prompt"]) for r in rows]
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            if (rows[i]["manifest"]["reference_sha256"] == rows[j]["manifest"]["reference_sha256"]
                    or C.jaccard(g[i], g[j]) >= 0.30):
                parent[find(i)] = find(j)
    clusters = collections.defaultdict(list)
    for i in range(len(rows)):
        clusters[find(i)].append(i)
    by_comp = collections.defaultdict(list)
    for members in clusters.values():
        by_comp[rows[members[0]]["component"]].append(members)
    n_comp = collections.Counter(r["component"] for r in rows)
    quota = {c: round(N_HOLDOUT * n / len(rows)) for c, n in n_comp.items()}
    while sum(quota.values()) != N_HOLDOUT:   # rounding: adjust the largest strata
        big = max(quota, key=lambda c: n_comp[c] - quota[c])
        quota[big] += 1 if sum(quota.values()) < N_HOLDOUT else -1
    rng = random.Random(20261025)
    held = set()
    for c in sorted(by_comp):
        cl = sorted(by_comp[c], key=lambda m: rows[m[0]]["id"])
        rng.shuffle(cl)
        got = 0
        for m in cl:
            if got + len(m) <= quota[c]:
                held |= {rows[i]["id"] for i in m}; got += len(m)
    left = sorted((m for v in by_comp.values() for m in v if rows[m[0]]["id"] not in held),
                  key=lambda m: (len(m), rows[m[0]]["id"]))
    for m in left:   # a stratum whose clusters overshoot its quota (e.g. one 9-prompt Denormalizer cluster): fill with
        if len(held) + len(m) <= N_HOLDOUT:   # the smallest remaining clusters
            held |= {rows[i]["id"] for i in m}
    hi = [i for i, r in enumerate(rows) if r["id"] in held]
    ti = [i for i, r in enumerate(rows) if r["id"] not in held]
    report.update(near_duplicate_clusters=len(clusters), largest_cluster=max(len(m) for m in clusters.values()),
                  holdout_quota=quota,
                  holdout_max_jaccard_to_pool=round(max(max(C.jaccard(g[i], g[j]) for j in ti) for i in hi), 3))
    return held


def resplit():
    """Re-split an existing pool + holdout (no server runs) and update the report."""
    rows = sorted(C.read_jsonl(C.DATA / "pool.jsonl") + C.read_jsonl(C.DATA / "holdout.jsonl"), key=lambda r: r["id"])
    report = json.loads((C.DATA / "build_report.json").read_text())
    held = split_holdout(rows, report)
    C.write_jsonl(C.DATA / "pool.jsonl", [r for r in rows if r["id"] not in held])
    C.write_jsonl(C.DATA / "holdout.jsonl", [r for r in rows if r["id"] in held])
    report.update(pool=len(rows) - len(held), holdout=len(held), holdout_by_component=dict(sorted(
        collections.Counter(r["component"] for r in rows if r["id"] in held).items())))
    (C.DATA / "build_report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    print({k: report[k] for k in ("pool", "holdout", "holdout_by_component", "near_duplicate_clusters", "largest_cluster",
                                  "holdout_max_jaccard_to_pool")})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="link and overlap-check only, no server runs")
    ap.add_argument("--resplit", action="store_true", help="only redo the holdout split of an existing pool")
    a = ap.parse_args()
    if a.resplit:
        return resplit()
    fixtures = corpus_fixtures()
    report = dict(fixtures_read=len(fixtures), records=collections.Counter(), dropped=collections.Counter(), dropped_ids=[])
    prot = protected_prompts()
    report["protected_prompts"] = len(prot)
    cands = []
    for rec in records():
        report["records"][f"{rec['set']}:{rec['task']}"] += 1
        if rec["task"] not in ("generate", "fix"):
            continue
        if rec["gold"] is None:
            report["dropped"]["no CTL block in the answer (explanation)"] += 1; continue
        g = C.grams(rec["prompt"])
        top = max(prot, key=lambda kv: C.jaccard(g, kv[1]))
        rec["max_overlap"] = [top[0], round(C.jaccard(g, top[1]), 3)]
        if rec["max_overlap"][1] >= 0.30:
            report["dropped"]["suite overlap (5-gram Jaccard >= 0.30)"] += 1
            report["dropped_ids"].append([rec["source_id"], f"overlap {rec['max_overlap']}"]); continue
        f, code_match = link(rec, fixtures)
        if f is None:
            report["dropped"]["no corpus fixture"] += 1
            report["dropped_ids"].append([rec["source_id"], "no corpus fixture"]); continue
        rec["component"] = C.H.TYPE_MAP.get(f["component"], f["component"])   # zeroDate checks name it "Reformat"
        cands.append((rec, f, code_match))
    print(f"{len(cands)} candidates; dropped so far {dict(report['dropped'])}")
    if a.dry:
        print(collections.Counter((r["set"], r["task"], cm, bool(f["expected"])) for r, f, cm in cands))
        return
    keep = asyncio.run(verify(cands, report))
    rows = [dict(id=f"rft_{r['source_id']}", source_file=r["source_file"], source_id=r["source_id"], set=r["set"],
                 component=r["component"], task=r["task"], prompt=r["prompt"], fixture_source=r["fixture_source"],
                 max_overlap=r["max_overlap"], manifest=r["manifest"]) for r in keep]
    rows.sort(key=lambda r: r["id"])
    held = split_holdout(rows, report)
    C.write_jsonl(C.DATA / "pool.jsonl", [r for r in rows if r["id"] not in held])
    C.write_jsonl(C.DATA / "holdout.jsonl", [r for r in rows if r["id"] in held])
    cnt = lambda key, sel: dict(sorted(collections.Counter(r[key] for r in sel).items()))
    report.update(
        kept=len(rows), pool=len(rows) - len(held), holdout=len(held),
        by_source=cnt("set", rows), by_component=cnt("component", rows), by_task=cnt("task", rows),
        by_fixture_source=cnt("fixture_source", rows),
        holdout_by_component=cnt("component", [r for r in rows if r["id"] in held]),
        max_overlap_kept=max(r["max_overlap"][1] for r in rows),
        corpus_expectation_mismatch_then_reference=[[r["source_id"], r["corpus_mismatch"]] for r in keep if r.get("corpus_mismatch")])
    report["records"] = dict(sorted(report["records"].items())); report["dropped"] = dict(report["dropped"])
    (C.DATA / "build_report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k not in ("dropped_ids", "corpus_expectation_mismatch_then_reference")}, indent=1))


if __name__ == "__main__":
    main()
