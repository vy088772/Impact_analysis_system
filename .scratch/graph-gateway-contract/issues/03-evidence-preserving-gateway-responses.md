# 03 — Evidence-Preserving Gateway Responses

**What to build:** Gateway evidence reaches reverse lookup, path, table, and flow responses without being silently upgraded. Users can inspect `proven`, `likely`, and `unresolved` records with their reason, database attribution state, caller, and source identity, while only `proven` records create formal relationships.

**Blocked by:** 01 — Graph-Only Cache Contract; 02 — Graph-Required Relationship APIs.

**Status:** ready-for-agent

- [x] Gateway and downstream response records preserve evidence, stable reason, caller/source identity, procedure identity, branch context, and explicit database attribution semantics.
- [x] A catalog-unique but connection-unresolved invocation stays `likely`; its database candidate is not represented as a trusted resolved database.
- [x] Only `proven` records enter formal calls, reads, writes, confirmed SP matches, table access matches, and confirmed Execution Paths.
- [x] Candidate and unresolved records remain visibly queryable as diagnostics without changing confirmed relationship counts.
