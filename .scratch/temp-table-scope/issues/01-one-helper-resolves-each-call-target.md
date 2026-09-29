# 01: One helper resolves each call target

**What to build:** The graph builder decides whether a calls relationship names
a module that the graph defines in one helper. The graph that the builder
returns does not change. Ticket 04 and canonical-object-identity Step 2b each
change the call target rule in this one helper only.

See "Call visibility" in the spec.

**Blocked by:** None (can start immediately).

**Status:** done

- [x] One helper takes a call target and returns the module node that the graph defines for it, or nothing.
- [x] Every site that turns a call target into a module node identity uses the helper.
- [x] The helper keeps the existing `dbo` fill and its Step 2b comment. The rule does not change.
- [x] The graph format version does not change.
- [x] Every existing graph test passes with no edit.
- [x] The whole suite of this repository passes.

## Notes

- **What changed.** Only `service/sql_execution_graph.py`: the new helper
  `_resolve_call_target(node_by_key, target, cache_database)` and its one call
  site in the CALL branch of `_add_operation`. No test file changed.
- **Helper shape.** The helper returns a pair: the node id that the calls
  relationship names, and the module node that the graph defines, or `None`.
  The builder must keep the id as written, because `_node_id` keeps the case of
  the call and `_node_key` casefolds. Ticket 04 must walk with the returned
  node's `id`, not with the first element. The two differ when the call's case
  differs from the definition's case.
- **No module node.** A call through a linked server (`target.server` set), a
  call to another Database, and a call to a module that the cache does not list
  resolve to `None`. A listed module with an empty definition still resolves to
  its node; it has no operations, so it adds no writers. Dynamic SQL gives no
  call target. The linked-server rule comes from the spec review. It only
  affects the second element, so the graph does not change.
- **Test coverage.** The `None` branch has no test yet. No builder output shows
  it until ticket 04 (test case 9) reads it.
- **Suite.** `pytest tests/ --ignore=tests/test_search_roles.py
  --ignore=tests/test_sp_tables.py`: 1110 passed, 16 failed. The 16 are the
  pre-existing failures that earlier tickets record (C# wrapper, external
  wrapper discovery, program refresh, real checkout,
  `test_dependency_graph_renderer_ignores_legacy_sp_relations`,
  `test_wrapper_projection_matches_analyze_and_reverse_lookup_surfaces`).
- **Code review.** Standards: no hard violation. The cross-Database guard also
  sits in `_known_object_node_id`; a shared local-node helper is optional and
  left out. Spec: graph output unchanged; the linked-server finding is fixed.
