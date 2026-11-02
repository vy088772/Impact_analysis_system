# A Question Never Rebuilds a Cache

**Status:** Accepted
**Date:** 2026-10-16

## Context

Before this decision, a question rebuilt a cache when it found the cache unusable. A C# Scan Result with an old format made `get_or_scan` scan the whole repository during the question. A changed input of Derived Execution Evidence made the question derive it again. The analyst waited on the Web page with no feedback, and could not tell why.

## Decision

A question never rebuilds a SQL cache or a C# Scan Result. Only a Refresh Job rebuilds a cache, and the Refresh Queue runs one Refresh Job at a time. The Impact service owns the Refresh Queue and the Cache Freshness of each cache, because it already owns the Scan Record (`llamaindex-spec-rag` ADR-0005).

When a question needs a cache with the Cache Freshness `outdated` or `refreshing`, the run does not read that cache. The run lists the system as an Unread System with the reason `cache_outdated` or `cache_refreshing`, and the answer links to the update page. When a Pinned System has such a cache, the run stops before it starts, and spends no LLM tokens. When every system that the run needs has such a cache, the answer only tells the analyst which systems to update.

A `behind_source` cache does not block a question. The answer stays correct for the scanned state: the scanned commit of a C# Scan Result, or the scanned Database of a SQL cache.

Derived Execution Evidence is not a cache that an analyst refreshes. Each Refresh Job derives it as its last step. A change to one of the three configuration inputs of Derived Execution Evidence starts a Refresh Job automatically. If a question still finds no valid Derived Execution Evidence, the question derives it and shows a progress stage. This exception is acceptable because a derivation reads the existing caches only. It never scans a repository or connects to SQL Server.

## Considered Options

- **Rebuild during the question, with progress events.** Rejected. The analyst still waits for a full scan, and two questions can rebuild the same cache at the same time.
- **Block a question on invalid Derived Execution Evidence too.** Rejected. Each configuration edit would block questions, and the update page would need a button for an internal result.
- **Refuse the whole question when any system is outdated.** Rejected. One outdated system in a Cross-system Lookup would block answers for all the other systems. The Unread System already discloses a skipped system.

## Consequences

- `refresh_cli` and `refresh_sql_cli` submit Refresh Jobs to the Refresh Queue. They do not rebuild a cache directly.
- An analyst can cancel a waiting Refresh Job. An analyst cannot stop a running Refresh Job, because a stop can leave a partly written cache.
- A failed Refresh Job keeps the previous Cache Freshness. The update page shows the last error. The Refresh Queue does not retry.
- The Refresh Queue lives in memory. A restart of the Impact service drops the waiting Refresh Jobs.
- The update page checks for `behind_source` when an analyst opens it, and again when the analyst asks for a new check. The page shows the time of the last check. A question never runs this check. It never reads a remote repository or the Fingerprint of a Database.
- An "update all" action submits a Refresh Job for each `outdated` cache. It does not include a `behind_source` cache. An analyst submits each `behind_source` cache alone.
- Any later proposal to rebuild a cache inside a question reverses this ADR and needs its own ADR.

## Amendment: the Environment Check locks rows (2026-10-22)

`llamaindex-spec-rag` ADR-0020 adds an Environment Check. The Impact service tests SQL Server access and Azure Repos access itself, because it is the process that makes the connections. The test logs in to each server of the Database Registry (and each server that only the catalog names), and runs `git ls-remote` one time for each repository of the catalog, with at most 8 at one time. A test for each repository, and not one for each Azure DevOps project, keeps the failure of one repository (for example a removed repository) from locking the other repositories. On 2026-10-22, 30 calls took about 1 second at 8 at one time.

The service keeps the last result in memory. Each SQL row of a failed server and each C# row of a failed repository gets a `locked_reason`. A Refresh Job for a locked row gets HTTP 409 with that reason, and no job starts. "Update all" skips the locked rows and still submits the other `outdated` caches. Before the first check, and after a restart, no row is locked.

## Amendment: a SQL cache can be `behind_source` (2026-10-30)

Before this amendment, only a C# Scan Result could be `behind_source`. A person can change a procedure, a view, a function, or a table directly in SQL Server, and the update page still showed that SQL cache as `current`. The accepted decisions are in `.scratch/sql-cache-behind-source/spec.md`.

The source of a SQL cache is its Database. Each SQL scan reads the Fingerprint of the Database before it reads any definition, and the Scan Record holds it beside `saved_at`. The SQL cache format version 12 adds this field, so every older SQL cache is `outdated` one time. Version 12 also limits a scan to the objects of the Kind Groups that SQL Server does not ship, so the scope of the scan equals the scope of the Fingerprint.

The decision for the check follows. Ticket 02 of `.scratch/sql-cache-behind-source/` builds it.

- The `behind_source` check also reads the current Fingerprint of each declared SQL cache that is usable and not locked.
- A SQL cache is `behind_source` when the current Fingerprint differs from the recorded Fingerprint. `outdated` and `refreshing` win over `behind_source`.
- A missing Fingerprint gives no `behind_source`. This covers no check yet, an unreachable server, a failed query, a locked row, and a null recorded Fingerprint.
- The rules for C# also apply to SQL. A question never runs the check. A `behind_source` SQL cache does not block a question. "Update all" leaves the cache out.
- The check reads a shared SQL cache one time. It connects with the address that a refresh of that cache uses, so a named instance connects.
- The service keeps the current Fingerprints in memory with the remote heads, and keeps one check time for both. A restart forgets them.

## Amendment: one check time for each system (2026-11-02)

This amendment changes the rule "keeps one check time for both" of the amendment of 2026-10-30. The accepted decisions are in `TCCDIV1/AI_LlamaIndex` issue #8. Issue #9 builds this part.

- `POST /cache_freshness/check` accepts an optional `system_id`. With `system_id`, the check reads only the repository and the declared SQL Databases of that catalog system. Without `system_id`, the check reads every system, as before.
- The check merges its answers into the answers that the service keeps. It replaces only the remote heads and the Fingerprints that it read. Thus a check of one system keeps the results of the other systems. A source that gives no answer loses its kept answer.
- The service keeps one check time for each catalog system. The listing gives each system its own `source_checked_at`. A full check sets the time of every system. The listing has no global check time.
- A shared SQL cache has one Fingerprint. A check of one system shows the new result under every system that uses the cache. Only the time of the checked system changes.
- A locked C# row stays out of the check, as a locked SQL row does. A lock that arrives after the check hides the kept head, so a locked row is never `behind_source`.
- An unknown `system_id` gets HTTP 404, and the check reads nothing.

Each analyst action on the update page still asks for the check, so the rule "A question never runs this check" stays. Later tickets of issue #8 move the full check from the page open to a daily background check of the web.

## Amendment: the page shows a read failure (2026-11-02)

Before this amendment, a row whose repository or Database the check could not read looked `current`. The analyst could not see the failure. The accepted decisions are in `TCCDIV1/AI_LlamaIndex` issue #8. Issue #10 builds this part.

- The check keeps a short reason for each source that it could not read, for example a timeout or a failed login. The reason never holds the PAT or the password.
- The listing gives the reason on the row as `source_check_failure`. The field is empty when the check read the source, before the first check, and for a locked row. A locked row needs no failure, because its Lock Reason already explains it.
- A source has a kept answer or a failure, never both. A later successful read clears the failure. A failed read still forgets the kept answer, so a failure is never `behind_source`.
- A read failure is not a Cache Freshness value. It changes no `freshness`. The rules for a Pinned System, an Unread System, and "update all" stay the same.
- The Environment Check and the check give the same reasons for the same `git ls-remote` failure and the same SQL Server login failure.
- The update page shows "無法檢查" for a C# or SQL row with a failure, and the reason as the hover text. `outdated` and `refreshing` show before "無法檢查".

## Amendment: the web checks in the background (2026-11-02)

This amendment replaces the rule "The update page checks for `behind_source` when an analyst opens it, and again when the analyst asks for a new check". The accepted decisions are in `TCCDIV1/AI_LlamaIndex` issue #8. Issue #12 builds this part.

- The update page does not start a check when it opens. It shows the results of the last check immediately.
- The web starts a Daily Source Check in the background when it starts. The web does not wait for it. After that, the web starts it again every 24 hours. The interval starts when the web starts.
- The Daily Source Check puts every catalog system into the Source Check Queue of the web in catalog order. The queue checks one system at a time, with `POST /cache_freshness/check` and that `system_id`.
- An analyst checks one system with the "檢查來源" button of that system. The request moves the system to the front of the queue. Thus the Daily Source Check does not check that system again.
- The page header shows the progress of the Daily Source Check, for example "背景檢查中：3 / 12 個系統". The page header has no "檢查來源" button.
- The web has no endpoint for a full check. The Impact service still accepts a check without `system_id`.
- The web keeps no check result and no check time in a file. A restart of the web starts a new Daily Source Check.

The rule "A question never runs this check" stays.
