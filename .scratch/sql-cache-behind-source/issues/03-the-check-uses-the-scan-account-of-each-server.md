# 03: The Check Uses the Scan Account of Each Server

**What to build:** A server whose Database Registry entry names `uid_env` and `pwd_env` gets its SQL check with that account. The check reads the same account as a refresh of that server. No credential comes from an application Web.config (ADR-0010).

This ticket crosses two repositories. Impact_analysis_system accepts the accounts. `llamaindex-spec-rag` sends them.

See the spec: `.scratch/sql-cache-behind-source/spec.md` (section "Check" and section "`llamaindex-spec-rag` web side").

**Blocked by:** 02 (The Check Marks a Changed SQL Cache `behind_source`)

**Status:** done (2026-10-30)

- [x] `POST /cache_freshness/check` takes an optional body with `sql_credentials`, keyed by server, with the same shape as in `/environment/check` and `/refresh_jobs/update_all`.
- [x] A request with no body still works and uses the global account.
- [x] The check passes the override of a server to the Fingerprint reader. A server with no override gets no override.
- [x] In `llamaindex-spec-rag`, the client call for the check sends the scan account overrides from the Database Registry, the same as the "update all" call.
- [x] An Impact HTTP API test with a fake reader shows that the reader gets the override of its server.
- [x] A `llamaindex-spec-rag` test shows that the check request carries the overrides from the Database Registry.

## Comments

**Implementation notes (2026-10-30)**

- **Branches and commits.** Both repositories use the branch `feat/sql-cache-fingerprint`.
  Impact_analysis_system: `60c7df9` builds the check body, and `2a3511f` holds the review follow-ups.
  `llamaindex-spec-rag`: `5ab49e6` sends the accounts, and `7d678b7` holds the review follow-ups.
- **Impact side.** The new schema `CacheFreshnessCheckRequest` has one field, `sql_credentials`.
  `POST /cache_freshness/check` takes it as an optional body. `cache_freshness.sql_check_targets()`
  looks up the override by `identity.server`, the normalized server that a listing row shows.
  The Scan Connection keeps the catalog address, so a named instance connects with its override.
- **Web side.** `rag_client.check_behind_source()` reads the listing first. It sends the overrides
  of the servers of the SQL rows that the check reads: not `outdated`, and not locked. This is the
  same rule as "update all", which sends the overrides of the servers of `outdated` rows.
- **A broken override.** A broken override of a server that the check reads stops the check. The
  error names each broken server. The check never uses the global identity in its place (ADR-0004).
  A broken override of another server has no effect on the check.
- **Tests.** `tests/test_sql_behind_source_api.py` has 3 new Impact HTTP API tests: the override of
  the server, no override, and a named instance. `tests/test_check_behind_source_client.py` in
  `llamaindex-spec-rag` has 2 tests: the request body, and a broken override.
- **Suite proof.** Impact: `pytest tests/ --ignore=tests/test_search_roles.py
  --ignore=tests/test_sp_tables.py` gives 2040 passed and 1 known failure
  (`test_the_shipped_sqlobject_contract_states_its_required_parameter_counts`, which fails before
  ticket 01). `llamaindex-spec-rag`: 2531 passed, with `tests/test_conversion_encrypted_file.py`
  left out, because it needs `pywintypes` (Windows only). mypy shows no new errors in either repository.
- **OpenAPI.** `docs/openapi/openapi.json` is regenerated for the new request body.

**Review follow-ups (2026-10-30)**

The Standards review and the Spec review ran after the first commits.

- **Fixed: a broken override stopped the whole check.** Before the fix, the client read the account
  of each server in the Database Registry. A broken entry for any server stopped the check, and also
  the C# check. Now the client reads only the servers that the check reads.
- **Fixed: one broken server in the message.** The error now names each broken server, not the first.
- **Fixed: one helper.** `_scan_accounts(servers)` serves the check, "update all", and the
  Environment Check. Each caller decides what a broken override does.
- **Fixed: the docstring of the endpoint.** "A question never runs this check" now comes before the
  sentence about the body, so it cannot read as a sentence about the account.
- **Fixed: the import.** `CacheFreshnessCheckRequest` is now beside `CacheFreshnessResponse`.
- **Fixed: the test docstring.** The new client test has a Chinese docstring, as its sibling tests do.
- **Fixed: line endings.** The first edit changed `service/api.py` from CRLF to LF. The amended
  commit keeps CRLF, so the diff shows only the real change.
- **Kept on purpose.** `CacheFreshnessCheckRequest` and `EnvironmentCheckRequest` have the same
  field. A shared base type is not useful for two models yet. The helper returns a tuple of two dicts,
  and the two callers unpack it at once. A named type adds no clarity here.
- **Kept on purpose.** The broken-override behavior differs from the Environment Check. The
  Environment Check reports one failed item for each server. The check has no item for one server,
  so it stops and shows the reason, the same as "update all".

**Open points for later tickets**

- "Update all" still builds a SQL refresh from `row["server"]`, the normalized server with no named
  instance (from ticket 02). This ticket does not change it, because it is not in the checklist.
