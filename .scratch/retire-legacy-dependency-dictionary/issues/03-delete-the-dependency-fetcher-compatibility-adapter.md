# 03 — Delete the dependency_fetcher compatibility adapter and its guard test

**What to build:** Remove the `dependency_fetcher` module in full. It is not a reader of the legacy dependency dict — it is already graph-backed (it takes a graph argument and computes the legacy result shape from graph nodes and relationships) and its own docstring says it never falls back to the legacy indexes. It has zero production callers; its only caller was a dedicated guard test asserting that formal output consumers no longer depend on legacy relations. That invariant no longer needs a code-level guard once the module it guards is gone.

**Blocked by:** None — can start immediately.

**Status:** done

- [x] The `dependency_fetcher` module is deleted.
- [x] The guard test that imported and exercised it is deleted, along with its now-dangling import, from the formal-output-migration test file. That file's other tests (which exercise unrelated modules) are left unchanged.
- [x] The line describing `dependency_fetcher.py` in the architecture-map documentation is removed.
- [x] A repo-wide search confirms no remaining reference to the deleted module outside of this change's own diff and the ADR from ticket 01.
- [x] The affected test file passes (a pre-existing, unrelated failure in that same file — an `edges` key-shape mismatch in a different test — is out of scope and should still fail the same way it did before this change, not be silently fixed).

**Note (2026-09-22):** Deleted `service/dependency_fetcher.py` in full, plus the stale `service/__pycache__/dependency_fetcher.cpython-314.pyc`. Removed the guard test `test_dependency_fetcher_requires_execution_graph` and its `from service.dependency_fetcher import fetch_dependencies` import from `tests/test_formal_output_migration.py`; the file's other two tests (`test_dependency_graph_renderer_ignores_legacy_sp_relations`, `test_sp_fetcher_uses_graph_lineage_and_keeps_dynamic_sql_unresolved`) and their imports (`json`, `SimpleNamespace`, `service.sp_fetcher`) are untouched. Removed the `dependency_fetcher.py` row from `docs/進階手冊.md`'s architecture map. Ran `pytest tests/test_formal_output_migration.py -v`: 1 passed, 1 failed — the failure is the pre-existing `edges` key-shape mismatch in `test_dependency_graph_renderer_ignores_legacy_sp_relations` (expects `{"from", "to", "weight"}`, code returns `{"source", "target"}`), unrelated to this change and left as-is per instructions. Repo-wide grep for `dependency_fetcher` now only matches the ADR (`docs/adr/0031-...`) and this task's own ticket/spec files under `.scratch/`.
