"""Tally init errors (code that does not compile in the component) against the 11 causes of findings §3.29.

The server message in a scored record is cut at exec_score.DETAIL_LEN, so a cause is read from the code first and from
the message second, in the order below (first match wins). The patterns follow spec/ctl2_syntax_pitfalls_brief.md R1–R8
and the §3.29 table.

    ~/venv/bin/python scripts/exec_rft/causes.py results/exec_rft/samples_off.jsonl [...]      # sample files
    ~/venv/bin/python scripts/exec_rft/causes.py --exec-scores results/exec/exec_scores.json --match c13c
"""
import argparse, collections, json, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

UNITS = r"(?:millisec|second|minute|hour|day|week|month|year)"
TYPES = r"(?:integer|long|string|date|decimal|number|double|boolean)"
CAUSES = [   # (name, code pattern or None, message pattern or None)
    ("DataIntersection writes $out.1/$out.2", None, r"Cannot write to output port"),
    ("regex negation !~ / !x ~= re", r"!~|!\s*[$A-Za-z_][\w.$]*\s*~=", r"Syntax error on token '!'"),
    ("time-unit keyword as variable name", rf"\b{TYPES}\s+{UNITS}\b\s*[=;,)]", None),
    ("invented function (raise, sendPort, …)", r"\braise\s*\(|\bsendPort\s*\(|\bgetDictionaryValue\s*\(|\bdate2year\s*\(",
     r"Function '[^']*' is not declared"),
    ("str2date/isDate argument order", r"\b(?:str2date|isDate)\s*\([^;]*?,\s*(?:true|false)\s*,\s*\"",
     r"Function (?:str2date|isDate)\b.*not applicable"),
    ("invalid escape in a string (\"\\.\")", None, r"Invalid escape sequence"),
    ("return constant in a ternary", r"\?\s*(?:ALL|OK|SKIP|STOP)\b|\?[^;:]*:\s*(?:ALL|OK|SKIP|STOP)\s*;", r"Syntax error on token '\?'"),
    ("field not in the metadata", None, r"Field '[^']*' does not exist in record"),
    ("undeclared variable", None, r"Variable '[^']*' is not declared"),
    ("dictionary access", r"\bdictionary\.\w+", r"Dictionar"),
    ("other wrong arguments", None, r"not applicable for the arguments"),
]
EXTRA = [   # not among the 11 causes of §3.29 (the suite gap tests rarely hit them), tallied apart
    ("missing Rollup lifecycle function", None, r"Required function\(s\)|function must be defined|function is not defined"),
    ("type mismatch", None, r"Type mismatch"),
]


def cause(code, detail, component=None):
    code = code or ""
    if component == "DATA_INTERSECTION" and re.search(r"\$out\.[12]\b", code):
        return CAUSES[0][0]
    for name, cp, mp in CAUSES + EXTRA:
        if cp and re.search(cp, code):
            return name
        if mp and re.search(mp, detail or ""):
            return name
    return "other"


def tally(rows):
    """rows: (code, detail, component) of init_error answers -> Counter of causes (11 causes + other)."""
    c = collections.Counter(cause(*r) for r in rows)
    return ({n: c.get(n, 0) for n, _, _ in CAUSES} | {"sum of the 11": sum(c.get(n, 0) for n, _, _ in CAUSES)}
            | {n: c.get(n, 0) for n, _, _ in EXTRA} | {"other": c.get("other", 0), "total": sum(c.values())})


def from_samples(files):
    rows = []
    for f in files:
        man = {}
        for s in C.read_jsonl(f):
            if s["status"] == "init_error":
                rows.append((C.extract_code(s["answer"]), s["detail"], s.get("component")))
    return rows


def from_exec_scores(path, match):
    """init_error answers of results files whose name contains `match` (code re-read from the results file)."""
    rows = []
    recs = [r for r in json.loads(Path(path).read_text()) if match in r["results_file"]]
    cache = {}
    for r in recs:
        bad = [v for v in r.get("variants", {}).values() if v["status"] == "init_error"]
        if not bad or r["status"] != "init_error":
            continue
        if r["results_file"] not in cache:
            p = next(C.ROOT.glob(f"results/**/{r['results_file']}"))
            cache[r["results_file"]] = {(t["test_id"], t["run"]): t for t in json.loads(p.read_text())["tests"]}
        t = cache[r["results_file"]][r["test_id"], r["run"]]
        comp = "DATA_INTERSECTION" if "DataIntersection" in (t.get("component") or "") else None
        rows.append((C.extract_code(t.get("mut_response")), bad[0]["detail"], comp))
    return rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*")
    ap.add_argument("--exec-scores")
    ap.add_argument("--match", default="")
    a = ap.parse_args()
    rows = from_exec_scores(a.exec_scores, a.match) if a.exec_scores else from_samples(a.files)
    print(json.dumps(tally(rows), indent=1))
