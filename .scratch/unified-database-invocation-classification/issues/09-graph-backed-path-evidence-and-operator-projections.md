# 09 — Graph-Backed Path Evidence and Operator Projections

**What to build:** 將 proven `Database Invocation` 接入既有 `SQL Execution Graph`，形成可追溯的 `Execution Path` 與完整 `Path Evidence`；同時讓 refresh、analyze、reverse lookup、audit 與 CLI 對同一 source snapshot 輸出一致的 unified classification。

**Blocked by:** 05 — Adapter and Fill Sink Parity; 06 — External Wrapper Contract Classification; existing `graph-gateway-contract` 03 — Evidence-Preserving Gateway Responses; existing `csharp-sql-execution-paths` 04 — First Execution Path Summary; existing `csharp-sql-execution-paths` 10 — Exact Path Evidence.

**Status:** ready-for-agent

- [ ] proven stored-procedure invocation 能 join 到正確 SQL module 與 terminal DML，形成穩定的 `Execution Path`。
- [ ] `Path Evidence` 保留 C# method、method semantics、invocation mode、command-text candidate、procedure target、terminal sink、connection source、branch predicate、source span、provenance 與 `Evidence Status`。
- [ ] inline SQL 會保留為 inline `Database Invocation`；embedded `EXEC` 是額外 target evidence，不會被序列化成 stored-procedure mode。
- [ ] unresolved target、ambiguous connection 或 dynamic SQL 會保留 documented unresolved evidence，不會被硬接成 proven graph relationship。
- [ ] refresh、analyze、SP/table reverse lookup、optional wrapper audit 與 CLI summary 對相同 invocation 回傳一致的 mode、sink、target、connection source、status 與 unresolved reason。
- [ ] SQL Execution Graph 仍是 SQL relationship、lineage、reverse lookup 與 terminal DML evidence 的唯一正式來源。
