"""Count source method declarations that the cached C# scan holds, by declaration shape.

Run from the Impact repo root:
    .venv/bin/python .scratch/rttalentdb-program-to-sql-chain/probes/method_coverage.py data/scan_cache/f681f601165fe4e8.pkl

The source regex is a probe, not an oracle: it reads one-line declarations only,
so a multi-line parameter list counts on neither side.
"""
import collections
import pickle
import re
import sys
sys.path.insert(0, ".")
from pathlib import Path

DECL = re.compile(
    r'(?:public|private|protected|internal)\s+(?:static\s+|async\s+|override\s+|virtual\s+)*'
    r'([\w<>\[\],?.() ]+?)\s(\w+)\s*(?:<[^>()]*>)?\s*\([^;{]*\)\s*(?:where[^{]*)?(\{|=>)'
)

scan = pickle.load(open(sys.argv[1], 'rb'))
counts = collections.Counter()
missing = []
for result in scan.csharp_results:
    text = Path(result.file_path).read_text(encoding='utf-8-sig', errors='ignore')
    scanned = {m.name for c in result.classes for m in c.methods} | {c.name for c in result.classes}
    for match in DECL.finditer(text):
        return_type, name = match.group(1), match.group(2)
        shape = 'tuple-return' if '(' in return_type else 'other-return'
        found = name in scanned
        counts[(shape, 'in scan' if found else 'MISSING')] += 1
        if not found:
            missing.append(f'{Path(result.file_path).name}:{name}')
for key, n in sorted(counts.items()):
    print(n, key)
print('missing total', len(missing))
if '-v' in sys.argv:
    print('\n'.join(missing))
