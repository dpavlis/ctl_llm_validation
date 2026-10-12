"""Check the round-three prompt schema and required batch coverage.

Semantic review and real compiler responses live in the companion audit/report.
"""
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def check():
    rows = [json.loads(line) for line in (ROOT / 'hard_cases3.jsonl').read_text().splitlines()]
    assert len(rows) == 40
    assert [r['id'] for r in rows] == [f'opcd_hard3_{i:02d}' for i in range(1, 41)]
    common = {'id', 'part', 'task_type', 'component', 'user', 'kind', 'expected'}
    for r in rows:
        if r['component'] == 'ROLLUP':
            assert 'inputSorted=true' in r['user'] and 'Input is sorted ascending by ' in r['user'], r['id']
        if r['component'] == 'DENORMALIZER':
            assert 'order=asc' in r['user'] and 'Input is sorted ascending by ' in r['user'], r['id']
    a_fields = common | {'sentinel', 'reference_compiles'}
    b_fields = common | {'acc_fields', 'trap_vars', 'other_defects', 'compile_expected', 'compile_result'}
    a, b = rows[:20], rows[20:]
    for r in a:
        assert set(r) == a_fields, r['id']
        assert r['part'] == 'A' and r['task_type'] == 'generate'
        assert r['kind'] == 'gen_first_record_sentinel' and r['reference_compiles'] is True
        assert set(r['sentinel']) == {'name', 'type', 'default'}
        assert r['sentinel']['default'] == ({'integer': '0', 'long': '0', 'string': '""', 'date': '1970-01-01 00:00:00 GMT'}.get(r['sentinel']['type'], '[]'))
        assert r['user'].startswith('Write the complete CTL2 '), r['id']
        assert '```ctl' not in r['user'], r['id']
        assert '<Record ' in r['user'] and '<Field ' in r['user']
    comp = Counter(r['component'] for r in a)
    assert comp['DENORMALIZER'] == 6 and comp['ROLLUP'] == 4
    assert comp['REFORMAT'] == 4 and comp['PARTITION'] == 3
    assert comp['NORMALIZER'] + comp['JOIN'] + comp['JOINER'] == 3
    types = {r['sentinel']['type'] for r in a}
    assert {'long', 'integer', 'string', 'date'} <= types
    assert any(t.endswith('[]') for t in types)
    for r in b:
        assert set(r) == b_fields, r['id']
        assert r['part'] == 'B' and r['component'] == 'ROLLUP'
        assert r['task_type'] in {'validate', 'fix'}
        assert 2 <= len(r['other_defects']) <= 3, r['id']
        assert 1 <= len(r['trap_vars']) <= 2
        assert r['acc_fields']
        for f in r['acc_fields']:
            assert set(f) == {'name', 'type', 'nullability', 'default'}
            assert f['nullability'] in {'unmarked', 'nullable', 'non-nullable'}
        if r['kind'] == 'acc_nullable_uninit':
            assert any(f['nullability'] in {'unmarked', 'nullable'} and f['default'] is None for f in r['acc_fields'])
        elif r['kind'] == 'acc_nonnullable_uninit':
            assert all(f['nullability'] == 'non-nullable' and f['default'] is None for f in r['acc_fields'])
        else:
            assert any(f['nullability'] == 'non-nullable' and f['default'] is not None for f in r['acc_fields'])
        acc_xml = re.search(r'Accumulator metadata:\s*```xml\s*\n(.*?)```', r['user'], re.S)
        if acc_xml:
            node = ET.fromstring(acc_xml[1])
            record = node if node.tag == 'Record' else node.find('Record')
            actual = [{'name': f.attrib['name'], 'type': f.attrib['type'], 'nullability': {'true': 'nullable', 'false': 'non-nullable'}.get(f.attrib.get('nullable'), 'unmarked'), 'default': f.attrib.get('default')} for f in record.findall('Field')]
            assert actual == r['acc_fields'], r['id']
        for t in r['trap_vars']:
            assert set(t) == {'name', 'type', 'scope', 'first_use'}
            assert t['scope'] == 'global'
            assert re.search(r'\b' + re.escape(t['type']) + r'\s+' + re.escape(t['name']) + r'\s*;', r['user']), r['id']
            assert t['first_use'] in r['user'], r['id']
        code = re.findall(r'```ctl\s*\n(.*?)```', r['user'], re.S)
        assert len(code) == 1 and code[0].startswith('//#CTL2'), r['id']
        if r['task_type'] == 'validate':
            assert r['user'].startswith('Validate this Rollup component CTL2 transform'), r['id']
        else:
            assert r['user'].startswith('Fix the following CTL2 '), r['id']
            assert re.search(r'(?m)^1\. ', r['user'])
        result = r['compile_result']
        if isinstance(result, str):
            result = json.loads(result)
        assert result['overall'] in {'PASS', 'FAIL'}, r['id']
        errors = [p for p in result['problems'] if p['severity'] == 'ERROR']
        assert bool(errors) == r['compile_expected'].startswith('error:'), r['id']
        assert len(errors) <= 1, r['id']
    assert Counter(r['task_type'] for r in b) == {'validate': 12, 'fix': 8}
    kinds = Counter(r['kind'] for r in b)
    assert kinds == {'acc_nullable_uninit': 10, 'acc_nonnullable_uninit': 5, 'acc_metadata_default': 5}
    prompts = [r['user'] for r in rows]
    assert len(set(prompts)) == 40
    old = {json.loads(s)['user'] for f in ('hard_cases.jsonl', 'hard_cases2.jsonl') for s in (ROOT / f).read_text().splitlines()}
    assert not (set(prompts) & old)
    audit = json.loads((ROOT / 'hard_cases3.audit.json').read_text())
    assert {r['id'] for r in audit} == {r['id'] for r in rows}
    assert all(r['reviewed_date'] == '2026-10-11' for r in audit)
    print(json.dumps({'records': 40, 'part_a_components': dict(comp), 'part_a_sentinel_types': sorted(types), 'part_b_tasks': dict(Counter(r['task_type'] for r in b)), 'part_b_kinds': dict(kinds)}, indent=2))


if __name__ == '__main__':
    check()
