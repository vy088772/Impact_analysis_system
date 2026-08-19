# SQL Cache Identity Is (Server, Database, Schema), Not System

**Status:** Accepted
**Date:** 2026-08-18

## Context

`sql_cache_store.py` keys each cached SP/View/Function/table scan by `database_alias` alone — in practice the caller always passes a `system_id` (e.g. cache file `Y-Docs_TTPUR__dbo.json` for a database actually named `PUR`), and `server` is not part of the key at all. This was workable while each System owned exactly one Database. It breaks once a Database can be shared by many Systems or owned by none (see `llamaindex-spec-rag` [ADR-0001](../../../llamaindex-spec-rag/docs/adr/0001-system-to-database-is-many-to-many.md)): the same Database would otherwise be scanned and cached once per referencing System, and two different servers with a same-named database would collide.

## Decision

The cache key becomes the normalized triple `(server, database, schema)`, independent of any System. Cache filenames take the form `{server}__{database}__{schema}.json`.

Server normalization is algorithmic, not a lookup table: a host that already contains `.` keeps the domain it has; a bare host with no `.` gets `.topmost.com.tw` appended. Hostnames are case-insensitive, so the normalized form is lowercased: a `VMSYSTEST07` in one Web.config and a `vmsystest07` in another name the same server and must therefore share one cache file, not open two. This assumes every internal SQL Server host lives under the single domain `topmost.com.tw` — confirmed against STC's, TTPUR's, and Y-DOCs/Response's actual Web.config content at decision time. A named SQL Server instance suffix (`host\instance`) is discarded during normalization — only the host is used to reach the server in practice.

Whether a Database is cataloged is determined solely by whether its normalized cache file exists on disk. No separate whitelist or registry gates this check.

## Consequences

- Existing cache files (`STC__dbo.json`, `Y-Docs_TTPUR__dbo.json`) must be renamed to the new key format and kept, not regenerated — one of them is 33MB and re-scanning is slow.
- The C# analysis pipeline (`ConnectionInfo` in `db_connection_tracker.py`, `connection_sources` in `project_scanner.py`, `DbInvocation` in `csharp_analysis_gateway.py`) currently tracks only a database name string end-to-end, with no `server` field anywhere. All three need a `server` field added, and `_resolve_database()` needs to return it, before connection-source resolution can compute a correct cache key under this decision.
- If a future internal SQL Server host lives outside `topmost.com.tw`, the algorithmic suffix rule silently produces a wrong FQDN; that will require an explicit exception, not abandoning the algorithmic rule generally.
