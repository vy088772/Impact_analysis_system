# 13 — 產生 legacy-vs-Gateway migration report

**What to build:** 對代表性系統比較 legacy regex 與 CSharpAnalysisGateway invocation，輸出 dropped、new、confidence-changed 與 unresolved 差異，讓人工只需審查真正不一致項目。

**Blocked by:** 05 — 自動解析 source-available database wrapper；06 — 支援分支 SP 名稱與常見 data-access adapters；07 — 處理跨 DB 歧義與 unresolved invocation

**Status:** ready-for-agent

- [x] 報告依 caller/database/SP identity 對齊新舊結果並分類差異。
- [x] legacy 命中若未成為新 formal relation，必須有 unresolved reason 或 dropped 記錄。
- [x] 報告能辨識新 Gateway 發現的 direct SqlClient、wrapper 或 branch invocation。
- [x] 至少 2 至 3 個 data-access 風格不同的代表性系統可重複產生報告。