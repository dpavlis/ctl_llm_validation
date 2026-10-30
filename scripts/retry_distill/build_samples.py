"""Retry-distill training rows (spec/retry_distill_brief.md, Data 2-3) in the exec-RFT sample format (opcd.py prompts.exec).

From agent_harness results (k runs x 2 feedback rounds with --rows-feedback) take every triple — attempt 0 failed and a later
attempt passed — and write, per triple, one pool prompt `<task_id>:r<run>` (so exec_rows pairs the corrected answer with
the failure of the SAME run) and two samples: sample 0 = the failed attempt 0 (status = its status), sample 1 = the corrected
answer (pass). Both are re-tokenized under the plain student prompt, as the student will see it:
  off:  answer + <|im_end|>
  on:   thinking + "\\n</think>\\n\\n" + answer + <|im_end|>   (the prompt ends with "<think>\\n")
Thinking-on targets come from a re-sample that stored the thinking text (attempt["think"]). Sentences of the thinking and
of the answer prose that refer to the feedback (error, previous attempt, "the user ran", corrected, ...) are removed and
counted per pattern; a target whose stripped thinking still mentions the error, or shrank below a third / 200 chars, is
dropped. The failed sample (rejected side of the DPO pair) is never stripped (it saw no feedback).

    ~/venv/bin/python scripts/retry_distill/build_samples.py --config configs/opcd_exec_rft1.yaml \\
        --pools data/agent_harness/pool_retry.jsonl data/agent_harness/pool_retry_tweak.jsonl \\
        --off results/agent_harness/c13c_pool_retry_rows.jsonl results/agent_harness/c13c_pool_retry_tweak_rows.jsonl \\
        --on results/agent_harness/c13c_pool_retry_on_think.jsonl --out data/retry_distill
"""
import argparse, collections, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import opcd  # noqa: E402
import self_distill as sd  # noqa: E402

# sentences that refer to the feedback turn; order matters only for the counts (first match wins)
PATTERNS = [
    ("error_message", r"\b(the|this|that|an?) (compil\w+ |runtime |init\w* |server |validation |reported )?error(s)?\b|\berror (message|says|said|is|was|states|indicates|mentions|reported|report)\b|\bNullPointerException\b|\bCannot write to output port\b|\bcannot be resolved\b|\bLine \d+ column\b|\bLine \d+\b"),
    ("previous_attempt", r"\b(previous|earlier|original|first|last|initial|my) (attempt|version|answer|code|solution|implementation|try)\b|\bpreviously\b|\b(I|we) (had|wrote|used|returned|declared|assumed|forgot|missed|left|put)\b"),
    ("user_ran", r"\b(the user|they|you) (ran|tested|executed|reported|says|said|tells|told|got|see|saw|mentioned|observed)\b|\bI ran\b|\bwas run\b|\brunning it\b|\b(this|that|the|its) run\b|\bobserved\b|\bproduced (rows?|\d)"),
    ("failed", r"\bfail(ed|s|ure|ing)?\b|\bdid(n't| not) (work|compile|run|pass|match)\b|\bbroke\b|\bcrash\w*\b"),
    ("wrong_output", r"\b(wrong|incorrect|unexpected|mismatch\w*|differs?|different) (output|rows?|results?|values?|records?)\b|\b(output|rows?|result) (is|was|are|were) (wrong|incorrect|off)\b|\bexpected .{0,60}\b(but|got|actual)\b|\bactual(ly)? (output|rows?|got)\b|\brows? (mismatch|differ)\w*\b"),
    ("fix_corrected", r"\b(fix|fixed|fixes|fixing|correct(ed|ion|ing)|revised|updated|adjusted|patched|repaired|rewrite|rewritten|retry|redo)\b|\bthe (issue|problem|bug|mistake|culprit|root cause)\b|\bwhat went wrong\b|\bchange(d)? (it|this|that|the code)\b"),
    ("feedback", r"\bfeedback\b|\bas (reported|noted|shown|seen|indicated|mentioned)\b|\baccording to the (report|output|run|message)\b|\b(the|this) (report|message|complaint|diagnostic)\b"),
]
STILL_RE = re.compile(r"\berror\b|\bpreviou\w+\b|\bfeedback\b|\bfail\w*\b|\bfix\w*\b|\bcorrected\b", re.I)
SENT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z`\"'(\[$])|\n+")
CODE_RE = re.compile(r"```.*?```", re.S)


# on a fix task the prompt itself shows broken code, so sentences about fixing, failing or the previous version are legitimate;
# only sentences about the RUN (what the harness fed back) are stripped there
FIX_TASK_PATTERNS = {"user_ran", "wrong_output", "feedback", "error_message"}
SPLIT_RE = re.compile(r"((?<=[.!?])[ \t]+(?=[A-Z`\"'(\[$])|\n+)")


def strip_text(text: str, counts: collections.Counter, protect_code: bool, task: str = "generate"):
    """Remove the sentences that refer to the feedback; separators are kept, code blocks are kept whole (protect_code)."""
    pats = [(n, rx) for n, rx in PATTERNS if task != "fix" or n in FIX_TASK_PATTERNS]
    parts, pos = [], 0
    blocks = list(CODE_RE.finditer(text)) if protect_code else []
    for b in blocks + [None]:
        seg = text[pos:b.start()] if b else text[pos:]
        pieces = SPLIT_RE.split(seg)   # sentence, separator, sentence, ...
        kept = []
        for i in range(0, len(pieces), 2):
            sent = pieces[i]; sep = pieces[i + 1] if i + 1 < len(pieces) else ""
            hit = next((n for n, rx in pats if re.search(rx, sent, re.I)), None) if sent.strip() else None
            if hit:
                counts[hit] += 1; counts["_sentences_removed"] += 1
                if kept and "\n" in sep and not kept[-1].endswith("\n"):
                    kept.append(sep)   # keep the paragraph break of a removed sentence
            else:
                kept.append(sent + sep)
        parts.append("".join(kept))
        if b:
            parts.append(b.group(0)); pos = b.end()
    out = re.sub(r"[ \t]+\n", "\n", "".join(parts))
    return re.sub(r"\n{3,}", "\n\n", out).strip()


def build(a):
    cfg = opcd.load_cfg(a.config)
    roles = opcd.Roles(cfg)
    tok = roles.tok
    im_end = tok.convert_tokens_to_ids("<|im_end|>")
    pools = {}
    for pf in a.pools:
        for t in sd.read_jsonl(Path(pf)):
            pools[t["id"]] = dict(t, _file=Path(pf).name)
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    pool_rows, samples = {}, {"off": [], "on": []}
    stats = collections.Counter(); pat = {"off": collections.Counter(), "on": collections.Counter()}
    dropped = []

    def enc(text):
        return tok.encode(text, add_special_tokens=False)

    def completion(mode, think, answer):
        answer = answer.strip()
        if mode == "off":
            return enc(answer) + [im_end]
        return enc(think.strip() + "\n</think>\n\n" + answer) + [im_end]

    for mode, files in (("off", a.off), ("on", a.on)):
        for f in files:
            for r in sd.read_jsonl(Path(f)):
                if r["mode"] != mode or not (r["first"] != "pass" and r["final"] == "pass"):
                    continue
                stats[f"{mode}_triples"] += 1
                t = pools[r["task_id"]]
                a0, ac = r["attempts"][0], r["attempts"][-1]
                assert ac["status"] == "pass" and a0["status"] != "pass"
                if mode == "on" and not (a0.get("think") and ac.get("think")):
                    stats[f"{mode}_no_think"] += 1; continue
                # the target: feedback references stripped from the corrected attempt
                c = collections.Counter()
                think_c = strip_text(ac.get("think") or "", c, protect_code=False, task=t["task"]) if mode == "on" else ""
                ans_c = strip_text(ac["answer"], c, protect_code=True, task=t["task"])
                pat[mode].update(c)
                if "```" not in ans_c:
                    dropped.append((mode, r["task_id"], r["run"], "answer lost its code block")); stats[f"{mode}_dropped"] += 1; continue
                if mode == "on":
                    orig = ac["think"]
                    if STILL_RE.search(think_c) or len(think_c) < max(200, len(orig) / 3):
                        why = "still refers to the error" if STILL_RE.search(think_c) else "thinking shrank too much"
                        dropped.append((mode, r["task_id"], r["run"], why)); stats[f"{mode}_dropped"] += 1; continue
                pid = f"{r['task_id']}:r{r['run']}"
                if pid not in pool_rows:
                    pool_rows[pid] = dict(id=pid, task=t["task"], component=t["component"], source_file=t["_file"], source_id=t["id"],
                                          set=t.get("set"), prompt=t["prompt"])
                base = dict(prompt_id=pid, task_type=t["task"], component=t["component"], mode=mode, hit_cap=False)
                samples[mode].append(dict(base, sample_idx=0, status=a0["status"], cause=a0.get("cause"), detail=(a0.get("detail") or "")[:300],
                                          completion_ids=completion(mode, a0.get("think") or "", a0["answer"]),
                                          thinking=a0.get("think") or "", answer=a0["answer"]))
                samples[mode].append(dict(base, sample_idx=1, status="pass", completion_ids=completion(mode, think_c, ans_c),
                                          thinking=think_c, answer=ans_c, orig_thinking=ac.get("think") or "", orig_answer=ac["answer"],
                                          stripped=dict(c)))
                stats[f"{mode}_kept"] += 1
    with open(out / "pool.jsonl", "w") as fh:
        for p in pool_rows.values():
            fh.write(json.dumps(p, ensure_ascii=False) + "\n")
    for mode in ("off", "on"):
        with open(out / f"samples_{mode}.jsonl", "w") as fh:
            for s in samples[mode]:
                fh.write(json.dumps(s, ensure_ascii=False) + "\n")
    lens = {m: sorted(len(s["completion_ids"]) for s in samples[m] if s["sample_idx"] == 1) for m in ("off", "on")}
    rep = dict(stats=dict(stats), patterns=dict(pat), dropped=dropped, prompts=len(pool_rows),
               by_component=dict(collections.Counter(p["component"] for p in pool_rows.values())),
               by_set=dict(collections.Counter(p["set"] for p in pool_rows.values())),
               by_cause={m: dict(collections.Counter((s.get("cause") or s["status"]) for s in samples[m] if s["sample_idx"] == 0)) for m in ("off", "on")},
               target_tokens={m: dict(n=len(l), median=l[len(l) // 2] if l else 0, max=l[-1] if l else 0) for m, l in lens.items()})
    (out / "report.json").write_text(json.dumps(rep, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({k: v for k, v in rep.items() if k != "dropped"}, indent=1))
    print("dropped:", len(dropped))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/opcd_exec_rft1.yaml")
    ap.add_argument("--pools", nargs="+", required=True)
    ap.add_argument("--off", nargs="*", default=[])
    ap.add_argument("--on", nargs="*", default=[])
    ap.add_argument("--out", default="data/retry_distill")
    build(ap.parse_args())
