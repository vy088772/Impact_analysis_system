# 02 — `/path_evidence` gets its evidence from the module and finds a path by its path_id

**What to build:** `/path_evidence` asks the module for evidence and finds the requested Execution Path through a path_id index. It does not rebuild paths one invocation at a time. A request with program names gives the module its needed files. On a miss, the module rates those files only and retains nothing. A new ADR-0040 records this partial-rating exception. See the spec, sections "Cache behaviour", "Paths and the disk format", and "Decision record".

**Blocked by:** 01 — Derived Execution Evidence moves into its own module.

**Status:** done (2026-10-02). See "Implementation notes" at the end.

- [x] The entry point takes an optional list of needed files.
- [x] A miss with no needed files runs a full derivation and retains it in memory and on disk.
- [x] A miss with needed files rates those files only. The module writes nothing to memory or to disk.
- [x] The evidence keeps the Execution Paths per invocation. It gives the paths of a given list of invocations, built on first use.
- [x] The evidence finds one path by path_id, together with its invocation, or gives nothing.
- [x] The disk store format version increases by one. A module-seam test shows that a file of the old version counts as a miss.
- [x] A module-seam test shows that a partial miss leaves the retention and the disk folder empty.
- [x] `/path_evidence` takes an optional evidence source. Endpoint-seam tests cover a found path, a missing path, and program ownership on an MVC screen.
- [x] Without program names, `/path_evidence` asks for the whole scope.
- [x] `/path_evidence` gives the same response as before for the present test cases.
- [x] ADR-0040 states that the freshness rule does not change. It states that only the miss behaviour of a request with needed files differs from ADR-0013.

## Implementation notes

**Test runs.** Full suite: 1611 passed, the same 2 collection errors as the baseline (`test_search_roles.py`, `test_sp_tables.py`, `KeyError: 'PUR'`, a real database connection). Ticket 01 ended at 1595. The typecheck (mypy on the four changed service modules) gives no new error against HEAD a7d5eea. The 36 present errors in `analyze_service.py` are old.

**The path builder.** `build_execution_paths` now has two parts. `build_execution_paths_by_invocation(invocations, graph)` gives the paths of each invocation, in input order, and builds the graph index one time per call. `ordered_execution_paths(pairs)` joins them in the old order. `build_execution_paths` calls both, so its output does not change. A per-invocation call of the old function would build the graph index again for each invocation, which is slow on a large scope.

**The evidence.** `DerivedExecutionEvidence(rated_invocations, graph, paths_by_invocation=None, on_paths_built=None)`. The paths are a list aligned with `rated_invocations`; `None` marks an invocation with no paths yet.
- `paths_of(invocations)` builds the missing paths in one batch. It finds an invocation by object identity (`id()`). **Ticket 03 trap:** `/analyze` must give back the same objects from `rated_invocations`. A copy (for example `dataclasses.replace`) raises `KeyError`.
- `execution_paths()` is `paths_of(rated_invocations)`.
- `path_by_id(path_id, produced_by=...)` builds every path of the scope on first use, then indexes them. The index keeps every match per path_id. `produced_by` selects among them, so two scan roots with one relative path cannot hide an owned path behind a foreign one (found by the Spec review).
- `on_paths_built` runs only when the last invocation gets its paths. A partial build stays in memory only.

**The module.** `evidence_for_scope(..., needed_files=None, refresh=False)`. A hit returns the whole scope with or without needed files. A miss with needed files rates those files and returns evidence with no `on_paths_built`; it skips `_retain` and the store.

**The disk store.** Version 5. The field `execution_paths` became `paths_by_invocation`. `store()` takes `paths_by_invocation=`.

**`/path_evidence`.** `get_path_evidence(req, evidence_source=evidence_for_scope)`. With program names it gives `matched_files` as the needed files and passes the ownership check as `produced_by`. Without program names it asks for the whole scope. `missing_snapshot` still reads the owned invocations, so `stale_path` and `path_not_found` keep their meaning. On a retained hit, the first `path_by_id` builds every path of the scope and writes the file again. Later requests reuse them.

**ADR and glossary.** New `docs/adr/0040-a-request-that-names-its-files-rates-them-without-retention.md`. `CONTEXT.md` (Derived Execution Evidence) links to it in one short sentence.

**Tests.**
- `tests/test_derived_execution_evidence.py`: the `_scan` helper takes `beta_calls` for a second program, and `_evidence` takes `needed`. 12 new module-seam tests: old version 4 file is a miss, partial miss rates only the needed files, partial miss leaves memory and disk empty, memory hit and disk hit with needed files give the whole scope, `paths_of` per invocation, `execution_paths()` equals one old build, paths built one time, path_id found with its invocation, `produced_by` filter, unknown path_id, paths survive a restart. `_forbid_path_builds` now patches `build_execution_paths_by_invocation`.
- `tests/test_path_evidence_program_files.py`: moved to the endpoint seam. `_GivenEvidence` records the needed files. The old patches of `_rated_execution_invocations` and `build_execution_paths` are gone. New: the screen finds the path of its own action (Index), it does not find the path of an action it does not own (Delete), and no program names gives `needed_files=None`. The scan gets a source snapshot of `OrdersController.cs`.
- `tests/test_exact_path_evidence.py`: an autouse `RatedInvocationsRetention`, because a request without program names now retains to memory and disk. New endpoint-seam tests for a found path and a missing path (`path_not_found`).
- `test_inline_sql_table_database.py` and `test_inline_read_through_view.py` give `paths_by_invocation=[[] ...]` in place of `execution_paths=[]`.

**Code review (two axes).** Standards: no hard violation. Fixed: the duplicated rating call in `evidence_for_scope`, `needed_files` typed as `FileAnalysisResult`, an unused test parameter, the `_STORE_VERSION` inline comment that named v2, and the glossary addition shortened to one link sentence. Not changed: the signature clump of the evidence source (a Protocol already names it). Also not changed: the stub `rated(scope, scans, merged, root, *, refresh=False)` in `test_inline_sql_table_database.py` has no `needed_files`. It works because `/find_by_table` asks for the whole scope. **Ticket 03 trap:** if `/analyze` starts to pass `needed_files` to a stub of that shape, the stub breaks. Spec: nothing missing. Fixed: the path_id index with several matches (see above). Accepted: a retained hit makes the first `/path_evidence` build every path of the scope.
