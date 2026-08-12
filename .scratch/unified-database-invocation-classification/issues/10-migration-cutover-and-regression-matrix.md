# 10 — Migration Cutover and Regression Matrix

**What to build:** 建立 unified classifier 的 focused regression matrix 與 migration cutover criteria，確認不同資料存取方式、contract revision lifecycle、recoverable refresh transaction 與 operator manifest 都能穩定產生相同的 `Database Invocation` contract，並確保 legacy regex parser 只作 comparison input，不再回灌正式 evidence。

**Blocked by:** 08 — Atomic Refresh Commit and Scope Guards; 09 — Graph-Backed Path Evidence and Operator Projections; existing `csharp-sql-execution-paths` 13 — Migration Difference Report; existing `csharp-sql-execution-paths` 14 — Cutover and Contract.

**Status:** resolved

- [x] Focused suite 覆蓋 direct `SqlClient`、source wrapper、external wrapper、Dapper、Entity Framework、SQLObject、inline SQL、embedded `EXEC`、branch、overload、`Fill`、dynamic SQL、UI false positive 與 cross-database ambiguity。
- [x] Contract fixtures 覆蓋 complete/incomplete `Database Behavior Surface`、exact Metadata as Source、single assembly revision、unknown overload/helper、conflicting revision、canonical signature normalization、deterministic fingerprint、equivalent reuse、behavior change、append-only registry 與 historical `Analysis Manifest`。
- [x] Refresh/transaction fixtures 覆蓋 selector normalization、explicit candidate boundary、invalid selector preservation、one-versus-many deterministic selector serialization、preflight status separation、two-file rollback/recovery、transaction manifest、program-scoped guard、full-system onboarding 與 cached reclassification。
- [x] 每個 fixture 以 Gateway 對外的 `Database Invocation`、`Execution Path`、`Analysis Manifest` 或 review/unresolved result 驗證，不依賴 private helper、regex traversal order 或 registry order。
- [x] legacy parser 與 Gateway 的差異只產生 migration comparison report；legacy output 不會合併進 formal invocation、graph relationship 或 path evidence。
- [x] raw invocation schema 或 classification semantics 改變時會使不相容 cache invalidated；contract-only change 能 reclassify compatible cached raw facts 而不重新掃描 source，source change 則需要新的 refresh。
- [x] focused suite 不需要 live SQL Server、live external repository、LLM service 或 runtime invocation；至少一個 smoke test 以真實 `StaticAnalyzerHost` 驗證 typed receiver 與 branch facts。
- [x] cutover report 能清楚列出 proven、likely、unresolved、review candidate、contract onboarding lifecycle 與 legacy difference，供維護者決定是否淘汰舊 formal path。

**Resolution notes:**
- The eight acceptance-matrix categories (issues 01–09) were already covered by
  the existing focused suites: [tests/test_csharp_analysis_gateway.py](../../../tests/test_csharp_analysis_gateway.py)
  (130+ Gateway-external fixtures, including a real-`StaticAnalyzerHost` smoke
  test), [tests/test_external_wrapper_contract_identity.py](../../../tests/test_external_wrapper_contract_identity.py),
  [tests/test_contract_acceptance.py](../../../tests/test_contract_acceptance.py),
  [tests/test_contract_transaction.py](../../../tests/test_contract_transaction.py),
  [tests/test_refresh_contract_preflight.py](../../../tests/test_refresh_contract_preflight.py),
  [tests/test_refresh_atomic_commit.py](../../../tests/test_refresh_atomic_commit.py),
  and [tests/test_program_refresh.py](../../../tests/test_program_refresh.py).
- Cache invalidation was already handled by `scan_store.py`'s `_CACHE_VERSION`
  (raw schema/classification changes) and `contract_acceptance.reclassify_cached_scans`
  (contract-only changes reclassify cached raw facts without rescanning source).
- This issue added the missing cutover-decision artifact: `build_cutover_report`
  in [service/migration_report.py](../../../service/migration_report.py), which
  aggregates evidence status counts, review-candidate counts, contract lifecycle
  status counts, and the legacy-vs-Gateway migration diff into one report for
  maintainers, plus tests in [tests/test_migration_report.py](../../../tests/test_migration_report.py).
- Added [tests/test_migration_cutover_regression_matrix.py](../../../tests/test_migration_cutover_regression_matrix.py)
  as a consolidated, table-driven regression matrix tying all issue-10 fixture
  categories to the cutover report and confirming legacy detections never merge
  into formal evidence, review-candidate, or contract-lifecycle state.

