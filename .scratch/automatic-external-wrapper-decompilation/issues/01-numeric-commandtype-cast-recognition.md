# 01 — Recognize numeric `CommandType` casts as equivalent to named members

**What to build:** `StaticAnalyzerHost`'s existing `CommandType` resolution logic (used by both direct ADO recognition and wrapper-semantics resolution) recognizes a cast of a numeric literal to `CommandType` — e.g. `(CommandType)4` — as equivalent to the named member access it already recognizes (`CommandType.StoredProcedure`). The mapping covers at least `1` → `Text`, `4` → `StoredProcedure`, and `512` → `TableDirect`. This applies uniformly to local source and any future decompiled input — it is not a decompile-only special case.

**Blocked by:** None — can start immediately.

**Status:** resolved

- [x] `IsStoredProcedureCommandType` (direct ADO recognition) recognizes `(CommandType)4` as `CommandType.StoredProcedure`, and analogously for `Text` (1) and `TableDirect` (512)
- [x] `ContainsStoredProcedureMember` (wrapper-semantics recognition) recognizes the same numeric casts inside wrapper method bodies
- [x] A numeric cast to a `CommandType` value with no defined mapping (e.g. `(CommandType)999`) is still treated as unresolved/unknown rather than silently misclassified
- [x] Existing named-member recognition (`CommandType.StoredProcedure`, etc.) is unaffected — no regression in `test_csharp_analysis_gateway.py`'s existing named-member and false-positive cases
- [x] New unit tests (small synthetic C# fixtures, no decompiler needed) cover: numeric cast for each of the three mapped values, and an unmapped numeric cast staying unresolved

## Answer

Added a shared `CommandTypeCastRecognizer` helper in `tools/StaticAnalyzerHost/CSharpAnalyzer.cs` that maps numeric `CommandType` casts (`1`→`Text`, `4`→`StoredProcedure`, `512`→`TableDirect`) to their named-member equivalent. `DirectSqlClientAnalyzer.IsStoredProcedureCommandType`/`IsTextCommandType` (direct ADO recognition) and `WrapperAnalyzer.ContainsCommandTypeMember` (wrapper-semantics recognition, used by `ContainsStoredProcedureMember`/`ContainsTextMember`) both now consult this shared resolver in addition to their existing named-member checks. An unmapped numeric cast (e.g. `(CommandType)999`) resolves to `null` and falls through to the existing "unknown"/"unresolved" path — it is never misclassified.

`(CommandType)512` resolves to `TableDirect` in the shared mapping, but no direct-invocation or wrapper-semantics consumer currently branches on `TableDirect` (only `StoredProcedure`/`Text` drive classification) — so it correctly stays `command_type_mode: "unknown"` rather than being misclassified as stored-procedure or text, the same as any other non-SP/Text value.

Validation: `dotnet build tools/StaticAnalyzerHost/StaticAnalyzerHost.csproj` succeeded with 0 warnings/errors. Five new fixture tests added to `tests/test_csharp_analysis_gateway.py` (direct SP cast, direct Text cast, direct TableDirect cast, unmapped direct cast, wrapper-body SP cast) — `140 passed` for the combined Gateway + StaticAnalyzerHost suite. Full repository suite: `330 passed`, with the two pre-existing unrelated failures (hard-coded Windows-path `test_mvc_project_scan.py` and a pre-existing `test_formal_output_migration.py` edge assertion) and two pre-existing live-DB collection errors (`test_search_roles.py`, `test_sp_tables.py`, missing ODBC driver) — none introduced by this change.
