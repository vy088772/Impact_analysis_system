# 03 — Inline SQL tables come from the parser

**What to build:** An analyst asks `/find_by_table` about a table that inline C# SQL uses, and the answer comes from the analyzer host's parser. The scan sends each literal command text of a Database Invocation to SQL Text Analysis. Each table in each returned operation gives one table relation with its own access type and the reason `inline_sql_parsed`. The relation keeps the source span of its Database Invocation. A regular expression relation with the same text in the same file is replaced. Other regular expression relations stay as they are, and carry the reason `inline_sql_regex`. `/find_by_table` reports the reason and the access type of the relation. When SQL Text Analysis raises an error for a text, the scan stops, and the error names the source file and the text. The C# Scan Result format version rises by one.

A parsed relation stores the Database that the C# parser finds for the same text, and the record shows that Database. Ticket 05 changes what the record shows.

See "The parsed source", "The table relation format", "The consumers", "Testing Decisions", and user stories 1 to 13, 17, 22, 28, 29, 40, and 41 in the spec.

**Blocked by:** 01 — The graph build reads the host's answer through SQL Text Analysis (the scan calls the module that ticket makes). 02 — The readers of the table relations read through the inline table relations module (the reason and the access type of a record change in that module).

**Status:** done

- [x] A failing Seam 1 test with the real host comes first: a small C# source with `UPDATE ord SET ... FROM dbo.Orders ord JOIN dbo.Items it` gives `Orders` as `UPDATE` and `Items` as `SELECT`, both with `inline_sql_parsed`, and no `ord`. This is the only Seam 1 test with the real host.
- [x] Seam 3, with the real host, for a statement outside a SQL module: a CTE query gives no CTE name and keeps the tables of the CTE body.
- [x] Seam 3: `UPDATE ord ... FROM dbo.Orders ord JOIN dbo.Items it` writes `Orders`, reads `Items`, and names no `ord`.
- [x] Seam 3: a table name in an SQL comment and in an SQL string literal gives no table.
- [x] Seam 3: `INSERT INTO t (cols) SELECT ... FROM s` writes `t` and reads `s`.
- [x] Seam 3: `SELECT ... INTO t FROM s` writes `t` with the operation type `SELECT_INTO`.
- [x] Seam 3: a text that is not SQL gives a parse error and no operation.
- [x] Seam 1, with the in-memory adapter: a written table takes the operation type, and a read table takes `SELECT`. Both carry `inline_sql_parsed`.
- [x] Seam 1, with the in-memory adapter: a `#temp` table, an `@table` variable, a function reference, and an unresolved write target give no relation.
- [x] Seam 1, with the in-memory adapter: a text that both sources see gives only the parsed relations.
- [x] Seam 1, with the in-memory adapter: a parsed relation carries the source span of its Database Invocation.
- [x] Seam 1, with the in-memory adapter: a parsed relation stores the Database that the C# parser finds for the same text. When the parser finds no such text, the stored Database is not resolved.
- [x] Seam 1, with the in-memory adapter: an error from SQL Text Analysis stops the scan, and the error names the source file and the text.
- [x] Seam 2: `/find_by_table u write_only=True` does not report a program whose only use of `u` is the read in `UPDATE t ... FROM t JOIN u`.
- [x] Seam 2: a record carries the relation's reason in place of the fixed `inline_sql_source_fact`.
- [x] The host contract does not change.
- [x] The new relation fields use only built-in types, so the companion repository's restricted unpickler still loads the C# Scan Result.
- [x] The C# Scan Result format version rises by one, and its comment states why.
- [x] The whole suite shows no new failure.

**Notes:**

- A Seam 3 case that fails shows a defect of the host. The fix of the host is part of this ticket.
- On 2026-09-30, the real host gave the expected answer for the CTE case, the `UPDATE ord` case, the `SELECT INTO` case, and the text that is not SQL.

Files this ticket changed (other tickets run in parallel; these are the only ones):

- `code_analyzer/project_scanner.py`: `CSharpTableRelation` gains `reason` (default `inline_sql_regex`) and `invocation_span` (`(start_offset, end_offset)`, empty for a regular expression relation). New constants `INLINE_SQL_PARSED` and `INLINE_SQL_REGEX`. `ProjectScanner._build_table_relations` now takes the file results. It sends the literal command text of each Database Invocation to SQL Text Analysis in one call, builds one relation per table and operation, and drops the regular expression relations of the same file and the same text (whitespace collapsed, `--` removed, as the C# parser's cleaner removes it). `ProjectScanner.sql_text_analysis` is the adapter; a scanner that skips `__init__` builds the host adapter on first use. A host failure raises `StaticAnalyzerHostError` with the source file and the text.
- `service/scan_store.py`: C# Scan Result format version 40 → 41, with the comment.
- `service/analyze_service.py`: one line in `find_by_table`: `reason=rel.reason` in place of `"inline_sql_source_fact"`.
- `tests/test_inline_sql_table_relations.py` (new, Seam 1, one real-host case), `tests/test_inline_sql_table_answer.py` (new, Seam 2), `tests/test_sql_text_analysis_statements_outside_a_module.py` (new, Seam 3).

Decisions and facts:

- The scan skips a stored-procedure invocation. Its literal text is a procedure name, and the host would only give a parse error for it. The `_is_formal_sp_invocation` test decides. A refresh test in `tests/test_program_refresh.py` has a fake host with no SQL command; the skip keeps that test unchanged.
- A text is "parsed" when the host reports no parse error and at least one operation reads or writes a table. A text with only a `#temp` table is parsed, and it gives no relation.
- The line number of a parsed relation comes from the regular expression query of the same text. Without one, it comes from the source offset of the invocation. The class and method name come from the invocation record.
- All Seam 3 cases passed on the first run. The host needed no fix.
- Ticket 04 also raises the format version. Whoever lands second must raise it again (41 → 42) and extend the comment.
- The `access_type` of a regular expression relation is still the statement type. Ticket 04 changes it to `UNRESOLVED`.
- Whole suite: 16 failures, none from this ticket. 15 of them fail the same way on a clean `HEAD` worktree (wrapper contract and graph renderer tests). The 16th, `test_real_iqcs_refresh_creates_and_commits_a_contract`, also fails when `_build_table_relations` does nothing, so uncommitted work of a parallel ticket causes it. `tests/test_search_roles.py` and `tests/test_sp_tables.py` fail to import without a database (`KeyError: 'PUR'`), on `HEAD` too.
