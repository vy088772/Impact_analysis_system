# 17 — METHOD_PATTERN backtracks on a long run of whitespace

**What to build:** After ticket 16, the C# parser still takes about 16 s to
parse `TOPCSCY/TOPCSCY/Services/DSM/ToolExcelCreateService.cs`. All of this
time is in `METHOD_PATTERN` (`_extract_methods`). Make `METHOD_PATTERN`
linear on a run of whitespace, so this file parses in less than one second.

**Blocked by:** 16

**Status:** needs-triage

**Category:** bug (performance)

- [ ] `ToolExcelCreateService.cs` parses in less than one second
- [ ] The parser output of each scan root does not change, or each change has a report
- [ ] A test parses a long run of whitespace in a time limit

**Notes:**

- Source: ticket 16 (2026-10-07). Ticket 16 put `METHOD_PATTERN` out of scope
  and asked for a separate ticket if a measurement shows a cost on a real file.
- Measurements with the project `.venv`, after the ticket 16 fix:
  - `re.finditer(METHOD_PATTERN, " " * n, re.M)`: 2,000 spaces 0.20 s,
    4,000 spaces 0.82 s, 8,000 spaces 3.03 s. When n doubles, the time
    becomes about 4 times larger, so the cost is O(n²).
  - `METHOD_PATTERN` on the file after `strip_csharp_comments`: 16.31 s.
  - `cProfile` of `parse_file` on the file: `_extract_methods` takes almost
    all of the total time (18.3 s of 18.8 s). The machine had other load.
- Possible cause: the pattern starts `^[ \t]*(?P<access>...)?\s*`. When
  `access` is absent, `[ \t]*` and `\s*` can split the same whitespace in
  many ways. With `re.MULTILINE`, `^` matches at each line of the run.
- The fix of ticket 16 can show a form: let one place take the whitespace,
  for example `(?:(?P<access>...)\s+)?`.
- Parse time of the slowest files after ticket 16 (10 processes in parallel):
  `TOPCSCY/Services/DSM/ToolExcelCreateService.cs` 18.5 s,
  `TTRDQ/PQR/PQRForm_V.aspx.cs` 13.8 s, `ETR/Controllers/StandardController.cs`
  5.1 s. All 2,641 files of the 16 scan roots take 482 s.
- The old-to-new comparison script of ticket 16 can check the output.
