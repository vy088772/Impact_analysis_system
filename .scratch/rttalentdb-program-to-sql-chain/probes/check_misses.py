"""Check the forward and backward probe output against the named list of misses (ticket 09).

Run from the probes directory after compare_flow.py and backward_flow.py:
    python3 check_misses.py flow_after.json backward_after.json

misses.json gives each truth action that is not fully matched: a reason, the stored
procedures that the forward chain does not reach, and the source lines that show the
reason. The check fails when a miss is not on the list, when a listed action is now
fully matched (remove it from the list), or when the forward chain misses other
stored procedures than the list says.
"""
import collections
import json
import os
import sys

S = os.path.dirname(os.path.abspath(__file__)) + '/'
listed = json.load(open(S + 'misses.json'))
forward = json.load(open(S + sys.argv[1]))
backward = json.load(open(S + sys.argv[2]))

forward_missing = {
    r['action']: sorted(set(r['want']) - set(r['got']))
    for r in forward if r['want'] and not set(r['want']) <= set(r['got'])
}
pairs = collections.defaultdict(list)
for r in backward:
    pairs[r['action']].append(r['reached'])
backward_missed = {action for action, reached in pairs.items() if not all(reached)}

problems = []
for action, missing in sorted(forward_missing.items()):
    if action not in listed:
        problems.append(f'forward miss not on the list: {action} {missing}')
    elif listed[action]['missing'] != missing:
        problems.append(f'forward miss differs from the list: {action} {missing} != {listed[action]["missing"]}')
for action in sorted(set(listed) - set(forward_missing)):
    problems.append(f'listed but now fully matched forward: {action}')
for action in sorted(backward_missed - set(listed)):
    problems.append(f'backward miss not on the list: {action}')

reasons = collections.Counter(entry['reason'] for entry in listed.values())
print('truth actions', sum(1 for r in forward if r['want']),
      '| forward fully matched', sum(1 for r in forward if r['want']) - len(forward_missing),
      '| backward fully reached', len(pairs) - len(backward_missed))
print('listed misses', len(listed), dict(sorted(reasons.items(), key=lambda kv: -kv[1])))
print('backward misses', len(backward_missed),
      '| listed forward misses that the backward probe reaches', len(set(listed) - backward_missed))
print('\n'.join(problems) or 'every miss is on the list')
sys.exit(1 if problems else 0)
