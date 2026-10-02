# 01 — Each request handler builds the SQL Cache Identity once

**What to build:** Each request handler of this repository builds the SQL Cache
Identity one time, at its top. Every function below the handler receives that
identity. No function below the handler receives a Database name and an
optional server. A reverse lookup lists the cache directory at most one time.
The answers of all endpoints stay the same.

The endpoints are `/find_by_sp`, `/find_by_table`, `/path_evidence`,
`/flow_chain` and `/analyze`. The functions below the handler are the SQL
Execution Graph loader, the SP catalog builder, the derived execution evidence
scope and its validity stamp.

Rules from the spec (`../spec.md`):

- With a host, the handler uses the pure identity constructor. With no host, the
  handler uses the disk lookup function. The branch stays at each call site. Do
  not add a function that takes an optional server (the decision that reverted
  a362aac).
- `/find_by_sp` and `/find_by_table` refuse an ambiguous-server value with HTTP
  409 `ambiguous_database`. The refusal stays before any source scan and before
  the `cache_only` skip.
- `/path_evidence`, `/flow_chain` and `/analyze` treat an ambiguous-server value
  as no cache. They answer "not scanned", as `CONTEXT.md` states.
- The refresh path and the wrapper discovery tool call the disk lookup function
  at their own call site.
- The scope keeps the Database name for the inputs that use the name only, such
  as the wrapper review exclusions.
- The request schemas do not change. `db_server` stays optional.

**Blocked by:** None — can start immediately.

**Status:** done (agent, 2026-10-02)

- [x] A failing `TestClient` test comes first, then the change.
- [x] A request that names `vmsystest07`, for a Database with a cache on `vmsystest08` only, answers `sql_execution_graph_required`. No match comes from `vmsystest08`.
- [x] A reverse lookup with no host, for a Database on two hosts, answers 409 `ambiguous_database`. The cache store lists the directory one time for that request.
- [x] A reverse lookup that names a host lists the cache directory zero times.
- [x] `/path_evidence` and `/flow_chain` with no host, for a Database on two hosts, still answer "not scanned".
- [x] The separate ambiguity check function no longer exists.
- [x] The SQL Execution Graph loader and the SP catalog builder take a SQL Cache Identity, or no identity. They take no server argument.
- [x] The derived execution evidence scope carries the identity that the handler built, in place of its `db_server` field. The validity stamp does not build the identity again.
- [x] Two Databases with the same name on different hosts give two different scope retention keys.
- [x] All current tests stay green, including the lookup `db_server` API tests and the exact path evidence tests.

## Notes (agent, 2026-10-02)

### Files that this ticket changed

Another session works on ticket 02 at the same time. Ticket 02 changes
`llamaindex-spec-rag` only. This ticket changes these files of this repository:

- `service/analyze_service.py`: the five handlers, `_execution_sql_context`,
  `load_sp_catalog`, `_require_sql_execution_graph`,
  `DerivedExecutionEvidenceScope` (field `sql_cache_identity` in place of
  `db_server`), `_rated_invocations_validity_stamp`,
  `_build_program_execution_paths` (`scope` is now required),
  `_materialize_path_evidence`, two log lines. `_reject_ambiguous_database`
  is removed.
- `service/sp_fetcher.py`, `service/view_fetcher.py`, `service/udf_fetcher.py`:
  each fetcher takes a SQL Cache Identity, or no identity, in place of a
  Database name and an optional `db_server`.
- `service/derived_execution_evidence_store.py`: `_key()` reads the identity
  cache key.
- `service/sql_cache_store.py`: the `find_cache_identity()` docstring only.
- `tests/test_sql_cache_identity_http_seam.py`: new.
- `tests/sql_cache_fixtures.py`: `one_server_holds_every_database("")` returns
  `None`, as the real lookup does.
- Test call sites updated for the new signatures:
  `test_derived_execution_evidence_scope.py`, `..._reuse.py`,
  `..._retention_bound.py`, `..._disk_retention.py`,
  `test_execution_path_integration.py`, `test_path_evidence_api.py`,
  `test_path_evidence_program_files.py`, `test_sql_cache_store.py`,
  `test_sp_fetcher.py`, `test_formal_output_migration.py`,
  `test_exact_path_evidence.py`.

### Decisions

- The red tests: a reverse lookup with no host, for a Database on one host,
  listed the cache directory 4 times. `/analyze` with `include_sp_defs` listed
  it 2 times, and answered 400 for a host of spaces only. Now each lists it
  1 time, and the blank host is no host.
- The spec says that the identity code exists in four places. The code had
  seven: the three fetchers had their own copy. The code review found that
  the `/analyze` fetchers can take the handler identity with no change to the
  answer, so the fetchers now take an identity.
- The branch condition is `req.db_server.strip() and req.database.strip()`.
  A blank host is no host on all five endpoints. Before, `/analyze`,
  `/path_evidence` and `/flow_chain` could give 400 for a host of spaces only.
- `/flow_chain` builds the identity before the `cache_only` skip, as the
  ticket says "at its top". A skipped request with no host now lists the
  directory one time. The answer does not change.
- Scope equality: a request with no host and a request that names the same
  host now give one scope, because both reach one identity. Before, they gave
  two scopes and derived the same evidence two times. Two hosts still give two
  scopes and two retention keys.
- The retention key on disk changes from the host to the identity key. Old
  stored evidence is not found, and the next request derives it again. This
  loss recovers by itself, so the store version stays the same.

### Left for a follow-up

- The literal-SP branch of `/path_evidence` (`_materialize_path_evidence`)
  still builds an identity below the handler. It reads the cache of the
  Database that the path names (`invocation.database`), which can differ from
  the requested Database. A change to the handler identity changes the answer
  when the two names differ, so it needs its own decision.
- `inline_table_relations._InlineSchemaResolver` calls `find_cache_identity()`
  for each connection Database. A `/find_by_table` request that names a host
  can still list the directory when an inline table has no schema. The
  zero-listing test passes because its fixture has no such table. This goes
  against user story 13 and needs a decision.
