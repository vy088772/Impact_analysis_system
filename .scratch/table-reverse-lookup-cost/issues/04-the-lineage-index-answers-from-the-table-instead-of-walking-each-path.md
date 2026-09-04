# 04 — The lineage index answers from the table instead of walking each path

**What to build:** A table reverse lookup that asks the SQL Execution Graph one
question — which terminal operations reach this table — instead of asking, once
for every Execution Path, whether that path reaches the table. Each path then
costs one membership test rather than one graph walk.

Ticket 03 stopped the index being rebuilt. This ticket stops the walk itself.
The index is inverted: it maps a table to the terminal operations that reach
it, following the same `reads` and `contains` relationships the forward walk
follows today, in the opposite direction. A path matches when its terminal
operation appears in the entry for the target table.

The inversion covers every table in the graph in one build. A second table
asked in the same request therefore rebuilds nothing, which is what makes a
multi-table request cheap.

The answer does not change. The inverted index must reproduce the forward
walk's two rules exactly: it follows `reads` only, and it stops at a table
node. Write matching stays where it is, against the path's own recorded writes.

**Blocked by:** 03 — A table reverse lookup builds its lineage index once for
each request.

**Status:** ready-for-agent

- [ ] The index maps each table in the graph to the terminal operations that
      reach it, built in one pass.
- [ ] A path is matched by testing its terminal operation against that entry,
      with no per-path graph walk.
- [ ] Asking two tables in one request builds the index once and returns each
      table's own records.
- [ ] A table reached only through a View is still reported.
- [ ] A table reached through two levels of View is still reported.
- [ ] A table reached only through a Function is still reported.
- [ ] A cycle among Views or Functions terminates instead of looping.
- [ ] A dynamic-SQL path and a non-proven path stay excluded.
- [ ] The read lineage still infers no writes.
- [ ] Every existing test in the graph query suite passes unchanged.

## Notes

Seam: unchanged from ticket 03 — `query_table_accesses(...)`, asserted in
`tests/test_graph_queries.py`.

The forward walk alternates between two node kinds: an operation reads an
object, and a View or Function contains operations that read further objects.
The inversion must respect that alternation, or it will report a table that no
operation actually reaches.

Cycle safety matters more here than in the forward walk. The forward walk
visits from one starting operation and carries its own visited set; a
graph-wide inversion visits everything, so a View that reads itself through a
chain must not loop.

Do not extend the index to `writes`. Writes are matched from the path's own
recorded writes, and an index that mixed the two would let a read prove a
write.
