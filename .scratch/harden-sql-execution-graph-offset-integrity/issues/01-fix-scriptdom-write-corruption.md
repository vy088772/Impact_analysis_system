# 01 — Fix the ScriptDom temp-file write corruption

**What to build:** Stop the SQL Execution Graph builder from writing stored-procedure definition text to disk in a way that a host OS's text-mode newline translation can silently lengthen before ScriptDom parses it. After this ticket, any freshly-built graph (via `refresh_sql_cli` or any other path that calls `build_sql_execution_graph`) records operation offsets that stay correctly aligned with the same definition text the JSON cache persists, on any host OS.

**Blocked by:** None — can start immediately

**Status:** done

- [x] `service/sql_execution_graph.py`'s temp-file write for ScriptDom input uses `write_text(definition, encoding="utf-8", newline="")` instead of the current call, so no newline translation occurs regardless of host OS.
- [x] A new test in `tests/test_sql_execution_graph.py`, using the real `StaticAnalyzerHost` (no mocking of ScriptDom), writes a definition containing `\r\n` line endings through the fixed write path and asserts every resulting operation's `start_offset + length` stays within the definition's own length.
- [x] A second new test deliberately re-creates the pre-fix corruption (`\r\n` → `\r\r\n`, the exact transformation the old `write_text()` call produced on a Windows host) on the same definition, runs it through the real host, and asserts the same class of out-of-bounds condition this investigation found in production reproduces — so the test proves the bug this ticket fixes, not just a passing assertion.
- [x] Confirmed (already checked during the investigation that produced this ticket) that no other `write_text()` call site in `service/` or `code_analyzer/` shares this risk shape; this ticket does not need to touch any other call site.

## Comments

- Implemented as specified: `service/sql_execution_graph.py:83` now writes with `newline=""`, disabling Python's text-mode newline translation regardless of host OS.
- Added `test_graph_offsets_stay_within_definition_length_for_crlf_source` (real `StaticAnalyzerHost`, `\r\n` definition run through `build_sql_execution_graph`, asserts every `dml_operation` node's `start_offset + length <= len(definition)`).
- Added `test_pre_fix_crlf_doubling_produces_out_of_bounds_offsets` — writes the definition with `\r\n` manually doubled to `\r\r\n` (the exact Windows-host `write_text()` transformation), runs it through the real host's `analyze_sql`, and asserts at least one operation's offset overruns the original definition length. Confirmed this reproduces the bug: needed ~40 padding lines before the final statement to accumulate enough CRLF-doubling drift to push the last operation's end offset past the original length — a short repro didn't overflow.
- Re-verified item 4 by grep: the other four `write_text()` sites (`scan_store.py:230`, `migration_report.py:292`, `sql_cache_store.py:303,336`) all write JSON/Markdown read back with plain `read_text()` in Python — none are parsed by ScriptDom or any external tool computing offsets against a separately-persisted copy of the same string, so none share this risk shape. No other call site touched.
- Both `/code-review` axes (Standards, Spec) came back clean — no blocking findings, only two minor judgement-call notes on test setup duplication (left as-is at 2 call sites).
- Full test suite run: 510 passed. 11 pre-existing failures (csharp_analysis_gateway / external_wrapper_discovery / mvc_project_scan / program_refresh) and 2 pre-existing collection errors (missing ODBC driver) reproduce identically with this change stashed out — unrelated to this ticket.
