# A Temp Table Belongs to the Procedure That Uses It

**Status:** Accepted
**Date:** 2026-09-29

## Context

The SQL Execution Graph gave one node to each temp table name in a Database. The node id of `#tmp` was the same in every stored procedure, so hundreds of unrelated procedures that each use `#tmp` joined one node.

The temp table lineage expansion then walked every path. For each read of a temp table, it walked back through every writer of the node, then through every temp table read of each writer, to a depth of 32. It kept no result. The work grew as K to the power L, where K is the number of procedures that share a name and L is the length of the temp table chain. A synthetic graph with K = 40 and L = 4 took more than 60 seconds. The PUR refresh never passed the graph stage.

The shared node also gave wrong answers. A read of `#tmp` in one procedure received the base tables of every unrelated procedure that writes a `#tmp`.

A real temp table belongs to one session. A session is one call tree. A procedure and its callees see the same `#tmp`. Two procedures with no call between them do not.

## Decision

### Temp Table Scope

A temp table is a table-like name that starts with one `#` and not with `##`. Each temp table gets one node for each module that uses it. The node id holds the plain table id and the id of the owning module. The node gains a `scope_module_id` field. The node keeps its written name in `name`. The node lookup key holds the scope, and it stays case-insensitive.

A global temp table (`##name`) keeps one node for the Database, because it crosses sessions. A table variable and a CTE do not change.

The graph format version rises. Every graph with shared temp table nodes is rejected until an operator rebuilds it.

### Call visibility

A temp table read resolves to base tables through the writers in its own module. It also resolves through the writers in modules that share its session by a call: the callers and the callees.

One helper decides which module node a calls relationship names. A call to a module that the graph does not define adds no lineage. The expansion reads calls only through this helper.

### Direction rule

A resolution that goes up to a caller can only go up again or stay in a module. A resolution that goes down to a callee can only go down again or stay in a module. Up then down, or down then up, is not allowed. Ancestors and descendants stay transitive.

Without this rule, two callers of one shared procedure join their temp tables through that procedure. The shared procedure is a callee of both. A resolution that goes up to A and then down to B would give A's `#tmp` the base tables of B.

A temp read inside a visible writer keeps the direction of the state that reached the writer. This choice loses one case: a callee writer that reads a temp table only the caller created, when the reach went down. The alternative would let a down reach turn up inside the callee, and that would join the siblings again.

### No shadowing detection

[ADR-0043](0043-a-select-into-temp-table-shadows-the-callers-temp-table.md) changes this section for a `SELECT ... INTO #name` that is in no branch. This section still applies to `CREATE TABLE #name`.

The expansion does not detect shadowing. The analyzer does not report `CREATE TABLE #name`, so the graph cannot tell whether a callee created its own `#tmp` and hid the caller's. The expansion takes the union of the visible writers. This over-reports on purpose. [ADR-0012](0012-object-location-index-authoritative-pruning.md) already prefers an over-report to a lost read.

Do not remove this over-report as a defect. A callee that creates its own `#tmp` adds the base tables of the caller's `#tmp` to the callee's read. That extra table is a known cost of this decision.

### Expansion

The expansion builds states. A state is a pair of a scoped temp node and a direction (none, up, or down). A worklist fixed point merges base table sets along the edges between states. The result does not depend on the visit order. A cycle gives a stable result. No depth limit is needed, and the cost grows about linearly with the graph.

Each derived reads relationship keeps `confidence: "proven"`. Its `lineage` field holds the chain of scoped temp node ids from the read to the base read. Each base table keeps the server and the database that its base read stated.

## Rejected alternative

[ADR-0043](0043-a-select-into-temp-table-shadows-the-callers-temp-table.md) detects shadowing from the `SELECT_INTO` operation that the graph already holds. It needs no analyzer change. The rejection below still applies to `CREATE TABLE #name`.

**Report `CREATE TABLE #name` in the analyzer.** With this fact, the graph could detect that a callee created its own `#tmp`, and the expansion could stop at that callee. This change needs an analyzer change, a new cache refresh for every Database, and a new graph field. It also does not cover `SELECT ... INTO #name` in every form. The over-report costs one extra base table in a rare pattern. The analyzer change stays a separate issue.

## Consequences

- An analyst sees a read of `#tmp` resolve only to tables that reach `#tmp` in the same procedure or in a procedure that shares its session.
- A "parent creates, child reads" pattern and a "parent creates, child fills" pattern keep their lineage.
- The PUR refresh passes the graph stage. The expansion reports its own progress stage, `lineage`.
- A `##name` global temp table does not change.
- Step 2b of canonical-object-identity starts from this graph version. Its node lookup must keep the scope of a scoped temp node. The calls helper is the one site that changes the call target rule.
- ADR-0033, ADR-0034, and ADR-0035 stay reserved for canonical-object-identity ticket 12.
