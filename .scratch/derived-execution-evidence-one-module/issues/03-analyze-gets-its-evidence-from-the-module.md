# 03 — `/analyze` gets its evidence from the module

**What to build:** `/analyze` asks the module for evidence one time per request. It gives the files of all its resolutions and of their shared components as the needed files. It filters each resolution and each shared component from that one result. A warm scope answers fast. A cold scope answers as fast as today. The answers do not change. See the spec, sections "Read-only evidence" and "Endpoints".

**Blocked by:** 02 — `/path_evidence` gets its evidence from the module and finds a path by its path_id.

**Status:** done (2026-10-02). See "Implementation notes" at the end.

- [x] One `/analyze` request calls the entry point one time.
- [x] The needed files include the files of every shared component.
- [x] `/analyze` filters invocations first, then asks for their paths.
- [x] The branch without a SQL graph and without a Database copies each path before it rewrites the unresolved reason.
- [x] An endpoint-seam test runs `/analyze` two times on one retained evidence. The retained paths do not change.
- [x] `/analyze` takes an optional evidence source. Endpoint-seam tests cover a WebForms program, an MVC Program Screen, and a shared component.
- [x] The present `/analyze` tests pass with no change in expected answers.

## Implementation notes

**Test runs.** Full suite: 1617 passed, the same 2 collection errors as the baseline (`test_search_roles.py`, `test_sp_tables.py`, `KeyError: 'PUR'`, a real database connection). Ticket 02 ended at 1611. The typecheck (mypy on `analyze_service.py` and `derived_execution_evidence.py`) gives 281 errors before and after the change, so the change adds no error.

**`/analyze`.** `analyze(req, evidence_source=evidence_for_scope)`. The function now has two passes.
- The first pass resolves every name. For each Program Screen it also resolves the shared components (`_AnalyzedUnit(resolution, contributions)`). It collects the files of all resolutions and of all component files, once each, as the needed files.
- One call to the evidence source follows. When no file is needed, `/analyze` makes no call and uses an empty evidence, as the old code made no rating.
- The second pass filters each resolution and each shared component from that one result. `invocations_in(files)` groups the rated invocations by `invocation.source.relative_path`. That value is `_rel(file_path, root)` from the rating step, so the key is the same on a cold scope and on a retained one. The walk follows the order of `matched_files`, which keeps the old order of `database_invocations`.

**Paths.** `_build_program_execution_paths(req, evidence, invocations, *, scope)` now takes the filtered invocations and calls `evidence.paths_of()`. The same objects from `rated_invocations` go back, as the ticket 02 trap requires. The old `entry_filter` is gone: for a non-screen resolution `owns_action` is always true, so the filtered list equals the old unfiltered one. Without a SQL graph and without a Database, `_unresolved_without_graph` rewrites a copy of the path. The retained path does not change.

**Order of the graph check.** `_require_sql_execution_graph` still runs after the rating, as before. On a missing graph the error is the same; the rating before it now covers all needed files at one time.

**Tests.**
- New `tests/test_analyze_evidence_source.py` (endpoint seam, 6 tests): one call per request with two names, the needed files include the component file, a WebForms program, an MVC Program Screen (Delete is not owned), a shared component (only the entry method, with its label), and two `/analyze` runs on one evidence object without a graph and without a Database (the retained paths do not change).
- `tests/test_execution_path_integration.py`: the helper `_build_paths_with_handler_scope` gets the evidence from `evidence_for_scope` with `matched_files` as the needed files. The expected answers did not change.
- No other `/analyze` test changed. The stub in `test_inline_read_through_view.py` that patches `_rated_execution_invocations` still works, because the module calls the rating step through `analyze_service`.

**Code review (two axes).** Spec: no blocking finding. Fixed: the module docstring still said that `/analyze` calls the rating step directly. Standards: no hard violation. Fixed: the nested tuple type became `_AnalyzedUnit`, the contributions have their real type, and the docstring of `_program_resolutions_for_names` no longer says that `/analyze` calls it. Not changed: `analyze()` stays one long function (it was long before; a split is a separate refactor), and the new test file imports the component scan helpers from `test_shared_component_contributions.py` and has its own `_GivenEvidence` (it counts calls; the ticket 02 variant records only the last call). A move into a shared fixtures module is a separate decision.

**A note for ticket 04 and 05.** `/flow_chain` is now the only caller of `_rated_execution_invocations` outside the module.
