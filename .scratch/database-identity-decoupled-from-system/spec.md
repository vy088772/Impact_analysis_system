---
status: ready-for-agent
triage: ready-for-agent
---

# Decouple Database Identity From System, and Resolve Connection Sources Correctly

## Problem Statement

Running `impact_orch.refresh_cli STC` leaves calls like `Global.asax.cs`'s `WriteDB` → `spAddRecordError` stuck at `unresolved`, reason `connection_source_unresolved`, even though the call is a completely ordinary stored-procedure invocation. The analyst reading that result cannot tell whether this is a real static-analysis gap worth investigating, or a database that simply hasn't been scanned yet — both currently look identical.

Tracing why surfaces two compounding problems, not one:

1. **Connection-source resolution trusts the wrong string.** `ConfigurationManager.AppSettings["error"]` resolves through Web.config's `<appSettings>` `key="error"` entry, whose value is `server=vmsystest07;uid=LogUser;pwd=topmost;DataBase=SysErrorRecord`. Today's parser (`db_connection_tracker.py`'s "模式4") never reads that value — it uppercases the *key* (`"error"` → `"ERROR"`) and treats that as the database name. `"ERROR"` is not a real database; `SysErrorRecord` is. The same shortcut misreads `ConfigurationManager.ConnectionStrings["TTOA"].ConnectionString` as database `"TTOA"` when the real database is `EFNETDB`. Both are Web.config-driven mismatches between a code-side lookup key and the real database name, and the analyst has no way to tell how many other calls across the codebase are silently mis-attributed the same way.

2. **The System-to-Database model can't represent what Web.config actually shows.** `system_catalog.json` models one Database per System (`database: {name, server}`), and every SQL cache file is keyed by `system_id`, not by the actual database. `SysErrorRecord` is written to by `STC`'s `Global.asax.cs` and by every other WebForms system's equivalent error handler — it belongs to no single System, yet a real fix to problem 1 would resolve it correctly and then immediately fail again, because there is nowhere in the model for a Database with no owning System to live, and no cache key that isn't system_id-shaped.

Both problems were traced to their root cause via `code_analyzer/db_connection_tracker.py`, `code_analyzer/project_scanner.py`, `code_analyzer/csharp_analysis_gateway.py`, `service/analyze_service.py`, `service/sql_cache_store.py`, `service/schemas.py`, `config/settings.py` (all in `Impact_analysis_system`), and `catalog/system_catalog.json`, `catalog/catalog_builder.py`, `impact_orch/refresh_sql_cli.py`, `impact_orch/refresh_cli.py` (all in `llamaindex-spec-rag`), and confirmed against the real Web.config content of `STC`, `Y-DOCs/TTPUR`, and `Y-DOCs/Response`.

## Solution

Connection-source resolution parses the real connection-string value out of Web.config — never the lookup key — for both `<appSettings>` and `<connectionStrings>` shapes, and carries both the resolved database *and* server all the way through to the evidence-rating gateway.

The System-to-Database relationship becomes many-to-many: a System's catalog entry declares the list of Databases it depends on; a new registry file lists every known Database (`name` + `server`) independent of any System. The SQL cache identity moves with it — keyed by normalized `(server, database, schema)`, not `system_id` — so a Shared Database like `SysErrorRecord` is scanned and cached exactly once no matter how many Systems reference it, and `refresh_cli`'s unresolved summary can tell an analyst "this database is real, it just hasn't been scanned yet" instead of lumping it in with genuine static-analysis gaps.

## User Stories

1. As an analyst running `refresh_cli`, I want a stored-procedure call through `ConfigurationManager.AppSettings["error"]` to resolve to the real database `SysErrorRecord`, so that I stop seeing ordinary logging calls reported as unresolved.
2. As an analyst running `refresh_cli`, I want a stored-procedure call through `ConfigurationManager.ConnectionStrings["TTOA"].ConnectionString` to resolve to the real database `EFNETDB`, not the connection-string name `TTOA`, so that cross-database calls written in the newer `<connectionStrings>` style resolve exactly as correctly as `<appSettings>`-style calls.
3. As a maintainer of `Impact_analysis_system`, I want connection-source resolution to read the connection-string *value*, never the AppSettings key or ConnectionStrings name, so that the resolved database name is never just a guess based on what the code happened to call the connection.
4. As a maintainer of `Impact_analysis_system`, I want the parser to recognize both `<appSettings><add key="..." value="..."/></appSettings>` and `<connectionStrings><add name="..." connectionString="..."/></connectionStrings>`, matched to which C# accessor produced the candidate, so that both real connection-string styles found in this codebase are covered, not just the older one.
5. As a maintainer of `Impact_analysis_system`, I want the connection-string value parsed through a synonym table (`server`/`Data Source`/`Address`/`Addr` → server; `database`/`Initial Catalog` → database; `uid`/`User ID` → uid; `pwd`/`Password` → pwd), so that `Data Source=...;Initial Catalog=...` resolves exactly as correctly as `server=...;database=...`.
6. As a maintainer of `Impact_analysis_system`, I want the parser to use a real XML parser rather than scanning raw file text, so that a commented-out `<!-- <add name="ErrLog" .../> -->` entry (confirmed present and dead in `Y-DOCs/Response/Web.config`) never produces a resolved connection.
7. As a maintainer of `Impact_analysis_system`, I want the existing `db_connection_tracker.py` "flexible pattern" (模式4) that uppercases the AppSettings key and uses it as the database name removed, not left running alongside the new parser, so that there is exactly one source of truth for connection-source resolution and no risk of the old wrong heuristic silently winning for some call shapes.
8. As a maintainer of `Impact_analysis_system`, I want `ConnectionInfo` (`db_connection_tracker.py`), `connection_sources` (`project_scanner.py`), and `DbInvocation` (`csharp_analysis_gateway.py`) to each carry a `server` field alongside `database`, so that a resolved connection can be turned into a cache lookup without losing which physical server it targets.
9. As a maintainer of `Impact_analysis_system`, I want `_resolve_database()` to return the resolved server as well as the database, so that the gateway's evidence rating has everything it needs to compute the correct SQL cache path.
10. As an analyst running `refresh_cli`, I want a call whose database resolves correctly but has no matching SQL cache on disk to be reported with reason `not_in_resolved_catalog`, distinct from a call whose database cannot be identified at all (`connection_source_unresolved`), so that I know immediately whether the next step is "scan this database" or "investigate this code."
11. As an analyst, I want a Database like `SysErrorRecord` — shared across many Systems and owned by none — treated as a first-class, catalogable Database, not excluded from analysis as infrastructure, so that a schema change to it can be impact-analyzed the same as a change to any System-owned database.
12. As a maintainer of `llamaindex-spec-rag`, I want `system_catalog.json`'s singular `database: {name, server}` object replaced with a `databases: [...]` list of database names, so that a System can declare dependence on more than one Database.
13. As a maintainer of `llamaindex-spec-rag`, I want a new `SQLServerData.json` file as the sole registry of Database entities (`name` + `server`), independent of any System, so that a server address is written once instead of duplicated across every System entry that happens to reference it.
14. As a maintainer of `llamaindex-spec-rag`, I want `catalog_builder.py`'s existing "preserve manually-curated fields across a rebuild" behavior extended to the renamed `databases` field, so that a catalog rebuild never silently drops a System's declared database dependencies, exactly as it already never drops the old singular `database` field.
15. As a maintainer of `Impact_analysis_system`, I want the SQL cache key to become the normalized triple `(server, database, schema)` instead of `system_id`, so that `SysErrorRecord` is scanned and cached exactly once regardless of how many Systems reference it.
16. As a maintainer of `Impact_analysis_system`, I want server hostnames normalized by a single algorithmic rule — append `.topmost.com.tw` when the hostname contains no `.`, leave it unchanged when it already does — rather than a maintained lookup table, so that a newly discovered server (e.g. a future `vmsystest09`) is handled correctly with no configuration change required.
17. As a maintainer of `Impact_analysis_system`, I want a named SQL Server instance suffix (`host\instance`, as seen in `TTOA`'s `vmsystest08.topmost.com.tw\vmsystest08_pdcs`) discarded during normalization, keeping only the host, so that the normalized identity matches how the scan tool actually connects in practice.
18. As an analyst, I want whether a Database is cataloged determined solely by whether its normalized `(server, database, schema)` cache file exists on disk — no separate whitelist or registry gate — so that a freshly-scanned database is recognized immediately with no extra registration step.
19. As a maintainer of `Impact_analysis_system`, I want the two existing SQL cache files (`STC__dbo.json`, `Y-Docs_TTPUR__dbo.json`) renamed to the new `(server, database, schema)` key format and their contents preserved, not regenerated, so that the 33MB `PUR` cache doesn't require a slow re-scan just to satisfy a naming change.
20. As an analyst, I want `refresh_cli`'s unresolved summary to separately call out how many results are `not_in_resolved_catalog`, with the message "N 筆為「資料庫未建檔」，refresh_sql_cli 建立 `<database>`", so that I get an actionable next step instead of an undifferentiated unresolved count.
21. As an analyst, I want that hint deduplicated once per uncataloged database regardless of how many invocations hit it, so that a database hit by many calls doesn't repeat the same suggested command dozens of times.
22. As an analyst, I want discovering an uncataloged database during `refresh_cli` to never automatically trigger a live SQL scan, so that a source-code-only refresh can never silently open a new live database connection on my behalf.
23. As a maintainer of `llamaindex-spec-rag`, I want `refresh_sql_cli` able to target one Database directly by `(server, database)`, so that a Database with no owning System (like `SysErrorRecord`) can still be scanned without inventing a fake System for it.
24. As an analyst, I want `refresh_sql_cli` to also accept a `system_id` as a convenience that resolves to every Database that System's catalog entry declares and scans each in turn, so that the common case — "refresh everything this system depends on" — stays a one-argument command.
25. As a maintainer of `Impact_analysis_system`, I want the scan tool's connecting identity kept independent of each scanned application's own Web.config credentials, using the existing global `DB_AUTH_MODE` (Windows Auth or one global SQL login) by default, so that resolving a Web.config connection string for identification purposes never implicitly grants the scan tool a new way to connect to a database.
26. As a maintainer of `Impact_analysis_system`, I want an optional credential override for one specific `(server, database)` pair, used only when both a user id and password are supplied, so that a database the global scan identity cannot reach can still be scanned without weakening the default trust boundary for every other database.
27. As an analyst who just discovered a new Database via connection-source resolution, I want to be told (or to be able to easily check) whether the existing global scan identity actually has read access to it before running `refresh_sql_cli`, so that a permission gap surfaces as a clear failure rather than a confusing partial scan.
28. As a code reviewer, I want no cross-file consistency check added for the case where the same database name resolves to different servers across different Web.config files, so that a confirmed-dead, commented-out entry (`SysErrorRecord` → `vmsystest03` in `Y-DOCs/Response/Web.config`) doesn't force unnecessary health-check machinery for a case that isn't live anywhere today.
29. As a code reviewer, I want `SQLServerData.json` to never contain credentials, so that a file whose entire purpose is a lightweight, low-risk identity registry doesn't become a secrets file by scope creep.

## Implementation Decisions

**Connection-source resolution (`Impact_analysis_system`)**

- A new Web.config connection-string resolver module replaces `db_connection_tracker.py`'s existing "模式4" heuristic. Given one `.config` file's content, it returns a mapping from each connection-lookup key (an AppSettings key or a ConnectionStrings name) to its resolved `{server, database}` pair.
- It is driven by a real XML parser (so `<!-- ... -->` comment nodes are structurally skipped, never matched), reads both `<appSettings>` and `<connectionStrings>` sections, and resolves each connection-string value through a synonym table covering `server`/`Data Source`/`Address`/`Addr`, `database`/`Initial Catalog`, `uid`/`User ID`, `pwd`/`Password`.
- The C# side of resolution (recognizing `ConfigurationManager.AppSettings["x"]` vs `ConfigurationManager.ConnectionStrings["x"].ConnectionString` call shapes and extracting `x`) stays a separate concern from parsing the `.config` file itself; the two compose — the C# side yields a lookup key, the config-parsing side turns that key into `{server, database}`.
- `ConnectionInfo` (`db_connection_tracker.py`), `connection_sources` (`project_scanner.py`), and `DbInvocation` (`csharp_analysis_gateway.py`) all gain a `server` field alongside the existing `database` field. `_resolve_database()` in `csharp_analysis_gateway.py` returns both.
- `_rate_literal_candidate()`'s existing reason-code branching (`not_in_resolved_catalog` when a database is resolved but not found in the loaded SP Catalog; `connection_source_unresolved`/`ambiguous_connection_source` when no database could be resolved at all) is unchanged — it already does the right thing once it is fed a correctly resolved database.

**SQL cache identity (`Impact_analysis_system`)**

- `sql_cache_store.py`'s cache key changes from `database_alias` (in practice always a `system_id`) to the normalized triple `(server, database, schema)`. Filenames take the form `{server}__{database}__{schema}.json`.
- Server normalization is a pure function, not a lookup table: append `.topmost.com.tw` to a hostname containing no `.`; leave an already-dotted hostname unchanged. A `host\instance` suffix (named SQL Server instance) is split off and discarded before normalization — only the host participates in the cache key.
- Whether a Database is cataloged is determined solely by whether its normalized cache file exists on disk. No whitelist, registry, or `SQLServerData.json` lookup gates this check.
- The two existing cache files (`STC__dbo.json`, `Y-Docs_TTPUR__dbo.json`) are migrated in place by a one-off script that renames them to the new key format (`vmsystest07.topmost.com.tw__STC__dbo.json`, `vmsystest07.topmost.com.tw__PUR__dbo.json`) and preserves their content — no re-scan.

**Scan-tool identity (`Impact_analysis_system`)**

- The scan tool's connecting identity (used by `refresh_sql_cli`/`/refresh_sql`) stays independent of each scanned application's own Web.config credentials. By default it uses the existing global `config/settings.py` `DB_AUTH_MODE` (Windows Auth trusted connection, or one global SQL login pair from `.env`).
- An optional per-`(server, database)` credential override may be supplied via environment variables (following the existing `DB_USER_ID`/`DB_PASSWORD` `.env` convention, keyed by the normalized server/database pair rather than global) — used only when both a user id and password are present for that pair; otherwise the global identity is used. Credentials are never read from or derived from Web.config, and are never stored in `SQLServerData.json`.

**System-to-Database model (`llamaindex-spec-rag`)**

- `system_catalog.json`'s per-system `database: {name, server}` object is replaced with `databases: [...]`, a list of database name strings declaring which Databases that System depends on. A System with no declared database dependency has `databases: []`.
- A new `SQLServerData.json` file is the sole registry of Database entities: a flat list of `{name, server}` pairs, independent of any System. A database name referenced from a System's `databases` list is looked up here for its server.
- `catalog_builder.py`'s existing manually-curated-field preservation (the mechanism `test_catalog_builder_database.py` already covers for the old singular `database` field) is extended to preserve `databases` across a rebuild the same way.
- A Database referenced by more than one System, or by none, is still fully cataloged and scannable — nothing in the model or the rebuild logic treats a Shared Database differently from a System-owned one.

**`refresh_sql_cli` / `refresh_cli` (`llamaindex-spec-rag`)**

- `refresh_sql_cli` gains the ability to target one Database directly by `(server, database)`, in addition to its existing `system_id` argument. Given a `system_id`, it resolves that System's `databases` list (via `SQLServerData.json`) and runs the same per-database scan for each entry in turn.
- `refresh_cli`'s unresolved-results summary buckets any `not_in_resolved_catalog` results separately from other unresolved reasons, printing "其中 N 筆為「資料庫未建檔」，refresh_sql_cli 建立 `<database>`" once per distinct uncataloged database (deduplicated across however many invocations hit it), rather than once per invocation.
- Neither `refresh_cli` nor any other automated path triggers `refresh_sql_cli` (or an equivalent live scan) on discovering a new database name. Scanning a newly discovered database is always a separate, explicitly human-triggered command.

## Testing Decisions

A good test here asserts the resolved `{server, database}` value, the cache filename produced, or the reported reason code / summary text for a given input — never internal parsing call sequencing.

- **Web.config connection-string resolver**: new direct unit tests (extending or replacing `tests/test_connection_tracking.py`'s existing `DBConnectionTracker` coverage) — cases: `<appSettings>` short-hostname style (`STC`'s own `error` key), `<connectionStrings>` FQDN style (`TTPUR`'s `PUR`/`TTOA`/`ErrLog` entries), a commented-out `<add .../>` entry (must not resolve), and a case where the AppSettings key differs from the real database name (`error` → `SysErrorRecord`, `TTOA` → `EFNETDB`) to lock down the exact bug this spec fixes.
- **`CSharpAnalysisGateway` reason codes**: extend `tests/test_csharp_analysis_gateway.py` with cases constructed via its existing `CSharpAnalysisGateway(catalog, connection_sources=...)` direct-instantiation pattern — a resolved-but-uncataloged database must produce `not_in_resolved_catalog`; an unresolvable connection must still produce `connection_source_unresolved`/`ambiguous_connection_source` exactly as today.
- **`sql_cache_store` normalization**: new `tests/test_sql_cache_store.py` (no prior coverage exists) — direct unit tests of the server-normalization function (bare host gets the domain suffix; already-dotted host is unchanged; `host\instance` loses its instance suffix) and the cache filename builder, following this repo's existing convention of testing pure helper functions directly.
- **`catalog_builder.py` field preservation**: extend `tests/test_catalog_builder_database.py`'s existing pattern (forced-rebuild preserves the field; absent field stays absent) to `databases` instead of `database`.
- **`refresh_sql_cli`**: new `tests/test_refresh_sql_cli.py` (no prior coverage exists) — the `(server, database)`-direct invocation path and the `system_id`-resolves-to-multiple-databases convenience path, following `tests/test_refresh_cli.py`'s existing `monkeypatch`-based CLI-test pattern.
- **`refresh_cli` summary**: extend `tests/test_refresh_cli.py` — the `not_in_resolved_catalog` bucket, its message text, and deduplication across multiple invocations hitting the same uncataloged database.
- Cache-file migration is a one-off script, not ongoing runtime code; it gets a smoke test confirming a file renamed under the old key format is readable and produces an identical parsed result under the new key format — not full regression coverage.

## Out of Scope

- Any UI/field to mark a System's dependency on a Database as "primary/owned" vs "merely dependent" within the `databases` list — raised during design, never settled, and not needed for this spec's scope. All entries in a System's `databases` list are equivalent today.
- A maintained server-hostname alias/lookup table — explicitly rejected in favor of the algorithmic `.topmost.com.tw` suffix rule; revisit only if a real internal server outside that domain is found.
- A cross-file health check that warns when the same database name resolves to different servers across different Web.config files — the one observed case (`SysErrorRecord` → `vmsystest03` in a commented-out, dead `Y-DOCs/Response/Web.config` entry) isn't live anywhere, so there's nothing to detect today.
- Automatic/cascading live SQL scanning triggered by `refresh_cli` discovering a new database — scanning stays a separate, explicit `refresh_sql_cli` step, always human-triggered.
- Storing any credential inside `SQLServerData.json` or `system_catalog.json` — credentials, when overridden per `(server, database)`, live in environment configuration, never in these catalog files.
- Any change to how `SysErrorRecord` (or any other Database) is granted database-level read permissions — this spec assumes the scan tool's identity may need a permission grant to reach a newly in-scope Database, but obtaining that grant is an operational step outside this spec.
- Migrating or re-validating any SQL cache scope beyond the two that exist today (`STC`, `PUR`) — the migration script only needs to handle those two.

## Further Notes

This spec was produced from a `/grilling` session (`domain-modeling` skill) that started from one concrete unresolved call (`Global.asax.cs:55`, `spAddRecordError`) and widened once it became clear the immediate fix (parse Web.config correctly) would only work if the System-to-Database model could represent a database with no owning System. The two problems are addressed together here because fixing either alone leaves the other blocking it: correct connection-source resolution with nowhere to catalog the result still reports `SysErrorRecord` as broken; a flexible Database registry with connection-source resolution still guessing wrong keys never populates it correctly.

Domain vocabulary and hard-to-reverse decisions from this session are recorded as ADRs and `CONTEXT.md` entries in both repos before this spec was written:

- `Impact_analysis_system`: [ADR-0008](../../docs/adr/0008-web-config-connection-string-resolution.md) (connection-string resolution), [ADR-0009](../../docs/adr/0009-sql-cache-identity-decoupled-from-system.md) (cache identity), [ADR-0010](../../docs/adr/0010-scan-identity-independent-of-app-credentials.md) (scan-tool credential independence); `CONTEXT.md` gains **Uncataloged Database**.
- `llamaindex-spec-rag`: [ADR-0001](../../../llamaindex-spec-rag/docs/adr/0001-system-to-database-is-many-to-many.md) (System-to-Database multiplicity), [ADR-0002](../../../llamaindex-spec-rag/docs/adr/0002-new-database-scanning-is-explicit.md) (no auto-cascade scanning); `CONTEXT.md` gains **Database** and **Shared Database**.

Rollout order was not explicitly decided during grilling, but follows from the dependency chain laid out in the Problem Statement: the connection-source resolver (`Impact_analysis_system`) and the System-to-Database model (`llamaindex-spec-rag`) can be built in parallel, but the cache-key migration (`Impact_analysis_system`) should land before `refresh_sql_cli`'s `(server, database)` argument (`llamaindex-spec-rag`) starts writing cache files under the new key format, so no cache file is ever written under a scheme the reader doesn't yet expect.
