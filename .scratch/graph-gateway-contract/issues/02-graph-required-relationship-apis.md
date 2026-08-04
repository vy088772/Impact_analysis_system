# 02 — Graph-Required Relationship APIs

**What to build:** Callers receive explicit graph-readiness failures when requesting formal SQL relationships without a valid database-scoped SQL Execution Graph, while source-only C# facts continue to work without database graph enrichment.

**Blocked by:** 01 — Graph-Only Cache Contract.

**Status:** ready-for-agent

- [ ] Path construction and evidence, SP reverse lookup, graph-backed table lookup, and forward/backward flow all reject missing, stale, invalid, or mismatched graphs through one machine-readable readiness contract.
- [ ] Source-only C# method Flow, raw invocation facts, source spans, and direct inline-SQL facts remain available without a graph and do not claim formal SQL relationships.
- [ ] API tests distinguish invalid requests, unavailable graphs, source-scan skips, and genuine domain not-found results.
