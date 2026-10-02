# 01 — Derived Execution Evidence moves into its own module

**What to build:** A new service module owns Derived Execution Evidence. The scope type, the validity stamp, the in-memory retention, the eviction, and the calls to the disk store move into it. `/find_by_sp` and `/find_by_table` get their evidence through the one entry point of the module. Their answers do not change. This ticket is a prefactor: it changes no behaviour. See the spec, sections "The module" and "Testing Decisions".

**Blocked by:** None — can start immediately.

**Status:** done (2026-10-02). See "Implementation notes" at the end.

- [x] Before the first code change, run the Impact benchmark suite and save the result in this feature folder as the baseline.
- [x] The module has one entry point. It takes the scope, the per-root scans, the merged scan, the scan root, and the refresh flag.
- [x] The entry point returns one evidence object with the rated Database Invocations, the joined SQL graph, and the Execution Paths of the scope.
- [x] The stamp keeps its five inputs and its comparison rule. `refresh` still skips the memory copy and the disk copy.
- [x] `/find_by_sp` and `/find_by_table` call only the entry point. They read no retention state directly.
- [x] `/find_by_sp` and `/find_by_table` take an optional evidence source. The default is the real module.
- [x] One endpoint-seam test per lookup gives an in-memory evidence source and checks the filtered answer.
- [x] The present freshness tests move to the module seam. They call the entry point with the real retention and an isolated disk folder. They do not patch the rating step.
- [x] The present lookup tests pass with no change in expected answers.

## Implementation notes

**Baseline.** `baseline-pytest.txt` in this folder holds the run before the first code change (HEAD 43d7167): 1592 passed, 2 collection errors. `after-pytest.txt` holds the run after the change: 1595 passed, the same 2 collection errors. The 2 errors (`test_search_roles.py`, `test_sp_tables.py`, `KeyError: 'PUR'`) need a real database connection. They are not a regression. Use `--continue-on-collection-errors`, or the run stops at collection.

**The module.** `service/derived_execution_evidence.py` holds `DerivedExecutionEvidenceScope`, `ValidityStamp` (was `_RatedInvocationsValidityStamp`), `rating_config_inputs`, the retention `_retention`, the eviction, and the calls to the disk store. The entry point is `evidence_for_scope(scope, per_root_scans, merged_scan, root, *, refresh=False)`. It returns a `DerivedExecutionEvidence` with `rated_invocations`, `graph`, and `execution_paths()`. `execution_paths()` builds the paths of the whole scope on first use, and then writes the evidence to disk again, as before. `/find_by_sp` never calls it, so it still builds no paths.

**The rating step stays in `analyze_service`.** `evidence_for_scope` imports `analyze_service` inside the function to avoid an import cycle. `analyze_service` imports `rating_config_inputs` from the module, because the stamp and the rating must read the configuration in the same way. Ticket 06 makes the rating step private to the module, and that removes the cycle.

**The evidence source.** `find_by_sp(req, evidence_source=evidence_for_scope)` and `find_by_table(...)` take the optional source. `EvidenceSource` is a Protocol with the same signature as the entry point. Ticket 02 adds the needed files to both.

**The disk format version stays at 4.** A v4 file from before this change names the old stamp class. `load()` cannot unpickle it, so it counts as a miss with no bump. Ticket 02 bumps the version one time, as the spec says.

**Tests.**
- New `tests/test_derived_execution_evidence.py` (module seam, 35 tests). It takes over `test_derived_execution_evidence_disk_retention.py` and `test_derived_execution_evidence_retention_bound.py` (both deleted), and the reuse, freshness, and refresh tests of the two reuse files. A test sees which copy served a request by content: scan B has new content but the same recorded state, so retained evidence still gives scan A's answer. The tests do not patch the rating step. Path reuse uses a guard that makes `build_execution_paths` raise. Eviction is read from the printed message.
- `RatedInvocationsRetention` now wraps the module retention and gains `simulate_restart()`.
- One endpoint-seam test per lookup gives evidence that differs from the real scan, so the answer proves which evidence the lookup read.
- The "reuse active and defeated" tests defeat reuse with `refresh=True`. `clear()` of memory alone no longer defeats it since the disk tier. The expected answers did not change.
- Tests that patched `analyze_service.cached_saved_at` / `cached_commit` for a stable stamp now patch `derived_execution_evidence`.

**A trap for later tickets.** `tests/conftest.py` pins the contract registry by patching `load_contract_registry` on each module that imports it. The rating now reads it through `derived_execution_evidence`, so the conftest patches that module too. Without that, one test (`test_wrapper_projection_matches_analyze_and_reverse_lookup_surfaces`) read the live registry and failed with `ambiguous_overload`. A module that starts to read the registry needs the same pin.

**Code review (two axes).** Standards: no hard violations. Fixed: the `evidence_source` docstring paragraph is now in Chinese like the docstring around it, a long line in `find_by_sp`, the conftest wrap, a duplicated depth constant (the builder default of 5 is used), and an unused `graph` from `_require_sql_execution_graph`. Not changed: the fixture name `RatedInvocationsRetention` (43 uses; a rename is a separate decision), and the lazy import (ticket 06). Spec: no blocking defect. Fixed: the store version bump was reverted (see above), and three lost assertions came back (refresh builds the paths again, the fixture restores an outside entry, the real TableB answer). The patch of `_rated_execution_invocations` in `test_inline_read_through_view.py` stays, because its `/flow_chain` tests still use it.
