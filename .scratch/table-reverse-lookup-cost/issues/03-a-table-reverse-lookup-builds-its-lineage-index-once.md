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

**Status:** ready-for-agent

- [ ] The lineage index is built at most once for each table reverse lookup.
- [ ] A lookup that never reaches the read branch builds no index at all.
- [ ] The lineage resolution reads only the index it is given, not the graph.
- [ ] The index and the graph it was derived from are passed together, so a
      caller cannot pair an index with a different graph.
- [ ] A table reached only through a View is still reported.
- [ ] A table reached through two levels of View is still reported.
- [ ] A table reached only through a Function is still reported.
- [ ] A dynamic-SQL path and a non-proven path stay excluded.
- [ ] Write matching is unchanged; the read lineage still infers no writes.
- [ ] Every existing test in the graph query suite passes unchanged.

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
