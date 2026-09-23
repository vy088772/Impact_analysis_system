# 01 — Remove the unused db_name parameter from fetch_sp_definitions

**What to build:** Remove the `db_name` parameter from `service/sp_fetcher.fetch_sp_definitions()` — the function's own docstring already says it doesn't use it. Remove the corresponding docstring line. Remove the one keyword argument passing it (`db_name=req.db_name or None`) at the call site in `service/analyze_service.py`.

**Blocked by:** None — can start immediately.

**Status:** done

- [x] `service/sp_fetcher.fetch_sp_definitions()` no longer declares a `db_name` parameter, and its docstring no longer mentions it
- [x] `service/analyze_service.py`'s call to `fetch_sp_definitions()` no longer passes `db_name`
- [x] `tests/test_sp_fetcher.py` and `tests/test_formal_output_migration.py` pass unmodified — the `fetch_sp_definitions` tests pass; see the note about one pre-existing failure

## Comments

### 2026-09-23 — implementation notes

**Files changed (and nothing else):**

- `service/sp_fetcher.py` — removed the `db_name: Optional[str] = None` parameter from `fetch_sp_definitions()`. Removed the sentence "db_name 參數保留供呼叫端相容，本函式不使用它。" from the docstring.
- `service/analyze_service.py` — removed `db_name=req.db_name or None,` from the `fetch_sp_definitions()` call in `analyze()` (the `include_sp_defs` branch).
- `service/flow_chain_builder.py` — removed `db_name=db_name,` from the `fetch_sp_definitions()` call in `_expand_sp_chain()`.

**Deviation from the spec:** the spec says one production caller passes `db_name`. A second caller, `service/flow_chain_builder._expand_sp_chain()`, also passed it. Without that edit, the call raises `TypeError`, so the edit is required by this ticket. `_expand_sp_chain()` and `build_forward_chain()` still accept and thread their own `db_name` parameter, which is now inert. I did not change those signatures; that trim is out of this ticket's scope and a candidate for a follow-up ticket.

**Follow-up candidate (found in code review):** nothing in the repo calls `_expand_sp_chain()` — it is dead code. Also, `build_forward_chain()` does not read its `database_alias`, `db_server`, or `db_name` parameters. A follow-up ticket can delete `_expand_sp_chain()` and trim those three parameters.

**Line endings:** the three `.py` files use CRLF. The committed diff keeps CRLF (5 changed lines total).

**Verification:**

- `tests/test_sp_fetcher.py`, `tests/test_exact_path_evidence.py`, `tests/test_execution_path_integration.py` — all pass, unmodified.
- `tests/test_formal_output_migration.py` — the `fetch_sp_definitions` test passes. `test_dependency_graph_renderer_ignores_legacy_sp_relations` fails, but it fails the same way on unmodified HEAD (checked in a separate worktree). It tests the dependency graph renderer's edge format, not this change.
- mypy on the three files: the error set is identical to HEAD, apart from line-number shifts.
- Full suite: 16 failed, 1036 passed, 2 collection errors. No failure traceback mentions `fetch_sp_definitions`, `db_name`, `sp_fetcher`, or `flow_chain_builder`.
