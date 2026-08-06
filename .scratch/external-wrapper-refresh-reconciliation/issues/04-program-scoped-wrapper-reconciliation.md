# 04 — Program-Scoped Wrapper Reconciliation

**What to build:** Extend program-scoped refresh so `--program` reconciles only the selected program records while using the current cache and the selected scan root as source context. The operation must remain fail-closed for stale or missing roots and must never trigger a full-system C# analyzer.

**Blocked by:** 02 — Full Refresh Wrapper Reconciliation; 03 — Catalog-Selected Contract Propagation

**Status:** ready-for-agent

- [ ] A program-scoped refresh replaces only selected C# records and their derived raw wrapper facts in the scan cache.
- [ ] The selected-file analyzer receives the complete current scan root as source context, allowing same-root source wrappers to remain source-backed without scanning unrelated input files.
- [ ] Wrapper reconciliation covers the resulting logical cache state without triggering a second C# analyzer pass.
- [ ] All scan roots pass current-cache preflight before any selected-root update begins; stale or missing roots return the existing fail-closed error.
- [ ] A forbidden full-project scan test fails if program-scoped refresh attempts to fall back to full analysis.
- [ ] Unchanged files retain their raw invocation facts and wrapper observations; removed files no longer appear in the reconciled result.
- [ ] Multi-root tests verify that source-wrapper lookup does not cross a scan-root boundary.
- [ ] The CLI returns a non-zero exit code for program-refresh failures and exposes the wrapper summary for successful partial refreshes.
