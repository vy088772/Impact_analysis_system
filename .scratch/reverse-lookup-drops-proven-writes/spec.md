# A Reverse Lookup Reports Every Proven Writer It Found

Status: ready-for-agent

The measurement behind this spec lives in the companion repository, at
`llamaindex-spec-rag/.scratch/first-round-exact-lookup-misses/`. Read it before
you change any count in this document.

This spec uses this repository's Evidence Status vocabulary — `proven`,
`likely`, `unresolved`, `not_applicable`. The companion repository calls a
non-proven writer a **Possible Writer**. That is its word, not this
repository's. ADR-0007 records why the two must not be mixed.

## Problem Statement

An analyst asks which programs write one database table. The service answers
with a short list. The list is missing programs that write that table.

The missing programs are not guesses. Their C# calls are `proven` Database
Invocations. Their stored procedures hold literal `INSERT` and `UPDATE`
statements against the table. The SQL Execution Graph holds the `writes`
relationship. Every piece of evidence exists, and the answer still omits them.

Six measured questions in the companion repository miss seven required programs
in one mode and eight in the other. All of them trace to the same cause.

The analyst cannot see that anything is missing. The response looks like a
complete answer.

### The cause

`_ensure_referenced_node()` in `service/sql_execution_graph.py` returns an
object id that names no node.

`_node_key()` compares an object name without case. `_node_id()` builds an id
with case. The first reference to `dbo.VQM` creates a node with the id
`table:dbo.VQM`. A later reference to `dbo.vqm` matches the same key, so
`_add_node()` keeps the first node and adds nothing. `_ensure_referenced_node()`
then returns `table:dbo.vqm`, the id of the node it did not add.

The PUR cache holds 87 such ids across 6,206 relationships. Every one of the 87
has a case variant that does exist. No node is missing.

### Why one bad id removes a proven write

`_build_path()` in `service/execution_path_builder.py` resolves each
relationship target against the node map. An id that resolves to nothing joins
`missing_targets`. Any entry in `missing_targets` sets the whole Execution Path
to `unresolved`.

`missing_targets` joins the missing reads and the missing writes. One unresolved
read therefore unresolves a proven write in the same operation.

`filter_table_accesses()` in `service/graph_queries.py` then requires
`evidence == "proven"`. An Execution Path that fails this test produces no
access record at all. The proven write disappears with it.

The PUR cache holds 2,919 DML operations that write a real table. 272 of them —
9.3 percent — carry at least one unresolvable id.

### A second, independent loss

`_prefer_table_match()` in `service/analyze_service.py` keys its result by file.
One program keeps one access fact for one table, whatever paths reached it.

One program that reads a table through one stored procedure and writes it
through another reports only the write. The read disappears. This contradicts
Path-scoped Writer Evidence, which the companion repository's glossary defines
as evidence that must stay tied to one Execution Path.

## Solution

The reverse lookup keeps every access fact it proved, and it names every fact it
could not prove.

An analyst who asks which programs write a table receives every program the
graph proves. An analyst who asks which programs touch a table also receives the
paths that stayed `unresolved`, each with the reason it stayed unresolved. The
analyst can tell "no program does this" apart from "the service could not prove
it".

One program that reaches one table through several stored procedures reports one
row for each path, not one row for the program.

## User Stories

1. As an analyst, I want the reverse lookup for a table to list every program
   whose stored procedure writes that table, so that I can plan a schema change
   against the real set.
2. As an analyst, I want a stored procedure that writes `VQM` in lower case to
   count the same as one that writes `VQM` in upper case, so that source
   formatting never changes my answer.
3. As an analyst, I want a temporary table in a stored procedure body to leave
   the procedure's real writes intact, so that a scratch table cannot hide a
   production write.
4. As an analyst, I want an unresolvable read to leave the proven writes of the
   same operation intact, so that one unknown does not erase a known.
5. As an analyst, I want an Execution Path that the service cannot prove to
   appear in the response with its Evidence Status, so that I know it exists.
6. As an analyst, I want that path to carry the reason it is unresolved, so that
   I can tell Unresolved Dynamic SQL apart from a graph defect.
7. As an analyst, I want `write_only` to return only `proven` writes, so that a
   write list stays a list of facts.
8. As an analyst, I want the count of paths that `write_only` excluded, so that
   a short list never reads as a complete list.
9. As an analyst, I want one program that writes a table through two stored
   procedures to appear twice, so that I can review each path.
10. As an analyst, I want one program that reads and writes the same table to
    report both facts, so that a write never hides a read.
11. As an analyst, I want two paths that differ only in their entry method to
    stay separate, so that I can find the screen that triggers each one.
12. As an analyst, I want two identical paths to appear once, so that the
    response does not repeat one fact.
13. As a developer, I want every relationship in a stored SQL Execution Graph to
    name a node that exists, so that this class of defect fails a test instead
    of reaching an analyst.
14. As a developer, I want a graph built before this change to be rejected as
    invalid, so that no analyst reads an answer from a graph that holds bad ids.
15. As a developer, I want `find_by_sp` and `find_by_table` to agree about which
    programs reach one stored procedure, so that two lookups of the same fact
    cannot disagree.
16. As a maintainer, I want the decision to retain unresolved paths recorded as
    an ADR, so that a future reader does not restore the deletion.
17. As a maintainer, I want the decision to key deduplication by path recorded as
    an ADR, so that a future reader does not restore the per-file key.
18. As a maintainer, I want the temporary-table lineage expansion to keep
    working, so that a read through a scratch table still resolves to its base
    table.
19. As an operator, I want one cache rebuild to deliver all three changes, so
    that I rescan five databases once and not three times.
20. As an operator, I want the response size measured before and after the
    deduplication change, so that a larger response cannot silently break the
    Answer Latency target.

## Implementation Decisions

### 1. `_ensure_referenced_node()` returns the id of the node that survives

`_add_node()` already keeps one node for one case-insensitive key. Change
`_ensure_referenced_node()` to return that node's id.

The simplest form makes `_add_node()` return the node it kept, and
`_ensure_referenced_node()` returns that node's id. Do not change `_node_key()`.
Do not change `_node_id()`. Both are correct as they stand.

Apply the same rule to every other caller that builds an id and then adds a
node. `_known_object_node_id()` already reads the map, so it is correct.

### 2. Temporary tables stay in the graph

Do not filter temporary tables out of the graph. `_expand_temp_table_lineage()`
walks a temporary table's writers back to its base tables, and it produces
78,200 lineage relationships in the PUR cache. A temporary table is a load-
bearing node.

`table:dbo.#Order` and `table:dbo.#tmpPart` dangle for the same case reason as
every other dangling id. Decision 1 resolves them.

### 3. `filter_table_accesses()` downgrades a path instead of dropping it

Today the function emits nothing for an Execution Path whose evidence is not
`proven`. Change it to emit an access record for that path too.

The record carries the path's Evidence Status and its `unresolved_reason`. It
does not claim a mutation. A caller that wants only proven writes filters on
Evidence Status.

Keep the existing `access` parameter. Add a way for the caller to ask for
proven-only records, so `find_by_table(write_only=True)` keeps its present
meaning: proven writes and nothing else.

The response reports how many records the proven-only filter removed. A caller
that hides unresolved paths must still be able to say how many there were.

### 4. The deduplication key becomes the Execution Path identity

`_prefer_table_match()` keys by file. Change the key to the identity that the
companion repository's glossary calls Writer Evidence Identity: program, file,
`path_id`, entry method, stored-procedure chain, and access type.

This is not the removal of deduplication. Two identical paths still collapse to
one record. Two paths that differ in any of those parts stay separate.

Measure the record count for one table before and after this change. The PUR
graph holds 962 DML operations that touch `Quotation` across 310 stored
procedures, so the count can grow by more than one order of magnitude if the key
is too fine. Record the measured numbers in the issue before you close it.

### 5. `GRAPH_VERSION` moves from 3 to 4

A graph built before decision 1 holds relationship targets that name no node.
`_is_valid_cache()` in `service/sql_cache_store.py` already rejects a graph whose
`graph_version` does not match. Raising the constant therefore invalidates every
stored cache and forces a rebuild.

Land all three changes under one version rise. Do not raise it three times.

### 6. Response contract

`TableMatchProgram` already carries `evidence_status`, `reason`, `path_id`,
`entry_method` and `sp_chain`. No new field is required for decision 3 or
decision 4.

The consumer in `llamaindex-spec-rag` does not copy `evidence_status` today.
That change belongs to that repository and is out of scope here.

### 7. Two ADRs, already written

Decision 3 is recorded in
[ADR-0015](../../docs/adr/0015-an-unproven-execution-path-is-reported-not-dropped.md).
Decision 4 is recorded in
[ADR-0016](../../docs/adr/0016-a-table-match-is-deduplicated-by-execution-path-not-by-file.md).

Read both before you implement. Each one records the alternative it rejected, so
do not re-open a rejected alternative without amending its ADR.

Decision 1 is a defect repair, not a trade-off. It needs no ADR.

## Testing Decisions

A good test here states what an analyst receives, not how the service built it.
It asserts on the programs, the access types, and the Evidence Status in a
response. It does not assert on node ids, dictionary keys, or call counts.

### The one behavioural seam

Use `analyze_service.find_by_table()` and `analyze_service.find_by_sp()`. This
is the seam `tests/test_graph_reverse_lookup.py` already uses. Every one of the
three changes is visible there.

Change the fixture shape for the new cases. `tests/test_graph_reverse_lookup.py`
writes its graph dictionary by hand, so it cannot show a case defect that only
`build_sql_execution_graph()` creates. Build the graph from stored-procedure
text instead. `tests/test_sql_execution_graph.py` and
`tests/test_nested_sql_execution_paths.py` show how.

Cases to cover at this seam:

- A stored procedure writes `VQM` in upper case and reads `vqm` in lower case.
  The calling program appears with a write access type.
- A stored procedure writes a real table and reads a temporary table. The
  calling program appears with a write access type.
- A stored procedure contains Unresolved Dynamic SQL. The calling program
  appears with a non-proven Evidence Status and a reason.
- The same request with `write_only=True` omits that program and reports the
  excluded count.
- One program reaches one table through two stored procedures. Two records
  appear.
- One program reads and writes one table through two stored procedures. Both
  records appear.
- The same path reached twice produces one record.

### The one structural invariant

Add one test at `build_sql_execution_graph()`: every relationship target
resolves to a node in the same graph. This is a structural guarantee, not a
second copy of the behaviour above. It stops this class of defect returning.

Run it over the fixtures that already exist in `tests/test_sql_execution_graph.py`
and `tests/test_nested_sql_execution_paths.py`.

### Tests that must keep passing

`tests/test_graph_queries.py`, `tests/test_execution_path_builder.py`,
`tests/test_derived_execution_evidence_reuse_table.py`,
`tests/test_table_reverse_lookup_traffic_record.py`, and
`tests/test_sql_cache_store.py`.

Expect `tests/test_graph_queries.py` to need new expectations. It asserts on the
present drop behaviour, which decision 3 changes on purpose.

### Acceptance outside the unit tests

Run `refresh_sql_cli` for all five databases. Then run the deterministic reverse-
lookup baseline in the companion repository. All six table questions must find
every required program in both modes. The six stored-procedure questions must not
lose any program they find today.

## Out of Scope

- Every change in `llamaindex-spec-rag`. That includes the `SELECT_INTO` gap in
  its write-type list, copying `evidence_status` into its own record shape, and
  whether a non-proven path enters its Locked Analysis Scope.
- The silent discard of a failed or skipped System in that repository's
  `cross_system_lookup`.
- The replacement of its routing expectation generator.
- Proving Unresolved Dynamic SQL. The PUR graph holds nine such nodes. They stay
  unresolved. This spec makes them visible, not proven.
- Program name identity, such as whether an expectation names
  `pur_somaintain.aspx` or `pur_somaintain`.
- Any change to `Answer Latency` for its own sake. Decision 4 measures response
  size because it can affect latency, and that is the only latency work here.

## Further Notes

The earlier reading of this defect named three causes: a case-sensitive node id,
a missing temporary-table node, and an all-or-nothing evidence gate. The data
shows one cause and one amplifier. Every dangling id, temporary tables included,
has a case variant that exists. Decision 2 records why the temporary-table
change was dropped.

The companion repository's `context_assembly_concurrency16_candidateset` result
set is unusable for this work. Five of its six table questions ended in a 150
second workflow timeout.

### One file is under active change elsewhere

At the time of writing, `service/graph_queries.py` and
`tests/test_graph_queries.py` hold uncommitted work from
`.scratch/table-reverse-lookup-cost/`, which is rewriting `_LineageIndex` into a
table-keyed reverse index.

Decision 3 changes `filter_table_accesses()` in that same file. Read the working
tree before you start, and land after that effort or coordinate with it. The two
changes do not conflict in intent: one makes the walk cheaper, and this one stops
the walk discarding what it proved.
