# 03 — Catalog-Selected Contract Propagation

**What to build:** Use the system catalog as the source of the `wrapper_contract` selector for refresh, while preserving explicit caller overrides. The spec-rag client and Impact refresh API must use the same selector semantics already used by analyze and path-evidence requests.

**Blocked by:** 02 — Full Refresh Wrapper Reconciliation

**Status:** ready-for-agent

- [ ] The refresh request contract accepts an optional `wrapper_contract` selector.
- [ ] When the caller does not provide a selector, the spec-rag refresh client resolves it from the system catalog.
- [ ] An explicit caller-provided selector takes precedence over the catalog value.
- [ ] The resolved selector is forwarded through the spec-rag client, Impact API, refresh service, and shared reconciliation boundary.
- [ ] A catalog selector is treated as routing configuration and is not reported as proof of a stored-procedure or database operation by itself.
- [ ] `Y-Docs_TTPUR` can select the existing `sqlobject` contract through its catalog entry without a second discovery HTTP request.
- [ ] Client, API, and service tests verify catalog resolution, explicit override behavior, and payload compatibility with existing refresh callers.
