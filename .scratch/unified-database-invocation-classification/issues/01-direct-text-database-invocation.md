# 01 — Direct Text Database Invocation

**What to build:** 讓 direct `SqlClient` 與 literal inline SQL 呼叫經過同一個 `CSharpAnalysisGateway`，產生可供後續 `Execution Path` 使用的 `Database Invocation`。資料庫呼叫不再只因為不是 stored procedure 就被丟棄；普通 UI helper 仍不會被當成資料庫呼叫。

**Blocked by:** Existing `csharp-sql-execution-paths` 01 — Source Snapshot Seam; existing `csharp-sql-execution-paths` 02 — Direct SqlClient Invocation.

**Status:** ready-for-agent

- [x] Direct `SqlClient` default/Text 呼叫會產生一筆 `Database Invocation`，並保留 `method semantics`、`invocation mode`、command text、terminal sink、connection source、source span、provenance 與 `Evidence Status`。
- [x] `SELECT`、`INSERT`、`UPDATE`、`DELETE` 等 literal SQL 會被記錄為 `inline_sql`，不會被轉成 stored-procedure invocation。
- [x] Raw facts 會保留 receiver、method、argument、literal value、source span 與 connection-related facts，供 Gateway 做正式分類；不需要第二套 regex evidence source。
- [x] 同一 class 中的 alert、script 或其他沒有 command-text argument 的 UI helper 不會產生 `Database Invocation`，但真正的 database call 仍會被保留。
- [x] Focused Gateway tests 能在沒有 live SQL Server、LLM 或 runtime invocation 的情況下驗證上述結果。

- 本次設計決策影響後續 06/07/08/10。01 維持 direct SqlClient / inline SQL 的既定範圍，不負責 wrapper contract identity 或 system binding。
