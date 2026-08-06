# 07 — End-to-End Evidence and Audit Parity

**What to build:** Make refresh, analyze, path evidence, reverse lookup, and the optional wrapper audit CLI expose the same wrapper classification and Evidence Status. Accepted contracts must affect downstream results without falsely promoting inline SQL, dynamic SQL, or unresolved database targets to `proven`.

**Blocked by:** 03 — Catalog-Selected Contract Propagation; 04 — Program-Scoped Wrapper Reconciliation; 06 — Explicit Contract Acceptance and Cached Reclassification

**Status:** ready-for-agent

- [ ] The same shared reconciliation semantics are observable through refresh, analyze, path evidence, reverse lookup, and the optional audit CLI.
- [ ] An accepted external contract contributes only the evidence allowed by its declared receiver, method, mode, sink, call-site mode, and database Catalog validation.
- [ ] `SQLObject.CreateReader` with a literal SELECT remains inline SQL and does not become a stored-procedure invocation.
- [ ] `CreateTable` and `CreateDataSet` produce stored-procedure evidence only when their call site explicitly selects stored-procedure mode.
- [ ] Dynamic command text, unknown receivers, missing methods, ambiguous contracts, and unresolved database attribution remain `unresolved` with provenance and reasons.
- [ ] Wrapper classification remains separate from SQL Execution Graph readiness; a current code refresh does not imply a current graph.
- [ ] The focused regression suite covers full refresh, program refresh, catalog propagation, proposal acceptance, cached reclassification, and audit parity.
- [ ] One end-to-end smoke test exercises typed receiver extraction from the real StaticAnalyzerHost and verifies the resulting downstream evidence shape.
