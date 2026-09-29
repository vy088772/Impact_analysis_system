# A Temp Table Belongs to the Procedure That Uses It

Status: ready-for-agent

This spec must land before `.scratch/canonical-object-identity/` ticket 11
(Step 2b) can start. Ticket 11 waits for an operator to refresh five caches,
PUR among them. The refresh of PUR never ends because of the defect below. The
graph repair tool builds the graph with the same function, so it never ends
either.

## Problem Statement

An operator runs the SQL refresh for PUR. The progress bar for the SQL
Execution Graph reaches 1697 of 1697 modules after 25 minutes. After that, the
terminal shows no change. The cache write stage never starts, and the command
never prints its result. After 30 minutes the client times out and reports that
it cannot reach the Impact service, but the service still runs.

Two defects cause the stop:

- **The graph holds one temp table node for each temp table name in the whole
  Database.** The node identity of `#tmp` is the same in every stored
  procedure. Hundreds of unrelated procedures that each use `#tmp` join one
  node.
- **The temp table lineage expansion enumerates every path.** For each read of a
  temp table, the expansion walks back through every writer of that node, then
  through every temp table read of each writer, to a depth of 32. It keeps no
  result that it already computed. The work grows as K to the power L, where K
  is the number of procedures that share a temp table name and L is the length
  of the temp table chain.

A measurement on a synthetic graph shows the growth:

| Procedures that share names (K) | Chain length (L) | Seconds |
|---|---|---|
| 10 | 3 | 0.027 |
| 10 | 4 | 0.369 |
| 10 | 5 | 3.193 |
| 20 | 4 | 8.115 |
| 40 | 4 | more than 60 |

The expansion also reports no progress, so the operator cannot see that the
service still works.

The shared node also gives wrong answers when the expansion does end. A read of
`#tmp` in one procedure receives the base tables of every unrelated procedure
that writes a `#tmp`.

## Solution

Each `#name` temp table becomes one node for each procedure that uses it. A
temp table read resolves to base tables through the writers in its own
procedure, and through the writers in procedures that share its session by a
call: its callers and its callees. The expansion computes each result once, so
its cost grows about linearly with the graph. The expansion reports its own
progress stage, and the refresh command shows a label for it.

After the change, the PUR refresh passes the graph stage, writes the cache, and
prints its result.

## User Stories

1. As an operator, I want the PUR refresh to finish, so that I can copy the refreshed cache and meet the Step 2a gate.
2. As an operator, I want every Database refresh to finish in a time that grows with the number of modules, not with the number of procedures that share a temp table name, so that a large Database does not stop a refresh.
3. As an operator, I want the refresh command to show a progress stage for the temp table lineage expansion, so that I can see that the service still works after the graph stage reaches 100%.
4. As an operator, I want the lineage stage to have a readable label in the refresh command, so that I do not see an internal stage key.
5. As an operator, I want the graph repair tool to finish on PUR, so that I can rebuild an old graph without a connection to SQL Server.
6. As an analyst, I want a read of `#tmp` in one procedure to resolve only to tables that reach `#tmp` in that procedure or in a procedure that shares its session, so that an impact answer does not list tables of an unrelated procedure.
7. As an analyst, I want a procedure that creates `#tmp` and then calls a child procedure that reads `#tmp` to show the child's read as a read of the parent's source tables, so that a "parent creates, child reads" pattern stays in the answer.
8. As an analyst, I want a parent procedure that reads `#tmp` after a call to a child procedure that fills `#tmp` to show the parent's read as a read of the child's source tables, so that a "parent creates, child fills" pattern stays in the answer.
9. As an analyst, I want a temp table visible through a chain of calls (A calls B, B calls C) to resolve across the full chain, so that a deep call tree keeps its lineage.
10. As an analyst, I want two procedures that call the same shared procedure to stay separate, so that the shared procedure does not join their temp tables.
11. As an analyst, I want a global temp table (`##name`) to stay one node for the whole Database, so that a table that really crosses sessions keeps its real scope.
12. As an analyst, I want a temp table read to keep the database and server that the base read stated, so that a cross-Database base table stays correct.
13. As an analyst, I want a lineage read that crosses a call to carry the chain of temp table nodes it passed through, so that I can trace why the read exists.
14. As an analyst, I want a temp table to keep its written name, such as `#tmp`, in every answer, so that the name I see matches the SQL text.
15. As an analyst, I want the Object Location Index to keep the same temp table names as before, so that `/locate_object` does not change for a temp table name.
16. As an analyst, I want a recursive call or a cycle of temp table writes to give one stable result, so that two refreshes of the same Database give the same graph.
17. As an analyst, I want a call to a procedure that the graph does not define to add no temp table lineage, so that a guess does not enter the graph.
18. As a maintainer, I want the graph format version to rise, so that every graph with shared temp table nodes is rejected until it is rebuilt.
19. As a maintainer, I want one helper to decide which module a calls relationship names, so that Step 2b changes that rule in one place.
20. As a maintainer, I want the scoped node's lookup key to contain its scope, so that the node lookup does not merge two scoped nodes back into one.
21. As a maintainer, I want the scoped node identity to come from the same node identity function as every other node, so that Step 2b changes the schema default in one place.
22. As a maintainer, I want an ADR that records the scope rule, the call visibility rule, the direction rule, and the decision to not detect shadowing, so that nobody removes the over-report as a defect.
23. As a maintainer, I want a glossary entry for Temp Table Scope, so that every document uses one term.
24. As a maintainer, I want a regression test that proves the expansion finishes on a graph where many procedures share temp table names, so that the exponential growth cannot return.
25. As a maintainer, I want the tests to build payloads from the shared test fixture module and read the graph version from its constant, so that this spec obeys the canonical-object-identity rules.
26. As a maintainer of canonical-object-identity, I want ticket 11 to state that the graph version starts at the new value and that scoped temp nodes exist, so that Step 2b does not assume the old node shape.

## Implementation Decisions

### Temp Table Scope

- A temp table is a table-like name that starts with one `#` and not with `##`.
- Each temp table gets one node for each module that references it. The node
  identity holds the plain table identity and the identity of the owning
  module. The node keeps `type: "table"` and keeps the written name in `name`.
  The node gains a `scope_module_id` field that names the owning module.
- The scoped identity is built from the node identity function that builds
  every other node. It does not write `dbo` directly.
- The node lookup key of a scoped node contains the scope. Two modules that use
  `#tmp` produce two nodes. One module that writes `#Tmp` and reads `#tmp`
  still produces one node, because the lookup stays case-insensitive.
- A global temp table (`##name`) keeps one node for the whole Database, as today.
- A table variable and a CTE do not change.

### Call visibility

- One helper resolves the target of a calls relationship to a module node that
  the graph defines. A calls relationship to a module that the graph does not
  define (another Database, a missing definition, dynamic SQL) resolves to
  nothing. The temp table expansion reads calls only through this helper.
- Session sharing follows calls relationships in two directions: up to callers
  and down to callees.
- Direction is monotonic. A resolution that goes up can only go up again or stay
  in a module. A resolution that goes down can only go down again or stay in a
  module. Up then down, or down then up, is not allowed. This rule stops two
  callers of one shared procedure from joining their temp tables. Ancestors and
  descendants stay transitive.
- The expansion does not detect shadowing. The analyzer does not report
  `CREATE TABLE`, so the graph cannot tell whether a callee created its own
  `#tmp`. The expansion takes the union of the visible writers. This choice
  over-reports on purpose, which ADR-0012 already prefers to a lost read.

### Expansion algorithm

- The expansion builds a graph of states. A state is a pair of a scoped temp
  node and a direction (none, up, or down).
- The base tables of a state are the non-temp reads of every visible writer of
  that state. A temp read of a visible writer adds an edge to another state.
- A worklist fixed point merges base table sets along those edges until no set
  changes. This is the same pattern the lineage index in the graph query module
  uses. The result does not depend on visit order, a cycle gives a stable
  result, and no depth limit is needed.
- Each base table in a result keeps the server and database that its base read
  stated.
- Each derived reads relationship keeps `confidence: "proven"`. Its `lineage`
  field holds the chain of scoped temp node identities from the read to the base
  read.
- The expansion reports progress under a new stage key, `lineage`. The refresh
  command in `llamaindex-spec-rag` gains a label for that key.

### Versions and documents

- The graph format version rises by one. The version comment states the scoped
  node identity and the new expansion. Every graph on disk is rejected until the
  operator refreshes it or the repair tool rebuilds it.
- The SQL cache format version does not change.
- ADR-0036 records Temp Table Scope. ADR-0033, ADR-0034, and ADR-0035 stay
  reserved for canonical-object-identity ticket 12.
- `CONTEXT.md` gains a Temp Table Scope entry under SQL Execution Analysis.
- The Notes of canonical-object-identity ticket 11 gain one line: Step 2b
  starts from the new graph version, the node lookup must keep the scope of a
  scoped temp node, and the calls helper is the one site that changes the call
  target rule.

## Testing Decisions

- A good test drives the graph builder with a module payload and asserts on the
  returned graph: its nodes, its relationships, and the progress reports. It
  does not call the private expansion function, and it does not assert on
  private data structures.
- The one seam is the graph builder. It already accepts a host and a progress
  callback. A fake host returns operations built with the shared fixture's
  operation helper, so a test does not start the analyzer host. One test uses
  the real host to prove the `SELECT ... INTO #name` path end to end.
- Payloads come from the shared test fixture module. The graph version comes
  from the graph module's constant.
- Write each test first. Watch it fail. Then change the code.

Test cases:

1. **Cost.** Forty procedures each run the chain `#t1` to `#t4`. The build ends
   in a few seconds, and each procedure's final read resolves only to its own
   base table.
2. **Isolation.** Two procedures with no call between them both write and read
   `#tmp`. Each read resolves only to its own procedure's base table.
3. **Caller to callee.** A writes `#tmp` from a base table and calls B. B reads
   `#tmp`. B's read resolves to A's base table.
4. **Callee to caller.** A calls B. B writes `#tmp` from a base table. A reads
   `#tmp`. A's read resolves to B's base table.
5. **Siblings.** A and B both call U. A, B, and U all use `#tmp`. A's read never
   resolves to B's base table.
6. **Transitive chain.** A calls B, B calls C. A writes `#tmp`. C reads `#tmp`.
   C's read resolves to A's base table.
7. **Cycle.** A calls B and B calls A, and both write and read `#tmp`. The build
   ends, and two builds give the same relationships.
8. **Global temp table.** Two procedures with no call between them use `##g`.
   They share one node, as today.
9. **Undefined callee.** A calls a procedure that the graph does not define. The
   call adds no lineage.
10. **Node shape.** A scoped node keeps `name` as written and carries
    `scope_module_id`. Every relationship resolves to a known node.
11. **Progress.** The progress callback receives the `lineage` stage after the
    last `graph` report and before the builder returns.
12. **Refresh label.** In `llamaindex-spec-rag`, the refresh command maps the
    `lineage` stage key to a readable label.

Prior art: the graph tests that already cover temp table reads, case-variant
temp tables, and the database a base read stated; the lineage index tests in
the graph query module; the repair tool tests that rebuild a graph from cached
definitions.

## Out of Scope

- The refresh client's timeout message. It reports "cannot connect" when the
  service still runs. A separate issue handles it.
- Shadowing detection. That needs the analyzer to report `CREATE TABLE #name`.
  A separate issue handles it.
- The Step 2b schema rule for node identity and call targets. Ticket 11 of
  canonical-object-identity handles it.
- A new `confidence` value for a lineage read that crosses a call.
- Temp tables inside dynamic SQL.

## Further Notes

Order of work:

1. This spec lands in this repository and in `llamaindex-spec-rag`.
2. The operator deploys both repositories to the refresh machine.
3. The operator refreshes the five caches with the new code and copies them
   here. The new graph version on disk confirms the copy.
4. canonical-object-identity ticket 11 starts.

Acceptance on real data:

1. `refresh_sql_cli PUR` reaches the cache write stage and prints its result.
2. The `lineage` stage on PUR ends in 30 seconds or less.
3. From the new PUR cache, pick the two or three temp table names that the most
   procedures share. For each, a `/find_by_table` answer lists no unrelated
   procedure, and it keeps the base tables of a "parent creates, child fills"
   pattern.

The synthetic measurement script from the diagnosis is not part of the
repository. Test case 1 replaces it.
