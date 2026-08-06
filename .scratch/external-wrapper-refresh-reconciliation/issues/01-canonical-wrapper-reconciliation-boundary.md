# 01 — Canonical Wrapper Reconciliation Boundary

**What to build:** Establish one deterministic reconciliation boundary for raw `Database Invocation` facts. It must classify source wrappers, explicitly selected external contracts, receiver-type auto-selected contracts, ambiguous contracts, unresolved contracts, and review candidates. The existing wrapper audit CLI must consume this boundary instead of maintaining its own matching or semantic rules.

**Blocked by:** None — can start immediately

**Status:** ready-for-agent

- [ ] The reconciliation boundary accepts raw invocation facts, source-wrapper availability, an optional explicit contract, receiver-type contract candidates, and the database-scoped SP Catalog.
- [ ] Source-backed wrappers are classified separately from external wrappers and do not require an external contract when their implementation is available within the current scan root.
- [ ] An explicit contract takes precedence over receiver-type auto-selection; unique auto-selection, ambiguous selection, unknown receiver types, missing methods, and receiver mismatches have distinct machine-readable statuses.
- [ ] `inline_sql` methods are excluded from stored-procedure classification, and `call_site` methods require explicit stored-procedure mode at the call site.
- [ ] Literal stored-procedure candidates retain the existing database Catalog validation and `proven`/`likely`/`unresolved` Evidence Status rules.
- [ ] Every unresolved or ambiguous result retains receiver type, wrapper method, source span, scan root, candidate contracts, and an actionable unresolved reason.
- [ ] `discover_external_wrappers` consumes the shared reconciliation boundary and produces equivalent classifications without defining duplicate matching logic.
- [ ] Gateway-level tests cover the classification matrix through the highest existing analysis seam.
