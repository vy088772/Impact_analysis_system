# 02 — 自動辨識 direct SqlClient SP invocation

**What to build:** 讓 CSharpAnalysisGateway 從 direct SqlClient 使用方式產生 evidence-rated Database Invocation，並以 connection source 與 SP Catalog 驗證目標 stored procedure。

**Blocked by:** 01 — 建立 StaticAnalyzerHost、Gateway 與 source snapshot seam

**Status:** completed

- [x] 明確設定 StoredProcedure command type 且 Catalog 命中的呼叫被標為 `proven`。
- [x] 呼叫結果包含 caller identity、database source、normalized SP identity、evidence 與 source span。
- [x] inline SQL 不會被誤判為 `proven` SP invocation。
- [x] 無法解析名稱或 database source 時保留為 `likely` 或 `unresolved`，不猜測。