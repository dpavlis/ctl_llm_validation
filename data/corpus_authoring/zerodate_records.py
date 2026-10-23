"""Authoring source for the zeroDate() corpus records (2026-10-23, findings §3.30 follow-up).

rb1012s2 wrote `zeroDate` without parentheses 48 times, as a placeholder value (`date d = zeroDate;`). The corpus uses
`zeroDate()` correctly everywhere (430 code uses) but never explains that it is a function, nor when a placeholder date is
wrong. These records teach:
  - `zeroDate()` is a function returning 1970-01-01 00:00:00 GMT; the bare name is an undeclared variable
    (compiler: "Variable 'zeroDate' is not declared");
  - a declared `date` variable without an initializer already holds the epoch, so `= zeroDate()` adds nothing;
  - a missing date is better left null than replaced by a fake 1970 value; an epoch sentinel also breaks min/max logic;
  - legitimate use: the Unix epoch as a reference point, e.g. dateDiff(d, zeroDate(), second).

RECORDS / DPO hold the text. Each code block that should run has a CHECK entry (metadata, input rows, expected rows)
used by data/corpus_authoring/verify_zerodate.py, which compiles every block on the CloverDX server, runs the graphs and
writes the corpus files.
"""

SYSTEM = ("You are a CloverDX ETL expert specializing in transformation graphs, components, and CTL2. CTL and CTL2 mean "
          "the same language. Help users write, debug, and explain CTL2 code and related concepts. Provide working code, "
          "explanation, or both as needed. Prefer correct, practical, minimal solutions.")

def rec(fields, name):
    out = [f'<Record name="{name}" type="delimited" fieldDelimiter="|" recordDelimiter="\\n" nullValue="__NULL__">']
    for f in fields:
        n, t, nul = f[0], f[1], f[2]
        extra = ' format="yyyy-MM-dd HH:mm:ss" timeZone="UTC"' if t == "date" else ""
        out.append(f'  <Field name="{n}" type="{t}" nullable="{nul}"{extra}/>')
    out.append("</Record>")
    return "\n".join(out)

def meta_block(label, xml):
    return f"{label}:\n```xml\n{xml}\n```"

# ---------------------------------------------------------------- metadata
SCAN_IN = rec([("parcel_id", "string", "false"), ("scanned_at_text", "string", "true")], "ParcelScanIn")
SCAN_OUT = rec([("parcel_id", "string", "false"), ("scanned_at", "date", "true"), ("has_scan", "boolean", "false")], "ParcelScanOut")

EVT_IN = rec([("event_id", "string", "false"), ("occurred_at", "date", "false")], "TelemetryEvent")
EVT_OUT = rec([("event_id", "string", "false"), ("epoch_seconds", "long", "false")], "TelemetryEpoch")

INSP_IN = rec([("vessel", "string", "false"), ("inspected_on", "date", "true")], "HullInspection")
INSP_ACC = rec([("earliest", "date", "true"), ("inspections", "integer", "false")], "HullInspectionState")
INSP_OUT = rec([("vessel", "string", "false"), ("earliest_inspection", "date", "true"), ("inspections", "integer", "false")], "HullInspectionSummary")

POL_IN = rec([("policy_no", "string", "false"), ("effective_at", "date", "true")], "PolicyEffective")
POL_OUT = rec([("policy_no", "string", "false"), ("effective_at", "date", "false")], "PolicyEffectiveFilled")

BADGE_IN = rec([("site", "string", "false"), ("badge_id", "string", "false"), ("seen_at", "date", "true")], "BadgeSighting")
BADGE_ACC = rec([("first_seen", "date", "true"), ("sightings", "integer", "false")], "BadgeSiteState")
BADGE_OUT = rec([("site", "string", "false"), ("first_seen", "date", "true"), ("sightings", "integer", "false")], "BadgeSiteSummary")

MAIL_IN = rec([("letter_id", "string", "false"), ("sent_at", "date", "false")], "ArchiveLetter")
MAIL_OUT = rec([("letter_id", "string", "false"), ("era", "string", "false")], "ArchiveLetterEra")

READ_IN = rec([("meter_id", "string", "false"), ("read_at", "date", "false"), ("kwh", "decimal", "false")], "MeterRead")
READ_OUT = rec([("meter_id", "string", "false"), ("read_epoch_ms", "long", "false"), ("kwh", "decimal", "false")], "MeterReadEpoch")

LOAN_IN = rec([("loan_id", "string", "false"), ("returned_at_text", "string", "true")], "LibraryReturn")
LOAN_OUT = rec([("loan_id", "string", "false"), ("returned_at", "date", "true")], "LibraryReturnParsed")

TRIP_IN = rec([("route", "string", "false"), ("arrived_at", "date", "true")], "FerryArrival")
TRIP_ACC = rec([("latest", "date", "true")], "FerryRouteState")
TRIP_OUT = rec([("route", "string", "false"), ("latest_arrival", "date", "true")], "FerryRouteSummary")

# ---------------------------------------------------------------- code
C_SCAN = '''//#CTL2
function integer transform() {
    $out.0.parcel_id = $in.0.parcel_id;
    string raw = trim(nvl($in.0.scanned_at_text, ""));
    if (isEmpty(raw)) {
        $out.0.scanned_at = null;
        $out.0.has_scan = false;
    } else {
        $out.0.scanned_at = str2date(raw, "yyyy-MM-dd HH:mm:ss", "en.US", "UTC");
        $out.0.has_scan = true;
    }
    return ALL;
}'''

C_EPOCH = '''//#CTL2
function integer transform() {
    $out.0.event_id = $in.0.event_id;
    $out.0.epoch_seconds = dateDiff($in.0.occurred_at, zeroDate(), second);
    return ALL;
}'''

C_INSP = '''//#CTL2
function void initGroup(HullInspectionState acc) {
    acc.inspections = 0;
}

function boolean updateGroup(HullInspectionState acc) {
    acc.inspections++;
    date d = $in.0.inspected_on;
    if (d != null && (isnull(acc.earliest) || d < acc.earliest)) {
        acc.earliest = d;
    }
    return false;
}

function integer updateTransform(integer counter, HullInspectionState acc) {
    return SKIP;
}

function boolean finishGroup(HullInspectionState acc) {
    return true;
}

function integer transform(integer counter, HullInspectionState acc) {
    if (counter > 0) {
        return SKIP;
    }
    $out.0.vessel = $in.0.vessel;
    $out.0.earliest_inspection = acc.earliest;
    $out.0.inspections = acc.inspections;
    return ALL;
}'''

C_POL_BAD = '''//#CTL2
function integer transform() {
    $out.0.policy_no = $in.0.policy_no;
    $out.0.effective_at = nvl($in.0.effective_at, zeroDate);
    return ALL;
}'''
C_POL = C_POL_BAD.replace("zeroDate)", "zeroDate())")

C_BADGE_BAD = '''//#CTL2
function void initGroup(BadgeSiteState acc) {
    acc.first_seen = zeroDate;
    acc.sightings = 0;
}

function boolean updateGroup(BadgeSiteState acc) {
    acc.sightings++;
    if ($in.0.seen_at != null && $in.0.seen_at < acc.first_seen) {
        acc.first_seen = $in.0.seen_at;
    }
    return false;
}

function integer updateTransform(integer counter, BadgeSiteState acc) {
    return SKIP;
}

function boolean finishGroup(BadgeSiteState acc) {
    return true;
}

function integer transform(integer counter, BadgeSiteState acc) {
    if (counter > 0) {
        return SKIP;
    }
    $out.0.site = $in.0.site;
    $out.0.first_seen = acc.first_seen;
    $out.0.sightings = acc.sightings;
    return ALL;
}'''
C_BADGE = C_BADGE_BAD.replace("    acc.first_seen = zeroDate;\n", "").replace(
    "if ($in.0.seen_at != null && $in.0.seen_at < acc.first_seen) {",
    "if ($in.0.seen_at != null && (isnull(acc.first_seen) || $in.0.seen_at < acc.first_seen)) {")

C_MAIL_BAD = '''//#CTL2
function integer transform() {
    $out.0.letter_id = $in.0.letter_id;
    if ($in.0.sent_at < zeroDate) {
        $out.0.era = "PRE_EPOCH";
    } else {
        $out.0.era = "EPOCH";
    }
    return ALL;
}'''
C_MAIL = C_MAIL_BAD.replace("< zeroDate)", "< zeroDate())")

C_READ_BAD = '''//#CTL2
function integer transform() {
    date epoch = zeroDate;
    $out.0.meter_id = $in.0.meter_id;
    $out.0.read_epoch_ms = dateDiff($in.0.read_at, epoch, millisec);
    $out.0.kwh = $in.0.kwh;
    return ALL;
}'''
C_READ = '''//#CTL2
function integer transform() {
    $out.0.meter_id = $in.0.meter_id;
    $out.0.read_epoch_ms = dateDiff($in.0.read_at, zeroDate(), millisec);
    $out.0.kwh = $in.0.kwh;
    return ALL;
}'''

C_FIRST = '''//#CTL2
date previous;

function integer transform() {
    $out.0.meter_id = $in.0.meter_id;
    if (previous == zeroDate()) {
        $out.0.read_epoch_ms = 0L;
    } else {
        $out.0.read_epoch_ms = dateDiff($in.0.read_at, previous, millisec);
    }
    $out.0.kwh = $in.0.kwh;
    previous = $in.0.read_at;
    return ALL;
}'''

C_REDUNDANT = '''//#CTL2
function integer transform() {
    date cutoff = zeroDate();
    cutoff = str2date("2020-01-01 00:00:00", "yyyy-MM-dd HH:mm:ss", "en.US", "UTC");
    $out.0.letter_id = $in.0.letter_id;
    if ($in.0.sent_at < cutoff) {
        $out.0.era = "LEGACY";
    } else {
        $out.0.era = "CURRENT";
    }
    return ALL;
}'''

C_LOAN = '''//#CTL2
function integer transform() {
    $out.0.loan_id = $in.0.loan_id;
    string raw = trim(nvl($in.0.returned_at_text, ""));
    if (isEmpty(raw)) {
        $out.0.returned_at = null;
    } else {
        $out.0.returned_at = str2date(raw, "yyyy-MM-dd HH:mm:ss", "en.US", "UTC");
    }
    return ALL;
}'''
C_LOAN_SENTINEL = C_LOAN.replace("$out.0.returned_at = null;", "$out.0.returned_at = zeroDate();")

C_TRIP = '''//#CTL2
function void initGroup(FerryRouteState acc) {
}

function boolean updateGroup(FerryRouteState acc) {
    if ($in.0.arrived_at != null && (isnull(acc.latest) || $in.0.arrived_at > acc.latest)) {
        acc.latest = $in.0.arrived_at;
    }
    return false;
}

function integer updateTransform(integer counter, FerryRouteState acc) {
    return SKIP;
}

function boolean finishGroup(FerryRouteState acc) {
    return true;
}

function integer transform(integer counter, FerryRouteState acc) {
    if (counter > 0) {
        return SKIP;
    }
    $out.0.route = $in.0.route;
    $out.0.latest_arrival = acc.latest;
    return ALL;
}'''
C_TRIP_SENTINEL = C_TRIP.replace("function void initGroup(FerryRouteState acc) {\n}",
                                 "function void initGroup(FerryRouteState acc) {\n    acc.latest = zeroDate();\n}").replace(
    "if ($in.0.arrived_at != null && (isnull(acc.latest) || $in.0.arrived_at > acc.latest)) {",
    "if ($in.0.arrived_at != null && $in.0.arrived_at > acc.latest) {")

C_CUTOFF_BAD = '''//#CTL2
function integer transform() {
    date cutoff = zeroDate;
    $out.0.letter_id = $in.0.letter_id;
    if ($in.0.sent_at < cutoff) {
        $out.0.era = "PRE_EPOCH";
    } else {
        $out.0.era = "EPOCH";
    }
    return ALL;
}'''
C_CUTOFF = C_CUTOFF_BAD.replace("date cutoff = zeroDate;", "date cutoff = zeroDate();")
C_CUTOFF_TODAY = C_CUTOFF_BAD.replace("date cutoff = zeroDate;", "date cutoff = today();")

def ctl(code):
    return f"```ctl\n{code}\n```"

# ---------------------------------------------------------------- fixtures (runtime checks)
CHECKS = {
    "scan": dict(component="Reformat", ins=[SCAN_IN], outs=[SCAN_OUT],
                 inputs=[[{"parcel_id": "P1", "scanned_at_text": "2026-03-04 10:15:00"}, {"parcel_id": "P2", "scanned_at_text": None},
                          {"parcel_id": "P3", "scanned_at_text": "   "}, {"parcel_id": "P4", "scanned_at_text": " 2025-12-31 23:59:59 "}]],
                 expected={"0": [{"parcel_id": "P1", "scanned_at": "2026-03-04 10:15:00", "has_scan": True},
                                 {"parcel_id": "P2", "scanned_at": None, "has_scan": False},
                                 {"parcel_id": "P3", "scanned_at": None, "has_scan": False},
                                 {"parcel_id": "P4", "scanned_at": "2025-12-31 23:59:59", "has_scan": True}]}),
    "epoch": dict(component="Reformat", ins=[EVT_IN], outs=[EVT_OUT],
                  inputs=[[{"event_id": "E1", "occurred_at": "1970-01-01 00:00:00"}, {"event_id": "E2", "occurred_at": "2026-01-01 00:00:00"},
                           {"event_id": "E3", "occurred_at": "2026-07-01 12:30:15"}]],
                  expected={"0": [{"event_id": "E1", "epoch_seconds": 0}, {"event_id": "E2", "epoch_seconds": 1767225600},
                                  {"event_id": "E3", "epoch_seconds": 1782909015}]}),
    "insp": dict(component="Rollup", ins=[INSP_IN], outs=[INSP_OUT], acc=INSP_ACC, settings={"groupKeyFields": "vessel"},
                 inputs=[[{"vessel": "Aurora", "inspected_on": "2024-05-02 00:00:00"}, {"vessel": "Aurora", "inspected_on": None},
                          {"vessel": "Aurora", "inspected_on": "2023-11-20 00:00:00"}, {"vessel": "Boreas", "inspected_on": None},
                          {"vessel": "Corvus", "inspected_on": "2025-01-15 00:00:00"}]],
                 expected={"0": [{"vessel": "Aurora", "earliest_inspection": "2023-11-20 00:00:00", "inspections": 3},
                                 {"vessel": "Boreas", "earliest_inspection": None, "inspections": 1},
                                 {"vessel": "Corvus", "earliest_inspection": "2025-01-15 00:00:00", "inspections": 1}]}),
    "pol": dict(component="Reformat", ins=[POL_IN], outs=[POL_OUT],
                inputs=[[{"policy_no": "PL-1", "effective_at": "2024-02-01 00:00:00"}, {"policy_no": "PL-2", "effective_at": None}]],
                expected={"0": [{"policy_no": "PL-1", "effective_at": "2024-02-01 00:00:00"},
                                {"policy_no": "PL-2", "effective_at": "1970-01-01 00:00:00"}]}),
    "badge": dict(component="Rollup", ins=[BADGE_IN], outs=[BADGE_OUT], acc=BADGE_ACC, settings={"groupKeyFields": "site"},
                  inputs=[[{"site": "North", "badge_id": "B1", "seen_at": "2026-02-10 08:00:00"}, {"site": "North", "badge_id": "B2", "seen_at": "2026-02-09 17:30:00"},
                           {"site": "South", "badge_id": "B3", "seen_at": None}, {"site": "West", "badge_id": "B4", "seen_at": None},
                           {"site": "West", "badge_id": "B5", "seen_at": "2026-03-01 06:45:00"}]],
                  expected={"0": [{"site": "North", "first_seen": "2026-02-09 17:30:00", "sightings": 2},
                                  {"site": "South", "first_seen": None, "sightings": 1},
                                  {"site": "West", "first_seen": "2026-03-01 06:45:00", "sightings": 2}]}),
    "mail": dict(component="Reformat", ins=[MAIL_IN], outs=[MAIL_OUT],
                 inputs=[[{"letter_id": "L1", "sent_at": "1969-12-31 23:59:59"}, {"letter_id": "L2", "sent_at": "1970-01-01 00:00:00"},
                          {"letter_id": "L3", "sent_at": "1998-06-30 09:00:00"}]],
                 expected={"0": [{"letter_id": "L1", "era": "PRE_EPOCH"}, {"letter_id": "L2", "era": "EPOCH"}, {"letter_id": "L3", "era": "EPOCH"}]}),
    "read": dict(component="Reformat", ins=[READ_IN], outs=[READ_OUT],
                 inputs=[[{"meter_id": "M1", "read_at": "1970-01-01 00:00:01", "kwh": "1.50"}, {"meter_id": "M2", "read_at": "2026-01-01 00:00:00", "kwh": "20.00"}]],
                 expected={"0": [{"meter_id": "M1", "read_epoch_ms": 1000, "kwh": "1.50"}, {"meter_id": "M2", "read_epoch_ms": 1767225600000, "kwh": "20.00"}]}),
    "first": dict(component="Reformat", ins=[READ_IN], outs=[READ_OUT],
                  inputs=[[{"meter_id": "M1", "read_at": "2026-01-01 00:00:00", "kwh": "1.00"}, {"meter_id": "M1", "read_at": "2026-01-01 00:15:00", "kwh": "2.00"},
                           {"meter_id": "M1", "read_at": "2026-01-01 00:45:00", "kwh": "3.00"}]],
                  expected={"0": [{"meter_id": "M1", "read_epoch_ms": 0, "kwh": "1.00"}, {"meter_id": "M1", "read_epoch_ms": 900000, "kwh": "2.00"},
                                  {"meter_id": "M1", "read_epoch_ms": 1800000, "kwh": "3.00"}]}),
    "redundant": dict(component="Reformat", ins=[MAIL_IN], outs=[MAIL_OUT],
                      inputs=[[{"letter_id": "L1", "sent_at": "2019-12-31 23:59:59"}, {"letter_id": "L2", "sent_at": "2020-01-01 00:00:00"}]],
                      expected={"0": [{"letter_id": "L1", "era": "LEGACY"}, {"letter_id": "L2", "era": "CURRENT"}]}),
    "loan": dict(component="Reformat", ins=[LOAN_IN], outs=[LOAN_OUT],
                 inputs=[[{"loan_id": "K1", "returned_at_text": "2026-04-02 14:00:00"}, {"loan_id": "K2", "returned_at_text": None}, {"loan_id": "K3", "returned_at_text": ""}]],
                 expected={"0": [{"loan_id": "K1", "returned_at": "2026-04-02 14:00:00"}, {"loan_id": "K2", "returned_at": None}, {"loan_id": "K3", "returned_at": None}]}),
    "trip": dict(component="Rollup", ins=[TRIP_IN], outs=[TRIP_OUT], acc=TRIP_ACC, settings={"groupKeyFields": "route"},
                 inputs=[[{"route": "R1", "arrived_at": "2026-05-01 09:10:00"}, {"route": "R1", "arrived_at": "2026-05-01 18:40:00"},
                          {"route": "R2", "arrived_at": None}, {"route": "R3", "arrived_at": None}, {"route": "R3", "arrived_at": "2026-05-02 07:05:00"}]],
                 expected={"0": [{"route": "R1", "latest_arrival": "2026-05-01 18:40:00"}, {"route": "R2", "latest_arrival": None},
                                 {"route": "R3", "latest_arrival": "2026-05-02 07:05:00"}]}),
}

# ---------------------------------------------------------------- SFT records
# each: id, user, assistant, blocks = [(code, expect, check)], expect in PASS / FAIL:<message part> ; check = CHECKS key or None
RECORDS = [
    dict(id="zerodate_sft_001", blocks=[(C_SCAN, "PASS", "scan")],
         user="Write a Reformat transform for the parcel scan feed. Copy parcel_id. Parse scanned_at_text (format "
              "yyyy-MM-dd HH:mm:ss, UTC; surrounding spaces may occur) into scanned_at. When the text is missing or blank, "
              "the scan time is unknown and has_scan is false; otherwise has_scan is true.\n\n"
              + meta_block("Input port 0", SCAN_IN) + "\n" + meta_block("Output port 0", SCAN_OUT),
         assistant=ctl(C_SCAN) + "\n\nAn unknown scan time stays null. Filling it with `zeroDate()` would turn a missing "
              "scan into one that looks real, dated 1970-01-01 00:00:00 GMT, and every later date comparison would treat it as "
              "the oldest scan."),
    dict(id="zerodate_sft_002", blocks=[(C_EPOCH, "PASS", "epoch")],
         user="Telemetry events need a Unix timestamp. Copy event_id and output epoch_seconds, the number of whole seconds "
              "from 1970-01-01 00:00:00 GMT to occurred_at.\n\n"
              + meta_block("Input port 0", EVT_IN) + "\n" + meta_block("Output port 0", EVT_OUT),
         assistant=ctl(C_EPOCH) + "\n\n`zeroDate()` returns the epoch, 1970-01-01 00:00:00 GMT, so the difference in seconds "
              "is the Unix timestamp. It is a function: the parentheses are required."),
    dict(id="zerodate_sft_003", blocks=[(C_INSP, "PASS", "insp")],
         user="Hull inspections arrive grouped by vessel. For each vessel output the earliest inspected_on date and the "
              "number of inspection records. Records without a date still count; a vessel with no dated record gets no "
              "earliest date.\n\n" + meta_block("Input port 0", INSP_IN) + "\n" + meta_block("Accumulator", INSP_ACC)
              + "\n" + meta_block("Output port 0", INSP_OUT) + "\n\nWrite the complete Rollup CTL2.",
         assistant=ctl(C_INSP) + "\n\n`earliest` is nullable without a default, so it starts every group null and stays null "
              "for a vessel with no dated record. Seeding it with `zeroDate()` would be wrong twice: the 1970 epoch is earlier "
              "than any real inspection, so it would always remain the minimum, and undated vessels would report a 1970 date."),
    dict(id="zerodate_sft_004", blocks=[(C_POL_BAD, "FAIL:Variable 'zeroDate' is not declared", None), (C_POL, "PASS", "pol")],
         user="Fix this Reformat transform so that it compiles and does what the specification says. List every problem you "
              "fix with the reason, then give the complete corrected code.\n\nSpecification: copy policy_no; effective_at "
              "is copied, and a missing effective_at becomes the Unix epoch, 1970-01-01 00:00:00 GMT, which downstream "
              "reports treat as \"no effective date\".\n\n" + meta_block("Input port 0", POL_IN) + "\n"
              + meta_block("Output port 0", POL_OUT) + "\n\n" + ctl(C_POL_BAD),
         assistant="1. `zeroDate` is written without parentheses. It is a built-in function, not a constant, so the compiler "
              "reads the bare name as a variable and fails with \"Variable 'zeroDate' is not declared\". Calling "
              "`zeroDate()` returns the required epoch value.\n\n" + ctl(C_POL)),
    dict(id="zerodate_sft_005", blocks=[(C_BADGE_BAD, "FAIL:Variable 'zeroDate' is not declared", None), (C_BADGE, "PASS", "badge")],
         user="Fix this Rollup transform so that it compiles and does what the specification says. List every problem you fix "
              "with the reason, then give the complete corrected code.\n\nSpecification: badge sightings are grouped by site. "
              "Output the earliest seen_at per site (null when no sighting in the site has a time) and the number of "
              "sightings.\n\n" + meta_block("Input port 0", BADGE_IN) + "\n" + meta_block("Accumulator", BADGE_ACC) + "\n"
              + meta_block("Output port 0", BADGE_OUT) + "\n\n" + ctl(C_BADGE_BAD),
         assistant="1. `acc.first_seen = zeroDate;` does not compile: `zeroDate` is a function, and the bare name is reported "
              "as \"Variable 'zeroDate' is not declared\". Writing `zeroDate()` would compile but still be wrong: the 1970 "
              "epoch is earlier than every sighting, so no `seen_at` would ever replace it, and sites without a timed sighting "
              "would report 1970. The line is removed; `first_seen` is nullable, so the accumulator reset already starts it "
              "null for every site.\n2. With `first_seen` starting null, the comparison needs a null check: the first timed "
              "sighting is taken when `first_seen` is still null, and later ones only when they are earlier.\n\n" + ctl(C_BADGE)),
    dict(id="zerodate_sft_006", blocks=[(C_MAIL_BAD, "FAIL:Variable 'zeroDate' is not declared", None), (C_MAIL, "PASS", "mail")],
         user="Fix this Reformat transform so that it compiles and does what the specification says. List every problem you "
              "fix with the reason, then give the complete corrected code.\n\nSpecification: archive letters sent before "
              "1970-01-01 00:00:00 GMT are PRE_EPOCH, all others EPOCH.\n\n" + meta_block("Input port 0", MAIL_IN) + "\n"
              + meta_block("Output port 0", MAIL_OUT) + "\n\n" + ctl(C_MAIL_BAD),
         assistant="1. The comparison uses `zeroDate` as if it were a constant. It is a function returning 1970-01-01 00:00:00 "
              "GMT; without parentheses the compiler reports \"Variable 'zeroDate' is not declared\". The fix calls "
              "`zeroDate()`.\n\n" + ctl(C_MAIL)),
    dict(id="zerodate_sft_007", blocks=[(C_READ_BAD, "FAIL:Variable 'zeroDate' is not declared", None)],
         user="Validate this Reformat transform. It should output read_epoch_ms, the milliseconds from the Unix epoch to "
              "read_at, together with meter_id and kwh.\n\n" + meta_block("Input port 0", READ_IN) + "\n"
              + meta_block("Output port 0", READ_OUT) + "\n\n" + ctl(C_READ_BAD),
         assistant="ISSUES:\n  [ERROR] `date epoch = zeroDate;` does not compile. `zeroDate` is a built-in function, so the bare "
              "name is read as an undeclared variable (\"Variable 'zeroDate' is not declared\") and the transform fails when "
              "the graph starts.\n\nSUGGESTIONS:\n  - Call the function: `dateDiff($in.0.read_at, zeroDate(), millisec)`; the "
              "local `epoch` variable is then unnecessary.\n\nVERDICT: FAIL"),
    dict(id="zerodate_sft_008", blocks=[(C_FIRST, "PASS", "first")],
         user="Validate this Reformat transform. For each meter reading it outputs the milliseconds since the previous "
              "reading in the input, and 0 for the first reading. Readings arrive in time order and are all later than "
              "1970.\n\n" + meta_block("Input port 0", READ_IN) + "\n" + meta_block("Output port 0", READ_OUT) + "\n\n" + ctl(C_FIRST),
         assistant="ISSUES: none\nVERDICT: PASS"),
    dict(id="zerodate_sft_009", blocks=[(C_REDUNDANT, "PASS", "redundant")],
         user="Validate this Reformat transform. Letters sent before 2020-01-01 00:00:00 UTC are LEGACY, the rest CURRENT.\n\n"
              + meta_block("Input port 0", MAIL_IN) + "\n" + meta_block("Output port 0", MAIL_OUT) + "\n\n" + ctl(C_REDUNDANT),
         assistant="ISSUES:\n  [INFO] `date cutoff = zeroDate();` is redundant: a declared `date` variable already starts at the "
              "epoch, and the next line overwrites the value anyway. A date literal states the cutoff directly: "
              "`date cutoff = 2020-01-01 00:00:00;`.\n\nVERDICT: PASS"),
    dict(id="zerodate_sft_010", blocks=[],
         user="Is `zeroDate` a constant in CTL2? Can I write `date start = zeroDate;` to give a date variable a starting value?",
         assistant="No. `zeroDate()` is a function with no arguments that returns 1970-01-01 00:00:00 GMT, and it has to be called "
              "with parentheses. `date start = zeroDate;` fails to compile with \"Variable 'zeroDate' is not declared\".\n\n"
              "You usually do not need it as a starting value at all. A declared `date` variable without an initializer "
              "already holds the epoch, so `date start;` is equivalent to `date start = zeroDate();`. When the value means "
              "\"no date yet\", null is clearer than 1970: a nullable field or a variable set to null cannot be mistaken for "
              "a real date, and min/max logic does not pick it up. Use `zeroDate()` where the epoch itself is meant, for "
              "example `dateDiff(d, zeroDate(), second)` for a Unix timestamp."),
]

# ---------------------------------------------------------------- DPO pairs
DPO = [
    dict(id="zerodate_dpo_001",
         prompt="Meter reads need an epoch timestamp. Copy meter_id and kwh and output read_epoch_ms, the milliseconds from "
                "1970-01-01 00:00:00 GMT to read_at.\n\n" + meta_block("Input port 0", READ_IN) + "\n" + meta_block("Output port 0", READ_OUT),
         chosen=ctl(C_READ), rejected=ctl(C_READ.replace("zeroDate()", "zeroDate")),
         blocks=[(C_READ, "PASS", "read"), (C_READ.replace("zeroDate()", "zeroDate"), "FAIL:Variable 'zeroDate' is not declared", None)]),
    dict(id="zerodate_dpo_002",
         prompt="Write a Reformat transform for library returns. Copy loan_id and parse returned_at_text (format yyyy-MM-dd "
                "HH:mm:ss, UTC) into returned_at. A loan without a return text has not been returned yet.\n\n"
                + meta_block("Input port 0", LOAN_IN) + "\n" + meta_block("Output port 0", LOAN_OUT),
         chosen=ctl(C_LOAN) + "\n\nA loan that has not been returned keeps a null return time, which downstream logic can test "
                "with `isnull()`.",
         rejected=ctl(C_LOAN_SENTINEL) + "\n\nA loan that has not been returned gets `zeroDate()`, a safe default date that "
                "avoids nulls downstream.",
         blocks=[(C_LOAN, "PASS", "loan"), (C_LOAN_SENTINEL, "PASS", "loan!")]),
    dict(id="zerodate_dpo_003",
         prompt="What does `zeroDate` mean in CTL2, and how do I use it?",
         chosen="`zeroDate()` is a function that returns the Unix epoch, 1970-01-01 00:00:00 GMT. Call it with parentheses: "
                "`date d = zeroDate();`. Without them, `zeroDate` is read as a variable name and the compiler reports "
                "\"Variable 'zeroDate' is not declared\". It is useful where the epoch itself matters, such as "
                "`dateDiff(d, zeroDate(), second)` for a Unix timestamp; a declared `date` variable already starts at the epoch "
                "without it.",
         rejected="`zeroDate` is a built-in date constant equal to the Unix epoch, 1970-01-01 00:00:00 GMT. Use it like any "
                "constant, without parentheses: `date d = zeroDate;`. It is handy as a default value for dates that are "
                "missing.",
         blocks=[]),
    dict(id="zerodate_dpo_004",
         prompt="Validate this Reformat transform. Letters sent before 1970-01-01 00:00:00 GMT are PRE_EPOCH, the others "
                "EPOCH.\n\n" + meta_block("Input port 0", MAIL_IN) + "\n" + meta_block("Output port 0", MAIL_OUT) + "\n\n" + ctl(C_CUTOFF_BAD),
         chosen="ISSUES:\n  [ERROR] `date cutoff = zeroDate;` does not compile: `zeroDate` is a function, and the bare name is "
                "reported as \"Variable 'zeroDate' is not declared\", so the component fails at startup.\n\nSUGGESTIONS:\n  - "
                "Write `date cutoff = zeroDate();`.\n\nVERDICT: FAIL",
         rejected="ISSUES: none\nVERDICT: PASS",
         blocks=[(C_CUTOFF_BAD, "FAIL:Variable 'zeroDate' is not declared", None)]),
    dict(id="zerodate_dpo_005",
         prompt="Ferry arrivals are grouped by route. Output the latest arrived_at per route; a route with no timed arrival has "
                "no latest arrival.\n\n" + meta_block("Input port 0", TRIP_IN) + "\n" + meta_block("Accumulator", TRIP_ACC)
                + "\n" + meta_block("Output port 0", TRIP_OUT) + "\n\nWrite the complete Rollup CTL2.",
         chosen=ctl(C_TRIP) + "\n\n`latest` is nullable, so it starts each route null, and a route without a timed arrival "
                "outputs null.",
         rejected=ctl(C_TRIP_SENTINEL) + "\n\n`latest` starts at `zeroDate()`, so the first arrival always replaces it.",
         blocks=[(C_TRIP, "PASS", "trip"), (C_TRIP_SENTINEL, "PASS", "trip!")]),
    dict(id="zerodate_dpo_006",
         prompt="Fix this Reformat transform so that it compiles and does what the specification says. List every problem you "
                "fix with the reason, then give the complete corrected code.\n\nSpecification: letters sent before "
                "1970-01-01 00:00:00 GMT are PRE_EPOCH, all others EPOCH.\n\n" + meta_block("Input port 0", MAIL_IN) + "\n"
                + meta_block("Output port 0", MAIL_OUT) + "\n\n" + ctl(C_CUTOFF_BAD),
         chosen="1. `zeroDate` is a function and needs parentheses; the bare name fails with \"Variable 'zeroDate' is not "
                "declared\". `zeroDate()` returns 1970-01-01 00:00:00 GMT, the required cutoff.\n\n" + ctl(C_CUTOFF),
         rejected="1. `zeroDate` is not a valid name, so the cutoff is taken from `today()` instead.\n\n" + ctl(C_CUTOFF_TODAY),
         blocks=[(C_CUTOFF, "PASS", "mail"), (C_CUTOFF_TODAY, "PASS", "mail!")]),
]
