"""Check the round-two OPCD schema, coverage, metadata, and compiler evidence."""
import collections
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path


def result_payload(value):
    obj = json.loads(value) if isinstance(value, str) else value
    if 'structuredContent' in obj:
        return obj['structuredContent']
    if 'content' in obj:
        return json.loads(next(c['text'] for c in obj['content'] if c['type'] == 'text'))
    return obj


def check(path):
    rows = [json.loads(line) for line in Path(path).read_text().splitlines()]
    assert len(rows) == 15
    assert [r['id'] for r in rows] == [f'opcd_hard2_{i:02}' for i in range(1, 16)]
    expected = {'id', 'task_type', 'component', 'user', 'trap_vars', 'real_nulls',
                'other_defects', 'compile_expected', 'compile_result',
                't40_t42_features', 'date_trap_kind'}
    codes = []
    for row in rows:
        assert set(row) == expected, row['id']
        assert len(row['real_nulls']) in (1, 2), row['id']
        assert 4 <= len(row['real_nulls']) + len(row['other_defects']) <= 5, row['id']
        features = row['t40_t42_features']
        assert len(set(features)) == len(features) >= 3 and set(features) <= {1, 2, 3, 4, 5}
        assert row['date_trap_kind'] in {'max_tracker', 'prev_record', 'min_tracker_real_bug'}
        blocks = re.findall(r'```ctl\n(.*?)```', row['user'], re.S)
        assert len(blocks) == 1 and blocks[0].startswith('//#CTL2'), row['id']
        codes.append(blocks[0])
        dates = [t for t in row['trap_vars'] if t['type'] == 'date']
        assert dates, row['id']
        for trap in row['trap_vars']:
            assert set(trap) == {'name', 'type', 'scope', 'first_use'}
            assert trap['first_use'] in blocks[0], row['id']
            assert re.search(r'\b' + re.escape(trap['name']) + r'\s*;', blocks[0]), row['id']
        if row['date_trap_kind'] == 'min_tracker_real_bug':
            assert any('epoch' in d.lower() for d in row['other_defects']), row['id']
        numbered = re.findall(r'^\d+\. ', row['user'], re.M)
        assert 4 <= len(numbered) <= 6, (row['id'], len(numbered))
        wrappers = re.findall(r'<Metadata\b[^>]*>.*?</Metadata>', row['user'], re.S)
        assert wrappers, row['id']
        for wrapper in wrappers:
            root = ET.fromstring(wrapper)
            assert root.get('id') and root.find('Record') is not None, row['id']
            fields = root.findall('Record/Field')
            assert fields and all(f.get('nullable') in {'true', 'false'} for f in fields), row['id']
        if row['task_type'] == 'fix':
            assert 'List every problem you fix with the reason' in row['user'], row['id']
        else:
            assert 'ISSUES:' not in row['user'] and 'VERDICT:' not in row['user'], row['id']
        compiled = result_payload(row['compile_result'])
        assert row['compile_expected'].startswith('error:') and compiled['overall'] == 'FAIL', row['id']
        assert len(compiled['problems']) == 1 and compiled['problems'][0]['severity'] == 'ERROR', row['id']
    assert len(set(codes)) == 15 and len({r['user'] for r in rows}) == 15
    tasks = collections.Counter(r['task_type'] for r in rows)
    components = collections.Counter(r['component'] for r in rows)
    kinds = collections.Counter(r['date_trap_kind'] for r in rows)
    features = collections.Counter(f for r in rows for f in r['t40_t42_features'])
    assert tasks == {'fix': 12, 'validate': 3}, tasks
    assert components == {'DENORMALIZER': 4, 'PARTITION': 4, 'ROLLUP': 2,
                          'REFORMAT': 2, 'NORMALIZER': 2, 'JOIN': 1}, components
    assert kinds['min_tracker_real_bug'] == 3, kinds
    assert all(features[f] >= 3 for f in range(1, 6)), features
    locals_count = sum(any(t['scope'] == 'local' for t in r['trap_vars'] if t['type'] == 'date') for r in rows)
    assert locals_count <= 3
    first_path = Path(path).with_name('hard_cases.jsonl')
    previous = [json.loads(l) for l in first_path.read_text().splitlines()]
    assert not ({r['user'] for r in rows} & {r['user'] for r in previous})
    return {'records': len(rows), 'tasks': dict(tasks), 'components': dict(components),
            'date_trap_kinds': dict(kinds), 'feature_coverage': dict(features),
            'local_date_prompt_count': locals_count, 'isolated_compile_errors': 15}


if __name__ == '__main__':
    import sys
    print(json.dumps(check(sys.argv[1]), indent=2))
