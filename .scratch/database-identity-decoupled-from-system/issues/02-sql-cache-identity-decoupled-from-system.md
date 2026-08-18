# 02 — SQL Cache Identity Is (Server, Database, Schema), Not System

**Repo:** `Impact_analysis_system`
**Spec:** `.scratch/database-identity-decoupled-from-system/spec.md`
**ADR:** `docs/adr/0009-sql-cache-identity-decoupled-from-system.md`

**What to build:** `sql_cache_store.py`'s cache key moves from `system_id` to the normalized triple `(server, database, schema)`, so a Database with no owning System (or one shared by many) can be scanned and cached exactly once. The two existing cache files are migrated in place, not regenerated.

**Blocked by:** None — can start immediately

**Status:** ready-for-agent

- [ ] A pure normalization function: a hostname with no `.` gets `.topmost.com.tw` appended; a hostname that already contains `.` is unchanged.
- [ ] The same (or a paired) function strips a `host\instance` suffix down to just `host` before normalization — verified against `vmsystest08.topmost.com.tw\vmsystest08_pdcs` → `vmsystest08.topmost.com.tw`.
- [ ] Cache filenames take the form `{normalized server}__{database}__{schema}.json`, computed from `(server, database, schema)` alone — no `system_id` input anywhere in the key computation.
- [ ] Whether a Database is cataloged is determined solely by whether its computed cache file exists on disk — no whitelist or registry check added.
- [ ] A one-off migration script renames the two existing cache files (and their `.meta.json` siblings) to the new key format — `STC__dbo.json` → `vmsystest07.topmost.com.tw__STC__dbo.json`, `Y-Docs_TTPUR__dbo.json` → `vmsystest07.topmost.com.tw__PUR__dbo.json` — preserving file content byte-for-byte (no re-scan).
- [ ] New `tests/test_sql_cache_store.py` covers the normalization function (bare host, already-dotted host, named-instance suffix) and the filename builder.
- [ ] A smoke test confirms a file renamed by the migration script is readable under its new name and produces an identical parsed result to before the rename.
