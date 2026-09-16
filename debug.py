import gc
from pathlib import Path

import torch
import torch.nn.functional as F
from transformers import AutoModelForCausalLM, AutoTokenizer


BASE_MODEL = "Qwen/Qwen3.6-27B"
MERGED_MODEL = str(Path("~/exports/qwen36").expanduser())

PROMPT = r"""
//#CTL2
function integer transform() {
    $out.0.customer_name = null : string :
"""

TOP_K = 20


def topk_from_logits(logits, tokenizer):
    probs = F.softmax(logits.float(), dim=-1)

    values, indices = torch.topk(probs, TOP_K)

    return [
        {
            "id": idx.item(),
            "token": tokenizer.decode([idx]).replace("\n", "\\n"),
            "prob": val.item(),
        }
        for val, idx in zip(values, indices)
    ]


def collect(model, tokenizer, prompt):

    ids = tokenizer(prompt, return_tensors="pt").input_ids.to(model.device)

    results = []

    with torch.inference_mode():

        for step in range(ids.shape[1] - 1):

            prefix = ids[:, : step + 1]

            logits = model(prefix).logits[0, -1]

            expected = ids[0, step + 1].item()

            results.append(
                {
                    "expected": expected,
                    "expected_token": tokenizer.decode([expected]),
                    "top": topk_from_logits(logits, tokenizer),
                }
            )

    return results


######################################################################
# tokenizer
######################################################################

print("Loading tokenizer...")

tokenizer = AutoTokenizer.from_pretrained(
    BASE_MODEL,
    trust_remote_code=True,
)

######################################################################
# BASE
######################################################################

print("Loading BASE model...")

base = AutoModelForCausalLM.from_pretrained(
    BASE_MODEL,
    torch_dtype=torch.bfloat16,
    device_map="cuda",
    trust_remote_code=True,
).eval()

base_results = collect(base, tokenizer, PROMPT)

del base
gc.collect()
torch.cuda.empty_cache()

######################################################################
# MERGED
######################################################################

print("Loading MERGED model...")

merged = AutoModelForCausalLM.from_pretrained(
    MERGED_MODEL,
    torch_dtype=torch.bfloat16,
    device_map="cuda",
    trust_remote_code=True,
).eval()

merged_results = collect(merged, tokenizer, PROMPT)

del merged
gc.collect()
torch.cuda.empty_cache()

######################################################################
# COMPARE
######################################################################

for step, (b, m) in enumerate(zip(base_results, merged_results)):

    print("=" * 120)
    print(f"STEP {step}")
    print(f"Expected token: {repr(b['expected_token'])}")

    print("\nBASE")
    for x in b["top"]:
        print(f"{x['prob']:8.5f} {repr(x['token'])}")

    print("\nMERGED")
    for x in m["top"]:
        print(f"{x['prob']:8.5f} {repr(x['token'])}")

    if b["top"][0]["id"] != m["top"][0]["id"]:
        print("\n<<<<<<<<<<<< TOP-1 DIFFERS >>>>>>>>>>>>\n")


