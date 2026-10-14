#!/usr/bin/env python3
"""Fail-closed structural and artifact checks for the OPCD generate-gaps batch.

Run --help for paths. This does not judge business semantics or rubric quality;
those require independent review. Local evidence corroborates run claims but is
not a replacement for the CloverDX server's execution history.
"""
import argparse
import csv
import io
import json
import re
import sys
import xml.etree.ElementTree as ET

from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GAPS = tuple(f"G{i}" for i in range(1, 7))
TAGS = ("first_previous_state", "unsafe_text_conversion", "date_without_time", "nullable_read")
sys.path.insert(0,str(ROOT / 'generate_gaps_runs' / 'round2'))
from lint import check as check_text
from check_alternatives import audit as check_alternatives
from check_independent import check as check_independent

CLOSING = "Write the complete CTL2 for this component only, including its required entry functions."


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def prompts(value):
    """Handle suite lists, keyed tests, messages, and instruction/input schemas."""
    if isinstance(value, list):
        for item in value:
            yield from prompts(item)
    elif isinstance(value, dict):
        for key in ("user", "prompt", "user_prompt", "user_message"):
            if isinstance(value.get(key), str):
                yield value[key]
                return
        if isinstance(value.get("messages"), list):
            parts = [m.get("content", "") for m in value["messages"]
                     if isinstance(m, dict) and m.get("role") == "user"]
            if parts and all(isinstance(p, str) for p in parts):
                yield "\n\n".join(parts)
                return
        if isinstance(value.get("instruction"), str):
            yield value["instruction"] + "\n\n" + str(value.get("input", ""))
            return
        for item in value.values():
            if isinstance(item, (dict, list)):
                yield from prompts(item)


def read_document(path):
    if path.suffix.lower() == ".jsonl":
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return load_json(path)


def grams(text):
    tokens = re.findall(r"\b\w+\b", text.lower())
    return {tuple(tokens[i:i + 5]) for i in range(len(tokens) - 4)}


def jaccard(a, b):
    return len(a & b) / len(a | b) if a or b else 1.0


def records(path):
    """Read JSON, JSONL, or delimited text; preserve record and field order."""
    if path.suffix.lower() == ".json":
        value = load_json(path)
        if isinstance(value, dict) and isinstance(value.get("records"), list):
            value = value["records"]
        if not isinstance(value, list):
            raise ValueError(f"{path}: expected a JSON list or {{records:[...]}}")
        return value
    if path.suffix.lower() == ".jsonl":
        return read_document(path)
    text = path.read_text(encoding="utf-8")
    delimiter = "\t" if path.suffix.lower() == ".tsv" else ";" if path.suffix.lower() == ".del" else ","
    return list(csv.reader(io.StringIO(text), delimiter=delimiter))


def successful_compile(value):
    if not isinstance(value, dict):
        return False
    problems = value.get("problems", [])
    errors = [p for p in problems if isinstance(p, dict) and str(p.get("severity", "")).upper() == "ERROR"]
    return not errors and (value.get("overall") == "PASS" or value.get("valid") is True
                           or value.get("success") is True or value.get("status") == "PASS")


class Checker:
    def __init__(self, base):
        self.base = base
        self.errors = []

    def require(self, condition, message):
        if not condition:
            self.errors.append(message)
        return bool(condition)

    def artifact(self, value, label):
        if not self.require(isinstance(value, str) and bool(value), f"{label}: missing path"):
            return None
        path = Path(value)
        if not path.is_absolute():
            path = self.base / path
        if not self.require(path.is_file(), f"{label}: missing file {path}"):
            return None
        return path

    def metadata(self, row):
        label = row.get("id", "unknown")
        metadata = row.get("metadata")
        if not self.require(isinstance(metadata, dict), f"{label}: metadata object required"):
            return
        found = []
        for role in ("input", "output", "accumulator"):
            group = metadata.get(role, [])
            if not self.require(isinstance(group, list), f"{label}: metadata.{role} must be a list"):
                continue
            found.extend(group)
        self.require(bool(found), f"{label}: no metadata records")
        for record in found:
            if not self.require(isinstance(record, dict), f"{label}: metadata record is not an object"):
                continue
            fields = record.get("fields", [])
            if not self.require(isinstance(fields, list) and all(isinstance(f, dict) for f in fields), f"{label}: invalid fields"):
                continue
            self.require(8 <= len(fields) <= 25, f"{label}/{record.get('name')}: must have 8–25 fields")
            self.require(all(isinstance(f.get("name"), str) and isinstance(f.get("type"), str) and isinstance(f.get("nullable"), bool) for f in fields), f"{label}: field name/type/explicit nullable required")
            self.require(len({f.get("name") for f in fields}) == len(fields), f"{label}: duplicate field names")
            self.require({f.get("nullable") for f in fields} == {True, False}, f"{label}: mixed nullability required")
            self.require(any(f.get("type") == "date" for f in fields), f"{label}: date field required")
            self.require(any(f.get("unused") is True for f in fields), f"{label}: unused field must be marked")
            decimals = [f for f in fields if f.get("type") == "decimal"]
            self.require(bool(decimals), f"{label}: decimal field required")
            for field in decimals:
                length, scale = field.get("length"), field.get("scale")
                self.require(type(length) is int and type(scale) is int and length > 0 and 0 <= scale <= length, f"{label}: decimal needs valid length and scale")
            self.require(all(f.get("name", "") in row.get("user", "") for f in fields), f"{label}: metadata fields missing from prompt")

    def evidence(self, row):
        label = row.get("id", "unknown")
        artifacts = row.get("artifacts", {})
        if not self.require(isinstance(artifacts, dict), f"{label}: artifacts object required"):
            return
        def all_paths(value):
            if isinstance(value,str):
                self.artifact(value,f'{label}/artifacts')
            elif isinstance(value,list):
                for child in value: all_paths(child)
            elif isinstance(value,dict):
                for child in value.values(): all_paths(child)
        all_paths(artifacts)
        paths = {}
        for kind in ("inputs", "expected", "actual"):
            values = artifacts.get(kind)
            if not self.require(isinstance(values, list) and bool(values), f"{label}: artifacts.{kind} list required"):
                paths[kind] = []
                continue
            paths[kind] = [self.artifact(v, f"{label}/{kind}") for v in values]
        if paths["inputs"] and all(paths["inputs"]):
            count = sum(len(records(p)) for p in paths["inputs"])
            self.require(8 <= count <= 15, f"{label}: {count} input records; require 8–15 (headerless files)")
        self.require(len(paths["expected"]) == len(paths["actual"]), f"{label}: output port count differs")
        for expected, actual in zip(paths["expected"], paths["actual"]):
            if expected and actual:
                self.require(records(expected) == records(actual), f"{label}: expected/actual records differ: {actual.name}")
        compile_file = self.artifact(artifacts.get("compile"), f"{label}/compile")
        if compile_file:
            self.require(successful_compile(load_json(compile_file)), f"{label}: compile evidence not successful")
        comparison = self.artifact(artifacts.get("comparison"), f"{label}/comparison")
        if comparison:
            result = load_json(comparison)
            self.require(result.get("matches") is True and result.get("run_id") in row.get("run_ids", []), f"{label}: comparison claim/run ID mismatch")
        run_file = self.artifact(artifacts.get("run"), f"{label}/run")
        if run_file:
            result = load_json(run_file)
            self.require(result.get("status") == "FINISHED_OK" and result.get("run_id", result.get("runId")) in row.get("run_ids", []), f"{label}: run evidence must show FINISHED_OK and a declared run ID")
        self.require(bool(artifacts.get('alternative_runs')),f'{label}: missing alternative solution run')
        for extra in artifacts.get('extra_runs', [])+artifacts.get('alternative_runs', []):
            extra_path=self.artifact(extra,f'{label}/extra_run')
            if extra_path:
                result=load_json(extra_path)
                self.require(result.get('reference_runs') is True and result.get('completion',{}).get('status')=='FINISHED_OK',f'{label}: extra boundary run not verified')
                self.require(set(result.get('run_ids',[])) <= set(row.get('run_ids',[])),f'{label}: extra run IDs not declared')
        graph = self.artifact(artifacts.get("graph"), f"{label}/graph")
        if graph:
            root = ET.parse(graph).getroot()
            text = "\n".join(root.itertext())
            self.require(row.get("reference", "").strip() in text, f"{label}: reference source absent from graph")
            declared = {n.attrib.get("name"): n for n in root.iter() if n.tag.lower() == "record"}
            for group in row.get("metadata", {}).values():
                if isinstance(group, list):
                    for record in group:
                        if isinstance(record, dict):
                            self.require(record.get("name") in declared, f"{label}: metadata record absent from graph: {record.get('name')}")
                            xml_record = declared.get(record.get("name"))
                            if xml_record is not None:
                                xml_fields = {n.attrib.get("name"): n.attrib for n in xml_record if n.tag.lower() == "field"}
                                for field in record.get("fields", []):
                                    if not isinstance(field, dict):
                                        continue
                                    attributes = xml_fields.get(field.get("name"), {})
                                    self.require(attributes.get("type") == field.get("type"), f"{label}: graph field/type mismatch for {field.get('name')}")
                                    nullable = attributes.get("nullable", "true").lower() != "false"
                                    self.require(nullable == field.get("nullable"), f"{label}: graph nullability mismatch for {field.get('name')}")
                                    for key in ("length", "scale"):
                                        if key in field:
                                            self.require(str(field[key]) == attributes.get(key), f"{label}: graph {key} mismatch for {field.get('name')}")

    def row(self, row):
        if not self.require(isinstance(row, dict), "dataset row must be an object"):
            return
        label = row.get("id", "unknown")
        gap = row.get("gap")
        self.require(gap in GAPS, f"{label}: invalid gap")
        self.require(bool(re.fullmatch(r"opcd_gen_G[1-6]_(?:0[1-9]|1[0-9]|20)", str(label))) and str(label).split("_")[2] == gap, f"{label}: invalid ID")
        self.require(row.get("task_type") == "generate", f"{label}: task_type must be generate")
        self.require(isinstance(row.get("component"), str), f"{label}: missing component")
        user = row.get("user", "")
        if not self.require(isinstance(user, str), f"{label}: user must be a string"):
            return
        self.require(250 <= len(user.split()) <= 600, f"{label}: word count {len(user.split())} outside 250–600")
        self.require(user.rstrip().endswith(CLOSING), f"{label}: required closing sentence absent")
        self.require(isinstance(row.get("reference"), str) and row.get("reference", "").strip().startswith("//#CTL2"), f"{label}: complete raw CTL2 reference required")
        self.require(row.get("reference_compiles") is True and row.get("reference_runs") is True, f"{label}: references not both verified")
        run_ids = row.get("run_ids")
        self.require(isinstance(run_ids, list) and bool(run_ids) and all(type(r) is int and r > 0 for r in run_ids), f"{label}: positive integer run_ids required")
        self.require(isinstance(row.get("graph_file"), str) and row.get("graph_file", "").startswith("opcd_gaps/"), f"{label}: graph_file must be under opcd_gaps/")
        traps = row.get("traps")
        self.require(isinstance(traps, list) and len(traps) >= 3 and all(isinstance(t, str) and t.strip() for t in traps), f"{label}: at least three traps required")
        tags = row.get("trap_tags")
        self.require(isinstance(tags, list) and all(t in TAGS for t in tags) and len(tags) == len(set(tags)), f"{label}: invalid trap_tags")
        signature=row.get('diversity_signature')
        self.require(isinstance(signature,dict) and all(isinstance(signature.get(k),str) and signature[k].strip() for k in ('state_model','decision_rule','emission_pattern','cross_gap_edge','business_domain')),f'{label}: auditable substantive diversity signature required')
        rubric = row.get("rubric", {})
        ids = []
        covered = set()
        for kind, lower, upper in (("required", 6, 10), ("forbidden", 2, 3)):
            items = rubric.get(kind, []) if isinstance(rubric, dict) else []
            if not self.require(isinstance(items, list) and lower <= len(items) <= upper, f"{label}: {kind} rubric count invalid"):
                continue
            for item in items:
                if not self.require(isinstance(item, dict), f"{label}: invalid rubric item"):
                    continue
                self.require(all(isinstance(item.get(k), str) and item[k].strip() for k in ("id", "check", "rationale")), f"{label}: rubric ID/check/rationale required")
                ids.append(item.get("id"))
                if kind == "required":
                    clauses = item.get("clauses")
                    self.require((isinstance(clauses,list) and bool(clauses) and all(type(c) is int and c>0 for c in clauses)) or (isinstance(item.get("prompt_evidence"),str) and bool(item["prompt_evidence"]) and item["prompt_evidence"].lower() in user.lower()),f"{label}: required item needs clause indices or an exact prompt_evidence phrase")
                    if isinstance(clauses, list):
                        covered.update(c for c in clauses if type(c) is int and c > 0)
        self.require(len(ids) == len(set(ids)), f"{label}: duplicate rubric IDs")
        # Exact evidence phrases also link unnumbered or numbered prose to checks.
        clause_matches=list(re.finditer(r"(?m)^\s*(\d+)\.\s",user))
        evidence_phrases=[x.get('prompt_evidence','').lower() for x in rubric.get('required',[]) if isinstance(x,dict)]
        for index,match in enumerate(clause_matches):
            end=clause_matches[index+1].start() if index+1<len(clause_matches) else len(user)
            clause=user[match.end():end].lower()
            if any(phrase and phrase in clause for phrase in evidence_phrases):covered.add(int(match.group(1)))
        numbered = {int(n) for n in re.findall(r"(?m)^\s*(\d+)\.\s", user)}
        
        self.require(numbered <= covered, f"{label}: numbered prompt clauses lack rubric coverage: {sorted(numbered - covered)}")
        if isinstance(rubric, dict) and isinstance(rubric.get("required"), list) and rubric["required"]:
            first = rubric["required"][0]
            self.require(isinstance(first, dict) and str(first.get("id", "")).endswith(".1"), f"{label}: first required item must be component contract .1")
        self.metadata(row)
        try:
            self.evidence(row)
        except (ValueError, TypeError, KeyError, OSError, ET.ParseError) as exc:
            self.errors.append(f"{label}: unreadable/malformed evidence: {exc}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=ROOT / "generate_gaps.jsonl")
    parser.add_argument("--suite", type=Path, action="append", help="Repeat for v4 and v5 JSON/JSONL suite sources; defaults to downloaded prerequisites; directories scan both extensions")
    parser.add_argument("--report", type=Path, default=ROOT / "generate_gaps_report.json")
    parser.add_argument("--hard-cases-dir", type=Path, default=ROOT)
    parser.add_argument("--summary", type=Path, help="Optionally write machine-readable checker results")
    args = parser.parse_args(argv)
    if args.suite is None:
        args.suite = [ROOT / "generate_gaps_runs" / "sources" / "resources" / f"ctl2_test_suite_v{version}.json" for version in (4, 5)]
    checker = Checker(args.dataset.resolve().parent)
    try:
        rows = read_document(args.dataset)
    except (ValueError, OSError) as exc:
        rows = []
        checker.errors.append(f"dataset unavailable: {exc}")
    if not isinstance(rows, list):
        checker.errors.append("dataset must be JSONL records or a JSON array")
        rows = []
    checker.require(len(rows) == 120, f"dataset has {len(rows)} records; require 120")
    objects = [r for r in rows if isinstance(r, dict)]
    ids = [r.get("id") for r in objects]
    checker.require(len(ids) == len(set(ids)), "duplicate dataset IDs")
    counts = Counter(r.get("gap") for r in objects)
    components = defaultdict(set)
    tags = Counter()
    for row in rows:
        checker.row(row)
        if isinstance(row, dict):
            components[row.get("gap")].add(row.get("component"))
            if isinstance(row.get("trap_tags"), list):
                tags.update(set(t for t in row["trap_tags"] if isinstance(t, str)))
    for gap in GAPS:
        checker.require(counts[gap] == 20, f"{gap}: require 20 prompts, got {counts[gap]}")
        if gap in ("G1", "G3", "G5", "G6"):
            checker.require(len(components[gap] - {None}) >= 3, f"{gap}: require at least 3 components")
    checker.require(components["G2"] == {"ROLLUP"}, "G2: only ROLLUP permitted")
    checker.require(components["G4"] == {"NORMALIZER", "REFORMAT", "ROLLUP"}, "G4: require Normalizer, Reformat and Rollup")
    for tag in TAGS:
        checker.require(tags[tag] >= 15, f"{tag}: require at least 15 prompts, got {tags[tag]}")
    sources = []
    for source in args.suite:
        files = sorted(set(source.rglob("*.json")) | set(source.rglob("*.jsonl"))) if source.is_dir() else [source]
        checker.require(bool(files), f"no suite JSON/JSONL files: {source}")
        extracted = 0
        for file in files:
            try:
                values = list(prompts(read_document(file)))
                sources.extend((str(file), p) for p in values)
                extracted += len(values)
            except (ValueError, OSError) as exc:
                checker.errors.append(f"suite source unreadable {file}: {exc}")
        checker.require(extracted > 0, f"no suite prompts extracted from {source}")
    hard_files = sorted(args.hard_cases_dir.glob("hard_cases*.jsonl"))
    checker.require(bool(hard_files), "missing hard_cases*.jsonl prerequisite")
    for file in hard_files:
        try:
            values = list(prompts(read_document(file)))
            checker.require(bool(values), f"no hard-case prompts extracted from {file}")
            sources.extend((str(file), p) for p in values)
        except (ValueError, OSError) as exc:
            checker.errors.append(f"hard-case source unreadable {file}: {exc}")
    new_grams = [(r.get("id"), grams(r.get("user", ""))) for r in objects if isinstance(r.get("user"), str)]
    old_grams = [(source, grams(p)) for source, p in sources]
    maximum = 0.0
    for index, (label, candidate) in enumerate(new_grams):
        for other_label, other in old_grams + new_grams[:index]:
            score = jaccard(candidate, other)
            maximum = max(maximum, score)
            checker.require(score < 0.30, f"{label}: 5-gram Jaccard {score:.4f} >= 0.30 against {other_label}")
    try:
        report = load_json(args.report)
        checker.require(isinstance(report, dict), "report must be an object")
        for probe in report.get("probes", []):
            checker.require(isinstance(probe, dict) and probe.get("gap") in GAPS and isinstance(probe.get("run_ids"), list) and bool(probe.get("run_ids")), "probe needs gap and run_ids")
        checker.require(not report.get("unrun", []) and not report.get("blocked", []), "report records unrun or blocked work")
    except (ValueError, OSError, AttributeError) as exc:
        checker.errors.append(f"report unavailable/malformed: {exc}")
    text_summary=check_text(objects)
    checker.errors.extend(text_summary["errors"])
    alternative_summary=check_alternatives()
    independent_summary=check_independent(objects)
    checker.errors.extend(alternative_summary["errors"]+independent_summary["errors"])
    summary = {"alternative_checks":{k:v for k,v in alternative_summary.items() if k!="source_bound_reviews"},"independent_checks":independent_summary,"text_checks":text_summary,"passed": not checker.errors, "records": len(rows), "gap_counts": dict(counts), "components": {g: sorted(c for c in components[g] if isinstance(c, str)) for g in GAPS}, "component_counts": {g: dict(Counter(r.get("component") for r in objects if r.get("gap") == g)) for g in GAPS}, "trap_coverage": dict(tags), "comparison_prompts": len(sources), "maximum_jaccard": maximum, "errors": checker.errors, "limitations": ["Atomic rubric semantics, interacting traps, hint avoidance and scenario originality require human review.", "Suite versions must be supplied explicitly; checker cannot infer provenance from filenames.", "Local artifact evidence must be verified against server execution history."]}
    rendered = json.dumps(summary, indent=2)
    print(rendered)
    if args.summary:
        args.summary.write_text(rendered + "\n", encoding="utf-8")
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
