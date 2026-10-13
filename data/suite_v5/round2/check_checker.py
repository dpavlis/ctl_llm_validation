"""Verify that integrity gates reject representative corrupted suite copies."""
import copy
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

D = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(D))
spec = importlib.util.spec_from_file_location('suite_checker', D / 'check_suite_rw.py')
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)
original = json.loads((D / 'generate_rw.json').read_text())

def temperature(rows):
    rows[0]['temperature'] = 0.9

def execution(rows):
    rows[0]['reference_runs'] = False

def duplicate(rows):
    rows[1]['user_message'] = rows[0]['user_message']

def coverage(rows):
    last = max(n for r in rows[0]['rubric']['required'] for n in r['clauses'])
    for r in rows[0]['rubric']['required']:
        r['clauses'] = [n for n in r['clauses'] if n != last]

def reference(rows):
    rows[0]['reference'] += '\n// altered reference\n'

def standalone(rows):
    next(r for r in rows if not r['standalone_reference_compiles'])['standalone_reference_compiles'] = True

cases = [(temperature, 'category/temperature'), (execution, 'reference did not run successfully'),
         (duplicate, 'Cross-prompt5gram Jaccard'), (coverage, 'clause/rubric coverage'),
         (reference, 'stale compiler code'), (standalone, 'incorrect standalone flag')]
results = []
with tempfile.TemporaryDirectory(prefix='suite_checker_') as tmp:
    for mutate, expected in cases:
        rows = copy.deepcopy(original)
        mutate(rows)
        path = Path(tmp) / 'suite.json'
        path.write_text(json.dumps(rows))
        result = checker.check(path)
        detected = not result['passed'] and any(expected in e for e in result['errors'])
        results.append(dict(mutation=mutate.__name__, expected_diagnostic=expected, detected=detected))
report = dict(passed=all(r['detected'] for r in results), cases=results)
(D / 'checker_verification.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))
assert report['passed']
