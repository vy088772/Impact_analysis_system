# A SQL Cache Becomes `behind_source` When Its Database Changes

Status: ready-for-agent

This spec records the accepted decisions Q1 through Q12 from the discussion on 2026-10-30.
It covers Impact_analysis_system and the update page of `llamaindex-spec-rag`.
It creates no implementation tickets.

## Problem Statement

An analyst uses the update page to keep the SQL caches correct.
A SQL cache holds the definitions of the procedures, views, and functions of one Database, and the schema of its tables.

A person can change a procedure, a view, a function, or a table directly in SQL Server, without a code deployment.
After such a change, the SQL cache is old, but the update page still shows the row as `current`.
The "update all" action also skips the row, because it refreshes only `outdated` caches.

So the analyst cannot see that a Database changed.
Answers that use the old SQL cache can then omit or misreport an impact.
Today, the only remedy is to remember the change and to refresh the row by hand.

## Solution

Each SQL scan records a **Fingerprint**.
A Fingerprint is a small summary that Impact reads from the system catalog of SQL Server at the start of a scan.
It holds, for each object kind, the latest modification time and the number of objects.

The existing `behind_source` check also reads the current Fingerprint of each SQL cache.
When the current Fingerprint differs from the recorded Fingerprint, the row shows `behind_source`.
The update page shows the text "資料庫有變更" for such a SQL row.
The analyst then refreshes that row with its own update button.

A new cache format version makes every old SQL cache `outdated` one time.
One "update all" action rescans them, and each rescan records a Fingerprint.

## User Stories

1. As an analyst, I want a SQL row to show `behind_source` when someone changed a procedure in its Database, so that I know the cache is old.
2. As an analyst, I want a SQL row to show `behind_source` when someone changed a view, so that view changes are visible too.
3. As an analyst, I want a SQL row to show `behind_source` when someone changed a scalar, inline, or table-valued function, so that function changes are visible too.
4. As an analyst, I want a SQL row to show `behind_source` when someone added or altered a column of a table, so that schema changes are visible.
5. As an analyst, I want a SQL row to show `behind_source` when someone dropped a procedure, view, function, or table, so that a removal is visible even though it leaves no modification time.
6. As an analyst, I want a SQL row to show `behind_source` when someone created a new procedure, view, function, or table, so that additions are visible.
7. As an analyst, I want the check to run when I open the update page, so that I see the state without an extra click.
8. As an analyst, I want the "check again" action to check the SQL caches too, so that one action checks every source.
9. As an analyst, I want one "last check" time for C# and SQL together, so that the page stays simple.
10. As an analyst, I want a SQL `behind_source` row to show "資料庫有變更", so that I know to look at the Database and not at a repository.
11. As an analyst, I want a C# `behind_source` row to keep the text "來源有新 commit", so that the C# meaning does not change.
12. As an analyst, I want a SQL `behind_source` row to keep its update button enabled, so that I can refresh it at once.
13. As an analyst, I want a refresh of a SQL `behind_source` row to clear the state, so that the row shows `current` after the new scan.
14. As an analyst, I want "update all" to leave SQL `behind_source` rows out, so that SQL rows follow the same rule as C# rows.
15. As an analyst, I want a question to never run the SQL check, so that questions stay fast and never touch SQL Server for this reason.
16. As an analyst, I want a `behind_source` SQL cache to never block a question, so that I still get an answer from the scanned state.
17. As an analyst, I want a SQL row whose server I cannot reach to keep its previous state, so that a network fault never shows as a Database change.
18. As an analyst, I want a SQL row that the Environment Check locks to keep its previous state, so that a locked row shows no false change.
19. As an analyst, I want every old SQL cache to show `outdated` after the upgrade, so that I know every cache needs one rescan to get a Fingerprint.
20. As an analyst, I want one "update all" action to rescan every old SQL cache, so that the upgrade costs me one click.
21. As an analyst, I want a change that occurs during a scan to show `behind_source` at the next check, so that a concurrent change never hides.
22. As an analyst, I want a SQL cache that several systems share to show the same state under each system, so that the page stays consistent.
23. As an analyst, I want the check to use the same scan account as a refresh of that server, so that a server with an account override works.
24. As an operator, I want the check to read the scan account from the Database Registry, so that no credential comes from an application Web.config.
25. As an operator, I want a change to a trigger, an index, or a synonym to cause no `behind_source`, because the SQL cache does not hold those objects.
26. As an operator, I want a change to an object that SQL Server ships to cause no `behind_source`, because the scan excludes those objects.
27. As an operator, I want the check to read only the system catalog, so that the check is fast and never reads definitions.
28. As an operator, I want a service restart to forget the last SQL check, as it forgets the C# check, so that both sources behave the same.
29. As a maintainer, I want the Fingerprint in the Scan Record beside `saved_at`, so that one file records the facts of one scan.
30. As a maintainer, I want `llamaindex-spec-rag` to keep reading `saved_at` without change, so that the new field breaks no reader.
31. As a maintainer, I want ADR-0045 and CONTEXT.md to state that a SQL cache can be `behind_source`, so that the documents match the code.

## Implementation Decisions

**Fingerprint shape.**
- A Fingerprint has one entry for each kind group: procedures (`P`), views (`V`), functions (`FN`, `IF`, `TF`), and tables (`U`).
- Each entry holds the latest `modify_date` and the object count for that group.
- Two Fingerprints are equal only when every entry is equal.
- Impact compares two Fingerprints only for equality. It never orders them.
- A group with no objects gives a count of zero and an empty latest time.

**Fingerprint scope.**
- The query reads `sys.objects` in the scanned Database only.
- The query excludes objects where `is_ms_shipped` is 1.
- The query excludes the schemas `sys`, `INFORMATION_SCHEMA`, and `guest`, the same as the object listing of the SQL analyzer.
- The scope of the Fingerprint equals the scope of the scan. A change outside the scan scope gives no `behind_source`.
- The granularity is one Database. The check does not name the changed objects.

**Fingerprint reader.**
- One new function reads the Fingerprint of one SQL Cache Identity from SQL Server.
- The scan and the check both call this function. No other code reads the Fingerprint from SQL Server.
- The function takes the SQL Cache Identity and the optional scan account override.
- The function returns no Fingerprint when it cannot connect or when the query fails.

**Scan.**
- A SQL scan reads the Fingerprint before it reads any definition.
- The scan writes the Fingerprint into the Scan Record (the meta file) beside `saved_at`.
- The SQL cache format version increases by one. Every cache with the old version lists as `outdated`.

**Check.**
- `POST /cache_freshness/check` takes an optional body with `sql_credentials`, keyed by server, with the same shape as in `/environment/check` and `/refresh_jobs/update_all` (ADR-0010).
- The check reads the current Fingerprint of each declared SQL cache that has a usable cache and no lock.
- The check reads each shared SQL cache one time.
- The check keeps the current Fingerprints in memory with the C# remote heads. A restart forgets both.
- The check keeps one check time for C# and SQL.
- The check never runs during a question. `GET /cache_freshness` never runs the check.

**Cache Freshness.**
- A SQL cache is `behind_source` when it is usable, the last check read a current Fingerprint, and that Fingerprint differs from the recorded Fingerprint.
- `refreshing` and `outdated` win over `behind_source`, the same as for C#.
- No current Fingerprint (no check yet, server unreachable, query failed, or row locked) gives no `behind_source`.
- A finished refresh writes a new recorded Fingerprint. The listing then compares again and clears `behind_source` with no second check.

**Update all.**
- "Update all" still submits only `outdated` caches. It leaves `behind_source` SQL caches out.

**`llamaindex-spec-rag` web side.**
- The web client passes the scan account overrides from the Database Registry to the check, the same as it does for "update all".
- The label of `behind_source` depends on the row kind: "資料庫有變更" for a SQL row and "來源有新 commit" for a C# row.
- The sort order of states and the button state do not change.
- Comments that say only C# can be `behind_source` change to include SQL.

**Documents.**
- ADR-0045 changes: a SQL cache can be `behind_source`, and its source is the Database.
- The CONTEXT.md entries for Cache Freshness and Scan Record add the Fingerprint.
- CONTEXT.md adds the term **Fingerprint**.

## Testing Decisions

A good test checks external behavior only.
It sends an HTTP request or calls a public function, and it checks the response.
It does not check private helpers or the order of internal calls.

**Seam 1: the Impact HTTP API.**
- The tests call `GET /cache_freshness`, `POST /cache_freshness/check`, and `POST /refresh_jobs/update_all`.
- The tests replace the one Fingerprint reader with a fake, the same as `test_behind_source_api.py` replaces the remote head reader.
- The tests cover: a changed Fingerprint gives `behind_source`; an equal Fingerprint gives `current`; a changed count with an equal time gives `behind_source`.
- The tests cover: a plain listing never calls the reader; a reader failure gives no `behind_source`; a locked row gives no `behind_source`.
- The tests cover: `outdated` and `refreshing` win; a refresh clears `behind_source`; "update all" leaves the row out.
- The tests cover: a cache with the old format version lists as `outdated`; a shared cache gets one read and one state.
- The tests cover: the scan writes the Fingerprint that the reader returned before the scan started; the check passes the account override to the reader.
- The tests cover: a question never calls the reader.
- Prior art: `test_behind_source_api.py`, `test_cache_freshness_api.py`, and `sql_cache_fixtures.py`.

**Seam 2: the SQL analyzer query.**
- The tests use a fake cursor and check the Fingerprint query.
- The tests cover the kind groups, the `is_ms_shipped` exclusion, the schema exclusions, and the empty group.
- Prior art: `test_sql_analyzer_object_listing.py`.

**Seam 3: the update page label.**
- The tests call the pure label function of the update page.
- The tests cover the SQL label and the C# label for `behind_source`.
- Prior art: `updates.test.ts` in `llamaindex-spec-rag`.

## Out of Scope

- A list of the changed objects inside one Database.
- A check of one schema, or of one object.
- Triggers, indexes, synonyms, sequences, user-defined types, and permissions.
- Automatic refresh of a `behind_source` SQL cache.
- A `behind_source` SQL cache in "update all".
- A SQL check during a question.
- A separate check time for SQL.
- A persistent store for check results across a restart.
- Databases that the catalog does not declare. The update page does not list them.

## Further Notes

- The work crosses two repositories. Impact_analysis_system owns the Fingerprint, the check, and Cache Freshness. `llamaindex-spec-rag` owns the credential pass-through and the label.
- `sys.objects.modify_date` of a table changes when an `ALTER TABLE` statement changes a column. So the table group covers schema changes.
- A drop leaves no row and no time. The object count of the group covers drops.
- Impact reads the Fingerprint at the start of the scan. A change during the scan makes the recorded Fingerprint older than the cache content. The next check then shows `behind_source`, and one extra rescan is the only cost.
- The upgrade makes every SQL cache `outdated` one time. Plan one "update all" run after the deployment.
