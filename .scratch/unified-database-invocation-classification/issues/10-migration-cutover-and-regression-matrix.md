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

## Comments

The first seven acceptance-matrix categories (direct `SqlClient` through
cross-database ambiguity, contract-revision fixtures, and refresh/transaction
fixtures) were already covered by the existing focused suites built for
issues 01–09: [tests/test_csharp_analysis_gateway.py](../../../tests/test_csharp_analysis_gateway.py)
(130+ Gateway-external fixtures, including a real-`StaticAnalyzerHost` smoke
test), [tests/test_external_wrapper_contract_identity.py](../../../tests/test_external_wrapper_contract_identity.py),
[tests/test_contract_acceptance.py](../../../tests/test_contract_acceptance.py),
[tests/test_contract_transaction.py](../../../tests/test_contract_transaction.py),
[tests/test_refresh_contract_preflight.py](../../../tests/test_refresh_contract_preflight.py),
[tests/test_refresh_atomic_commit.py](../../../tests/test_refresh_atomic_commit.py),
and [tests/test_program_refresh.py](../../../tests/test_program_refresh.py). All of
those assert through public Gateway/service types only — none rely on private
helpers, regex traversal order, or registry order.

Cache invalidation was already handled by `scan_store.py`'s `_CACHE_VERSION`
(raw schema/classification changes invalidate incompatible cache) and
`contract_acceptance.reclassify_cached_scans` (contract-only changes
reclassify cached raw facts without rescanning source).

This issue added the missing cutover-decision artifact:
`build_cutover_report` and `render_cutover_report_markdown` in
[service/migration_report.py](../../../service/migration_report.py), which
aggregate evidence-status counts, review-candidate counts, contract-lifecycle
status counts, legacy-only-detection count, and the legacy-vs-Gateway
migration diff into one maintainer-readable report (savable as JSON or
Markdown via `save_migration_report`), plus test-first coverage in
[tests/test_migration_report.py](../../../tests/test_migration_report.py)
asserting aggregation correctness, that legacy-only detections never leak
into evidence/lifecycle/review-candidate counts (only into the nested
`legacy_migration` diff), and that the report can be saved as a JSON/Markdown
review artifact.

Follow-up from `/code-review` (Spec axis): the first cut summarized
`evidence_summary` with a `defaultdict`, so a status with zero occurrences
(e.g. zero `unresolved`) was silently absent from the dict and the rendered
Markdown table — a maintainer couldn't tell "zero unresolved" apart from "not
measured". Fixed by seeding `evidence_summary` with all three
`InvocationEvidence` statuses up front. The first cut also added a
`cutover_signals.ready_for_legacy_retirement` boolean computed only from
`legacy_only_detections == 0`, ignoring the `unresolved_count` and
`review_candidate_count` fields sitting right next to it in the same
dict — a scan with no legacy-only detections but many unresolved/review
candidates would still report `true`, and the spec bullet only asks the
report to *list* these signals so a maintainer can decide, not to render a
verdict itself. Removed that signal and the `cutover_signals` wrapper
entirely; `review_candidate_count` and `legacy_only_detections` are now
plain top-level fields alongside `evidence_summary`/
`contract_lifecycle_summary`. Follow-up from `/code-review` (Standards axis):
consolidated three separate loops over `records` into one, and replaced the
duplicated evidence/lifecycle Markdown table-building blocks with a shared
`_count_table` helper (matching `render_migration_report_markdown`'s existing
label/key-tuple convention); also removed the near-duplicate
`_lifecycle_invocation` test helper by extending the existing `_gateway`
helper with optional lifecycle/review-candidate kwargs.

Full test suite run (excluding two pre-existing, unrelated failures needing a
live SQL Server ODBC driver or a hardcoded Windows path): 321 passed, 2
pre-existing unrelated failures — no regressions from this change.
