# 03 — 建立基本 SQL Execution Graph

**What to build:** SQL refresh 使用 AST 將直接 DML 儲存成 typed SQL Execution Graph，使查詢端能取得 module、操作順序、讀寫表、寫入欄位與 source evidence。

**Blocked by:** 01 — 建立 StaticAnalyzerHost、Gateway 與 source snapshot seam

**Status:** completed

- [x] SELECT、INSERT、UPDATE、DELETE 與 SELECT_INTO 產生 typed operation nodes。
- [x] graph 能區分 `reads`、`writes` 與 `contains` relationships。
- [x] operation 保留 module identity、sequence、條件、欄位與 source location。
- [x] graph 可由 SQL refresh 建立、落地並重新載入。