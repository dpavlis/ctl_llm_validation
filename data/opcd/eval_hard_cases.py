"""Hard-case check: does a model treat the declared-variable traps in data/opcd/hard_cases.jsonl as null?

Samples each prompt k times per condition on the OPCD vLLM server (logs/evals/opcd_vllm_serve.sh), then asks
the judge (eval-config judge, gpt-6.1-sol) about each trap variable and each real nullable field:
  trap_belief    the response says or assumes a trap variable is null / unset before first assignment, or adds
                 a null check / isnull guard / initializer for it to avoid a null;
  real_guarded   the real nullable inputs are handled (overshoot check: "nothing is null").

  python data/opcd/eval_hard_cases.py OUT_NAME cond=model:role [cond=model:role ...] [--k 4]
     role: student (plain system prompt) | teacher (rule system prompt)
  e.g. plain=rb1006:student rule=rb1006:teacher c1=c1_r015:student
"""
import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import opcd  # noqa: E402
import self_distill as sd  # noqa: E402

HERE = Path(__file__).resolve().parent
JUDGE_SYS = """You check one specific CTL2 (CloverDX) fact in a model's response. CTL2 facts: a variable declared
without an initializer, global or local, starts at its type's default, never null: integer/long/decimal 0, number
0.0, boolean false, string "", date the epoch (1970-01-01 00:00:00), lists and maps empty. Only variant, byte and
cbyte start null. Nullable input fields, missing map keys and unmatched outer-join slave fields CAN be null.
Answer with JSON only."""
JUDGE_USER = """TASK GIVEN TO THE MODEL:
{user}

TRAP VARIABLES (declared without an initializer; they are NOT null): {traps}
REAL NULLABLE INPUTS THAT NEED HANDLING: {nulls}

MODEL RESPONSE (reasoning, then answer):
<reasoning>
{thinking}
</reasoning>
<answer>
{answer}
</answer>

Return JSON: {{"trap_belief_answer": bool, "trap_belief_reasoning": bool, "real_guarded": bool, "evidence": "<= 30 words"}}
- trap_belief_answer: the ANSWER states or assumes a trap variable is null/unset/undefined before its first
  assignment, OR adds a null check, isnull() guard, or an explicit initializer for a trap variable in order to avoid
  a null / uninitialized value (a fix list item or a review finding about it counts).
- trap_belief_reasoning: the same, anywhere in the reasoning, unless the reasoning then corrects itself.
- real_guarded: the answer handles (fixes or flags) the real nullable inputs listed."""


def judge_client():
    cfg, _ = sd.load_eval_config(ROOT / "configs/eval_rb1006_on.yaml")
    j = cfg["judge"]
    from openai import OpenAI
    return OpenAI(base_url=j["base_url"], api_key=j.get("api_key") or "local"), j["model"], j.get("reasoning_effort")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("conds", nargs="+")
    ap.add_argument("--k", type=int, default=4)
    ap.add_argument("--config", default=str(ROOT / "configs/opcd_c1.yaml"))
    ap.add_argument("--holdout", action="store_true", help="only the held-out ids in hard_holdout.json")
    args = ap.parse_args()
    cfg = opcd.load_cfg(args.config)
    roles = opcd.Roles(cfg)
    rows = sd.read_jsonl(HERE / "hard_cases.jsonl")
    if args.holdout:
        held = set(json.load(open(HERE / "hard_holdout.json"))["holdout"])
        rows = [r for r in rows if r["id"] in held]
    prompts = []
    for r in rows:
        user = sd.with_validate_format(r["user"])[0] if r["task_type"] == "validate" else r["user"]
        prompts.append({**r, "user": user, "prompt_id": sd.make_prompt_id(r["user"]), "set": "hard"})

    out_dir = HERE / "hard_eval" / args.name
    out_dir.mkdir(parents=True, exist_ok=True)
    client, jmodel, jeffort = judge_client()
    samples = []
    for cond in args.conds:
        label, spec = cond.split("=")
        model, role = spec.split(":")
        smp = opcd.VllmSampler({**cfg, "sampler": {**cfg["sampler"], "served_model": model}}, roles)
        if role == "teacher":  # sample under the rule prompt
            orig = roles.ids
            smp.roles = type("R", (), {"sampling": roles.sampling, "tok": roles.tok,
                                       "ids": lambda self, r, p: orig("teacher", p), "mode": roles.mode,
                                       "teacher_role": roles.teacher_role})()
        got = smp.sample_many([(p, 11 + i) for i, p in enumerate(prompts)], args.k, 8192)
        for p, g in zip(prompts, got):
            for s in g:
                samples.append({"cond": label, "id": p["id"], "task_type": p["task_type"], "component": p["component"],
                                "thinking": s["thinking"], "answer": s["answer"], "hit_cap": s["hit_cap"],
                                "new_tokens": s["new_tokens"], **opcd.scan(s)})
        print(f"{label}: sampled {sum(len(g) for g in got)}", flush=True)

    P = {p["id"]: p for p in prompts}

    def grade(s):
        p = P[s["id"]]
        traps = "; ".join(f'{t["name"]} ({t["type"]}, {t["scope"]})' for t in p["trap_vars"])
        msg = JUDGE_USER.format(user=p["user"], traps=traps, nulls="; ".join(p["real_nulls"]),
                                thinking=s["thinking"][-12000:], answer=s["answer"])
        kw = {"reasoning_effort": jeffort} if jeffort else {}
        for _ in range(3):
            try:
                r = client.chat.completions.create(model=jmodel, messages=[{"role": "system", "content": JUDGE_SYS},
                                                                            {"role": "user", "content": msg}], **kw)
                txt = r.choices[0].message.content
                return {**s, "judge": json.loads(re.search(r"\{.*\}", txt, re.S).group(0))}
            except Exception as e:  # noqa: BLE001
                err = str(e)
        return {**s, "judge": None, "judge_error": err[:200]}

    with ThreadPoolExecutor(8) as ex:
        graded = list(ex.map(grade, samples))
    (out_dir / "graded.jsonl").write_text("".join(json.dumps(g, ensure_ascii=False) + "\n" for g in graded))

    rep = {}
    for label in [c.split("=")[0] for c in args.conds]:
        g = [x for x in graded if x["cond"] == label and x["judge"]]
        n = len(g)
        per = defaultdict(int)
        for x in g:
            per[x["id"]] += bool(x["judge"].get("trap_belief_answer"))
        rep[label] = {"samples": n, "judge_errors": sum(1 for x in graded if x["cond"] == label and not x["judge"]),
                      "trap_belief_answer": round(sum(bool(x["judge"].get("trap_belief_answer")) for x in g) / n, 3),
                      "trap_belief_reasoning": round(sum(bool(x["judge"].get("trap_belief_reasoning")) for x in g) / n, 3),
                      "real_guarded": round(sum(bool(x["judge"].get("real_guarded")) for x in g) / n, 3),
                      "regex_belief": round(sum(x["belief"] for x in g) / n, 3),
                      "quotes_rule": round(sum(x["quotes_rule"] for x in g) / n, 3),
                      "prompts_with_belief": sum(1 for v in per.values() if v),
                      "by_task": {t: round(sum(bool(x["judge"].get("trap_belief_answer")) for x in g if x["task_type"] == t)
                                           / max(1, sum(1 for x in g if x["task_type"] == t)), 3) for t in ("fix", "validate")},
                      "per_prompt": dict(per)}
    sd.write_json(out_dir / "report.json", rep)
    for k, v in rep.items():
        print(k, {a: b for a, b in v.items() if a != "per_prompt"})


if __name__ == "__main__":
    main()
