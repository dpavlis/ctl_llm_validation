#!/home/pavlisd/venv/bin/python
"""Part B2 of spec/harness_measurement_brief.md: corpus validate records with reference answers, as ground-truth records.

The validate records (assistant answer with ISSUES / VERDICT) of the seven runtime-harness sets become records of the
same shape as the planted mutants (make_mutants.py): truth = the reference VERDICT, and for each reference [ERROR] /
[WARNING] line an anchor set, i.e. the identifiers that line names that also occur in the prompt (backticked
identifiers and dotted paths, Rollup lifecycle names, `$out.N` / output N). An answer finds that issue when one of its
ISSUES lines names any anchor of the set. A FAIL record is kept only when every reference issue line has at least one
anchor; the rest are dropped and counted (ambiguous). PASS records need no anchors.

These records are training data of the models measured (findings §3.30/§3.34 recipes), so they measure recall of
trained answers more than validation skill; they are reported apart from B1.

    ~/venv/bin/python scripts/harness_measurement/corpus_validate.py --out data/agent_harness/validate_corpus.jsonl
"""
import argparse, collections, json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SETS = {"scd2": "CTL_LoRA_scd2_sft.json", "syntax_pitfalls": "CTL_LoRA_syntax_pitfalls_sft.json",
        "rollup_acc": "CTL_LoRA_rollup_accumulator_sft.json", "normalizer_multi": "CTL_LoRA_normalizer_multirow_sft.json",
        "dataintersection": "CTL_LoRA_dataintersection_sft.json", "zerodate": "CTL_LoRA_zerodate_sft.json",
        "rollup_lifecycle": "CTL_LoRA_rollup_lifecycle_validate_sft.json"}
LIFECYCLE = ["initGroup", "updateGroup", "finishGroup", "updateTransform", "transform", "count", "append", "clean",
             "getOutputPort", "generate"]
GENERIC = {"null", "true", "false", "all", "ok", "string", "integer", "long", "decimal", "number", "boolean", "date",
           "return", "function", "void", "if", "else", "in", "out", "acc", "a", "i", "counter", "isnull", "nvl", "trim",
           "ctl2", "ctl", "map", "list", "record", "text", "value", "result"}
ISSUE_RE = re.compile(r"^\s*(?:[-*]\s*)?\[(ERROR|WARNING|INFO)\]\s*(.*)$", re.M)


def issues(answer):
    sect = answer.split("SUGGESTIONS:")[0]
    return [(s, t) for s, t in ISSUE_RE.findall(sect) if s != "INFO"]


def verdict(answer):
    v = re.findall(r"VERDICT:\s*\**\s*(PASS|FAIL)", answer)
    return v[-1] if v else None


def anchor_re(name):
    return r"(?<!\w)\$?" + re.escape(name) + r"(?!\w)"


def declared_names(prompt):
    """Field, record-member and variable names of the prompt: metadata names, `$in.N.x` / `$out.N.x` / `acc.x` members,
    locals declared in the code, and prose field lists (`name:type`, `name type`) when the name has an underscore."""
    code = "\n".join(re.findall(r"```.*?```", prompt, re.S))
    names = set(re.findall(r'"name"\s*:\s*"(\w+)"', prompt))
    names |= set(re.findall(r"\$(?:in|out)\.\d+\.(\w+)", prompt))
    names |= set(re.findall(r"\b[a-z]\w*\.([a-z_]\w*)\b(?!\s*\()", code))
    names |= set(re.findall(r"\b(?:string|integer|long|decimal|number|boolean|date)(?:\[\])?\s+(\w+)\s*[=;]", code))
    prose = set(re.findall(r"\b(\w+)\s*(?:\(|:)\s*(?:string|integer|long|decimal|number|boolean|date)\b", prompt))
    prose |= set(re.findall(r"\b(\w+)\s+(?:\(|has type )?(?:string|integer|long|decimal|number|boolean|date)\b", prompt))
    names |= {n for n in prose if "_" in n or re.search(rf"\b{n}\b", code)}
    return {n for n in names if len(n) >= 3 and n.lower() not in GENERIC and not n[0].isupper()}


def anchors_of(line, prompt):
    """Identifiers the reference issue line names that also occur in the prompt."""
    names = []
    for b in re.findall(r"`([^`]+)`", line):
        b = b.strip()
        m = re.fullmatch(r"\$?([\w.]+?)(\(\))?", b)
        if not m:
            continue
        last = m.group(1).split(".")[-1]
        if re.fullmatch(r"out\.\d+|\d+", m.group(1)):
            continue
        if last.lower() in GENERIC or len(last) < 3:
            continue
        names.append(last)
    # a missing or misspelled lifecycle function is named in the line but absent from the prompt's code; the line's
    # first lifecycle name is its subject (later ones are usually the server message listing every missing function)
    lc = sorted((m.start(), f) for f in LIFECYCLE if f not in ("count", "append", "clean")
                for m in [re.search(rf"\b{f}\b", line)] if m)
    lifecycle = [lc[0][1]] if lc and not names else []
    if not names and not lifecycle:      # no backticked identifier: bare declared names in the line
        known = declared_names(prompt)
        names = [w for w in re.findall(r"(?<![\w.$])([A-Za-z_]\w{2,})(?!\w)", line) if w in known]
    ports = re.findall(r"\$out\.(\d+)(?!\.\w)|\boutput (?:port )?(\d+)\b|\bport (\d+)\b", line)
    out = []
    for n in dict.fromkeys(names + lifecycle):
        if n in lifecycle or n in LIFECYCLE or re.search(anchor_re(n), prompt, re.I):
            out.append(dict(anchor=n, anchor_res=[anchor_re(n)]))
    for p in dict.fromkeys(next(x for x in g if x) for g in ports):
        out.append(dict(anchor=f"$out.{p}", anchor_res=[rf"\$?out\.{p}(?!\d)", rf"\b(output|port)\s*'?{p}'?(?!\d)"]))
    return out


def main(a):
    recs, dropped = [], collections.Counter()
    base = ROOT / "ctl_lora_training/sft_training_data"
    for set_name, fname in SETS.items():
        for r in json.loads((base / fname).read_text()):
            msgs = r.get("messages") or []
            users = [m for m in msgs if m["role"] == "user"]
            asst = [m for m in msgs if m["role"] == "assistant"]
            if len(users) != 1 or len(asst) != 1:
                continue
            ans, prompt = asst[0]["content"], users[0]["content"]
            v = verdict(ans)
            if not (v and re.search(r"^ISSUES:", ans, re.M)):
                continue
            iss = issues(ans)
            if v == "FAIL" and not iss:
                dropped[f"{set_name}:fail_without_issue_lines"] += 1; continue
            if v == "PASS" and any(s == "ERROR" for s, _ in iss):
                dropped[f"{set_name}:pass_with_error"] += 1; continue
            refs = []
            for sev, text in iss:
                anc = anchors_of(text, prompt)
                refs.append(dict(severity=sev, text=text[:400], anchors=anc))
            if v == "FAIL" and any(not x["anchors"] for x in refs):
                dropped[f"{set_name}:ambiguous_anchor"] += 1; continue
            recs.append(dict(id=f"corpus_{r['id']}", task_id=r["id"], source=f"corpus_{set_name}", component=None,
                             kind="corpus_fail" if v == "FAIL" else "corpus_pass", truth=v, issues=refs,
                             prompt=prompt, system=next((m["content"] for m in msgs if m["role"] == "system"), None)))
    out = Path(a.out)
    with open(out, "w") as fh:
        for r in recs:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    report = dict(records=len(recs), by_set_truth=collections.Counter(f"{r['source']}:{r['truth']}" for r in recs),
                  issues_per_fail_record=collections.Counter(len(r["issues"]) for r in recs if r["truth"] == "FAIL"),
                  issue_severity=collections.Counter(i["severity"] for r in recs for i in r["issues"] if r["truth"] == "FAIL"),
                  dropped=dropped)
    out.with_suffix(".report.json").write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "data/agent_harness/validate_corpus.jsonl"))
    main(ap.parse_args())
