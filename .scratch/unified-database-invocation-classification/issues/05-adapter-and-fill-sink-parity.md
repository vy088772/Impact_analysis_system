# 05 — Adapter and Fill Sink Parity

**What to build:** 將 Dapper、Entity Framework、SQLObject 與 ADO.NET adapter 呼叫納入與 direct call 相同的 `Database Invocation` 規則，並完整保留 terminal sink 差異。SQLObject 的 default Text、explicit SP mode 與 fixed implementation semantics 必須反映 source evidence。

**Blocked by:** 03 — Source-Backed Overload and Method Semantics; 04 — Branch-Aware Command Text and Embedded EXEC; existing `csharp-sql-execution-paths` 06 — Branch and Adapter Invocations.

**Status:** resolved

- [x] Dapper 與 Entity Framework 的 inline SQL、stored procedure 與 unresolved mode 使用相同的 command-text、Catalog 與 `Evidence Status` 規則。
- [x] `CreateTable` 與 `CreateDataSet` 沒有明確 SP mode 時遵循 source-defined default Text；只有 call-site mode 明確選擇 SP 時才產生 stored-procedure evidence。
- [x] `ExeProcRead` 與 `ExeProcNon` 依 fixed implementation semantics 分別保留 reader 與 non-query sink，不需要 method-name heuristic。
- [x] `SqlDataAdapter.Fill` 會以獨立的 `Fill` terminal sink 輸出，不得被重新命名為 `ExecuteReader`。
- [x] Adapter fixture 能驗證 DataTable/DataSet 操作、Fill、call-site SP mode、default Text 與 literal SQL 的結果在同一 invocation shape 中一致呈現。
- [x] Inline `EXEC` 不會因為經過 Dapper、EF 或 SQLObject adapter 就被提升成 stored-procedure mode。

## Answer

Implemented adapter parity at the StaticAnalyzerHost and CSharpAnalysisGateway seams. Dapper and Entity Framework now retain finite branch command text, explicit SP/Text modes, unresolved modes, sink, and common Catalog evidence. Source-backed and external SQLObject call-site methods preserve default Text, while explicit SP mode alone enters stored-procedure classification; fixed reader/non-query semantics remain source-defined.

ADO.NET adapters now preserve `Fill` for command-argument, constructor-text, fluent, and `SelectCommand` assignment shapes, including DataTable/DataSet operations. Inline `EXEC` remains inline SQL with separate embedded-target evidence. Contract acceptance now persists `Fill` and call-site default mode, and scan cache version is v27.

Validation: focused Gateway suite `130 passed`; contract acceptance plus StaticAnalyzerHost integration suites `21 passed`; analyzer `dotnet build` passed. With `PYTHONPATH=.` and the four unrelated environment/schema tests excluded, the repository suite passed `281 tests` with 9 existing warnings. The full suite still has two pre-existing Windows-path collection failures (`D:\PUR\TTPUR` and `d:\TOPCSCY\Andy\TOPCSCY\Services`) and one pre-existing formal-output edge assertion failure when those tests are included.
