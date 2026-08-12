# 02 — Catalog-Validated Stored-Procedure Invocation

**What to build:** 讓具備明確 `CommandType.StoredProcedure` 證據的 direct call 產生 stored-procedure `Database Invocation`，並以 resolved connection source 選擇正確的 `SP Catalog`。分類結果必須區分 `proven`、`likely` 與 `unresolved`，不能只靠 procedure name 外觀判斷。

**Blocked by:** 01 — Direct Text Database Invocation; existing `csharp-sql-execution-paths` 07 — Cross-Database and Unresolved.

**Status:** completed

- [x] 明確的 Stored Procedure mode、有限 command text、已知 terminal sink、resolved connection source 與 matching database-scoped `SP Catalog` entry 會產生 `proven` invocation。
- [x] 同一 procedure name 在不同 database 的 Catalog 中有不同結果時，分類只使用 resolved connection source 對應的 Catalog，不會建立跨 database 的錯誤關係。
- [x] connection source 未解析時，唯一跨 Catalog candidate 可標為 `likely`；多個 Catalog 都符合時必須維持 `unresolved`。
- [x] target 不存在於 resolved database 的 Catalog、command text 不完整或 terminal sink 不明時，不得產生 `proven`。
- [x] 結果會分開呈現 `connection source`、`invocation mode`、procedure target、terminal sink 與 `Evidence Status`。

## Comments

- Gateway focused regression: 41 passed; execution-path, integration, reverse-lookup and exact-path evidence tests: 53 passed.
- Added coverage for resolved database scoping, separated invocation projection fields, missing/blank terminal sinks, and incomplete literal command text.
