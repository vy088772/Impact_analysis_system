import json,re,collections
from pathlib import Path
KIND={'procedures':'stored_procedure','views':'view','functions':'function'}
def strip(t):
    t=re.sub(r'/\*.*?\*/',' ',t,flags=re.S); t=re.sub(r'--[^\n]*',' ',t); return re.sub(r"'(?:[^']|'')*'","''",t)
def bare(s): return s.split('.')[-1].strip('[]"').lower()
EXEC=re.compile(r'\bexec(?:ute)?\s+(?:@\w+\s*=\s*)?((?:\[?\w+\]?\.){0,3}\[?\w+\]?)',re.I)
TBL=re.compile(r'\b(?:from|join|into|update|delete\s+from|delete|merge)\s+((?:\[?\w+\]?\.){0,3}\[?\w+\]?)',re.I)
tot=collections.Counter(); ex=collections.defaultdict(list)
for p in sorted(Path('data/sql_cache').glob('*.json')):
    if p.name.endswith(('.index.json','.meta.json')): continue
    db=p.stem.split('__')[1]
    d=json.loads(p.read_text(encoding='utf-8')); g=d['sql_execution_graph']
    nodes={n['id']:n for n in g['nodes']}
    mods={}
    for c,k in KIND.items():
        for it in d[c]: mods[f"{k}:{it['schema']}.{it['name']}"]=strip(it['definition'] or '')
    known_proc={bare(m.split(':',1)[1]) for m in mods if m.startswith('stored_procedure')}
    known_tbl={bare(n['name']) for n in nodes.values() if n['type']=='table'}|{bare(t.get('name','')) for t in d['tables']}
    # per-module graph edges
    calls=collections.defaultdict(set); touched=collections.defaultdict(set)
    dml_owner={}
    for r in g['relationships']:
        if r['type']=='contains': dml_owner[r['target']]=r['source']
    for r in g['relationships']:
        if r['type']=='calls': 
            calls[r['source'] if r['source'] in mods else dml_owner.get(r['source'],r['source'])].add(bare(r['target']))
        if r['type'] in('reads','writes','uses'):
            touched[dml_owner.get(r['source'],r['source'])].add(bare(r['target']))
    for m,txt in mods.items():
        oc={bare(x) for x in EXEC.findall(txt)}-{'sp_executesql'}
        oc={x for x in oc if x in known_proc or not x.startswith('sp_')}
        gc=calls[m]
        tot['mods']+=1
        miss=oc-gc-{x for x in oc if x not in known_proc}   # known procs exec'd in text but no edge
        extra=gc-{bare(x) for x in EXEC.findall(txt)}
        if miss: tot['call_missing']+=1; ex['call_missing'].append((db,m,sorted(miss)))
        if extra: tot['call_extra']+=1; ex['call_extra'].append((db,m,sorted(extra)))
        ot={bare(x) for x in TBL.findall(txt)}&known_tbl
        mt=ot-touched[m]
        if mt: tot['table_missing']+=1; ex['table_missing'].append((db,m,sorted(mt)))
        et={t for t in touched[m] if not re.search(r'\b'+re.escape(t)+r'\b',txt,re.I)}
        if et: tot['table_extra']+=1; ex['table_extra'].append((db,m,sorted(et)))
print(dict(tot))
for k,v in ex.items():
    print('==',k,len(v))
    for x in v[:8]: print('  ',x)
