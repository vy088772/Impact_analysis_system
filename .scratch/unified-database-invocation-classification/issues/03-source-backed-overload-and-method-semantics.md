# 03 — Source-Backed Overload and Method Semantics

**What to build:** 讓 `CSharpAnalysisGateway` 以 source implementation 或可接受的 implementation evidence 決定 wrapper method 的實際 semantics，而不是以 method name 或 procedure prefix 猜測。Overload identity 必須足以區分同名但不同資料庫行為的 methods。

**Blocked by:** 01 — Direct Text Database Invocation; 02 — Catalog-Validated Stored-Procedure Invocation; existing `csharp-sql-execution-paths` 05 — Source Wrapper Discovery.

**Status:** ready-for-agent

- [ ] 每個可分類的 method 都保留 receiver type、method name、arity 與可取得的 parameter types，並以這些 facts 選擇 overload。
- [ ] Source implementation 能區分 fixed `CommandType.Text`、fixed `CommandType.StoredProcedure`、call-site selected 與 unresolved method semantics。
- [ ] fixed Text implementation 即使 command text 以 `sp`、`usp` 或 `proc` 開頭，也維持 `inline_sql`；method name 或 prefix 不得單獨產生 stored-procedure evidence。
- [ ] fixed Stored Procedure implementation 只有在 target finite 且 terminal sink 已知時，才進入 stored-procedure classification。
- [ ] 無法唯一選擇 overload 時保留所有候選、source provenance 與 `ambiguous_overload` reason，不得依 registry order 或 method name 任意選擇。
- [ ] Source-backed SQLObject fixture 能驗證 text-mode reader/scalar/edit、fixed stored-procedure reader/non-query 與 call-site semantics。
