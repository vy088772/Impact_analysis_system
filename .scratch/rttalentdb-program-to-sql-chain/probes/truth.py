"""Ground truth from source: controller action -> reachable SP names.
Rules: method bodies by brace matching; a call `recv.M(` where recv is a ctor/field
of interface IX resolves to the class implementing IX; SP = string literal arg of
usp_ExecCmd*Async or of a same-class helper whose parameter feeds it."""
import re, json, sys
from pathlib import Path
ROOT = Path(sys.argv[1])
CLASS = re.compile(r'\bclass\s+(\w+)\s*(?:\(([^)]*)\))?\s*(?::\s*([^{]+))?\{')
METHOD = re.compile(r'(?:public|private|protected|internal)[\w\s<>\[\],?.()]*?\s(\w+)\s*(?:<[^>]*>)?\s*\(([^)]*)\)\s*(?:where[^{=]+)?(\{|=>)')
SPLIT = re.compile(r'\s*,\s*(?![^<]*>)')
def block(t, i):
    d = 0
    for j in range(i, len(t)):
        if t[j] == '{': d += 1
        elif t[j] == '}':
            d -= 1
            if d == 0: return j + 1
    return len(t)
classes = {}  # name -> {fields:{name:type}, bases:[...], methods:{name:body}}
for f in ROOT.rglob('*.cs'):
    if '/obj/' in str(f) or '/bin/' in str(f): continue
    t = f.read_text(encoding='utf-8-sig', errors='ignore')
    for m in CLASS.finditer(t):
        end = block(t, m.end() - 1); body = t[m.end():end]
        fields = {}
        for p in SPLIT.split(m.group(2) or ''):
            p = p.split('=')[0].strip().split()
            if len(p) >= 2: fields[p[-1]] = p[-2]
        for fm in re.finditer(r'(?:private|protected|public)\s+(?:readonly\s+)?([\w<>.]+)\s+(_\w+)\s*[;=]', body):
            fields[fm.group(2)] = fm.group(1)
        methods = {}
        for mm in METHOD.finditer(body):
            if mm.group(3) == '{': b = body[mm.end()-1:block(body, mm.end()-1)]
            else: b = body[mm.end():body.find(';', mm.end())+1]
            params = [p.split('=')[0].strip().split()[-1] for p in SPLIT.split(mm.group(2)) if p.strip()]
            methods.setdefault(mm.group(1), []).append((b, params, str(f.relative_to(ROOT))))
        bases = [b.strip().split('<')[0] for b in (m.group(3) or '').split(',')]
        classes[m.group(1)] = {'fields': fields, 'bases': bases, 'methods': methods}
impl = {}
for c, v in classes.items():
    for b in v['bases']:
        if b.startswith('I') and b[1:2].isupper(): impl.setdefault(b, []).append(c)
WRAP = re.compile(r'\.usp_ExecCmd\w+Async\(\s*("([^"]+)"|(\w+))')
def sp(s): return s.split('.')[-1].strip('[]').lower()
memo = {}
def reach(cls, meth, depth=0, param_args=None):
    """returns set of SPs; param_args maps parameter name -> literal"""
    key = (cls, meth, tuple(sorted((param_args or {}).items())))
    if key in memo or depth > 8: return memo.get(key, set())
    memo[key] = set(); out = set()
    for body, params, _ in classes.get(cls, {}).get('methods', {}).get(meth, []):
        for w in WRAP.finditer(body):
            if w.group(2): out.add(sp(w.group(2)))
            elif w.group(3) and param_args and w.group(3) in param_args: out.add(sp(param_args[w.group(3)]))
        for call in re.finditer(r'(?:(\b_?\w+)\.)?\b(\w+)\s*(?:<[^>]*>)?\(\s*("([^"]*)")?', body):
            recv, name, lit = call.group(1), call.group(2), call.group(4)
            if name.startswith('usp_ExecCmd'): continue
            targets = []
            if recv is None or recv == 'this':
                if name in classes[cls]['methods'] and name != meth: targets = [cls]
            else:
                typ = classes[cls]['fields'].get(recv)
                if typ: targets = impl.get(typ, [typ] if typ in classes else [])
            for tc in targets:
                for tb, tparams, _ in classes[tc]['methods'].get(name, []):
                    pa = {tparams[0]: lit} if lit and tparams else None
                    out |= reach(tc, name, depth + 1, pa)
    memo[key] = out
    return out
truth = {}
for c, v in classes.items():
    if not c.endswith('Controller'): continue
    for m in v['methods']:
        if m[0].isupper(): truth[f'{c[:-10]}.{m}'] = sorted(reach(c, m))
json.dump(truth, open(sys.argv[2], 'w'), ensure_ascii=False, indent=1)
print('actions', len(truth), 'with SP', sum(1 for x in truth.values() if x), 'distinct SP', len({s for x in truth.values() for s in x}))
print('JobType.JobTypeInvalid ->', truth.get('JobType.JobTypeInvalid'))
