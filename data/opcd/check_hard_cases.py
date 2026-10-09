"""Check the prompt-only OPCD batch structure and required coverage."""
import collections
import json
import re
from pathlib import Path


def check(path):
    rows = [json.loads(line) for line in Path(path).read_text().splitlines()]
    assert len(rows) == 40
    assert [r['id'] for r in rows] == [f'opcd_hard_{i:02}' for i in range(1, 41)]
    assert len({r['user'] for r in rows}) == 40
    expected = {'id', 'task_type', 'component', 'user', 'trap_vars',
                'real_nulls', 'other_defects', 'compile_expected', 'compile_result'}
    for row in rows:
        assert set(row) == expected, row['id']
        assert row['real_nulls'] and 2 <= len(row['other_defects']) <= 3, row['id']
        blocks = re.findall(r'```ctl\n(.*?)```', row['user'], re.S)
        assert len(blocks) == 1 and blocks[0].startswith('//#CTL2'), row['id']
        for trap in row['trap_vars']:
            assert set(trap) == {'name', 'type', 'scope', 'first_use'}, row['id']
            assert trap['scope'] in {'global', 'local'}
            assert re.search(r'\b' + re.escape(trap['name']) + r'\s*;', blocks[0]), row['id']
            assert trap['first_use'] in blocks[0], (row['id'], trap['first_use'])
        assert row['compile_result'], row['id']
        compiled = json.loads(row['compile_result'])
        if 'structuredContent' in compiled:
            compiled = compiled['structuredContent']
        elif 'content' in compiled:
            compiled = json.loads(next(c['text'] for c in compiled['content'] if c['type'] == 'text'))
        assert row['compile_expected'] == 'ok' and compiled['overall'] == 'PASS', row['id']
        assert not compiled['problems'], row['id']
        if row['task_type'] == 'validate':
            assert 'ISSUES:' not in row['user'] and 'VERDICT:' not in row['user'], row['id']
        else:
            assert 'List every problem you fix with the reason' in row['user'], row['id']
    tasks = collections.Counter(r['task_type'] for r in rows)
    assert tasks == {'fix': 28, 'validate': 12}, tasks
    components = collections.Counter(r['component'] for r in rows)
    for component, minimum in [('DENORMALIZER', 5), ('PARTITION', 5), ('REFORMAT', 5),
                               ('JOIN', 5), ('ROLLUP', 3), ('NORMALIZER', 3), ('DATA_GENERATOR', 3)]:
        assert components[component] >= minimum, components
    scopes = collections.Counter()
    types = collections.Counter()
    for row in rows:
        scope_set = {t['scope'] for t in row['trap_vars']}
        assert len(scope_set) == 1, row['id']
        scopes.update(scope_set)
        types.update({t['type'] for t in row['trap_vars']})
        if row['component'] == 'ROLLUP':
            assert scope_set == {'global'}, row['id']
    assert scopes == {'global': 20, 'local': 20}, scopes
    assert types['date'] >= 20 and types['string'] >= 6, types
    containers = sum(any('[' in t['type'] for t in r['trap_vars']) for r in rows)
    assert containers >= 8, containers
    assert sum(len(r['trap_vars']) == 2 for r in rows) == 10
    assert all(1 <= len(r['trap_vars']) <= 2 for r in rows)
    return {'records': len(rows), 'tasks': dict(tasks), 'components': dict(components),
            'scope_by_prompt': dict(scopes), 'type_by_prompt': dict(types),
            'container_prompts': containers, 'two_trap_prompts': 10}


if __name__ == '__main__':
    import sys
    print(json.dumps(check(sys.argv[1]), indent=2))
