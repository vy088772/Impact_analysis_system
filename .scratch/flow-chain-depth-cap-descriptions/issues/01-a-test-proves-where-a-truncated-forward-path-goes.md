# 01 — A test proves where a truncated forward path goes

**What to build:** A server test proves the forward-chain behavior that the spec-rag description will promise. A forward chain gets a SQL Execution Graph with a nested stored-procedure chain that is deeper than the default expansion limit. The truncated path appears in `diagnostics` with the reason `call_expansion_truncated`. It does not appear in `stored_procedures`. Its tables do not appear in `tables`. No product code changes. See `../spec.md` for the reason.

**Blocked by:** None — can start immediately.

**Status:** done

- [x] One new test calls the forward chain with a graph whose nested stored-procedure chain is deeper than the default expansion limit
- [x] The test gives one `proven` Database Invocation into the top stored procedure
- [x] The test does not pass an expansion limit, because the forward chain passes none
- [x] The test asserts that `diagnostics` contains a path with the reason `call_expansion_truncated`
- [x] The test asserts that `stored_procedures` does not contain the truncated path
- [x] The test asserts that `tables` does not contain a table that only the truncated path reaches
- [x] The test does not check the text of a docstring
- [x] The new test follows the prior art: the forward-chain unresolved-path test in the execution path integration test module
- [x] No product code changed
- [x] No existing test changed
- [x] mypy on the changed files has no new error compared to the commit before this ticket
- [x] The full test suite has no new failure compared to the commit before this ticket

**Note:** if the test shows a different behavior, stop. Do not change product code. Record the observed behavior in this file, because tickets 02 and 03 depend on it.

## Comments

### 2026-09-29 — implemented

- New test: `tests/test_execution_path_integration.py::test_forward_chain_sends_a_truncated_nested_sp_path_to_diagnostics_only`. It sits before `test_forward_chain_without_graph_keeps_inline_sql`. The import of `analyzer_operation` from `tests.sql_cache_fixtures` is the only other change in that file. No product code changed. No existing test changed.
- **Observed behavior — it matches the spec, so nothing stopped.** The graph holds 8 nested stored procedures (`usp_Level0` calls `usp_Level1` and so on up to `usp_Level7`). Only `usp_Level0` and `usp_Level7` write a table. The Database Invocation is `proven` and goes into `usp_Level0`. The test passes no expansion limit. The forward chain returned:
  - `diagnostics`: one path, `evidence` `unresolved`, `unresolved_reason` `call_expansion_truncated`. Its `sp_chain` has 7 names and ends at `dbo.usp_Level6`. The builder stops at the seventh nested stored procedure, and it does not read the operations of that procedure.
  - `unresolved_paths`: the same one path.
  - `stored_procedures`: only `dbo.usp_Level0`. The truncated path is absent.
  - `tables`: only `dbo.ReachedTable`. `OnlyTruncatedTable`, which only the truncated path reaches, is absent.
- The test also asserts that the resolved path stays (`stored_procedures` and `tables` are not empty). Without that check, the two "absent" asserts pass for an empty result.
- Mutation check: with `build_execution_paths` forced to `max_call_depth=10` (a temporary monkeypatch, no file changed), the test fails. Thus the test fails if the forward chain starts to pass a limit that expands the full chain. The code review found that a lower limit (0, 3 or 6) keeps the test green, because the chain stays truncated. The test proves where a truncated path goes. It does not fix the value of the limit.
- The test does not state the numeric limit. It uses 8 levels, which is deeper than the default. Tickets 02 and 03 can rely on the behavior above. The cycle reason `stored_procedure_call_cycle` has the same route in the builder (`unresolved` goes to `diagnostics` and `unresolved_paths`). This test does not cover it, because the ticket asks for the truncation case only.
- mypy `tests/test_execution_path_integration.py`: 304 errors before and after (the count is for the whole checked import graph). The first version of the test added 5 errors, because `build_forward_chain` returns `Optional`. The line `assert response is not None` removed them.
- Full suite (`--continue-on-collection-errors`): 16 failed, 1110 passed, 2 errors. The commit before this ticket gives 16 failed, 1109 passed, 2 errors, with the same failing tests. The failures need a real checkout, the ODBC driver, or `preflight`. The 2 errors are the collection of `tests/test_search_roles.py` and `tests/test_sp_tables.py` (`KeyError: 'PUR'`, no database connection).
