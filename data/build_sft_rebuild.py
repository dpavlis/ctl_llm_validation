"""Build an SFT + DPO training set for the current recipe (rb1005/rb1006; findings §5).

  cd ~/llama_train && ~/venv/bin/python data/build_sft_rebuild.py rb1006 data/sft_rebuild_20261006

SFT  = every record in ctl_lora_training/sft_training_data/*.json (answer-only; minus EXCL), plus the
       self-distilled thinking traces of runs full1 + gen2full, each twice (minus stale traces listed in
       data/self_distill/sd_stale.json and traces over 4096 tokens under the qwen3_8 template).
DPO  = every ctl_lora_training/sft_training_data/CTL_LoRA_DPO_*.jsonl pair.
Eval = ctl_lora_training/sft_eval_data copies. Writes build_report.json (corpus commit, counts, drops).
Register the four files in ~/LlamaFactory/data/dataset_info.json (it carries git skip-worktree) and copy
them into ~/LlamaFactory/data/. Needs ~/LlamaFactory/src on PYTHONPATH (llamafactory imports).
"""
import json,glob,shutil,subprocess,sys,os
from collections import Counter
from transformers import AutoTokenizer
from llamafactory.data.template import get_template_and_fix_tokenizer
from llamafactory.hparams import DataArguments
TAG,O=sys.argv[1],sys.argv[2]; os.makedirs(O,exist_ok=True)
C="ctl_lora_training/sft_training_data/"
EXCL={"CTL_LoRAT_reasoning_v2_agent_authored_20_fewshot.json"}
sft=[]
for f in sorted(glob.glob(C+"*.json")):
    name=f.split("/")[-1]
    if name in EXCL: continue
    for i,r in enumerate(json.load(open(f))):
        sft.append({"id":f"{TAG}-{len(sft)+1}","messages":[{"role":m["role"],"content":m["content"]} for m in r["messages"]],"reviewed_date":r.get("reviewed_date"),"source_file":name,"source_index":i,"source_id":r.get("id")})
n_corpus=len(sft)
tok=AutoTokenizer.from_pretrained("/home/pavlisd/exports/qwen38_fix6_sftdpo",trust_remote_code=True)
tpl=get_template_and_fix_tokenizer(tok,DataArguments(template="qwen3_8",enable_thinking=None,reasoning_effort="medium"))
stale=json.load(open("data/self_distill/sd_stale.json"))
sd_kept=[]; dropped={"stale":[],"over_4096":[]}
for run in ("full1","gen2full"):
    st={i for i,_ in stale[run]}
    for r in json.load(open(f"data/self_distill/{run}/selfdistill_{run}_train.json")):
        if r["id"] in st: dropped["stale"].append(r["id"]); continue
        sysm=next((m["content"] for m in r["messages"] if m["role"]=="system"),None); conv=[m for m in r["messages"] if m["role"]!="system"]
        p,c=tpl.encode_oneturn(tok,conv,sysm)
        if len(p)+len(c)>4096: dropped["over_4096"].append(r["id"]); continue
        sd_kept.append((run,r))
for rep in (1,2):
    for run,r in sd_kept:
        sft.append({"id":f"{TAG}-sd{rep}-{r['id']}","messages":[{"role":m["role"],"content":m["content"]} for m in r["messages"]],"source_file":f"self_distill/{run}","source_id":r["id"],"repeat":rep})
json.dump(sft,open(f"{O}/CTL_LoRA_training_data_{TAG}.json","w"),ensure_ascii=False,indent=1)
dpo=[]
for f in sorted(glob.glob(C+"CTL_LoRA_DPO_*.jsonl")):
    name=f.split("/")[-1]
    for i,l in enumerate(open(f)):
        if not l.strip(): continue
        r=json.loads(l); x={k:r[k] for k in ("system","prompt","chosen","rejected")}; x.update(id=f"{TAG}dpo-{len(dpo)+1}",source_file=name,source_index=i,source_id=r.get("id")); dpo.append(x)
open(f"{O}/CTL_LoRA_DPO_data_{TAG}.jsonl","w").write("".join(json.dumps(x,ensure_ascii=False)+"\n" for x in dpo))
shutil.copy("ctl_lora_training/sft_eval_data/CTL_LoRA_eval_data.json",f"{O}/CTL_LoRA_eval_data_{TAG}.json")
shutil.copy("ctl_lora_training/sft_eval_data/CTL_LoRA_DPO_eval.jsonl",f"{O}/CTL_LoRA_DPO_eval_{TAG}.jsonl")
mx=0; per=Counter(); permx=Counter()
for r in sft[:n_corpus]:
    sysm=next((m["content"] for m in r["messages"] if m["role"]=="system"),None); conv=[m for m in r["messages"] if m["role"]!="system"]
    p,c=tpl.encode_oneturn(tok,conv,sysm); L=len(p)+len(c); mx=max(mx,L)
commit=subprocess.check_output(["git","-C","ctl_lora_training","rev-parse","--short","HEAD"]).decode().strip()
json.dump({"corpus_commit":"ctl_lora_training "+commit,"corpus_records":n_corpus,"self_distill_kept":len(sd_kept),"self_distill_repeats":2,"dropped":dropped,"excluded_files":sorted(EXCL),"dpo_pairs":len(dpo),"dpo_by_file":Counter(x["source_file"] for x in dpo),"sft_by_file":Counter(r["source_file"] for r in sft[:n_corpus])},open(f"{O}/build_report.json","w"),indent=1)
print("SFT",len(sft),"(corpus",n_corpus,"+ sd",len(sd_kept),"x2) | DPO",len(dpo),"| commit",commit,"| max corpus len",mx)
