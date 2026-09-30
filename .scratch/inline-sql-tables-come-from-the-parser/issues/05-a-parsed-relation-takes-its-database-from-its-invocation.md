# 05 — A parsed relation takes its Database from its Database Invocation

**What to build:** An analyst reads an inline SQL table record, and its Database agrees with the stored procedure answer for the same call. At question time, the by-table query of the inline table relations module pairs a parsed relation with its rated Database Invocation, by the source span. The answer takes the Database, the database candidates, and the Database attribution from that rating. A relation with the attribution `candidate` matches a question on any Database, as `unresolved` does, and the record shows the candidates. When a parsed relation has no rated Database Invocation, the answer takes the stored Database. A fallback relation keeps the Database that the C# parser finds.

See "The Database of a relation", "The inline table relations module", and user stories 23 to 26, 48, and 49 in the spec.

**Blocked by:** 03 — Inline SQL tables come from the parser (this ticket reads the source span and the stored Database that ticket stores).

**Status:** done

- [x] A failing Seam 2 test comes first: a parsed relation whose invocation resolves to `PUR` gives a record with the Database `PUR` and the attribution `resolved`.
- [x] Seam 2: a parsed relation whose invocation has the candidates `PUR` and `STC` matches a question on `ETON`, and the record carries both candidates and the attribution `candidate`.
- [x] Seam 2: a parsed relation whose invocation is `unresolved` matches a question on any Database, and the record carries the attribution `unresolved`.
- [x] Seam 2: a parsed write keeps the Evidence Status `not_applicable` and stays in a `write_only` answer when its Database is not resolved.
- [x] Seam 2: a parsed relation with no rated Database Invocation gives a record with the stored Database, and the attribution `resolved` or `unresolved`. One case is a request that names no Database. One case is a source span that no rated Database Invocation has.
- [x] Seam 2: a fallback relation keeps its current Database rule.
- [x] The rating runs only when the request names a Database, as today.
- [x] Only the inline table relations module pairs a relation with its rated Database Invocation.
- [x] The whole suite shows no new failure.

**Notes:**

Files this ticket changed (other tickets run in parallel; these are the only ones):

- `service/inline_table_relations.py`: `by_table` takes two new arguments, `rated_invocations` and `root`. It pairs a relation with its rated Database Invocation by the key (source file relative to `root`, start offset, end offset). New private helpers `_span_key` and `_rated_by_span`. A paired relation takes the Database, the candidates, and the attribution from the rating (`database_attribution` of the Execution Path builder). An unpaired relation takes the stored Database, as before. A fallback relation has an empty span, so it is never paired.
- `service/analyze_service.py` (`find_by_table`): the rating step (`_require_sql_execution_graph` and `_execution_paths_for_scope`) now runs before the inline loop, still only when the request names a Database. The loop passes `rated_invocations` and `root` to `by_table`. No other line of the function changed. The file has CRLF line ends; the edit keeps them.
- `tests/test_inline_sql_table_database.py` (new): the Seam 2 tests of this ticket. They stub `_execution_paths_for_scope` and `filter_table_accesses`, so no SQL cache is needed.

Decisions and facts:

- A `candidate` or `unresolved` rating passes an empty Database to the table match. The match then ignores the Database, and the schema resolver opens no Object Location Index for it.
- The `unresolved` stored Database is the string `unknown` (`UNRESOLVED_CONNECTION_DATABASE`), not `unresolved`.
- Whole suite (without `test_search_roles.py` and `test_sp_tables.py`, which need a database): 16 failures, none from this ticket. 13 of them fail the same way with `analyze_service.py` and `inline_table_relations.py` reverted to `HEAD` (wrapper contract, `sqldbcontext`, preflight). `tests/test_program_refresh.py` does not collect at `HEAD`; its 3 failures with this patch are wrapper and catalog assertions, not table answers.
