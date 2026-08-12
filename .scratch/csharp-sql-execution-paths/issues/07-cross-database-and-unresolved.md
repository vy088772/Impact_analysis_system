# 07 — 處理跨 DB 歧義與 unresolved invocation

**What to build:** 讓 Gateway 對 database source 不明、跨 DB 同名、missing wrapper source 與 dynamic C# SQL 提供可解釋的 unresolved evidence，而不是猜測目標。

**Blocked by:** 04 — 串起第一條 C# 到 DML 的 Execution Path

**Status:** ready-for-agent

- [x] 已解析 database source 時只比對該 database 的 SP Catalog。
- [x] database source 不明但名稱全域唯一時最多標為 `likely`。
- [x] 同名存在多個 database 時標為 `unresolved` 並列出歧義原因。
- [x] dynamic string 與 unavailable wrapper source 保留 caller、span 與 unresolved reason。