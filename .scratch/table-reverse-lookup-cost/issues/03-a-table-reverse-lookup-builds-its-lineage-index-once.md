# 03 — A table reverse lookup builds its lineage index once for each request

**What to build:** A table reverse lookup that resolves View and Function reads
without rebuilding the same lookup structure for every Execution Path it
examines. The analyst gets the same records as before, and gets them without
waiting for the same index to be built thousands of times.

Today the lineage resolution builds four dictionaries from the SQL Execution
Graph at the top of every call, and it is called once for each Execution Path
that reaches the read branch. One measured scope holds 3,719 Execution Paths,
2,969 of which reach that branch. Each rebuild costs about 17 milliseconds, so
one lookup pays 51 to 54 seconds building the same thing repeatedly. The
dictionaries depend on neither the path nor the table name, so every rebuild
produces the same result.

The index moves out of the loop. The caller builds it and hands it to the
lineage resolution, which stops reading the graph directly. The graph and the
index must travel together, so the signature shows that they are one pair.

The index is built on first use inside the request. A lookup whose matches are
all direct never reaches the read branch, and it must keep paying nothing.

This ticket changes no answer. Every record a lookup returns is identical,
field for field. It is the safe half of the saving, and its result is the raw
material ticket 04 inverts.

**Blocked by:** 02 — The routing baseline is recorded before the first
performance change.

**Status:** done

- [x] The lineage index is built at most once for each table reverse lookup.
- [x] A lookup that never reaches the read branch builds no index at all.
- [x] The lineage resolution reads only the index it is given, not the graph.
- [x] The index and the graph it was derived from are passed together, so a
      caller cannot pair an index with a different graph.
- [x] A table reached only through a View is still reported.
- [x] A table reached through two levels of View is still reported.
- [x] A table reached only through a Function is still reported.
- [x] A dynamic-SQL path and a non-proven path stay excluded.
- [x] Write matching is unchanged; the read lineage still infers no writes.
- [x] Every existing test in the graph query suite passes unchanged.

## Notes

Seam: `query_table_accesses(graph, invocations, table_name, access=...)`, where
`tests/test_graph_queries.py` already asserts on returned access records. Do
not add a seam below it.

`test_query_table_accesses_resolves_view_read_lineage_without_writer` pins the
exact path this ticket rewrites. It must keep passing without modification. If
it needs editing, the change altered behaviour and the ticket is wrong.

Do not assert that the index was built once. That is the implementation of the
saving, not the saving. The observable claims are the returned records and,
in ticket 09, the measured seconds.

The forward walk follows `reads` relationships only and treats a table node as
terminal. Keep both rules. Inferring writes here would turn a Possible Writer
into a Proven Writer.

## Implementation note

`service/graph_queries.py`: the module-level `_matching_graph_read_lineage`
function -- which rebuilt the `nodes` / `reads_by_source` / `contains_by_source`
dictionaries from `graph` on every call -- is replaced by a `_LineageIndex`
class. `filter_table_accesses` holds one local `lineage_index: _LineageIndex
| None = None` for the whole call and constructs it lazily, only the first
time a path falls through to the lineage branch (no direct `reads` match);
every later path in the same call reuses that one instance. A lookup that is
`access="write"`, or where every match is direct, never constructs one.

`_LineageIndex(graph)` stores the graph itself, not just its derived
dictionaries, so `read_lineage(path, target_name)` -- the method the
per-path loop calls -- takes no `graph` parameter at all; there is no
signature through which a caller could hand it a different graph's index.
The three built dictionaries are bundled into one `_LineageIndexData`
NamedTuple returned by `_ensure_built()`, rather than three parallel
`Optional` fields on the instance, so there is a single built/not-built
state instead of three fields whose nullness has to stay in lockstep.

The forward-walk algorithm inside `read_lineage` is a verbatim move of the
old function's body -- same BFS over `reads` then `contains` edges, same
table-terminal rule, same target-name match. No ticket 04 work (inverting
the index to answer from the table instead of walking each path) is
included here.

Verified: `pytest tests/test_graph_queries.py` -- 5 passed, including
`test_query_table_accesses_resolves_view_read_lineage_without_writer`
unmodified (`git diff HEAD -- tests/test_graph_queries.py` shows no diff).
Full suite (`pytest`, excluding the two files that require a live ODBC
connection this environment doesn't have): 636 passed, the same 12
pre-existing failures as on HEAD before this change (confirmed by running
the same command against a stash of the diff) -- none in
`service/graph_queries.py` or its tests.

Reviewed with `/code-review` (fixed point: HEAD, `03f0419`) before commit.
Spec axis: all ten checklist items satisfied, no scope creep into ticket
04's territory. Standards axis: no documented standard in this repo to
violate; one Fowler-baseline judgement call (Data Clumps: three parallel
`Optional` fields) was raised and fixed by introducing `_LineageIndexData`
before this note was written.
