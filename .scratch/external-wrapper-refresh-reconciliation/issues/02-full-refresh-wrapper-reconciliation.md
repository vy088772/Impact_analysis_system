# 02 — Full Refresh Wrapper Reconciliation

**What to build:** Make a full code refresh run one raw source scan, contract preflight, formal wrapper classification, and reconciliation, then return a machine-readable wrapper summary through the Impact refresh API and `refresh_cli`. A valid selector prevents automatic contract changes; an unspecified or invalid selector may stage only complete source/DLL-backed contracts and commit them atomically after successful classification and reconciliation.

**Blocked by:** 01 — Canonical Wrapper Reconciliation Boundary

**Status:** ready-for-agent

- [x] A full refresh invokes one source scan and then reconciles the resulting raw wrapper facts from that scan.
- [x] `POST /refresh` returns additive wrapper summary data including observed receiver types, methods, classification statuses, selected contracts, selection sources, candidate contracts, source provenance, and review reasons.
- [x] `refresh_cli` displays or forwards the wrapper summary without requiring a separate `discover_external_wrappers` invocation.
- [x] A successful source refresh can return source-backed and unresolved wrapper results without requiring a live SQL connection when SQL enrichment is not otherwise needed.
- [x] A valid existing selector does not create or overwrite `external_wrapper_contracts` or `system_catalog`; an unspecified or invalid selector writes only a validated complete proposal after formal classification and reconciliation succeed.
- [x] Existing refresh counts, source-root information, partial-refresh fields, and legacy response aliases remain backward compatible.
- [x] API and service tests verify the single-scan/preflight flow, response serialization, conditional write and rollback behavior, and machine-readable unresolved results.
