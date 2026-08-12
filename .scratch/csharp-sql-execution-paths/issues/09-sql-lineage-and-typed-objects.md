# 09 — 補齊 SQL lineage 與 typed object nodes

**What to build:** 擴充 SQL Execution Graph，使 CTE、temp table、View、UDF 與 dynamic SQL 都能以正確型別與 lineage 參與路徑和影響分析。

**Blocked by:** 03 — 建立基本 SQL Execution Graph

**Status:** ready-for-agent

- [x] CTE 與 temp table lineage 能展開回基礎資料來源。
- [x] View、Function 與 Table 使用不同 node types 並保留 uses/reads relationships。
- [x] dynamic SQL 產生 unresolved operation，不建立猜測目標。
- [x] lineage recursion 有循環保護且輸出順序可重現。