# 05 — The lookup endpoints accept the Database host and name an ambiguous Database

**What to build:** `/find_by_sp` and `/find_by_table` accept an optional `db_server`, as `/path_evidence` and `/flow_chain` already do. The server resolves the one SQL cache from that host. A Database name that lives on more than one host, with no host named, gets the new error code `ambiguous_database`. A Database that is not scanned keeps the code for "not scanned". See the SQL Cache Identity entry in `CONTEXT.md` and ADR-0033. The work is in this repository, and it ships after ticket 04.

**Blocked by:** 04 — The client sends the Database host and reads "several hosts" as its own reason

**Status:** done

- [x] Both request schemas gain an optional `db_server`.
- [x] The server passes `db_server` to the same cache-identity resolution that the other endpoints use.
- [x] A test at the HTTP API shows the new code for a Database on two hosts with no host named.
- [x] A test shows a correct answer when `db_server` names one of the two hosts.
- [x] A test shows the old code for a Database that is not scanned.
- [x] A call without `db_server` for a Database on one host keeps today's behavior.

## Note (implementation)

- `service/schemas.py`: `FindBySPRequest` and `FindByTableRequest` have an optional `db_server` (default empty).
- `service/analyze_service.py`: new `AmbiguousDatabaseError` (code `ambiguous_database`, with `database` and `servers`). `_require_sql_execution_graph` has a keyword flag `name_ambiguous_database`. Only `find_by_sp` and `find_by_table` set it, and both now pass `req.db_server`. With a `db_server`, the cache identity comes from `CacheIdentity.of`, as in `/path_evidence` and `/flow_chain`. Without one, `find_cache_identity` runs, and several hosts raise the new error. `/analyze`, `/path_evidence` and `/flow_chain` keep the old code for that case, because the client of ticket 04 reads the new code in the two lookups only.
- `service/api.py`: both routes map the new error to HTTP 409 with `{code, database, servers, message}`. The code for "not scanned" (`sql_execution_graph_required`) does not change.
- Tests: new `tests/test_lookup_db_server_api.py` (10 tests, HTTP client, two real cache files on disk). It covers the new code, the answer from the named host, a host name with a domain and instance suffix, not scanned (no host and a named host with no cache), and one host without `db_server`. Two stubs of `_require_sql_execution_graph` in `tests/test_inline_read_through_view.py` and `tests/test_inline_sql_table_database.py` now accept the new arguments. `docs/openapi/openapi.json` is regenerated.
- Docstring of `sql_cache_store.find_cache_identity` no longer says the two lookups have no `db_server`.
- Full suite: 1461 passed. 3 tests fail in a worktree on a clean copy too: they read `llamaindex-spec-rag/catalog` as a sibling directory. `tests/test_search_roles.py` and `tests/test_sp_tables.py` fail at collection for the same path reason, and I skipped them.
- Scope decision: no caller passes `db_server` to these two endpoints yet. The client of ticket 04 sends it only when a caller names one.
- Code review: I read the diff myself. I did not run `/code-review`.
