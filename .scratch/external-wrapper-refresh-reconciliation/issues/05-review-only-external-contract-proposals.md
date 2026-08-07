# 05 — Review-Only External Contract Proposals

**What to build:** Report unknown receiver types, ambiguous contracts, missing methods, and unavailable external wrappers as structured review candidates. Normal refresh must preserve these candidates as unresolved evidence and must never promote them into active contract semantics or write Git-tracked configuration.

**Blocked by:** 01 — Canonical Wrapper Reconciliation Boundary; 02 — Full Refresh Wrapper Reconciliation

**Status:** ready-for-agent

- [x] A new external receiver type produces a review candidate with unresolved contract status rather than an inferred active contract.
- [x] A method missing from an otherwise matching contract produces a distinct `unresolved_method` review item.
- [x] Ambiguous receiver-type matches retain every candidate contract name and do not choose by registry order, method similarity, or frequency.
- [x] Review candidates include receiver type, observed method, source span, scan root, source snapshot identity when available, contract candidates, and unresolved reason.
- [x] A source-available wrapper is not turned into an external contract proposal merely because its method is absent from the registry.
- [x] Normal refresh leaves the contract registry and system catalog unchanged, including when new wrapper observations are found.
- [x] The refresh response distinguishes review candidates from active contract selection and from `InvocationEvidence`.
- [x] Tests verify that unknown and ambiguous observations remain review-only and cannot become `proven` by name matching alone.
