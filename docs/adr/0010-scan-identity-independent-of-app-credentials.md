# The SQL Scan Tool's Identity Is Independent of Each Application's Runtime Credentials

**Status:** Accepted
**Date:** 2026-08-18

## Context

Each scanned application's Web.config carries its own SQL login for its own runtime use — STC's app connects as `STCWeb`, PUR's as `webaccess`, the shared error-logging database as `LogUser` — including different logins for different databases on the very same server. `config/settings.py` already connects for offline scanning (`refresh_sql_cli`) with one global identity: `DB_AUTH_MODE=windows` (a trusted service account) or one global SQL login pair. It would be tempting to make the scan tool "just reuse" whatever credentials are parsed out of each Web.config, since connection-source resolution already extracts them.

## Decision

The scan tool's connecting identity stays a separate trust boundary from the credentials embedded in scanned application config. Web.config's `uid`/`pwd` are used only to help identify which database a call resolves to (as evidence for the SP Catalog lookup) — never to build the live connection the scan tool itself opens.

Optionally, one server may carry an explicit credential override, recorded as `uid`/`pwd` on that server's `SQLServerData.json` entry in `llamaindex-spec-rag` and shared by every database listed under it (used only when both are non-blank); when either is blank, the scan falls back to the existing global `DB_AUTH_MODE` identity. The caller sends the pair as `db_user_id`/`db_password` on the `/refresh_sql` request, and `build_database_config()` applies it only for that one scan. `SQLServerData.json` is a local, `.gitignore`d data file, so the override never enters version control.

## Consequences

Bringing a newly discovered shared Database (e.g. `SysErrorRecord`) into scope requires confirming the scan tool's existing global identity actually has read access to it — that access is not automatically granted just because that database's own application-level SQL login happens to have it.
