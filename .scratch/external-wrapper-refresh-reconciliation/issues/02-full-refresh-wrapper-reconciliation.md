# 02 — Full Refresh Wrapper Reconciliation

**What to build:** Make a full code refresh run one source scan followed by wrapper reconciliation and return a machine-readable wrapper summary through the Impact refresh API and `refresh_cli`. The refresh must report contract provenance and review items without modifying the active contract registry or system catalog.

**Blocked by:** 01 — Canonical Wrapper Reconciliation Boundary

**Status:** ready-for-agent

- [x] A full refresh invokes one source scan and then reconciles the resulting raw wrapper facts from that scan.
- [x] `POST /refresh` returns additive wrapper summary data including observed receiver types, methods, classification statuses, selected contracts, selection sources, candidate contracts, source provenance, and review reasons.
- [x] `refresh_cli` displays or forwards the wrapper summary without requiring a separate `discover_external_wrappers` invocation.
- [x] A successful source refresh can return source-backed and unresolved wrapper results without requiring a live SQL connection when SQL enrichment is not otherwise needed.
- [x] The refresh does not write `external_wrapper_contracts` or `system_catalog` as a side effect.
- [x] Existing refresh counts, source-root information, partial-refresh fields, and legacy response aliases remain backward compatible.
- [x] API and service tests verify the single-scan flow, response serialization, no-write behavior, and machine-readable unresolved results.
