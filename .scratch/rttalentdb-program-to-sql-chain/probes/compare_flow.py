"""Compare mode-4 seam rag_client.flow_chain(forward) against source truth."""
import json, sys, collections
from impact_orch import rag_client
S = __import__('os').path.dirname(__import__('os').path.abspath(__file__)) + '/'
truth = json.load(open(S + 'truth.json'))
rows = []; errs = collections.Counter()
for key, want in sorted(truth.items()):
    prog, action = key.split('.')
    try:
        fc = rag_client.flow_chain('RTTalentDB', 'forward', program_name=prog, anchor_method=action)['forward_chain'] or {}
    except rag_client.ImpactServiceError as e:
        errs[str(e)[:80]] += 1; continue
    names = [s['name'] if isinstance(s, dict) else s for s in (fc.get('stored_procedures') or [])]
    got = sorted({s.split('.')[-1].strip('[]').lower() for s in names})
    rows.append({'action': key, 'want': want, 'got': got, 'reach': len(fc.get('reachable_methods') or []),
                 'paths': len(fc.get('execution_paths') or []), 'tables': len(fc.get('tables') or [])})
json.dump(rows, open(S + sys.argv[1], 'w'), ensure_ascii=False, indent=1)
w = [r for r in rows if r['want']]
full = sum(1 for r in w if set(r['want']) <= set(r['got']))
part = sum(1 for r in w if set(r['got']) & set(r['want']) and not set(r['want']) <= set(r['got']))
print('called', len(rows), 'errors', dict(errs))
print('actions that should reach SP', len(w), '| fully matched', full, '| partial', part, '| none', len(w) - full - part)
print('extra SPs not in truth', sum(len(set(r['got']) - set(r['want'])) for r in rows))
print('reachable_methods == 1 (stops at action):', sum(1 for r in rows if r['reach'] <= 1), 'of', len(rows))
print('SP coverage', len({s for r in w for s in r['got']} & {s for r in w for s in r['want']}), '/', len({s for r in w for s in r['want']}))
