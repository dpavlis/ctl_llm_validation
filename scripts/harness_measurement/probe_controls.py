#!/home/pavlisd/venv/bin/python
"""Server probes for the validate controls whose [ERROR] claims could not be settled from the code alone.

Each probe feeds the control's reference code a small input built to trigger one recurring claim, runs the acceptance
graph on the CloverDX server (sandbox MiscExamples, suite_v5/agent/probe/), and compares the output rows with what the
task's requirements prescribe. `expect` lists, per output port, the rows in order as partial dicts (only the fields that
decide the claim). A probe passes when the reference does what the requirements say, i.e. the claim is false.

    ~/venv/bin/python scripts/harness_measurement/probe_controls.py [--only T46 T55 ...] \
        --out results/agent_harness/control_probes.json
"""
import argparse, asyncio, json, sys, xml.etree.ElementTree as E
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import agent_harness as AH  # noqa: E402

H = AH.H
CTRL = {r["id"]: r for r in map(json.loads, (ROOT / "data/agent_harness/validate_mutants.jsonl").read_text().splitlines())}
POOL = {r["id"]: r for r in map(json.loads, (ROOT / "data/agent_harness/pool1.jsonl").read_text().splitlines())}
R7, R18 = "rollup_acc_runtime_rollup_acc_sft_007", "rollup_acc_runtime_rollup_acc_sft_018"


def T46(**kw):
    return dict(dict(movement_txt="SHIP", quantity_txt="2", unit_value_txt="1.25", original_manifest=None,
                     dispatch_txt="20260101"), **kw)


def T55a(ref, **kw):   # planned invoice
    return dict(dict(business_ref=ref, tenant_cd="PLAN", source_file="plan.csv", expected_amount="10.00"), **kw)


def T55b(ref, **kw):   # bank entry
    return dict(dict(business_ref=ref, tenant_cd="BANK", source_file="bank.csv", settled_txt="10.00",
                     settlement_state="POSTED"), **kw)


def T56(key, row, **kw):
    return dict(dict(supplier_ref_no=key, source_row_no=row, legal_nm="L", tax_country="CZ", payment_iban="IB",
                     revision_at="2026-01-01 00:00:00", revision_no=1), **kw)


def T58(key, row, op, slot, units="1", **kw):
    return dict(dict(business_ref=key, source_row=row, tenant_cd=f"T{row}", operation=op, slot_id=slot,
                     units_txt=units, observed_at=None, unit_cost="1.00"), **kw)


def T67(trip, no, temp, off=False):
    return dict(trip_id=trip, sample_no=no, temperature_txt=temp, sensor_off=off)


def T69(cur, prev, unit="kWh"):
    return dict(current_text=cur, previous_text=prev, unit_code=unit)


# (control, probe name, claim it tests, inputs per port, expected rows per port)
PROBES = [
    ("suite_T46", "unknown_movement_positive_qty", "sign rule applied to an unknown movement",
     [[T46(movement_txt="HOLD", quantity_txt="12")]], {"1": [dict(defect_list="MOVEMENT")]}),
    ("suite_T46", "unknown_movement_negative_qty", "sign rule applied to an unknown movement",
     [[T46(movement_txt="X", quantity_txt="-7")]], {"1": [dict(defect_list="MOVEMENT")]}),
    ("suite_T46", "unknown_movement_zero_qty", "zero must pass / zero is accepted for unknown movement",
     [[T46(movement_txt="HOLD", quantity_txt="0")]], {"1": [dict(defect_list="MOVEMENT|QTY")]}),
    ("suite_T46", "value_nine_integer_digits", "unit-value regex permits nine integer digits",
     [[T46(unit_value_txt="123456789.50")]], {"1": [dict(defect_list="VALUE")]}),
    ("suite_T46", "value_with_comma", "str2decimal locale: comma text passes the regex",
     [[T46(unit_value_txt="1,234.50")]], {"1": [dict(defect_list="VALUE")]}),
    ("suite_T46", "malformed_value_no_throw", "malformed unit value throws instead of being rejected",
     [[T46(unit_value_txt="abc"), T46(manifest_id="M9", quantity_txt="3", unit_value_txt="2.00")]],
     {"0": [dict(manifest_id="M9", declared_value="6.00")], "1": [dict(defect_list="VALUE")]}),

    ("suite_T55", "void_garbage_bank_only", "VOID row with garbage text is parsed / routed to repair",
     [[], [T55b("V", settlement_state="VOID", settled_txt="garbage!")]],
     {"0": [dict(business_ref="V", reconcile_kind="UNPLANNED", settled_amount="0.00", error_reason="")]}),
    ("suite_T55", "void_garbage_matched_zero", "VOID exemption: matched VOID with zero expected is omitted",
     [[T55a("V", expected_amount="0.00")], [T55b("V", settlement_state="VOID", settled_txt="garbage!")]], {"0": []}),
    ("suite_T55", "void_with_spaces", "VOID compared without trimming (requirement: exactly VOID)",
     [[], [T55b("V", settlement_state=" VOID ", settled_txt="garbage!")]],
     {"0": [dict(reconcile_kind="REPAIR", error_reason="AMOUNT_TEXT")]}),
    ("suite_T55", "null_state_garbage", "null state should get the VOID zero",
     [[], [T55b("N", settlement_state=None, settled_txt="garbage!")]],
     {"0": [dict(reconcile_kind="REPAIR", error_reason="AMOUNT_TEXT")]}),
    ("suite_T55", "bank_only_context", "bank-only row leaves context empty / takes it from the invoice side",
     [[T55a("A")], [T55b("B", settled_txt="4.00")]],
     {"0": [dict(business_ref="A", tenant_cd="PLAN", reconcile_kind="WAITING"),
            dict(business_ref="B", tenant_cd="BANK", source_file="bank.csv", reconcile_kind="UNPLANNED",
                 expected_amount="0.00", settled_amount="4.00", remaining_amount="-4.00")]}),
    ("suite_T55", "matched_context_from_invoice", "matched pair copies the bank side's context",
     [[T55a("M", expected_amount="10.00")], [T55b("M", settled_txt="4.00")]],
     {"0": [dict(business_ref="M", tenant_cd="PLAN", source_file="plan.csv", reconcile_kind="SHORT",
                 remaining_amount="6.00")]}),
    ("suite_T55", "bare_minus_and_dot", "regex accepts a bare '-' or '.'",
     [[], [T55b("D1", settled_txt="-"), T55b("D2", settled_txt=".")]],
     {"0": [dict(business_ref="D1", error_reason="AMOUNT_TEXT"), dict(business_ref="D2", error_reason="AMOUNT_TEXT")]}),
    ("suite_T55", "malformed_bank_null_expected", "repair row should carry zero, not the invoice's null",
     [[T55a("R", expected_amount=None)], [T55b("R", settled_txt="x")]],
     {"0": [dict(error_reason="AMOUNT_TEXT", expected_amount=None, settled_amount=None, remaining_amount=None)]}),
    ("suite_T55", "invoice_only_null_expected", "null expected converted to zero before the EXPECTED_NULL check",
     [[T55a("E", expected_amount=None)], []],
     {"0": [dict(error_reason="EXPECTED_NULL", reconcile_kind="REPAIR", expected_amount=None)]}),

    ("suite_T56", "stale_fields_next_group", "clean() leaves winner fields, next key emits the previous supplier",
     [[T56("A", 1, revision_no=5, tax_country="CZ"),
       T56("B", 2, legal_nm=None, revision_at="2026-05-01 00:00:00"), T56("B", 3, legal_nm=None, revision_at="2026-02-01 00:00:00")]],
     {"0": [dict(supplier_ref_no="A", source_row_no=1, versions_seen=1),
            dict(supplier_ref_no="B", source_row_no=2, winner_complete=False, versions_seen=2)]}),
    ("suite_T56", "complete_null_ts_beats_incomplete", "complete version with null revision_at loses to incomplete",
     [[T56("A", 1, legal_nm=" ", revision_at="2026-06-01 00:00:00"), T56("A", 2, revision_at=None)]],
     {"0": [dict(source_row_no=2, winner_complete=True)]}),
    ("suite_T56", "null_null_revision_tiebreak", "null==null equality false/throws, revision tie-break skipped",
     [[T56("A", 1, revision_at=None, revision_no=9), T56("A", 2, revision_at=None, revision_no=10)]],
     {"0": [dict(source_row_no=2, revision_no=10)]}),
    ("suite_T56", "real_after_null", "date equality throws on a null operand",
     [[T56("A", 1, revision_at=None, revision_no=9), T56("A", 2, revision_no=1)]],
     {"0": [dict(source_row_no=2)]}),
    ("suite_T56", "null_after_real", "a null-revision candidate replaces / throws against a real timestamp",
     [[T56("A", 1, revision_no=1), T56("A", 2, revision_at=None, revision_no=99)]],
     {"0": [dict(source_row_no=1)]}),
    ("suite_T56", "pre_epoch", "pre-epoch timestamp mishandled",
     [[T56("A", 1, revision_at="1970-01-01 00:00:00"), T56("A", 2, revision_at="1969-12-31 00:00:00"),
       T56("B", 3, revision_at="1969-12-31 00:00:00"), T56("B", 4, revision_at="1970-01-01 00:00:00")]],
     {"0": [dict(source_row_no=1), dict(source_row_no=4)]}),

    ("suite_T58", "remove_retracts_all_duplicates", "REMOVE removes only the first/last matching addition",
     [[T58("A", 1, "ADD", "S", "5"), T58("A", 2, "ADD", "S", "6"), T58("A", 3, "ADD", "T", "2"), T58("A", 4, "REMOVE", "S")]],
     {"0": [dict(surviving_slots="T", chosen_slot="T", rows_seen=4)]}),
    ("suite_T58", "add_after_remove", "REMOVE prevents a later ADD",
     [[T58("A", 1, "ADD", "S", "5"), T58("A", 2, "REMOVE", "S"), T58("A", 3, "ADD", "S", "7")]],
     {"0": [dict(surviving_slots="S", chosen_units="7.00")]}),
    ("suite_T58", "second_group_context", "second group's context fields stay from the previous group",
     [[T58("A", 1, "ADD", "S"), T58("A", 2, "ADD", "T"), T58("B", 3, "ADD", "U"), T58("B", 4, "ADD", "V")]],
     {"0": [dict(business_ref="A", source_row=1, tenant_cd="T1"), dict(business_ref="B", source_row=3, tenant_cd="T3")]}),
    ("suite_T58", "tie_null_does_not_replace", "later equal-units null-timestamp addition replaces the pick",
     [[T58("A", 1, "ADD", "S", "5", observed_at="2026-01-01 00:00:00"), T58("A", 2, "ADD", "T", "5")]],
     {"0": [dict(chosen_slot="S")]}),

    ("suite_T67", "new_trip_ignores_stale_baseline", "prevNo/prevTemp not reset at trip change",
     [[T67("A", 5, "0"), T67("B", 100, "7"), T67("C", 0, "7"), T67("C", 1, "1")]],
     {"3": [dict(trip_id="C", sample_no=1)], "4": [dict(trip_id="A"), dict(trip_id="B"), dict(trip_id="C", sample_no=0)]}),
    ("suite_T67", "duplicate_after_gap", "duplicate after a gap sample compared with the wrong predecessor",
     [[T67("A", 10, "0"), T67("A", 12, "6"), T67("A", 12, "6")]],
     {"2": [dict(sample_no=12)], "4": [dict(sample_no=10), dict(sample_no=12)]}),
    ("suite_T67", "temperature_grammar", "regex rejects '7.5' / should accept '7.'",
     [[T67("A", 0, "7.5"), T67("A", 1, "-50"), T67("A", 2, "7."), T67("A", 3, "50.1")]],
     {"1": [dict(sample_no=2), dict(sample_no=3)], "3": [dict(sample_no=1)], "4": [dict(sample_no=0)]}),

    ("suite_T69", "both_invalid", "NEW_BAD/OLD_BAD precedence reversed",
     [[T69("abc", "xyz")]], {"0": [dict(delta_status="NEW_BAD")]}),
    ("suite_T69", "unit_whitespace", "label keeps trailing space / mishandles blank unit",
     [[T69("12.34", "1", unit=" kw "), T69("12.34", "1", unit=" k w "), T69("12.34", "1", unit="   ")]],
     {"0": [dict(reading_label="KW:12.34"), dict(reading_label="K W:12.34"), dict(reading_label=":12.34")]}),

    (R7, "ordinals_and_null_groups", "initGroup ordinal starts at 2 / skips groups; accumulators not reset",
     [[dict(firing_batch=1, thickness=4), dict(firing_batch=1, thickness=9), dict(firing_batch=2, thickness=None),
       dict(firing_batch=3, thickness=5)]],
     {"0": [dict(firing_batch=1, result=5, batch_group=1), dict(firing_batch=2, result=None, batch_group=2),
            dict(firing_batch=3, result=0, batch_group=3)]}),
    (R18, "ordinals_counts_positions", "initGroup ordinal off by one; accumulators carry over between groups",
     [[dict(heat_id=1, signal=None), dict(heat_id=1, signal=3), dict(heat_id=1, signal=8), dict(heat_id=2, signal=None),
       dict(heat_id=3, signal=2)]],
     {"0": [dict(heat_id=1, source_line_count=3, result=8, batch_group=1, peak_position=3),
            dict(heat_id=2, source_line_count=1, result=None, batch_group=2, peak_position=0),
            dict(heat_id=3, source_line_count=1, result=2, batch_group=3, peak_position=1)]}),
]


def matches(actual, expect):
    for port, rows in expect.items():
        got = actual.get(port, [])
        if len(got) != len(rows):
            return False
        for g, e in zip(got, rows):
            if any(g.get(k) != v for k, v in e.items()):
                return False
    return True


async def run_probe(call, cid, name, ports, expect):
    c = CTRL[f"{cid}__control"]
    m, code = POOL[c["task_id"]]["manifests"][0], c["code"]
    root = E.parse(AH.graph_path(m)).getroot()
    metas = {md.get("id"): E.tostring(md.find("Record"), encoding="unicode") for md in root.iter("Metadata")}
    key = f"probe_{m['label']}_{name}"
    xml, outs = AH.candidate_graph(m, code, key)
    remotes = [x["remote"] for x in m["files"] if "/data-in/" in x["local"]]
    for i, rows in enumerate(ports):
        tmpl = m["fixture"]["inputs"][i][0]
        full = [dict(tmpl, **r) for r in rows]
        path = f"{AH.PREFIX}probe/{key}_in{i}.csv"
        await call("sandbox_write_file", dict(sandboxCode=AH.SANDBOX, sandboxPath=path, content=H.csv_text(full, metas[f"In{i}"])))
        xml = xml.replace(f">{remotes[i]}<", f">{path}<")
    gpath = f"{AH.PREFIX}graph/{key}.grf"
    await call("sandbox_write_file", dict(sandboxCode=AH.SANDBOX, sandboxPath=gpath,
                                          content='<?xml version="1.0" encoding="UTF-8"?>\n' + xml))
    run = await call("job_run", dict(sandboxCode=AH.SANDBOX, sandboxPath=gpath, params=m.get("parameters", {})))
    done = await call("job_await", dict(runId=run["runId"], timeoutSeconds=90))
    res = dict(control=cid, probe=name, run_id=run["runId"], status=done.get("status"))
    if done.get("status") != "FINISHED_OK":
        res["error"] = str((done.get("error") or {}).get("message"))[:600]
        return res
    actual = {}
    for port, p in m["output_paths"].items():
        content = await call("sandbox_read_file", dict(sandboxCode=AH.SANDBOX, sandboxPath=outs.get(p, p)))
        text = content if isinstance(content, str) else content.get("content", content.get("text", ""))
        actual[port] = H.parse_actual(text, m["output_metadata"][int(port)])
    res["output"] = {p: [{k: r[k] for k in sorted({k for e in expect.get(p, []) for k in e} or r)} for r in rows]
                     for p, rows in actual.items() if rows}
    res["as_required"] = matches(actual, expect)
    return res


async def main(a):
    todo = [p for p in PROBES if not a.only or any(o in p[0] for o in a.only)]
    out = []
    async with AH.X.streamablehttp_client(AH.MCP_URL, timeout=180) as (rd, wr, _):
        async with AH.X.ClientSession(rd, wr) as s:
            await s.initialize()

            async def call(n, args):
                AH.guard(n, args)
                return AH.X.payload(await s.call_tool(n, args))

            for cid, name, claim, ports, expect in todo:
                r = await run_probe(call, cid, name, ports, expect)
                r.update(claim=claim, expected=expect)
                out.append(r)
                print(f"{cid.replace('rollup_acc_runtime_', ''):32} {name:36} {r['status']:12} "
                      f"{'as required' if r.get('as_required') else 'DIFFERS' if 'output' in r else r.get('error', '')[:200]}",
                      flush=True)
                if not r.get("as_required"):
                    print("    got:", json.dumps(r.get("output"), ensure_ascii=False)[:800], flush=True)
    Path(a.out).write_text(json.dumps(out, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--out", default=str(ROOT / "results/agent_harness/control_probes.json"))
    asyncio.run(main(ap.parse_args()))
