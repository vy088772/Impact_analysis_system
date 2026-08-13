# 03 — Shape decompiled facts into a contract-preflight snapshot proposal

**What to build:** The classified facts from a decompiled DLL (ticket 02) are shaped into an `Implementation Snapshot`-formatted proposal and exposed through `StaticAnalyzerHost`'s existing versioned console contract as an additive capability, so `ProjectScanResult.contract_preflight_proposals`/`contract_proposals` can be populated with it directly. Completeness is judged by reusing the existing `validate_implementation_snapshot` rules (identity fields, resolved method body/identity/argument roles/connection boundary/effective semantics/terminal sink for every relevant operation, no unresolved overloads, single assembly revision), plus one decompile-specific rule: any decompiler-reported translation problem for a relevant method makes the snapshot incomplete.

**Blocked by:** 02.

**Status:** resolved

- [x] The host's JSON response (`contract_version == 2`) carries a decompiled snapshot proposal in a shape that `_iter_scan_proposals()` already knows how to collect, with no change needed to `contract_preflight.py`
- [x] A snapshot with every relevant operation fully resolved (body, identity, argument roles, connection boundary, effective semantics, terminal sink) and a single assembly revision is judged complete
- [x] A snapshot with any unresolved overload, missing operation fact, or more than one assembly revision is judged incomplete, reusing the existing `validate_implementation_snapshot` failure reasons
- [x] A snapshot where any relevant method has a decompiler-reported translation problem is judged incomplete for that reason specifically (distinguishable from the existing failure reasons)
- [x] Unit tests exercise `validate_implementation_snapshot` (or its decompile-aware extension) directly against synthetic complete/incomplete/translation-failure snapshot shapes, following the existing pattern in `tests/test_refresh_contract_preflight.py`

## Answer

Implemented the additive proposal seam for decompiled wrapper facts.

- `decompile-wrapper` now returns `contract_proposals` under contract version 2. The proposal contains the SHA-256 artifact/assembly/revision identity, receiver binding, database operation facts, and retained helper operation facts. The existing `service/contract_preflight.py` collector is unchanged.
- `DecompiledWrapperProposalBuilder` maps classified `WrapperDefinition` records into snapshot operations. Terminal-sink methods form the database surface; adapter factory methods remain represented as complete helper operations. Translation-problem definitions remain in the database surface so they cannot be accepted silently.
- `validate_implementation_snapshot` recognizes `decompiler_translation_problem` on an operation or matching translation-problem method and reports that reason in addition to the existing completeness reasons.
- Tests cover complete, missing-fact, unresolved-overload, mixed-revision, and translation-failure snapshots, plus the real SQLFunc host response flowing directly through contract preflight.

Validation:

- `dotnet build tools/StaticAnalyzerHost/StaticAnalyzerHost.csproj --nologo` passed.
- Focused tests: 20 passed.
- Adjacent regression tests: 18 passed.
- Applicable full suite: 339 passed, 2 pre-existing failures (Windows-only hard-coded MVC path and legacy graph-output assertion).
- Two live-DB test modules could not collect because the machine lacks `ODBC Driver 17 for SQL Server`.
