# 10 — 提供 Exact Path Evidence API

**What to build:** 呼叫端能以 `path_id` 取得最小且完整的 Path Evidence，包括相關 C# methods、SP/DML、View/UDF definitions，而不帶入其他 branch 或重複 source。

**Blocked by:** 04 — 串起第一條 C# 到 DML 的 Execution Path

**Status:** ready-for-agent

- [x] valid path ID 能取得完整 method source、SP definitions 與 terminal DML evidence。
- [x] source snapshot 透過 identity 與 span 還原內容，不在 path 中重複保存原始碼。
- [x] sibling branches、無關 methods 與 FK extensions 預設不出現在 evidence。
- [x] invalid 或 stale path ID 回傳明確且可處理的錯誤。