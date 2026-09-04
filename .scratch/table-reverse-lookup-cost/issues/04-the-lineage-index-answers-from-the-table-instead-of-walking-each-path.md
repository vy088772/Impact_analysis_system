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

**Status:** done

- [x] The index maps each table in the graph to the terminal operations that
      reach it, built in one pass.
- [x] A path is matched by testing its terminal operation against that entry,
      with no per-path graph walk.
- [x] Asking two tables in one request builds the index once and returns each
      table's own records.
- [x] A table reached only through a View is still reported.
- [x] A table reached through two levels of View is still reported.
- [x] A table reached only through a Function is still reported.
- [x] A cycle among Views or Functions terminates instead of looping.
- [x] A dynamic-SQL path and a non-proven path stay excluded.
- [x] The read lineage still infers no writes.
- [x] Every existing test in the graph query suite passes unchanged.

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

## Implementation note

`service/graph_queries.py`: ticket 03's `_LineageIndexData`/`_LineageIndex`
pair (raw `nodes`/`reads_by_source`/`contains_by_source` dictionaries, walked
forward once per path with a per-path `visited` set) is replaced by a
`_LineageIndex` whose `_ensure_built()` inverts the graph once into
`operations_by_table: dict[str, dict[str, list[str]]]` -- normalized table
name -> {terminal `operation_id`: raw names reached}. `read_lineage(path,
target_name)` is now two dict lookups (`operations_by_table[target_name]`,
then `[operation_id]`), not a walk.

The inversion is a two-stage build, not a single forward BFS per table:

1. **Container graph.** For every View/Function, its child operations' own
   `reads` targets are classified into `direct_tables[container]` (tables
   read directly) and `successors[container]` / `predecessors[container]`
   (edges to/from other containers those children read).
2. **Worklist fixed point** over that container graph: each container starts
   at its own `direct_tables` and grows by folding in each successor's set,
   requeuing predecessors whenever a container's own set grows, until a
   round adds nothing. This is what makes a cycle among Views or Functions
   terminate -- the table universe is finite and each step only adds names,
   so the fixed point is reached, not looped past.
3. Every operation with `reads` edges (a path's own terminal operation, or
   one nested inside a container) then resolves in one hop: a table target
   counts directly, a container target counts via its now fully-resolved
   `reachable` entry.

An earlier version of step 2 used per-container recursive memoization with
an "in-progress" cycle guard instead of a worklist. `/code-review`'s Spec
pass caught that this version was wrong, not just less general: memoizing a
container's result the first time it finishes computing -- while it was
itself nested inside an ancestor's in-progress guard -- could cache a
*stunted* answer (a branch cut short by the guard), and a later, unrelated,
non-cyclic caller reaching that same container would silently inherit the
stunted answer instead of the full one. This is order-dependent on
relationship insertion order, so it would not have shown up reliably by
chance. `test_query_table_accesses_read_lineage_survives_a_shared_cyclic_view`
pins this exact shape (two independent stored procedures, one reaching a
table only through the side of a cycle that finishes computing second) and
was confirmed to fail against the recursive-memo version before the fixed
point replaced it.

`_merge_reachable` (module-level, used by both the container fixed point and
the final per-operation resolution) now returns whether it added anything,
so the worklist knows when to requeue. `_add_table_name` was pulled out to
remove the "append a raw name under its normalized key if not already
present" idiom that had drifted into three separate call sites. `_TableNames
= dict[str, list[str]]` names the recurring shape (normalized table name ->
raw names seen for it) that both the per-container and per-operation maps
share.

`test_query_table_accesses_resolves_view_read_lineage_without_writer`
(ticket 03's pin) keeps passing unmodified. Four new tests cover the
checklist's remaining cases: two levels of View, Function-only lineage, the
shared-cycle regression above, and two tables asked in the same graph
returning only their own records.

Cross-call reuse (a second table asked via a separate
`filter_table_accesses`/`query_table_accesses` call, same graph) is not
cached beyond one call -- `filter_table_accesses` still constructs one
`_LineageIndex` per call, as ticket 03 left it. Spec review confirmed this
matches scope: spec.md's testing note says neither test asserts a
dictionary was built once ("that is the implementation of the saving and
not the saving itself"), and the checklist's "one build" requirement is
satisfied within a call by the index covering every table, not by adding
cross-call caching -- which would need an identity-based cache keyed on the
graph object, a pattern this same spec's ticket 05 is written to retire
elsewhere, not to add here.

Verified: `pytest tests/test_graph_queries.py` -- 10 passed (the 6 from
ticket 03 plus 4 new), including the ticket-03 pin unmodified (`git diff
be81c2c -- tests/test_graph_queries.py` shows only additions after that
pinned test). Full suite (`pytest`, excluding the four files that need a
live ODBC connection this environment doesn't have): 628 passed, the same
12 pre-existing failures as on `be81c2c` (confirmed by stashing this diff
and rerunning) -- none in `service/graph_queries.py` or its tests.

Reviewed with `/code-review` (fixed point: `be81c2c`, ticket 03's commit)
before commit. Standards axis: no documented coding standard in this repo
to violate (`AGENTS.md` only documents issue-tracker/domain-doc layout);
two Fowler-baseline judgement calls were raised (Primitive Obsession on the
bare `dict[str, dict[str, list[str]]]` shape, and minor Duplicated Code in
the "add a unique name" idiom) and both were fixed (`_TableNames` alias,
`_add_table_name` helper) before this note was written. Spec axis: found
the recursive-memoization cycle bug described above, which was fixed with
the worklist redesign and pinned with the new regression test before this
note was written; no other missing requirements or scope creep found.
