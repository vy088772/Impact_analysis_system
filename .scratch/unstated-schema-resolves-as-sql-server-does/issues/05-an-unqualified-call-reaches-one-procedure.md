# 05 — An unqualified call reaches one procedure

**What to build:** An analyst follows a program into the procedures it reaches, and one unqualified call gives one Execution Path. The graph builder resolves a call that states no schema by the rule of ticket 04 and links it to the one procedure the rule names. An unqualified `sp_` or `xp_` name that the listing does not hold resolves to the `sys` schema and becomes no user node. This closes the conflict with ADR-0035 that the canonical-object-identity spec recorded as an open decision.

See "The resolution rule" (the `sys` rule and the static `EXEC` reading), "The graph builder", and user stories 8, 9, 13, 14 in the spec.

**Blocked by:** 04 — A read or write with no schema resolves as SQL Server does (the call rule uses that ticket's resolution).

**Status:** done (ticket 10 closed the last box)

- [x] A failing graph builder test comes first: a `COMMON` module calls `GetBudgetVersion` with no schema while `COMMON` and `Mitoosi` both hold it, and exactly one call relationship reaches `COMMON.GetBudgetVersion`.
- [x] A call that no listed procedure answers gives one path with the Unproven Schema mark. (This ticket gave one path and the `unresolved` schema source on the relationship. Ticket 10 added the `unproven_schema` flag to the path.)
- [x] An unqualified `sp_` or `xp_` name that the listing does not hold records schema `sys` and schema source `system`, and creates no `dbo` node. The seven caches' `sp_OACreate` and `sp_executesql` calls are the cases.
- [x] A listed user procedure whose name starts with `sp_` still gets the link.
- [x] A static `EXEC` inside a module resolves against the module's schema first.
- [x] The open-decision bullet in the canonical-object-identity spec points to this ticket as its resolution.
- [x] The golden `path_id` test stays unedited and passes.
- [x] The whole suite shows no new failure.

## Comments

Files this ticket changed (other tickets run in parallel; these are the only ones):

- `schema_resolution.py`: adds `SYSTEM_SCHEMA = "sys"`, the source `SYSTEM = "system"` (placed after `DEFAULT_SCHEMA_SOURCE` in `SOURCES`), and `resolve_call()`. It follows `resolve()`. An unqualified `sp_` or `xp_` name (case-insensitive) that `resolve()` leaves unresolved, with no `db..` part, becomes `sys` with source `system`. A listed user procedure with that prefix still wins, because `resolve()` runs first. Tickets 06 and 07 can reuse it.
- `service/sql_execution_graph.py`:
  - `_resolved_call_target()` (new) gives each `CALL` target its schema and schema source before the node lookup. A call through a linked server or to another Database keeps what it states (`written`, or `unresolved` with no schema).
  - `_add_operation()` passes `schema_source` to every `calls` relationship.
  - The bare-name bucket is gone: `_NodeIndex.bare` and the empty-schema branch of `_listed_nodes()` were removed, because the call was their last user. An empty schema now matches no listed node.
  - `GRAPH_VERSION` stays 7, and its comment is unchanged (ticket 09).
- `tests/test_sql_execution_graph.py`: the test `test_a_call_that_states_no_schema_names_every_listed_procedure_with_that_bare_name` became 7 tests (`_call_graph` helper): module schema, `dbo` module, fallback to `dbo`, unlisted call, unlisted `sp_`/`xp_` call to `sys`, listed `sp_` user procedure, written schema and `master..sp_who`. A static `EXEC` inside a module is a `CALL` operation, so the `COMMON` module test covers it.
- `.scratch/canonical-object-identity/spec.md`: a bullet before the open decision points to this ticket as its resolution.

Behaviour to know:

- A call that no listed procedure answers keeps an empty schema and the source `unresolved`. Its target id is `stored_procedure:.name`, which names no node. The path builder already gives that one `called_procedure_not_in_graph` path. A `sys` call gives the same one path with the target `stored_procedure:sys.name`, and no `dbo` node exists.
- The path builder sets no `unproven_schema` flag for a `called_procedure_not_in_graph` path today, and this ticket does not add one. The `schema_source` on the relationship is the record of the mark. If ticket 06 or the review wants the flag on the path, it is a new change.

Verification: `pytest tests/test_sql_execution_graph.py tests/test_rebuild_report.py tests/test_execution_path_builder.py` gives 101 passed. The golden `path_id` test passes, unedited. mypy on the two changed modules shows no issue. The whole suite (with `test_search_roles.py` and `test_sp_tables.py` ignored) shows 16 failures, the same 16 as the baseline of ticket 01.

**Whole-feature review, 2026-09-30** (`/code-review` from `b865587` to `154ad57`, then the fixes).

- The call target rule sat in two helpers that repeated one test (`target.server or names_another_database(...)`). ADR-0036 says that one site holds the rule. `_call_target()` is now that site (commit `aa323d7`). Behaviour does not change.
