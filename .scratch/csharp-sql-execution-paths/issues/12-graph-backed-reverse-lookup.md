# 12 — 將 table reverse lookup 與 backward flow 遷移至 graph

**What to build:** table lookup 與 backward flow 使用 SQL Execution Graph 和 Database Invocation，從 Table/DML/SP 一路反查 C# method 與 UI entry，不再依賴 legacy dependencies。

**Blocked by:** 05 — 自動解析 source-available database wrapper；06 — 支援分支 SP 名稱與常見 data-access adapters；08 — 展開 nested SP 與 SQL branch paths；09 — 補齊 SQL lineage 與 typed object nodes

**Status:** ready-for-agent

- [x] table lookup 能區分 direct/indirect read 與 write relationships。
- [x] write-only lookup 能找到 direct DML 與 nested SP writers。
- [x] backward flow 能從 Table 追到 SP、C# method 與 ASPX/UI entry。
- [x] View、Function 與 unresolved evidence 不會被錯當成 confirmed writer。