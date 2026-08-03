# 08 — 展開 nested SP 與 SQL branch paths

**What to build:** SQL Execution Graph 支援 stored procedure 呼叫與 SQL control flow，使同一 C# 入口下不同 SP branch 與 terminal DML 各自形成可選 Execution Path。

**Blocked by:** 04 — 串起第一條 C# 到 DML 的 Execution Path

**Status:** ready-for-agent

- [x] EXEC/EXECUTE 建立 typed `calls` relationship 並可遞迴展開。
- [x] IF/ELSE、TRY/CATCH 與迴圈條件保留在 operation branch path。
- [x] 同一 SP 不同 terminal DML branch 產生不同 `path_id`。
- [x] recursion 與循環呼叫有 deterministic visited/depth 保護。