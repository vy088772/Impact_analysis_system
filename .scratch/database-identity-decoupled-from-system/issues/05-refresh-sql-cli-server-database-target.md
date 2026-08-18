# 05 — `refresh_sql_cli` Targets a Database Directly, Independent of System

**Repo:** `llamaindex-spec-rag`
**Spec:** `Impact_analysis_system/.scratch/database-identity-decoupled-from-system/spec.md`
**ADR:** `Impact_analysis_system/docs/adr/0010-scan-identity-independent-of-app-credentials.md`

**What to build:** A Database with no owning System (like `SysErrorRecord`) can be scanned without inventing a fake System for it. `refresh_sql_cli` accepts `(server, database)` directly, in addition to its existing `system_id` argument (which now resolves to every Database that System declares, via ticket 04's `SQLServerData.json`, and scans each). Scan-tool credentials stay independent of each application's own Web.config credentials, with an optional per-`(server, database)` override.

**Blocked by:** 02 (cache-key format must match what `Impact_analysis_system` now writes/reads), 04 (`system_id` convenience mode needs `SQLServerData.json` to resolve a System's declared databases)

**Status:** ready-for-agent

- [ ] `refresh_sql_cli` accepts a direct `(server, database)` target and triggers a scan against exactly that pair — no `system_id` or `system_catalog.json` entry required.
- [ ] `refresh_sql_cli` still accepts a bare `system_id`; in that mode it resolves the System's `databases` list from `system_catalog.json`/`SQLServerData.json` and runs the same per-database scan for each entry in turn.
- [ ] The cache-key string this command sends as `RefreshSqlRequest.database` is computed by the *same normalization rule* ticket 02 implements in `Impact_analysis_system` (domain-suffix append, instance-suffix strip) — verified with a shared example (`vmsystest07` → `vmsystest07.topmost.com.tw`) so the two repos' independently-computed keys actually match on disk.
- [ ] Scanning uses the existing global `DB_AUTH_MODE` identity by default. An optional per-`(server, database)` credential override (env-var based, following the existing `DB_USER_ID`/`DB_PASSWORD` convention) is used only when both a user id and password are supplied for that pair.
- [ ] Credentials are never read from or derived from any scanned application's Web.config.
- [ ] `SysErrorRecord` can be scanned end-to-end via `refresh_sql_cli` targeting `(vmsystest07.topmost.com.tw, SysErrorRecord)` directly.
- [ ] New `tests/test_refresh_sql_cli.py` covers: the direct `(server, database)` path, the `system_id`-resolves-to-multiple-databases path, and the credential-override-vs-fallback-to-global behavior — following `tests/test_refresh_cli.py`'s existing `monkeypatch`-based CLI-test pattern.
