# 05 — Adapter and Fill Sink Parity

**What to build:** 將 Dapper、Entity Framework、SQLObject 與 ADO.NET adapter 呼叫納入與 direct call 相同的 `Database Invocation` 規則，並完整保留 terminal sink 差異。SQLObject 的 default Text、explicit SP mode 與 fixed implementation semantics 必須反映 source evidence。

**Blocked by:** 03 — Source-Backed Overload and Method Semantics; 04 — Branch-Aware Command Text and Embedded EXEC; existing `csharp-sql-execution-paths` 06 — Branch and Adapter Invocations.

**Status:** ready-for-agent

- [ ] Dapper 與 Entity Framework 的 inline SQL、stored procedure 與 unresolved mode 使用相同的 command-text、Catalog 與 `Evidence Status` 規則。
- [ ] `CreateTable` 與 `CreateDataSet` 沒有明確 SP mode 時遵循 source-defined default Text；只有 call-site mode 明確選擇 SP 時才產生 stored-procedure evidence。
- [ ] `ExeProcRead` 與 `ExeProcNon` 依 fixed implementation semantics 分別保留 reader 與 non-query sink，不需要 method-name heuristic。
- [ ] `SqlDataAdapter.Fill` 會以獨立的 `Fill` terminal sink 輸出，不得被重新命名為 `ExecuteReader`。
- [ ] Adapter fixture 能驗證 DataTable/DataSet 操作、Fill、call-site SP mode、default Text 與 literal SQL 的結果在同一 invocation shape 中一致呈現。
- [ ] Inline `EXEC` 不會因為經過 Dapper、EF 或 SQLObject adapter 就被提升成 stored-procedure mode。
