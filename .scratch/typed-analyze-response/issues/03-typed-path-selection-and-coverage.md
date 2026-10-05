# 03 - Use Typed Paths and Coverage

**What to build:** Path selection uses checked Analyze data and retains the correct Database for each selected path.
Coverage output still states which evidence the run checked and which evidence remains unavailable.

**Blocked by:** 02 - Keep Receive, Recovery, and Merge Typed.

**Status:** resolved

- [x] Work in llamaindex-spec-rag and migrate the Analyze inputs of path_selection and coverage.
- [x] Use model attributes for structured Analyze records instead of string keys with empty defaults.
- [x] Keep genuine dynamic maps and unrelated endpoint data in their existing forms.
- [x] Preserve path identity, entry methods, branch information, targets, evidence ratings, and candidate order.
- [x] Preserve each selected path's complete Database identity for Path Expansion.
- [x] Preserve the Bounded Candidate Set and existing selection rules; do not introduce a new ranking policy.
- [x] Preserve capacity notes, coverage counts, skipped reasons, and the Impact Coverage Scope.
- [x] Keep absent evidence distinct from a validated empty section without adding new evidence ratings.
- [x] Update adjacent call-site annotations and focused fixtures required by the typed input contract.
- [x] Test candidate selection, Database routing, omitted candidates, and coverage output with checked model inputs.
- [x] Assert observable selection and coverage results rather than private helper calls or call order.
- [x] Run focused path and coverage tests and introduce no new type errors in the touched slice.
- [x] Do not change the Path Evidence endpoint contract or add a dictionary compatibility adapter.
- [x] Keep this ticket independently executable from ticket 04 after ticket 02 completes.

## Comments

### Completion Notes

- The implementation commit is `18ae323` in llamaindex-spec-rag.
- The changed modules are `path_selection`, `coverage`, and the `select_path_evidence` caller in `orchestrator`.
- `collect_path_candidates` reads a Typed Analyze Result through model attributes.
- Each candidate keeps the complete Database identity from its merged path record.
- An incomplete Database pair still becomes no identity, as ADR-0003 requires.
- Compact paths keep priority over full Execution Paths, and candidate order is unchanged.
- The selector summary omits a null `terminal_operation` and an omitted `unresolved_reason`, as before.
- The fallback evidence bag keeps its Path Evidence shape as a dictionary.
- A literal SP candidate keeps the complete wire record of its Database Invocation.
- `PathSelectionCoordinator` keeps `CapacityNote` models until it renders the selector prompt.
- The rendered capacity-note JSON now uses the model field order. The content is unchanged.
- The coverage renderers read `ImpactCoverage`, `DatabaseRead`, and `DatabaseSkipped` attributes.
- A checked result always carries `impact_coverage`, so the renderer has no absent-coverage guard.
- A validated empty coverage renders "無" for read and skipped caches.
- The evidence checks use `DbInvocationEvidenceRating` and add no new evidence rating.
- The client adds no dictionary compatibility adapter and changes no Path Evidence contract.
- `tests/_sql_cache_fixtures.typed_analyze_result` builds checked results through the merge entry point.

### Verification

- The focused path, coverage, wiring, and declared-Database files pass 85 tests and fail 4.
- The 4 failures occur in `agent_tools._summarize_analysis` or `context_builder.build_context`.
- Tickets 04 and 05 own those consumers.
- `test_path_expansion_opens_the_sql_cache_that_produced_the_path` now passes.
- `path_selection` and `coverage` pass mypy with no errors.
- The full offline suite passes 1,463 tests and 68 subtests, with 57 failures.
- The baseline at `59f4e03` had 2 failures.
- 27 failures occur because workflow-test stubs give dict Analyze results to `collect_path_candidates`.
- 18 failures occur because `context_builder` or `agent_tools` give dict results to the coverage renderer.
- The remaining failures are assertion results of the same dict stubs, plus the mypy gate.
- The failing files are `test_architecture_modules` (29), `test_shape_fragment_composition` (5), `test_unread_system_evidence_gaps` (5), `test_evidence_gaps_reporting` (4), `test_coverage` (3), `test_evidence_flag_gating` (2), and one each in `test_mypy_gate`, `test_path_evidence_wiring`, `test_question_threading`, and `test_rescuable_empty_scope`.
- The commit at `59f4e03` passes those workflow tests. The stubs and consumers need tickets 04 and 05.
- The mypy gate reports 10 errors. The baseline had 5.
- The new errors are at callers that still annotate Analyze results as dictionaries.
- The new error locations are `orchestrator.py:293` and `:1371`, `agent_tools.py:377` and `:1591`, and `context_builder.py:1321`.
- A typed local list in `run_impact_analysis` moves the error to the `ImpactAnalysisResult` field and to `finalize_analysis`.
- Ticket 05 owns those result annotations, so this ticket keeps them unchanged.
- The offline suite excludes the live-service script `tests/_tmp_flow_chain_test.py`.

### Review

- The Standards review found no hard violations.
- The review fixes use the evidence enum, rename the path union to `ExecutionPathRecord`, and stop the fixture from changing a read in place.
- The `_compact_summary` and fallback field lists remain separate because their omission rules differ.
- The Spec review found no scope creep.
- The review fix adds a test for an omitted `unresolved_reason`.
- The Spec review confirmed the failure and type-error counts.
