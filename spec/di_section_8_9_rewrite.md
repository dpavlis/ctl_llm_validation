# Draft: DataIntersection in the join framing (reference §8.9 rewrite)

Owner rulings 2026-11-01: DataIntersection is taught as a join-like transform, not as three ports plus a `$out.0`
rule; the idiom is `return OK`. Evidence: `spec/sysprompt_rules_findings.md` (framing paragraph on valprec2: DI harness
first attempt 76 → 98/102, validate false alarm flat; the three-port text plus `ALL` made it worse). This draft is
for review before anything is edited; the correctness rule "update every copy" applies once approved.

## Proposed §8.9 (replaces the current section in `resources/ctl2-basics.md`)

```markdown
### 8.9 DataIntersection

A join over two inputs **sorted** on the Join key (`$a_key=$b_key;…`). Input 0 is flow A (e.g. the previous
snapshot), input 1 is flow B (e.g. the new data). There is no master or slave: for every key present on both sides
the component pairs the A record with the B record and calls `transform()` once per pair.

- `transform()` sees **one matched pair**: `$in.0` is the A record, `$in.1` the B record. It fills **one output
  record, `$out.0`**, with the transform's own output metadata, and returns `OK` to emit it or `SKIP` to drop the pair.
  `STOP` makes the component fail.
- Records whose key is on one side only never reach the CTL. The component passes them on by itself, unchanged, on
  its other outputs; which consumers are connected there is a graph matter and is not the CTL's business. INSERT /
  DELETE therefore need no code; the CTL only ever describes what a matched pair becomes.
- The return value does not choose an output. `$out.1` and `$out.2` do not exist in this transform; writing them fails
  when the component initializes.
- Defaults: *Equal NULL* = true (null key values match each other); *Allow key duplicates* = true (duplicate keys give
  the Cartesian product of pairs, A-major).

```ctl
//#CTL2
function integer transform() {
    if ($in.0.status == $in.1.status && $in.0.amount == $in.1.amount) {
        return SKIP;              // unchanged pair: nothing to emit
    }
    $out.0.* = $in.1.*;           // the pair's result record
    $out.0.cdc_action = "UPDATE";
    return OK;
}
```

Older code returns `ALL`, `0` or `1` from this transform; all of them behave exactly like `OK` here and are not an
error, but new code returns `OK`.
```

What changed and why:

- The three-port table is gone from the CTL explanation. The model applies the Reformat/Partition model (return value
  selects a port, `$out.N` is port N) and the table feeds it; the join framing removes the conflict instead of ruling
  against it (measured: `$out.1` misses 21 → 2 of 102).
- "Emitted on port 1" and "the return value never selects a port (unlike §8.1)" are replaced by "the return value does
  not choose an output" and "its other outputs", with no numbers.
- `return OK` is the idiom (owner ruling). The last sentence keeps the judge and the reviewer from calling existing
  `return ALL` code an error: without it the reviewer flagged every clean `return ALL` control (framing v1, 10/24).
  The sentence is deliberately last and does not say what `ALL` means elsewhere.
- Facts kept: sorted inputs, A/B sides, Equal NULL, Allow key duplicates, STOP fails, `$out.1`/`$out.2` fail at init
  (all compiler- or owner-verified, findings §7).

## Other lines in the reference

- §13 quick table, line "DataIntersection | See §8.9: `$out.0`, emitted on port 1; `STOP` fails the component." →
  "DataIntersection | See §8.9: a join over matched pairs, one output record `$out.0`, `return OK`; `STOP` fails the
  component."
- §8.1 return-constants table: add under the table one line "DataIntersection is the exception: its transform has one
  output record and `OK` emits it (§8.9)." so that "ALL = send to all connected output ports" is not read into §8.9.

## Copies to update when approved

| copy | action |
|---|---|
| `resources/ctl2-basics.md` | §8.9, §13 line, §8.1 note |
| `results/eval_snapshot_20261013/ctl2-basics.md` (suite v5) | same text (its §8.9 is identical to the working copy today) |
| `results/eval_snapshot_20261003/ctl2-basics.md` (suite v4) | nothing: it has no DataIntersection section |
| rule teachers `configs/eval_rb1006_rulev*` | nothing: none mentions DataIntersection (checked) |
| `ctl_lora_training/references/cloverdx-llm-reference.md` | component table row stays ("2 inputs, 3 outputs" is a graph fact); add a short DataIntersection CTL paragraph in the join framing |
| `ctl_lora_training/references/CTL2_Reference_for_LLM_compact.md` | has no DataIntersection text; add the §8.9 paragraph |
| suite v5 T53/T54 rubrics | no change needed: they already accept "OK, 0, 1 or ALL" as the emit value and describe `$out.0`; prompts keep their port talk (robustness) |

## Corpus brief (to write after approval)

- DataIntersection SFT/DPO sets re-explained in the join framing: two input records, one output record, `return OK`;
  no port numbers in the explanation or the code comments; `return ALL` nowhere in chosen answers (today 34 of 40 DPO
  records use it, `return OK` none).
- Keep a share of prompts (about half, as pool_tweak has today) that describe the graph's three outputs, so the model
  learns to ignore the port talk rather than never to see it.
- The validate ground-truth sets: the 12 DI clean controls in B1-tweak and the DI controls in B1 use `return ALL`.
  Once the idiom is OK, regenerate them from the new references (the `wrong_return` mutants on DI then plant a wrong
  value against `OK`).

## Measurement after the change

1. Judge side first, no model change: re-judge valprec2's stored T53/T54 answers with the rewritten reference
   (`data/rejudge_results.py`) and confirm the scores do not move on their own.
2. Model side: OPCD on valprec2 with the new §8.9 as the teacher context (the proven route), gates = DI harness subset
   paired (76/102 baseline), DI validate controls (0.08), then the standard full gates: pool_tweak paired, B1-tweak
   both modes, T40/T42 n20 twice, hard set 3.
