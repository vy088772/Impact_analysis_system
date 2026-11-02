# 02: The Check Marks a Changed SQL Cache `behind_source`

**What to build:** When the update page opens, or when an analyst asks to check again, the `behind_source` check also reads the current Fingerprint of each SQL cache. A usable SQL cache whose current Fingerprint differs from its recorded Fingerprint lists as `behind_source`. A refresh of that row clears the state. "Update all" leaves the row out. A question never runs the check.

In this ticket, the check connects with the global `DB_AUTH_MODE` account. Ticket 03 adds the account override of each server.

See the spec: `.scratch/sql-cache-behind-source/spec.md` (decisions Q2, Q3, Q4, Q9, Q10, Q12).

**Blocked by:** 01 (Each SQL Scan Records a Fingerprint, and Old Caches Become `outdated`)

**Status:** done (2026-10-30)

- [x] `POST /cache_freshness/check` reads the current Fingerprint of each declared SQL cache that is usable and not locked. It reads a shared SQL cache one time.
- [x] The check keeps the current Fingerprints in memory with the C# remote heads. A restart forgets both.
- [x] The listing has one check time for C# and SQL.
- [x] A usable SQL cache whose current Fingerprint differs from its recorded Fingerprint lists as `behind_source`. A different count with the same time also gives `behind_source`.
- [x] An equal Fingerprint gives `current`.
- [x] `refreshing` and `outdated` win over `behind_source`.
- [x] No current Fingerprint (no check yet, server unreachable, query failed, or row locked) gives no `behind_source`.
- [x] No recorded Fingerprint (a null in the Scan Record, from a scan that could not read one) gives no `behind_source`.
- [x] The check gives the reader the same connection address as a refresh of that server (`ScanConnection.server`), so a named instance connects correctly.
- [x] The listing reads the recorded Fingerprint back from the Scan Record into a `Fingerprint` (for example a `Fingerprint.from_dict()` beside `to_dict()`), and compares the two values for equality.
- [x] A finished refresh clears `behind_source` with no second check.
- [x] A shared SQL cache shows the same state under each system.
- [x] "Update all" submits no Refresh Job for a `behind_source` SQL cache.
- [x] `GET /cache_freshness` and a question never call the Fingerprint reader. A `behind_source` SQL cache never blocks a question.
- [x] HTTP API tests replace the Fingerprint reader with a fake (prior art: the `behind_source` API tests) and cover each criterion above. The existing test that says a SQL cache is never `behind_source` changes to match.
- [x] ADR-0045 states that a SQL cache can be `behind_source`, and that its source is the Database. The amendment of 2026-10-30 records the decision and says that this ticket builds the check. When the check ships, remove the sentence "Until then, a SQL cache is never `behind_source`."
- [x] CONTEXT.md adds the term **Fingerprint** and updates the entry for Scan Record. (Done in ticket 01 review follow-ups.)
- [x] CONTEXT.md updates the entry for Cache Freshness: a SQL cache can be `behind_source` when its Database changed.

## Comments

**Implementation notes (2026-10-30)**

- **Branch and commits.** Impact_analysis_system, branch `feat/sql-cache-fingerprint`.
  `a62d2ed` builds the check. A later commit on this branch holds the review follow-ups.
- **Where the code is.** `cache_freshness.sql_check_targets()` names the SQL caches
  to read. Each is declared, usable, and not locked, and has a Scan Connection.
  `source_check.check()` reads them and keeps the Fingerprints beside the remote heads.
  `source_check.current_fingerprint()` gives the kept value.
  `sql_cache_store.cached_fingerprint()` reads the recorded value from the Scan Record
  through `Fingerprint.from_dict()`. `cache_freshness.sql_row()` compares the two values.
- **Connection address.** The check uses the server of the catalog, as a single
  refresh does. So a named instance (`host\instance`) connects. The account is the
  global scan account. Ticket 03 adds the account override.
- **Tests.** `tests/test_sql_behind_source_api.py` holds 18 HTTP API tests with a fake
  reader. The `remote` fixture of `tests/test_behind_source_api.py` now also replaces
  the reader with one that returns no Fingerprint. So the C# tests never connect to
  SQL Server. The old test "a SQL cache is never `behind_source`" has a new name.
- **OpenAPI.** The docstring of `POST /cache_freshness/check` changed, so
  `docs/openapi/openapi.json` is regenerated.
- **Suite proof.** `pytest tests/ --ignore=tests/test_search_roles.py
  --ignore=tests/test_sp_tables.py` gives 1 failure only:
  `test_external_wrapper_contract_identity.py::test_the_shipped_sqlobject_contract_states_its_required_parameter_counts`.
  It also fails before ticket 01. mypy reports one error at the `RefreshRequest`
  call of `update_all_requests()`. That error also occurs before this ticket.

**Review follow-ups (2026-10-30)**

The user asked to fix the findings of the Standards review and the Spec review.

- **Fixed: a lock after a check.** Before the fix, an Environment Check that locked a
  server after a check left its rows `behind_source`, from an old Fingerprint.
  Now `sql_row()` gives no `behind_source` to a locked row. A new test covers it.
- **Fixed: one dedupe.** `sql_check_targets()` returns a map from identity to
  Scan Connection, and `check()` takes that map. The `SqlTarget` pair type is gone.
- **Fixed: names.** In `check()`, the answers are `heads` and `fingerprints`, and the
  map is `connections`.
- **Fixed: documents.** The CONTEXT.md sentence for `behind_source` had 36 words. Now
  it has three short sentences, one for each source. "Correct for the scanned commit"
  is now "correct for the scanned state", because a SQL cache has no commit.
  The docstring says "global scan account", the CONTEXT.md term. ADR-0045 says
  "a refresh of that cache".
- **Fixed: tests.** The helper imports are at the top of the file. One unused
  `monkeypatch` argument is gone. The refresh test now shows that the listing after
  the refresh calls the reader zero times. It no longer counts the read of the scan.
- **Kept on purpose.** `sql_check_targets()` stays in `cache_freshness`, because that
  module knows which rows are usable and not locked. `check()` still calls
  `sql_cache_store.read_fingerprint` through the module, as it calls
  `fetch_remote_head`: the tests replace the one reader there. The tests replace the
  private state `_fingerprints` and `_last`, as the C# tests replace `_heads`.
  The tests that count reader calls stay, because the spec says "one read" and
  "never calls the Fingerprint reader".

**Open points for later tickets**

- "Update all" builds a SQL refresh from `row["server"]`. That value is the normalized
  server, with no named instance. So "update all" and the check can use different
  addresses for a named instance. This code is older than this ticket. Ticket 03
  touches the same request, so it is a good place to fix it.
- The C# row has the same pattern as the old SQL lock bug: a lock after a check
  leaves the row `behind_source`. This ticket does not change C#.
- Two catalog addresses with one identity (for example `host\A` and `host\B`) give one
  read, at the first address. This follows from the design of SQL Cache Identity.
