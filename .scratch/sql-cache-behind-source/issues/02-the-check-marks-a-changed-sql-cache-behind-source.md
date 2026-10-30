# 02: The Check Marks a Changed SQL Cache `behind_source`

**What to build:** When the update page opens, or when an analyst asks to check again, the `behind_source` check also reads the current Fingerprint of each SQL cache. A usable SQL cache whose current Fingerprint differs from its recorded Fingerprint lists as `behind_source`. A refresh of that row clears the state. "Update all" leaves the row out. A question never runs the check.

In this ticket, the check connects with the global `DB_AUTH_MODE` account. Ticket 03 adds the account override of each server.

See the spec: `.scratch/sql-cache-behind-source/spec.md` (decisions Q2, Q3, Q4, Q9, Q10, Q12).

**Blocked by:** 01 (Each SQL Scan Records a Fingerprint, and Old Caches Become `outdated`)

**Status:** ready-for-agent

- [ ] `POST /cache_freshness/check` reads the current Fingerprint of each declared SQL cache that is usable and not locked. It reads a shared SQL cache one time.
- [ ] The check keeps the current Fingerprints in memory with the C# remote heads. A restart forgets both.
- [ ] The listing has one check time for C# and SQL.
- [ ] A usable SQL cache whose current Fingerprint differs from its recorded Fingerprint lists as `behind_source`. A different count with the same time also gives `behind_source`.
- [ ] An equal Fingerprint gives `current`.
- [ ] `refreshing` and `outdated` win over `behind_source`.
- [ ] No current Fingerprint (no check yet, server unreachable, query failed, or row locked) gives no `behind_source`.
- [ ] A finished refresh clears `behind_source` with no second check.
- [ ] A shared SQL cache shows the same state under each system.
- [ ] "Update all" submits no Refresh Job for a `behind_source` SQL cache.
- [ ] `GET /cache_freshness` and a question never call the Fingerprint reader. A `behind_source` SQL cache never blocks a question.
- [ ] HTTP API tests replace the Fingerprint reader with a fake (prior art: the `behind_source` API tests) and cover each criterion above. The existing test that says a SQL cache is never `behind_source` changes to match.
- [ ] ADR-0045 states that a SQL cache can be `behind_source`, and that its source is the Database.
- [ ] CONTEXT.md adds the term **Fingerprint** and updates the entries for Cache Freshness and Scan Record.
