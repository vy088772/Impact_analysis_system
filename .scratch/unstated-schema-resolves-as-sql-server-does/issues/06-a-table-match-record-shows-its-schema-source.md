# 06 — A table match record shows its schema source

**What to build:** An analyst reads a `/find_by_table` record and sees how its schema was found. Every record carries `schema_source`, taken from the graph relationship. An inline C# SQL table that states no schema resolves at question time: it takes `dbo` when the Object Location Index of the connection's Database holds `dbo.name`, and keeps the Unproven Schema mark otherwise. The question opens no cache.

See "The schema source", "The C# side" (the inline C# SQL table match), and user stories 17 to 20 in the spec.

**Blocked by:** 04 — A read or write with no schema resolves as SQL Server does (the record takes that ticket's relationship field).

**Status:** done

- [x] A failing table match test comes first for a record whose target the graph resolved to `module_schema`, and for one with a `written` schema.
- [x] An inline C# SQL table with no schema, over an index that holds `dbo.name`, gives a record with schema `dbo`, schema source `default_schema`, and no mark.
- [x] The same table over an index without `dbo.name` keeps the mark and schema source `unresolved`.
- [x] An inline C# SQL question opens no cache: a test fails the cache loader.
- [x] A located-database row from `/locate_object` gains no schema source field.
- [x] The OpenAPI document is regenerated.
- [x] The whole suite shows no new failure.

**Notes:**

Files this ticket changed (other tickets run in parallel; these are the only ones):

- `service/table_match.py`: `TableMatch` gains `schema_source`. `TableQuestion.match()` takes an optional `schema_source`; an empty value reads as `written` for a target with a schema, else `unresolved`.
- `service/execution_path_builder.py`: each `read_full_keys` and `write_full_keys` entry gains `schema_source`, taken from the graph relationship (same default). Two relationships to one table keep the strongest source. New public helper `schema_source_rank()`.
- `service/graph_queries.py`: `_matching_targets()` passes the source to the match. View and Function lineage carries the source of the read inside the container (`_Target.schema_source`; the merge keeps the strongest). `_access_record()` writes `schema_source` on each record (`unresolved` when no target matched).
- `service/schemas.py`: `TableMatchProgram.schema_source`. `LocatedDatabase` is unchanged.
- `service/analyze_service.py`: `find_by_table` copies the source into the record. New `_InlineSchemaResolver`: an inline C# SQL table with no schema takes `dbo` when the Object Location Index of the connection's Database holds `dbo.name` (table or procedure bucket); it opens no cache. Its record shows `table` as `dbo.name`, not the written text.
- `service/derived_execution_evidence_store.py`: `_STORE_VERSION` 2 to 3, because a stored full key now carries `schema_source`.
- `docs/openapi/openapi.json`: regenerated with `python -m tools.export_openapi_schema` (5 lines, one property).
- `tests/test_table_match.py`: 11 new tests; `_ask_inline` now fails any `load_cached` call and stubs the index; the full key test states `schema_source`.

Verification: `pytest tests/test_table_match.py` gives 27 passed. The golden `path_id` test passes, unedited (`path_id` does not hash full keys). The whole suite (with `test_search_roles.py` and `test_sp_tables.py` ignored) shows 16 failures, the same 16 as ticket 01's baseline.

Review: `/code-review` found no defect. Open points, not done here: the default source rule appears in four places and could move into `schema_resolution` (a parallel session edits that file); no test runs the real graph builder into `/find_by_table`; `test_a_located_database_row...` checks the model fields, not the endpoint output.

