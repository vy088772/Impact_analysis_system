# 10 — A call path to an unresolved procedure carries the Unproven Schema mark

**What to build:** An analyst follows a program into a procedure call that no listed procedure answers. The Execution Path for that call already exists (`called_procedure_not_in_graph`), but it carries no `unproven_schema` risk flag. The path builder reads the `schema_source` of the `calls` relationship (`unresolved`) and adds the flag to that one path. A call that resolves to `sys` (source `system`) is proven and carries no flag.

See user story 9 in the spec, and ticket 05, which left this box open.

**Blocked by:** 05 — An unqualified call reaches one procedure (done).

**Status:** done

- [x] A failing path builder test comes first: a call with `schema_source` `unresolved` gives one path with `unproven_schema` in `risk_flags`.
- [x] A call with source `system` gives one path and no `unproven_schema` flag.
- [x] A call to a listed procedure keeps its paths and gains no flag.
- [x] The golden `path_id` test stays unedited and passes.
- [x] The whole suite shows no new failure.

## Comments

- Check that `stored_procedure:sys.name` (no node) is tolerated by every consumer of a `calls` target; ticket 05 verified only the path builder.

Files this ticket changed:

- `service/execution_path_builder.py`: the `calls` loop of `_paths_from_module()` passes `unproven_schema` to `_unresolved_path()` when the relationship records the schema source `unresolved`. `_unresolved_path()` then puts `unproven_schema` after the reason in `risk_flags`. The flag value comes from `UNPROVEN_SCHEMA` of `service/table_match.py`. The Evidence Status, the reason, and the `path_id` of the path do not change.
- `tests/test_execution_path_builder.py`: 4 new tests. Three use a hand-written `calls` relationship (`_unanswered_call_graph` helper): source `unresolved`, source `system`, and a listed procedure. The fourth builds the graph with the graph builder and a stub host, so the two builders must agree on the schema source values.
- `tests/test_graph_queries.py`: 1 new test. A path with the mark gives no table match record, and the record of another target of that procedure carries no mark.
- `CONTEXT.md`: the Unproven Schema entry lists four places for the value, and its first sentence names a call.
- `docs/adr/0035-an-unproven-schema-marks-one-execution-path.md`: the amendment gains one paragraph. It narrows the second bullet of the Decision section ("not on the path itself") for a call. That bullet still holds for a table target.

Behaviour to know:

- The mark follows the schema source only. A call through the real graph builder gives these results:
  - Mark: `usp_Missing` (unlisted), `OtherDb..usp_Far`, `master..sp_who`.
  - No mark: `sp_executesql` (`system`), `HR.usp_Gone` and `OtherDb.dbo.usp_Far2` (`written`, no node).
- A `calls` relationship that records no `schema_source` field gets no mark. A version 8 graph always records the field, so this case reaches a hand-written graph only. A table target has a fallback for that case (`_relationship_targets()`); a call has none, because a call with no node has no node schema to read.
- The path of a call with the mark gives no table match record. It has no read key and no write key, and no `reads` relationship starts at its `terminal_operation_id`. So `_record_risk_flags()` in `service/graph_queries.py` cannot copy the mark to the record of another target.
- Two comments keep their text: `service/graph_queries.py` (`_access_record`, "never on the path") and `service/schemas.py` (the `risk_flags` comment of a table match record). Both describe a table match record, and both stay true for a table target.

The consumer check of a `calls` target with no node (`stored_procedure:sys.name` and `stored_procedure:.name`). Every consumer tolerates it:

- `service/execution_path_builder.py`: gives one `called_procedure_not_in_graph` path (tested).
- `service/sp_fetcher.py`, `_graph_tables_for_procedure()`: skips a target that has no node.
- `service/sql_cache_store.py`, `build_object_location_index()`: reads the target id as a dictionary key, then reads table nodes only. The index gains no key.
- `service/sql_execution_graph.py`, the temp table expansion: reads call edges that have a node only.
- `tools/rebuild_report.py`, `_references()`: parses the schema and the name from the target id. A `sys` call counts under `system` and adds no Unproven Schema target.
- `service/analyze_service.py`, `_materialize_path_evidence()` (`/path_evidence`): the `terminal_operation_id` names no node, and the Evidence Status `unresolved` permits that. Checked by reading; no test drives it.
- `service/graph_queries.py`: reads `reads` and `contains` relationships only.
- `llamaindex-spec-rag`: `path_selection.py` and `context_builder.py` copy `risk_flags` and read no value of it.

One defect that this ticket found and did not change:

- Two calls to one unlisted procedure inside one module give two paths with one `path_id`. Example: a module that runs `EXEC sp_executesql` two times, one inside `IF @b = 1`. The `calls` loop builds the identity from the conditions of the caller only, and it drops the conditions of the relationship. The two paths are equal, so the ADR-0016 deduplication loses no fact, but the path shows no branch condition of the call. A fix changes the `path_id` of those paths, so it needs its own ticket.

Verification: `pytest tests/test_execution_path_builder.py tests/test_graph_queries.py tests/test_fixture_shapes_have_one_source.py` gives 53 passed. The first new test failed before the change (`risk_flags` held the reason only). The `system` test fails when the mark is unconditional. The golden `path_id` test passes, unedited. mypy shows no issue in `service/execution_path_builder.py`. The whole suite (with `test_search_roles.py` and `test_sp_tables.py` ignored) shows 16 failed, 1251 passed. The 16 names are the same with and without the change to `service/execution_path_builder.py`.

Review (`/code-review`, Standards and Spec): no hard violation and no behaviour defect. The review changed the wording of the two documents and added the `tests/test_graph_queries.py` test. One finding stays open by choice: the spec says "A test that needs a schema source states it through the fixture module", and three new tests state it in a hand-written relationship. `tests/test_table_match.py` does the same, and the fourth new test goes through the fixture module.

**Whole-feature review, 2026-09-30** (`/code-review` from `b865587` to `154ad57`, then the fixes).

- The evidence stamp check that ticket 09 asked for: `_STORE_VERSION` is 4 (commit `7be9368`). The validity stamp reads the inputs, not the code. So a file that a version 8 graph gave before this ticket had no `unproven_schema` flag, and the store served it. Such a file is now a miss.
- This review closes the open finding above: `tests/sql_cache_fixtures.py` holds `with_schema_source()`. The hand-written relationships of `tests/test_execution_path_builder.py` and `tests/test_table_match.py` state their schema source through it. An unknown value raises `ValueError`.
