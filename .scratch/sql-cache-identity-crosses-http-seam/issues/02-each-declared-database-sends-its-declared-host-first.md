# 02 — Each declared Database sends its declared host on the first request

**Repository:** `llamaindex-spec-rag` (the client). The ticket lives here with
its spec (`../spec.md`).

**What to build:** A reverse lookup by stored procedure or by table reads the
cache of the host that the catalog declares. The answer never comes from a
cache on another host. A System that declares one Database name on two hosts
gets an answer from both hosts.

Rules from the spec:

- The lookup fan-out sends the declared host on the first request of each
  candidate Database. One candidate Database gets one request. The retry after
  `ambiguous_database` goes away.
- A candidate with a blank host sends no `db_server`, as today. This covers the
  `system_id` fallback candidate and a declared Database with a blank server. A
  409 `ambiguous_database` on such a request gives the `AMBIGUOUS_DATABASE`
  reason in `databases_skipped`, as today.
- The `skip_ambiguous_database` flag stays. The no-Database fallback query does
  not change.
- `find_by_sp` and `find_by_table` lose their `db_server` parameter. The catalog
  is the only source of the host.
- The resolver of lookup Databases removes duplicates by the `(server, name)`
  pair. Declared order stays. The single connection target resolver does not
  change.

**Blocked by:** None — can start immediately.

**Status:** done

- [x] A failing test with a mocked `httpx.post` comes first, then the change.
- [x] The catalog declares `PUR` on `vmsystest07`. The first and only request carries `db_server=vmsystest07`.
- [x] The catalog declares `PUR` on `vmsystest07` and on `vmsystest08`. The client sends two requests, one for each host. A host with no scan appears in `databases_skipped` with its own server.
- [x] A candidate with a blank host sends no `db_server`. A 409 `ambiguous_database` on it gives the `AMBIGUOUS_DATABASE` reason.
- [x] No request follows a 409 `ambiguous_database`. The request ceiling counts one request per candidate Database.
- [x] `find_by_sp` and `find_by_table` have no `db_server` parameter. Tests set the host through the catalog.
- [x] The current declared-host retry tests change to the new rule. All other current tests stay green.

## Notes

- Client files: `impact_orch/rag_client.py` (`_lookup_outcomes`, `find_by_sp`,
  `find_by_table`), `impact_orch/source_resolver.py`
  (`resolve_lookup_databases`), `tests/test_lookup_db_server.py`.
- The resolver normalizes the server before it compares two declarations, so
  `VMSYSTEST07` and `vmsystest07` are one pair. The candidate keeps the
  declared server text.
- `DeclaredHostRetryTests` and `DbServerOnTheRequestTests` went away.
  `DeclaredHostOnTheFirstRequestTests` replaces them. It mocks `httpx.post` and
  sets the host through `catalog_reader.list_systems`.
- `mypy` reports 6 errors in `rag_client.py`. They are on lines that this
  ticket did not change, and they were there before.
- Commits in `llamaindex-spec-rag`: `aeb746f` (the change) and `b3d81c1` (the
  code-review fixes).
- The review found that the `ambiguous_database` gap text told the analyst to
  send `db_server`. No caller can send it now. The gap text in
  `impact_orch/agent_tools.py` and the **Unread System** entry in `CONTEXT.md`
  now tell the analyst to declare the host in the catalog. A parallel session
  commit (`a9fa877`) took the `agent_tools.py` hunk with its own change.
- Open points from the review. This ticket does not change them:
  - The resolver also feeds the `/analyze` and `/flow_chain` fan-out. A System
    that declares `PUR` on two hosts now sends two requests there too.
  - A blank-host declaration and a declared-host declaration of one name are
    two pairs. The client keeps both. The blank-host request lets the server
    pick the host from the disk.
  - The resolver compares the Database name with case. `candidate_database_set`
    compares it with `casefold`. This difference was there before. The
    two-axis review closed it (see below).

## Follow-up of the two-axis review (2026-10-02)

- The resolver and `candidate_database_set` share one comparison key:
  `sql_cache_identity.database_identity()`. It normalizes the host and compares
  the name without case. A catalog that declares `PUR` and `pur` on one host
  gets one request.
- `_with_db_server` removes white space from the host. A host of spaces only
  sends no `db_server`. Its docstring names the catalog as the only source of
  the host.
- The spec section **Implementation Outcome** records the `/analyze` and
  `/flow_chain` fan-out effect.
