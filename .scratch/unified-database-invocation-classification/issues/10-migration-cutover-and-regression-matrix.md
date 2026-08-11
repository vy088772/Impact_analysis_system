# 10 — Migration Cutover and Regression Matrix

**What to build:** 建立 unified classifier 的 focused regression matrix 與 migration cutover criteria，確認不同資料存取方式、contract revision lifecycle、recoverable refresh transaction 與 operator manifest 都能穩定產生相同的 `Database Invocation` contract，並確保 legacy regex parser 只作 comparison input，不再回灌正式 evidence。

**Blocked by:** 08 — Atomic Refresh Commit and Scope Guards; 09 — Graph-Backed Path Evidence and Operator Projections; existing `csharp-sql-execution-paths` 13 — Migration Difference Report; existing `csharp-sql-execution-paths` 14 — Cutover and Contract.

**Status:** ready-for-agent

- [ ] Focused suite 覆蓋 direct `SqlClient`、source wrapper、external wrapper、Dapper、Entity Framework、SQLObject、inline SQL、embedded `EXEC`、branch、overload、`Fill`、dynamic SQL、UI false positive 與 cross-database ambiguity。
- [ ] Contract fixtures 覆蓋 complete/incomplete `Database Behavior Surface`、exact Metadata as Source、single assembly revision、unknown overload/helper、conflicting revision、canonical signature normalization、deterministic fingerprint、equivalent reuse、behavior change、append-only registry 與 historical `Analysis Manifest`。
- [ ] Refresh/transaction fixtures 覆蓋 selector normalization、explicit candidate boundary、invalid selector preservation、one-versus-many deterministic selector serialization、preflight status separation、two-file rollback/recovery、transaction manifest、program-scoped guard、full-system onboarding 與 cached reclassification。
- [ ] 每個 fixture 以 Gateway 對外的 `Database Invocation`、`Execution Path`、`Analysis Manifest` 或 review/unresolved result 驗證，不依賴 private helper、regex traversal order 或 registry order。
- [ ] legacy parser 與 Gateway 的差異只產生 migration comparison report；legacy output 不會合併進 formal invocation、graph relationship 或 path evidence。
- [ ] raw invocation schema 或 classification semantics 改變時會使不相容 cache invalidated；contract-only change 能 reclassify compatible cached raw facts 而不重新掃描 source，source change 則需要新的 refresh。
- [ ] focused suite 不需要 live SQL Server、live external repository、LLM service 或 runtime invocation；至少一個 smoke test 以真實 `StaticAnalyzerHost` 驗證 typed receiver 與 branch facts。
- [ ] cutover report 能清楚列出 proven、likely、unresolved、review candidate、contract onboarding lifecycle 與 legacy difference，供維護者決定是否淘汰舊 formal path。
