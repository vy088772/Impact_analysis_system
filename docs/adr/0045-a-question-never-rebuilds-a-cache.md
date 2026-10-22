# A Question Never Rebuilds a Cache

**Status:** Accepted
**Date:** 2026-10-16

## Context

Before this decision, a question rebuilt a cache when it found the cache unusable. A C# Scan Result with an old format made `get_or_scan` scan the whole repository during the question. A changed input of Derived Execution Evidence made the question derive it again. The analyst waited on the Web page with no feedback, and could not tell why.

## Decision

A question never rebuilds a SQL cache or a C# Scan Result. Only a Refresh Job rebuilds a cache, and the Refresh Queue runs one Refresh Job at a time. The Impact service owns the Refresh Queue and the Cache Freshness of each cache, because it already owns the Scan Record (`llamaindex-spec-rag` ADR-0005).

When a question needs a cache with the Cache Freshness `outdated` or `refreshing`, the run does not read that cache. The run lists the system as an Unread System with the reason `cache_outdated` or `cache_refreshing`, and the answer links to the update page. When a Pinned System has such a cache, the run stops before it starts, and spends no LLM tokens. When every system that the run needs has such a cache, the answer only tells the analyst which systems to update.

A `behind_source` cache does not block a question. The answer stays correct for the scanned commit.

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
- The update page checks for `behind_source` when an analyst opens it, and again when the analyst asks for a new check. The page shows the time of the last check. A question never checks the remote repository.
- An "update all" action submits a Refresh Job for each `outdated` cache. It does not include a `behind_source` cache. An analyst submits each `behind_source` cache alone.
- Any later proposal to rebuild a cache inside a question reverses this ADR and needs its own ADR.

## Amendment: the Environment Check locks rows (2026-10-22)

`llamaindex-spec-rag` ADR-0020 adds an Environment Check. The Impact service tests SQL Server access and Azure Repos access itself, because it is the process that makes the connections. The test logs in to each server of the Database Registry (and each server that only the catalog names), and runs `git ls-remote` one time for each remote host. A remote host is one Azure DevOps project, because every repository of the catalog is in one organization.

The service keeps the last result in memory. Each SQL row of a failed server and each C# row of a failed host gets a `locked_reason`. A Refresh Job for a locked row gets HTTP 409 with that reason, and no job starts. "Update all" skips the locked rows and still submits the other `outdated` caches. Before the first check, and after a restart, no row is locked.
