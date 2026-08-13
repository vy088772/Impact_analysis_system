# 05 — Wire automatic decompile onboarding into full-system refresh

**What to build:** During a full-system (non-program-scoped) refresh, when a system's `wrapper_contract` selector is unspecified, an unresolved external wrapper receiver traceable to a `.csproj` reference is decompiled (tickets 02–04) and the resulting proposal flows through the existing, unmodified `run_contract_preflight()` path exactly like any other complete preflight proposal — staged and committed through the existing two-file atomic transaction on success, or left `unresolved` with `contract_preflight_failed` on incompleteness. Running `refresh_cli STC` should now resolve `SQLFunc.ExeProcRead`/`SQLFunc.ExeProcNon` calls instead of leaving them `unresolved_contract` forever.

**Blocked by:** 04.

**Status:** resolved

- [x] `refresh_cli STC` (full-system refresh) onboards a contract for `SQLFunc` end-to-end, with no human review step, when the decompiled snapshot is complete
- [x] A decompiled snapshot that fails completeness leaves the affected wrapper `unresolved` with reason `contract_preflight_failed`, exactly like any other incomplete preflight proposal — no new failure semantics introduced
- [x] A program-scoped refresh never triggers decompile-based onboarding, reusing the existing precondition seam in `tests/test_program_refresh.py`
- [x] A system with a valid, explicitly configured `wrapper_contract` selector never triggers decompile-based onboarding, and that selector remains fully authoritative
- [x] Local source-backed implementation evidence remains stronger than a decompiled contract if both are somehow available for the same receiver (decompile path only runs when local resolution has already failed)
- [x] `run_contract_preflight()` and `_iter_scan_proposals()` require no code changes — only `ProjectScanResult.contract_proposals` population changes
- [x] The refresh summary reports whether a decompilation attempt was made, its outcome (complete/incomplete/cached-skip), and the reasons for an incomplete result

## Answer

Implemented refresh-time automatic wrapper decompilation in `service/analyze_service.py`.

- Full-system refreshes with an unspecified selector locate only matching `.csproj` `<Reference>` entries, invoke the existing `StaticAnalyzerHost.decompile_wrapper()` client, and append returned proposals to `ProjectScanResult.contract_proposals` before the unchanged Contract Preflight path.
- Complete SQLFunc fixture proposals proceed through the existing staged registry and two-file atomic commit; incomplete results remain `unresolved` with `contract_preflight_failed`.
- Program-scoped refreshes, valid selectors, and source-backed wrapper evidence skip the decompile path. Attempt summaries report `complete`, `incomplete`, `cached-skip`, or `not_attempted`, including incomplete reasons.
- Added focused tests for full onboarding, incomplete failure, cache hits, scope/selector guards, source precedence, and the real SQLFunc fixture.
