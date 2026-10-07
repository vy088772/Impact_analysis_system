"""Compare mode-4 seam rag_client.flow_chain(backward) against source truth (ticket 07).

For each table of each stored procedure that a truth action calls, ask the backward
chain for the table. The pair passes when one stored procedure chain of the table
gives a Program Screen anchor of the truth action on `{Controller}Controller.cs`.
The chain of one method keeps one stored procedure only (the first path of the
method), so the probe does not ask for the chain of that procedure; it counts those
chains apart. It also counts the pairs whose Program Screen view sits in `Views/{Controller}`.
`truth.json` gives no view, so the probe asserts the action only.

Tables come from the SQL Execution Graph of the RTTalentDB cache: the `reads` and
`writes` of the operations that the procedure itself contains (no nested call).
A table of another Database is left out and counted, and so is a temporary table
(`#name`), which no other module can read.
"""
import collections
import json
import os
import sys
from impact_orch import rag_client

S = os.path.dirname(os.path.abspath(__file__)) + '/'
CACHE = S + '../../../data/sql_cache/vmsystest09.topmost.com.tw__RTTalentDB.json'
truth = json.load(open(S + 'truth.json'))
graph = json.load(open(CACHE))['sql_execution_graph']


def sp(name):
    return name.split('.')[-1].strip('[]').lower()


operations = collections.defaultdict(set)  # procedure -> its operation ids
for r in graph['relationships']:
    if r['type'] == 'contains' and r['source'].startswith('stored_procedure:'):
        operations[sp(r['source'].split(':', 1)[1])].add(r['target'])
tables = collections.defaultdict(set)  # procedure -> tables of RTTalentDB
other_db = set()
for r in graph['relationships']:
    if r['type'] not in ('reads', 'writes') or not r['target'].startswith('table:') or '#' in r['target']:
        continue
    for proc, ops in operations.items():
        if r['source'] in ops:
            if (r.get('database') or 'RTTalentDB').lower() == 'rttalentdb':
                tables[proc].add(r['target'].split(':', 1)[1])
            else:
                other_db.add((proc, r['target']))

chains = {}
errs = collections.Counter()


def backward(table):
    if table not in chains:
        try:
            chains[table] = rag_client.flow_chain('RTTalentDB', 'backward', table_name=table)['backward_chains'] or []
        except rag_client.ImpactServiceError as e:
            errs[str(e)[:80]] += 1
            chains[table] = None
    return chains[table]


rows = []
for key, procs in sorted(truth.items()):
    prog, action = key.split('.')
    for proc in procs:
        for table in sorted(tables.get(proc, ())):
            got = backward(table)
            if got is None:
                continue
            of_proc = [c for c in got if proc in {sp(s) for s in (c.get('sp_chain') or [c.get('sp_name', '')])}]
            def holds(a):
                return (a.get('kind') == 'program_screen' and a.get('action', '').lower() == action.lower()
                        and os.path.basename(a.get('controller_file', '')).lower() == f'{prog}controller.cs'.lower())
            screens = [a for c in got if c.get('via') == 'stored_procedure' for a in c.get('ui_anchors') or [] if holds(a)]
            rows.append({
                'action': key, 'sp': proc, 'table': table, 'chains_of_sp': len(of_proc),
                'reached': bool(screens),
                'reached_by_sp': any(holds(a) for c in of_proc for a in c.get('ui_anchors') or []),
                'views': sorted({(a['file'], a['strength']) for a in screens}),
                'in_views_folder': any(f'/views/{prog.lower()}/' in '/' + a['file'].replace('\\', '/').lower() for a in screens),
            })

json.dump(rows, open(S + sys.argv[1], 'w'), ensure_ascii=False, indent=1)
actions = collections.defaultdict(list)
for r in rows:
    actions[r['action']].append(r['reached'])
print('tables asked', len(chains), 'errors', dict(errs), '| other-Database tables left out', len(other_db))
print('pairs (action, sp, table)', len(rows),
      '| sp has a chain', sum(1 for r in rows if r['chains_of_sp']),
      '| action reached', sum(1 for r in rows if r['reached']),
      '(by a chain of that sp', str(sum(1 for r in rows if r['reached_by_sp'])) + ')',
      '| view in Views/{Controller}', sum(1 for r in rows if r['in_views_folder']))
print('actions with a table', len(actions),
      '| fully reached', sum(1 for v in actions.values() if all(v)),
      '| partial', sum(1 for v in actions.values() if any(v) and not all(v)),
      '| none', sum(1 for v in actions.values() if not any(v)))
print('strengths', dict(collections.Counter(s for r in rows for _, s in r['views'])))
