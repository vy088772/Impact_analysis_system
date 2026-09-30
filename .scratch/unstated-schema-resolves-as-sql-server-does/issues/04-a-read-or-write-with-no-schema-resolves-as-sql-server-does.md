# 04 — A read or write with no schema resolves as SQL Server does

**What to build:** An analyst asks `/find_by_table COMMON.UserProgram` and gets `COMMON.ModuleList_Update` as a proven writer with no mark. The graph builder resolves every read, write, and View or Function reference that states no schema: inside a module in schema `S`, the listing's `S.name`, else `dbo.name`. A reference inside a view or a function resolves against that module's own schema. Every relationship records its schema source.

See "The resolution rule", "The schema source", "The graph builder", and user stories 1 to 7, 10 to 12, 15, 16 in the spec.

**Blocked by:** None — can start immediately.

**Status:** done

- [x] A failing graph builder test comes first for each case: a `COMMON` module reading a name that only `COMMON` holds; a `COMMON` module reading a name that only `dbo` holds; a `dbo` module reading a name that `dbo` holds; a name that neither holds; an unlisted name.
- [x] The lookup crosses object kinds inside one schema: a view `S.X` wins over a table `dbo.X`.
- [x] A reference inside a view or a function resolves against that view's or function's schema, and the lineage below it follows.
- [x] A name that neither `S` nor `dbo` holds, an unlisted name, and a `db..name` reference keep an empty schema and the Unproven Schema mark.
- [x] Every read, write, and function reference relationship carries `schema_source`: `written`, `module_schema`, `default_schema`, or `unresolved`.
- [x] A resolved schema becomes the node's schema, and the node id follows from it.
- [x] The default schema is one constant, `dbo`.
- [x] The golden `path_id` test stays unedited and passes.
- [x] The graph format version does not change here.
- [x] The whole suite shows no new failure.

## Comments

Files this ticket changed (other tickets run in parallel; these are the only ones):

- `schema_resolution.py` (new, repository root, beside `canonical_object_identity.py`): the rule. `DEFAULT_SCHEMA = "dbo"`, the source constants `WRITTEN`, `MODULE_SCHEMA`, `DEFAULT_SCHEMA_SOURCE`, `UNRESOLVED`, the order `SOURCES` (strongest first), and `resolve(reference, module_schema, holds) -> (schema, schema_source)`. Outside a module, pass `module_schema=""`: the rule then checks `dbo` only. Tickets 05, 06, and 07 can reuse it. Ticket 05 adds the `sys` rule and the `system` source here.
- `service/sql_execution_graph.py`:
  - `_NodeIndex` holds the listing (`list_object`, `holds`). Only the listing loops fill it. A node that only a reference adds is not listed, so the order of the modules cannot change a result.
  - `_resolved_reference()` resolves each read, write, and function reference before the node lookup. The resolved schema becomes the node's schema and its id.
  - `_ensure_referenced_nodes()` and `_known_object_node_ids()` match no listed View or Function for an unresolved reference. The bare-name bucket of `_listed_nodes()` now serves calls only (ticket 05 changes that).
  - `_add_relationship()` takes `schema_source`. Every `reads`, `writes`, and `uses` relationship carries it. `calls` does not yet (ticket 05).
  - The temp table lineage read carries the schema source of the base read at the end of its own chain. Two writers of one temp table that read one base table keep the strongest source.
  - `GRAPH_VERSION` stays 7, and its comment is unchanged (ticket 09).
- `tests/test_sql_execution_graph.py`: 15 new tests. The old test `test_a_reference_that_states_no_schema_names_every_listed_node_with_that_bare_name` became `test_a_call_that_states_no_schema_names_every_listed_procedure_with_that_bare_name`; its View read part left, because the new rule replaces it. Ticket 05 changes the call part.
- `tests/test_rebuild_report.py`: one expectation. An unlisted name now counts as `unresolved`, not `""`.

Decisions to carry into ticket 08 (the ADR):

- A `dbo` module that reads a name that `dbo` holds records `module_schema`, not `default_schema`. The module's own schema is the first step of the rule, and it found the name. `default_schema` means the fallback to `dbo` from another schema, or a reference outside a module.
- A `db..name` reference keeps an empty schema and `unresolved`, also when the Database is the cache's own Database. SQL Server resolves it against the default schema of the module schema owner, not against the module's schema, and this rule reads no listing for it.
- The lookup ignores case, through `casefold()`, as the node key does.
- `CONTEXT.md` lists "default schema" under *Avoid* for Unproven Schema. The code uses the term in the SQL Server sense. The Schema Resolution entry (ticket 08) must settle this.

Verification: `pytest tests/test_sql_execution_graph.py tests/test_rebuild_report.py` gives 64 passed. The golden `path_id` test (`tests/test_execution_path_builder.py`) passes, unedited. mypy on the two changed modules shows no issue. The whole suite (with `test_search_roles.py` and `test_sp_tables.py` ignored) shows 16 failures, the same 16 as ticket 01's baseline: C# wrapper and real-checkout tests, none of them on the SQL graph. One run showed 53 failures while a parallel session rebuilt the analyzer host; a rerun gave the 16 again.

**Whole-feature review, 2026-09-30** (`/code-review` from `b865587` to `154ad57`, then the fixes).

- `schema_resolution` now holds the schema source as one type, `SchemaSource`. It also holds `recorded_source()` (the default of a record that states none) and `strongest_source()` (the order of strength). Commit `aa323d7`.
- The graph payload does not change. A relationship still holds the schema source as plain text.
- `_ensure_referenced_nodes()` and `_known_object_node_ids()` returned a list of one element. They are now `_referenced_node_id()` and `_listed_function_id()`, and each returns one value.
- The test `..._falls_back_to_dbo_...` is now `..._resolves_to_dbo_...`. The glossary avoids "default schema fallback".
