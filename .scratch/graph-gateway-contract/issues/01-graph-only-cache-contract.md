# 01 — Graph-Only Cache Contract

**What to build:** After SQL refresh, formal SQL relationship consumers receive one version-compatible, database-scoped SQL Execution Graph and the SQL object data they require. Legacy dependency-shaped structures may be computed only as transient migration comparison input; they are not persisted and cannot provide a fallback relationship result.

**Blocked by:** None — can start immediately.

**Status:** done

- [x] A refreshed cache persists the SQL Execution Graph and required SQL object data, but no formal legacy dependency structures.
- [x] A graph-less, stale, or database-mismatched cache is rejected consistently rather than read through legacy relationship data.
- [x] Tests prove legacy-shaped comparison data cannot produce a formal relationship result after persistence.

## Comments

2026-11-02: Status corrected to `done`. Every acceptance box was already checked; only the status line was out of date.
