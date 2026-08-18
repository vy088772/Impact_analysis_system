# 07 — Analyze-Side Routing Sends the Database Name, Not the System ID

**Repo:** `llamaindex-spec-rag`
**Spec:** `Impact_analysis_system/.scratch/database-identity-decoupled-from-system/spec.md`
**ADR:** `Impact_analysis_system/docs/adr/0009-sql-cache-identity-decoupled-from-system.md`

**What to build:** Ticket 02 moved the SQL cache key off `system_id`, but the analyze-side request path still sends `"database": system_id`. For `Y-Docs_TTPUR` — whose database is actually named `PUR` — that now finds no cache at all, so `_require_sql_execution_graph` raises for that system. `rag_client` sends the catalog's `database.name` instead.

Found by the code review of ticket 02, not by the original grilling session: tickets 03 and 05 cover the gateway's `_resolve_database()` and `refresh_sql_cli`'s target argument respectively, but neither owns the `database` field of the `/analyze`, `/path_evidence`, `/find_by_sp`, `/find_by_table`, and `/flow_chain` requests.

**Blocked by:** 02 (the cache key must already be the normalized triple)

**Status:** done

- [x] One helper resolves "which SQL cache does this system read" from the catalog's `database.name`, and all five request builders use it — no call site computes it itself.
- [x] `Y-Docs_TTPUR` routes to `PUR` on all five endpoints, so its SQL cache is found again.
- [x] A system whose catalog entry has no `database.name` keeps sending its `system_id`, exactly as today — those systems have no cache to read either way, so their behaviour must not change.
- [x] `refresh_sql()`'s `database` field is deliberately left as `system_id`: it is a display/job label only, since `Impact_analysis_system` now computes that cache key from `server`/`db_name`. Ticket 05 owns that command's arguments.
- [x] `tests/test_path_evidence_wiring.py` covers the `Y-Docs_TTPUR` → `PUR` case across all five endpoints and the no-`database.name` fallback.

## Comments

The regression window was one commit: `Impact_analysis_system` `6732c30` (ticket 02) landed the new cache key; this ticket landed the caller-side fix. `STC` was never affected — its `system_id` and its database name are both `STC`.
