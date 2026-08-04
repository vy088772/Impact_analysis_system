# 05 — Independent Refresh Progress Contract

**What to build:** Operators can observe SQL refresh job progress and failure through a stable status lifecycle without progress state affecting SQL graph readiness, Gateway evidence, relationship provenance, or migration acceptance.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] SQL refresh creates, updates, completes, and fails bounded progress jobs that the status interface exposes consistently.
- [ ] Progress lifecycle and status API tests are independent from Graph/Gateway evidence and cache-readiness acceptance tests.
- [ ] Operational documentation and acceptance criteria state that progress completion is not proof of formal graph readiness and is not a Graph/Gateway migration release gate.
