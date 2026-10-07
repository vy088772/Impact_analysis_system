# 16 — CLASS_PATTERN backtracks on a long run of whitespace

**What to build:** The C# parser (`code_analyzer/csharp_parser.py`) takes
2656 s to parse one 21 KB file,
`TOPCSCY/TOPCSCY/Services/DSM/ToolExcelCreateService.cs`. Every other
TOPCSCY file takes less than 8 s. This one file is about 88% of each TOPCSCY
rescan (3015 s on 2026-10-07).

Make `CLASS_PATTERN` linear on a run of whitespace, so this file parses in
seconds and the parser output does not change.

**Blocked by:** None.

**Status:** needs-triage

**Category:** bug (performance)

- [ ] `ToolExcelCreateService.cs` parses in a few seconds
- [ ] The parser output of each scan root does not change
- [ ] A test parses a long run of whitespace in a time limit

**Notes:**

- Source: the shared cache rescan of ticket 11 (2026-10-07). The user asked
  why TOPCSCY takes so long.
- Cause, step by step:
  1. Lines 57 to 419 of the file are one block of old methods that `//`
     comments remove (`ExportExcelCus` and others).
  2. Since v44 (`e0cb3be`, inline-sql ticket 09), `strip_csharp_comments`
     replaces each comment with spaces before each extractor reads the text.
     The block becomes one run of 18,650 whitespace characters (lines 55 to
     419). The whole file is 20,689 characters.
  3. `CLASS_PATTERN` starts with two optional groups, each followed by
     `\s*`:
     `(?P<access>public|...)?\s*(?P<modifier>abstract|...)?\s*class\s+`.
     When both groups are absent, the two `\s*` can split one run of
     whitespace in O(n²) ways. `finditer` tries again from each position, so
     the cost is O(n³).
- Measure (`re.finditer(CLASS_PATTERN, " " * n, re.MULTILINE)`): 500 spaces
  0.03 s, 1,000 spaces 0.20 s, 2,000 spaces 1.43 s to 1.60 s. Each double
  multiplies the time by about 7 to 8.
- The other `*_PATTERN` of `CSharpParser` on 2,000 spaces: `METHOD_PATTERN`
  0.15 s, each other one 0.00 s.
- `CLASS_PATTERN` has a second call site, `csharp_parser.py:1890`, on
  `content_before`. It can run once for each lookup of a class and a method,
  which can explain why the total (2656 s) is more than one run of the
  pattern on the full file (about 1,150 s by the measure above).
- A sample of the scan process (`sample <pid>`) showed the time in the
  Python regex engine (`sre_ucs2_charset`, `sre_category`), not in the
  analyzer host. `faulthandler.dump_traceback_later` showed
  `_extract_classes`, `csharp_parser.py:481`.
- A possible fix: let one place take the whitespace, for example
  `\b(?:(?P<access>...)\s+)?(?:(?P<modifier>...)\s+)?class\s+`. Check that the
  matches stay the same on every scan root.
- To reproduce:
  `python -c "import re,time; from code_analyzer.csharp_parser import CSharpParser as P; t=time.time(); list(re.finditer(P.CLASS_PATTERN, ' '*2000, re.M)); print(time.time()-t)"`
- A parser change can change the scan output. Decide in triage if the scan
  cache version rises.
