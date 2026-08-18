# 02 — SQL Cache Identity Is (Server, Database, Schema), Not System

**Repo:** `Impact_analysis_system`
**Spec:** `.scratch/database-identity-decoupled-from-system/spec.md`
**ADR:** `docs/adr/0009-sql-cache-identity-decoupled-from-system.md`

**What to build:** `sql_cache_store.py`'s cache key moves from `system_id` to the normalized triple `(server, database, schema)`, so a Database with no owning System (or one shared by many) can be scanned and cached exactly once. The two existing cache files are migrated in place, not regenerated.

**Blocked by:** None — can start immediately

**Status:** done

- [x] A pure normalization function: a hostname with no `.` gets `.topmost.com.tw` appended; a hostname that already contains `.` is unchanged.
- [x] The same (or a paired) function strips a `host\instance` suffix down to just `host` before normalization — verified against `vmsystest08.topmost.com.tw\vmsystest08_pdcs` → `vmsystest08.topmost.com.tw`.
- [x] Cache filenames take the form `{normalized server}__{database}__{schema}.json`, computed from `(server, database, schema)` alone — no `system_id` input anywhere in the key computation.
- [x] Whether a Database is cataloged is determined solely by whether its computed cache file exists on disk — no whitelist or registry check added.
- [x] A one-off migration script renames the two existing cache files (and their `.meta.json` siblings) to the new key format — `STC__dbo.json` → `vmsystest07.topmost.com.tw__STC__dbo.json`, `Y-Docs_TTPUR__dbo.json` → `vmsystest07.topmost.com.tw__PUR__dbo.json` — preserving file content byte-for-byte (no re-scan).
- [x] New `tests/test_sql_cache_store.py` covers the normalization function (bare host, already-dotted host, named-instance suffix) and the filename builder.
- [x] A smoke test confirms a file renamed by the migration script is readable under its new name and produces an identical parsed result to before the rename.

## Comments

Implemented in `service/sql_cache_store.py` (`normalize_server()`, `cache_key()`,
`cache_filename()`, `resolve_server()`), `tools/migrate_sql_cache_keys.py`, and
`tests/test_sql_cache_store.py`. The migration ran against the real cache:
`STC__dbo.json` was a pure rename (byte-for-byte, mtime untouched);
`Y-Docs_TTPUR__dbo.json` → `vmsystest07.topmost.com.tw__PUR__dbo.json` also kept
every byte except the two identity strings (`"database": "Y-Docs_TTPUR"` →
`"database": "PUR"`, at the top level and inside `sql_execution_graph`). Those two
had to change: they held the `system_id`, not the database name, so the reader
would have rejected the file as an identity mismatch. The parsed payload is
otherwise identical (verified by digest), and no re-scan happened.

`load_cached()`/`has_cache()` take an optional `server`. With no server they fall
back to `resolve_server()`, which reads the one cache file on disk for that
database name and refuses to guess when two servers hold the same name. Callers
that still pass a `system_id` (e.g. `Y-Docs_TTPUR`) now find nothing — correct,
and fixed caller-side by tickets 03/05.
