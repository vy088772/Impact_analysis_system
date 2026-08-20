# 03 — Repair existing caches and cut over to the fixed graph version

**What to build:** Every SQL Execution Graph cache already on disk was built under the old, corrupting write behavior — `01` and `02` alone don't fix data that's already wrong. This ticket invalidates every existing cache and repairs it in one pass, without needing a live SQL Server connection to any target database, so the whole system moves onto correct offsets (and the new `02` staleness field) in a single, coordinated cutover instead of leaving stale caches to fail unpredictably.

**Blocked by:** 02 — the repair tool must run only after `02`'s node-schema addition exists, so its one pass produces caches carrying both the corrected offsets and the new defensive-check field together. If the version bump and repair shipped before `02`, every repaired cache would need a second repair pass once `02` landed.

**Status:** ready-for-agent

- [ ] `GRAPH_VERSION` in `service/sql_execution_graph.py` is bumped from `2` to `3`.
- [ ] A new repair tool, modeled on the existing `tools/migrate_sql_cache_keys.py` pattern (read each cache file directly off disk, transform, re-save), rebuilds `sql_execution_graph` for every cache file using that cache's own already-persisted `procedures`/`views`/`functions` `definition` text — no SQL Server connection or credentials required.
- [ ] The repair tool supports `--dry-run`, matching the existing migration tool's interface.
- [ ] The repair tool only modifies each cache file's `sql_execution_graph` field and its `graph_version`; every other field in the cache file is left byte-identical.
- [ ] `tests/test_sql_cache_store.py`'s `test_sql_cache_rejects_stale_graph_version` is extended/updated for the new constant value, confirming caches still carrying the old version are rejected.
- [ ] A new test builds a fixture cache carrying the old `graph_version` and already-correct `definition` text (no live database), runs the repair tool against it, and asserts the resulting `graph_version` matches the current constant, every operation's offset is in-bounds for that cache's own definitions, and `02`'s stored-length field is populated.
- [ ] The `GRAPH_VERSION` bump and the repair tool land together in this one ticket — the bump is never merged without the repair tool available to run immediately after, so declared databases never sit in a `SqlExecutionGraphRequiredError` window waiting on a manual SQL Server reconnect.
