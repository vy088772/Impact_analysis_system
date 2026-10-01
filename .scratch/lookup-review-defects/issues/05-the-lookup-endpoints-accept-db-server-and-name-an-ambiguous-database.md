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

- `service/schemas.py`: new base class `LookupDatabaseHost` holds the optional `db_server`. `FindBySPRequest` and `FindByTableRequest` inherit it. A validator strips the value, so a blank host counts as no host named.
- `service/analyze_service.py`: new `AmbiguousDatabaseError` (code `ambiguous_database`, `database`, `servers`). It is the error form of `sql_cache_store.AmbiguousServer`. New `_reject_ambiguous_database`: `find_by_sp` and `find_by_table` call it first, before the `cache_only` skip and before any source scan. A Database on several hosts with no host named costs one directory listing. Both lookups pass `req.db_server` to `_require_sql_execution_graph`, which keeps its old signature, so `/analyze`, `/path_evidence` and `/flow_chain` keep the old code for that case. The client of ticket 04 reads the new code in the two lookups only.
- `service/api.py`: both routes catch `SqlExecutionGraphRequiredError` and `AmbiguousDatabaseError` in one clause. `_lookup_conflict_http_error` maps the second to HTTP 409 with `{code, database, servers, message}`. The code for "not scanned" does not change.
- `CONTEXT.md`: new entry **Ambiguous Database**. `sql_cache_store.find_cache_identity` docstring no longer says the two lookups have no `db_server`. `docs/openapi/openapi.json` is regenerated.
- Tests: new `tests/test_lookup_db_server_api.py` (HTTP client, real cache files for two hosts). It covers the new code with the exact normalized hosts, the answer from the named host, a host name with a domain and instance suffix, not scanned, one host without `db_server`, the order before the `cache_only` skip, no source scan for an ambiguous Database, and a blank host. Two stubs of `_require_sql_execution_graph` accept the new arguments.
- Scope decision: no caller passes `db_server` to these two endpoints yet. The 409 body has a `servers` list beyond what ticket 04 needs; it tells the person which hosts to choose from.
- Result of the order change: a system whose C# repo is not scanned, asked about a Database on several hosts, now answers `ambiguous_database` and not `skipped`. The Database fact does not depend on the repo.
- Full suite: 3 tests fail in a worktree on a clean copy too. They read `llamaindex-spec-rag/catalog` as a sibling directory. `tests/test_search_roles.py` and `tests/test_sp_tables.py` fail at collection for the same path reason.

## Note (code review follow-up)

- Review: two axes (Standards, Spec), one commit `50cbff5`. All findings fixed in the follow-up commit: the Boolean flag on `_require_sql_execution_graph` is gone, the ambiguity check moved ahead of the skip and the scan, a blank host is stripped, the duplicated schema field and `except` clause are shared, the error names its link to `AmbiguousServer`, the CONTEXT.md entry is new, and the test compares the exact host strings.
- Left as is, on purpose: the `database` and `db_server` pair still travels as two arguments, as in the other endpoints.
