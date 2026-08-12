# 04 — 串起第一條 C# 到 DML 的 Execution Path

**What to build:** 將 direct SqlClient Database Invocation 與 SQL Execution Graph 串接，輸出一條從 C# entry method 到 terminal DML 的穩定 Execution Path 與 compact summary。

**Blocked by:** 02 — 自動辨識 direct SqlClient SP invocation；03 — 建立基本 SQL Execution Graph

**Status:** ready-for-agent

- [x] 已驗證的 direct SqlClient invocation 能連到對應 SP 與 terminal DML。
- [x] 每條 path 有穩定 `path_id`、method chain、SP chain、conditions、reads、writes 與 risk flags。
- [x] compact summary 不包含完整 C# 或 SQL 原始碼。
- [x] 找不到 graph target 時回傳明確 unresolved path evidence。