# 06 — 支援分支 SP 名稱與常見 data-access adapters

**What to build:** 將 branch-assigned procedure names、Dapper 與 Entity Framework 呼叫轉成相同 Database Invocation 模型，使每個可證明的分支都能形成正確 Execution Path。

**Blocked by:** 04 — 串起第一條 C# 到 DML 的 Execution Path

**Status:** ready-for-agent

- [x] 同一變數在不同 branch 指向不同 SP 時產生分離的 invocation 與 branch context。
- [x] 預設值與條件重新賦值都不會被遺漏。
- [x] Dapper 與 Entity Framework 的 SP mode 使用相同 evidence 與 Catalog 規則。
- [x] 普通 query、inline SQL 與不明 command type 不會被誤標為 `proven`。