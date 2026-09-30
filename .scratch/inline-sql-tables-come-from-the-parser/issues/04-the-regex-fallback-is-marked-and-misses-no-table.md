# 04 — The regular expression fallback is marked and misses no table

**What to build:** An analyst sees every inline SQL table that the parser does not cover, and each one is marked as a guess. A regular expression relation carries the access type `UNRESOLVED` and the reason `inline_sql_regex`. The fallback also applies to a text that the host parses but for which it returns no read and no write, such as `MERGE`. The regular expressions keep a statement that starts with `WITH` or `MERGE`, find the target of `INSERT INTO t (cols)`, and ignore SQL comments. A `write_only` question leaves the fallback relations out and counts them as excluded. The C# Scan Result format version rises by one.

See "The fallback source", "Testing Decisions", and user stories 14 to 16, 18 to 21 in the spec.

**Blocked by:** 03 — Inline SQL tables come from the parser (the fallback conditions depend on what the host parsed).

**Status:** done

- [x] A failing Seam 1 test with the in-memory adapter comes first: a text with no read and no write, as a `MERGE` gives, gives fallback relations with `UNRESOLVED`, and its target is among them.
- [x] Seam 3, with the real host: a `MERGE` text parses and gives no operation.
- [x] Seam 1, with the in-memory adapter: a concatenated text that the host records as `dynamic` gives fallback relations with `UNRESOLVED`.
- [x] Seam 1, with the in-memory adapter: a text with a parse error gives fallback relations with `UNRESOLVED`.
- [x] The C# parser's inline SQL table test keeps its case and states the `UNRESOLVED` access type.
- [x] The C# parser test: a text that starts with `WITH` gives its tables.
- [x] The C# parser test: `insert into ManifestNew (R_ID,data) values(...)` gives `ManifestNew`.
- [x] The C# parser test: a table name in an SQL comment gives no table.
- [x] Seam 2: `/find_by_table` with `write_only=True` leaves out a fallback relation and adds it to the excluded count.
- [x] The C# Scan Result format version rises by one, and its comment states why.
- [x] The whole suite shows no new failure.

**Notes:**

- On 2026-09-30, the real host parsed a `MERGE` text with no parse error and gave no operation.

Files this ticket changed (other tickets run in parallel; these are the only ones):

- `code_analyzer/csharp_parser.py`: new module function `strip_sql_comments` (removes `--` and `/* */`, keeps string literals, treats a C# `\n` escape as a line end). `_determine_sql_type` and `_extract_tables_from_sql` strip comments first. New `_is_kept_statement` keeps a statement that starts with `WITH` or `MERGE`. The table patterns gain `INSERT INTO t (cols)` with no function-call guard, `MERGE [INTO] t`, and `USING t`; `UPDATE SET` (inside `MERGE`) names no table. The method-call path keeps `raw_sql` (before the cleaner joins lines) for type and tables. The direct-string gate accepts `MERGE`.
- `code_analyzer/project_scanner.py`: new constant `UNRESOLVED_ACCESS_TYPE`; a regular expression relation takes it. `_collapse_whitespace` (the replacement key) also strips SQL comments, so a text with a comment still matches its parsed text.
- `service/scan_store.py`: C# Scan Result format version 41 → 42, with the comment.
- `tests/test_inline_sql_regex_fallback.py` (new): Seam 1 (in-memory adapter and real parser), Seam 2, Seam 3.

Decisions and facts:

- The three fallback conditions (no record, parse error, no read and no write) needed no new scanner code. Ticket 03 already leaves the regular expression relation in place for any text that is not parsed. Ticket 04 adds only the marks and the expression fixes.
- A `MERGE` text with no closing semicolon gives a parse error in the real host (`MERGE 陳述式必須以分號 (;) 結束`). With the semicolon, it parses with no error and no operation. Both cases use the fallback.
- "A statement that starts with a word the parser does not classify is kept" is narrowed to `WITH` and `MERGE`. Any other unknown start would keep prose that has the word `select` inside it, and `FROM the` would give a table `the`.
- The existing parser test file keeps its case. The `UNRESOLVED` statement is in `test_the_regular_expression_relations_of_the_parser_state_unresolved`, which scans the same `SELECT ... FROM PUR.dbo.Users ... JOIN Orders` text, because the access type belongs to the relation and not to the parser query.
- Whole suite (without the two files that need a database): 16 failures, none from this ticket. The same 16 fail on a clean `HEAD` worktree, except `test_real_iqcs_refresh_creates_and_commits_a_contract`. That test passes on a clean `HEAD` with this ticket's patch applied, so uncommitted work of a parallel ticket in the shared tree causes it (as ticket 03 found).
- The three source files use CRLF. Edit them with a tool that keeps CRLF.
