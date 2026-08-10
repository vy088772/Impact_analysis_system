# 05 — Review-Only External Contract Proposals

**What to build:** Report unknown receiver types, ambiguous contracts, missing methods, and unavailable external wrappers as structured review candidates. Normal refresh must preserve incomplete, conflicting, and ambiguous candidates as unresolved evidence; only complete source/DLL-backed semantics may enter a staged active contract when the selector is unspecified or invalid.

**Blocked by:** 01 — Canonical Wrapper Reconciliation Boundary; 02 — Full Refresh Wrapper Reconciliation

**Status:** ready-for-agent

- [x] A new external receiver type produces a review candidate with unresolved contract status unless preflight has complete verified semantics for a staged contract.
- [x] A method missing from an otherwise matching contract produces a distinct `unresolved_method` review item.
- [x] Ambiguous receiver-type matches retain every candidate contract name and do not choose by registry order, method similarity, or frequency.
- [x] Review candidates include receiver type, observed method, source span, scan root, source snapshot identity when available, contract candidates, and unresolved reason.
- [x] A source-available wrapper is not turned into an external contract proposal merely because its method is absent from the registry.
- [x] A valid selector leaves the contract registry and system catalog unchanged during refresh; incomplete or ambiguous observations never change them, while complete proposals commit only through the staged atomic workflow.
- [x] The refresh response distinguishes review candidates from active contract selection and from `InvocationEvidence`.
- [x] Tests verify that unknown and ambiguous observations remain review-only and cannot become `proven` by name matching alone.
