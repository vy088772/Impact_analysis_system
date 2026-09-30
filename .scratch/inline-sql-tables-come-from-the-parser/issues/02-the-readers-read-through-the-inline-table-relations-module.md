# 02 — The readers of the table relations read through the inline table relations module

**What to build:** A maintainer moves the rules that read a table relation into one module, and no analyst sees a change. The inline table relations module has two queries. The by-table query returns one answer for each relation that matches a table question. The by-method query returns each relation whose source file and method pass the caller's test. `/find_by_table` builds its inline matches from the by-table query. The `/analyze` screen table list and the shared component table list take their relations from the by-method query. The test of a write access type becomes one function.

`/flow_chain` does not change in this ticket. Ticket 06 moves it.

See "The inline table relations module", "Testing Decisions", and user stories 44, 45, 47, 48, and 50 in the spec.

**Blocked by:** None — can start immediately.

**Status:** done

- [x] Before any edit, record the baseline: for each inline table of the ten local C# Scan Results, the inline matches that `/find_by_table` gives.
- [x] `/find_by_table` reads the table relations only through the by-table query.
- [x] An answer of the by-table query holds the relation, the table with its resolved schema, the table match, the Database, the database candidates, and the Database attribution.
- [x] The resolver of the inline schema is in the module, and no longer in the analyze service.
- [x] The Database attribution of an answer comes from the rule that the Execution Path builder applies to a Database Invocation. Each record carries the attribution it carries today.
- [x] The screen table list and the shared component table list read the table relations only through the by-method query. Each one gives its own ownership test, and the two ownership rules do not change.
- [x] Seam 2: the screen table list and the shared component table list give the tables they give today.
- [x] One function in the table match module tests a write access type. The ranking of a match record and `write_only` both call it. No second set of write access types stays in the analyze service.
- [x] The rule that keeps the strongest inline match of a file stays in `/find_by_table`.
- [x] The scan statistics, the merge of scans, and the HTML report keep reading the stored fields.
- [x] The relation gains no method. The C# Scan Result format version does not change.
- [x] The Seam 2 tests that exist pass with no edit of their assertions.
- [x] A one-time check compares the inline matches after the move with the baseline. Each pair is equal. This ticket records the result. The check adds no tool, and it uses the scans of the old format.
- [x] The whole suite shows no new failure.

**Notes:**

Files this ticket changed (other tickets run in parallel; these are the only ones):

- `service/inline_table_relations.py` (new): `by_table(scan, question)` returns one `InlineTableAnswer` for each relation that matches. `by_method(scan, passes)` returns each relation whose source file and method name pass the caller's test. `_InlineSchemaResolver` moved here from the analyze service, with no change.
- `service/table_match.py`: new `is_write_access(access_type)`, with the one set of write access types.
- `service/execution_path_builder.py`: the private `_database_attribution(invocation)` became the public `database_attribution(database, database_candidates)`. The two path records call it, and the by-table query calls it.
- `service/analyze_service.py`: only these parts: the imports; the screen table list and the shared component table list in `analyze()`; the removal of `_InlineSchemaResolver`; `_table_match_rank`; the inline loop and the `write_only` filter in `find_by_table`. The `find_by_sp` changes in the same file belong to another ticket.
- `tests/test_table_match.py`: 3 new Seam 2 tests (an inline write outranks the read of its file and stays in a `write_only` answer; the record of a resolved connection; the record of an unresolved connection).
- `tests/test_shared_component_contributions.py`: 2 new Seam 2 tests (a screen lists the tables of its own actions only; a view component lists the tables of its entry method only).

The five new tests passed on the code before the move, and they pass after it. No existing assertion changed.

Decisions:

- The by-table query takes no rated Database Invocations yet. No relation holds a source span before ticket 03, so the parameter has no use here. Ticket 05 adds it with the pairing. Until then `database_candidates` is always empty, and the attribution is `resolved` or `unresolved`, as before.
- `is_write_access` ignores the case of the letters. Before the move, the ranking ignored the case and `write_only` did not. The two now agree (user story 47). No producer writes a lower-case access type: the C# parser writes the `SQLQueryType` values and the graph path writes upper-case constants. So no answer changes.
- `/flow_chain` backward still reads `scan.table_relations` itself (`service/flow_chain_builder.py`). Ticket 06 moves it. The module docstring says so.

One-time check (2026-09-30, scans of the old format, cache version 40):

- The check ran `find_by_table` on each of the ten local C# Scan Results (641 relations). The graph part was off, so each answer held inline matches only.
- For each inline table it asked four names: the bare name, the written name, `dbo.<name>`, and `otherschema.<name>`. It asked each name with no Database, with each connection Database of the scan, and with a Database that no scan has. It asked each with `write_only` off and on.
- Before the move: 3312 questions, 3530 match records. After the move: the same. The two JSON outputs are byte-equal (SHA-256 `f7f4ef8b...0d58fd`). Each pair is equal.
- Limit of the check: each of the 641 local relations has the access type `SELECT`. So the local data does not exercise a write access type. The Seam 2 tests cover it.

Verification: `pytest tests/test_table_match.py tests/test_shared_component_contributions.py` gives 39 passed. The whole suite gives 16 failed and 1279 passed. The 16 failures are the same 16 ids as the baseline that ran before any edit. `test_search_roles.py` and `test_sp_tables.py` fail at collection before and after (they need a Database connection).

Review: `/code-review` found no defect. Changes made after the review: the parameter of `by_method` is `passes` (not `owns`), the case rule moved into `is_write_access`, and the module docstring names the `/flow_chain` reader that ticket 06 moves. Open points, not done here: `CONTEXT.md` has no entry for the inline SQL table relation (ticket 07); the new `write_only` test repeats the monkeypatch lines of `_ask_inline`.
