# 01 — A referenced object resolves to the node that exists

**What to build:** A reverse lookup finds a write that the SQL Execution Graph
already proved, whatever case the stored procedure wrote the table name in.

An analyst asks which programs write `VQM`. A stored procedure that writes
`update vqm` in lower case counts, and so does one that writes `INSERT INTO
VQM`. Today the lower-case one is silently lost, together with every other
proven fact in the same DML operation.

The same repair fixes temporary tables. `#Order` and `#tmpPart` dangle for the
identical reason, and they are the two largest sources — 539 and 540
relationships in the PUR cache. Do not remove temporary tables from the graph:
the lineage expansion walks them back to their base tables and produces 78,200
relationships that depend on them.

After this ticket, a graph built by this service holds no relationship whose
target names a node the graph does not have.

**Blocked by:** None — can start immediately.

**Status:** done

- [x] A stored procedure writing a table in lower case, and one writing it in
      upper case, both appear in a reverse lookup for that table.
- [x] A stored procedure that writes a real table and reads a temporary table
      appears in a reverse lookup for the real table.
- [x] Every relationship in a newly built graph names a node that the same graph
      holds. This is asserted as a structural invariant over the existing graph
      fixtures, not only over a new one.
- [x] The temporary-table lineage expansion still resolves a read through a
      scratch table to its base table.
- [x] `GRAPH_VERSION` rises so that every stored cache is rejected as invalid
      and rebuilt. It rises once for this whole effort, not once per ticket.
- [x] The existing tests for the graph builder, the path builder and the cache
      store still pass.

## Comments

- Root cause confirmed exactly as the spec states: `_add_node()` kept the
  first node under a case-insensitive key, but `_ensure_referenced_node()`
  built its return value from the local dict it did not add, so a second
  case-variant reference returned an id that named no node.
- Fix: `_add_node()` (`service/sql_execution_graph.py`) now returns the node
  it actually kept — the existing node on a key collision, or the new node
  otherwise. `_ensure_referenced_node()` returns that node's id instead of
  `node["id"]`. `_node_key()` and `_node_id()` untouched, as the spec
  directs. `_known_object_node_id()` needed no change; it already reads the
  map.
- `GRAPH_VERSION` raised 3 → 4, with a docstring comment recording why.
  `_is_valid_cache()` in `service/sql_cache_store.py` already rejects a
  graph whose `graph_version` doesn't match, so this alone forces a rebuild
  of every stored cache. Raised once, per decision 5 — ticket 02 lands under
  the same version.
- Temporary tables were not touched — decision 2 in the spec confirms they
  stay in the graph; the dangling-id repair alone resolves their ids too.
- Tests added:
  - `tests/test_sql_execution_graph.py`:
    `test_referenced_node_id_resolves_despite_a_case_variant_first_reference`
    (upper/lower `VQM` write) and
    `test_write_to_real_table_survives_a_case_variant_read_through_a_temp_table`
    (`#TempStage` created, then read back as `#tempstage` inside the same
    write operation — the same shape that made `#Order`/`#tmpPart` the two
    largest dangling-id sources in the PUR cache).
  - `tests/test_graph_reverse_lookup.py`: the same two shapes repeated at the
    analyst-facing seam the spec calls for —
    `analyze_service.find_by_table()` — via
    `test_find_by_table_reports_writes_regardless_of_stored_procedure_case`
    and
    `test_find_by_table_keeps_a_real_write_behind_a_case_variant_temp_table_read`.
    Both build their graph with `build_sql_execution_graph()` from real
    stored-procedure text (not a hand-written graph dict), per the spec's
    testing decisions.
  - `tests/sql_cache_fixtures.py`: added
    `assert_relationships_resolve_to_known_nodes()`, the shared structural
    invariant. Wired into every existing graph-building test in
    `tests/test_sql_execution_graph.py` and
    `tests/test_nested_sql_execution_paths.py`, not only the two new
    fixtures above.
  - `tests/test_sql_execution_graph.py::test_sql_cache_rejects_stale_graph_version`
    updated to assert `GRAPH_VERSION == 4` and reworded — it was pinned to
    "3" by name.
- Full suite: `pytest tests/ --ignore=tests/test_search_roles.py
  --ignore=tests/test_sp_tables.py` → 673 passed, 12 failed. All 12 failures
  reproduce identically on the base branch with this change stashed out
  (`test_connection_tracking.py`, `test_csharp_analysis_gateway.py` ×3,
  `test_external_wrapper_discovery.py` ×3, `test_formal_output_migration.py`,
  `test_graph_reverse_lookup.py::test_wrapper_projection_matches_analyze_and_reverse_lookup_surfaces`,
  `test_mvc_project_scan.py`, `test_program_refresh.py` ×2) — none touch this
  ticket's files. The two ignored files fail to collect on this machine for
  lack of an installed ODBC driver, also pre-existing.
  Spec-listed must-keep-passing files (`test_graph_queries.py`,
  `test_execution_path_builder.py`,
  `test_derived_execution_evidence_reuse_table.py`,
  `test_table_reverse_lookup_traffic_record.py`, `test_sql_cache_store.py`):
  110 passed.
- `/code-review` was not run: the `mattpocock-skills:code-review` skill is
  disabled for model invocation in this session's `skillOverrides` setting.
  Flag this to a human reviewer before merge.
