Run `python3 data/opcd/generate_gaps_check.py --summary data/opcd/generate_gaps_runs/check_results.json`
from the repository. Exit 0 means every automated delivery check passed.
Defaults use retained v4/v5 suite sources and `hard_cases*.jsonl`; missing
prerequisites fail. `--suite` may be repeated to specify other suite files.

The checker verifies 120 records, 20 per gap, required component/trap coverage,
250–600 words, realistic metadata, rubric counts and full item IDs. Required
checks trace to numbered clauses or exact `prompt_evidence` phrases. Item `.1`
contains the component contract. `unused_fields` explicitly identifies fields
outside business decisions, including reserved or copied context fields.

It compares ordinary word 5-grams with every suite/hard-case prompt and every
new pair, requiring Jaccard below 0.30. Within each gap it also removes XML and
masks all underscore tokens and numbers, requiring every pair below 0.30 and
the average below 0.25. Eight-word sentences may occur in at most three prompts;
the prescribed closing sentence is exempt.

Text checks reject trap giveaways, digit gluing, doubled words and grammatical
splices. Rubric checks reject copied first-60-character prefixes, undeclared
field/resource/function identifiers, undefined output codes and forbidden text
repeated more than three times. Structured `output_codes`, `resources` and
metadata declarations make identifier checks auditable. Human author reviews
and the independent developer review cover grammar, atomicity, semantics,
contradictions and applicability beyond lexical checks.

Every nested artifact path must exist. Primary outputs are compared in complete
field and record order. Compile and completion evidence must succeed and have
declared run IDs. Dictionary/sequence references can require graph context;
standalone diagnostics are retained. Exact executed CTL, operational graph XML
and uploaded input bytes are bound to the final fixtures. Alternative and
independent execution results must also succeed.

`round2/check_alternatives.py` verifies all 1,363 rubric assessments against one
complete alternative per scenario, including hashes and current-source snippets.
`round2/check_independent.py` verifies three fresh independent solutions per gap,
exact prompt/rubric/source provenance, 206 per-item grades and successful runs.
These checks corroborate authored semantic reviews; they do not turn lexical
matching or test fixtures into a proof of all possible program behaviors.

`round2/test_checks.py` contains regression probes for named review defects and
checker bypasses. `round2/reproducibility.json` records a second identical
regeneration. Complete previous execution evidence is retained in
`round2/baseline/run_evidence.tar.gz`.
