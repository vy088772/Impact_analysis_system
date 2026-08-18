# 03 — Gateway Distinguishes "Uncataloged Database" From "Connection Unresolved"

**Repo:** `Impact_analysis_system`
**Spec:** `.scratch/database-identity-decoupled-from-system/spec.md`

**What to build:** With ticket 01's resolver now returning a real `{server, database}` and ticket 02's cache now keyed by that pair, wire them together so `CSharpAnalysisGateway` reports the correct reason. This closes the original bug: `Global.asax.cs`'s `spAddRecordError` call must report `not_in_resolved_catalog` (database known, not yet scanned) instead of `connection_source_unresolved` (database unknown).

**Blocked by:** 01 (needs resolved `{server, database}`), 02 (needs the new cache-key format to check catalog membership against)

**Status:** ready-for-agent

- [ ] `_resolve_database()` in `csharp_analysis_gateway.py` returns the resolved server alongside the database.
- [ ] `DbInvocation.server` is populated end-to-end for a resolved connection.
- [ ] Running analysis against `STC/Global.asax.cs`'s `WriteDB`/`spAddRecordError` call produces `evidence=UNRESOLVED`, `reason=not_in_resolved_catalog`, `database=SysErrorRecord` (not `connection_source_unresolved`, not `database="ERROR"`).
- [ ] A connection that genuinely cannot be resolved to any database still produces `connection_source_unresolved`/`ambiguous_connection_source` exactly as before — this ticket does not change behavior for that case.
- [ ] `_rate_literal_candidate()`'s existing branch logic is confirmed unchanged (it already does the right thing) — this ticket only fixes what feeds it.
- [ ] `tests/test_csharp_analysis_gateway.py` gains a case built via the existing `CSharpAnalysisGateway(catalog, connection_sources=...)` pattern that reproduces the `spAddRecordError` scenario: a resolved-but-uncataloged `(server, database)` pair must produce `not_in_resolved_catalog`.
