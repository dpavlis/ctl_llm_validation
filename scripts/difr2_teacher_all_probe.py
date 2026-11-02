# Sample the review TEACHER (rb1009 base, rulev6 validate system prompt + format + teacher_context in the system message,
# thinking on) on the training DI controls that return ALL, and count [ERROR] findings that mention ALL.
import json, re, sys, yaml, concurrent.futures as cf
import requests
cfg = yaml.safe_load(open('configs/eval_rb1006_rulev6_on.yaml'))
sysp = cfg['mut']['validate']['system_prompt']
rows = [json.loads(l) for l in open('data/validate_precision/review_prompts_v3.jsonl')]
rows = [r for r in rows if r['kind'] == 'control' and 'ntersection' in r['component'].lower() and r['mode'] == 'on'
        and 'return ALL' in r['user'] and r['tag'].endswith(':fmt')]
print('control rows', len(rows), file=sys.stderr)
rows = rows[:int(sys.argv[1]) if len(sys.argv) > 1 else 24]
def ask(r, with_ctx):
    system = sysp + (r.get('system_extra') or '') + ('\n\n' + r['teacher_context'] if with_ctx else '')
    body = {"model": "rb1009", "messages": [{"role": "system", "content": system}, {"role": "user", "content": r['user']}],
            "temperature": 0.4, "top_p": 1.0, "max_tokens": 6144, "chat_template_kwargs": {"enable_thinking": True}}
    j = requests.post('http://127.0.0.1:3012/v1/chat/completions', json=body, timeout=1200).json()
    m = j['choices'][0]['message']; ans = m.get('content') or ''
    errs = [l for l in ans.splitlines() if '[ERROR]' in l]
    return {'id': r['id'], 'ctx': with_ctx, 'any_error': bool(errs), 'all_error': any(re.search(r'\bALL\b', l) for l in errs),
            'errs': [e[:160] for e in errs]}
out = []
with cf.ThreadPoolExecutor(8) as ex:
    for res in ex.map(lambda a: ask(*a), [(r, c) for r in rows for c in (True, False)]):
        out.append(res)
for c in (True, False):
    sel = [o for o in out if o['ctx'] == c]
    print(f"teacher_context={c}: n {len(sel)}, any [ERROR] {sum(o['any_error'] for o in sel)}, mentions ALL {sum(o['all_error'] for o in sel)}")
json.dump(out, open('results/difr2/teacher_all_probe.json', 'w'), indent=1)
for o in out:
    if o['all_error']: print(o['ctx'], o['id'], o['errs'][0]); 
