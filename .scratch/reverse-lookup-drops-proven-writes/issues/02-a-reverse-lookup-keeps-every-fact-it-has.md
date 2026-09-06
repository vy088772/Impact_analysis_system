# 02 — A reverse lookup keeps every fact it has

**What to build:** A reverse lookup response states everything the service
learned about one table, and it never deletes a fact to make the answer shorter.

An analyst asking which programs write a table still receives proven writes
only, and now also learns how many paths were excluded because the service could
not prove them. An analyst asking which programs touch a table receives those
paths too, each carrying its Evidence Status and the reason it stayed
unresolved. Unresolved Dynamic SQL becomes visible instead of absent — nine such
operations exist in the PUR graph and no repair will ever prove them.

One program that reaches one table through two stored procedures now appears
twice, once per Execution Path. One program that reads a table through one
stored procedure and writes it through another reports both facts.

This ticket carries two decisions on purpose. Landing the first alone would
regress: an unproven write would take the file's single seat, a caller filtering
for proven writes would then discard it, and the proven read it displaced would
already be gone.

Read [ADR-0015](../../../docs/adr/0015-an-unproven-execution-path-is-reported-not-dropped.md)
and [ADR-0016](../../../docs/adr/0016-a-table-match-is-deduplicated-by-execution-path-not-by-file.md)
first. Each records the alternative it rejected.

**Blocked by:** None — can start immediately. Note that another effort,
`.scratch/table-reverse-lookup-cost/`, holds uncommitted work in the same query
module. Read the working tree before you start, and land after it or coordinate.

**Status:** done

- [x] A path the service cannot prove appears in the response, with its Evidence
      Status and the reason it is unresolved.
- [x] That path claims no mutation.
- [x] A proven-writes request returns exactly what it returns today, plus a
      count of the records it excluded.
- [x] One program reached through two stored procedures produces two records.
- [x] One program with a proven read and an unproven write on one table produces
      both records.
- [x] Two identical Execution Paths produce one record.
- [x] The record count for one busy table is measured before and after this
      change, and both numbers are recorded on this ticket before it closes.
- [x] The existing query-module tests are updated where they assert the present
      delete behaviour, and every other test in the suite still passes.

## Note

Landed after `.scratch/table-reverse-lookup-cost/` (its ticket 02/03 commits —
`4321c04`, `be81c2c`, `9ef5725` — were already on this branch). No conflict in
intent: that effort made the table reverse lookup's walk cheaper; this ticket
stops the walk from discarding what it proved.

`GRAPH_VERSION` stayed at 4 (raised once, by ticket 01) -- decisions 3 and 4
change query/service logic, not graph shape, so no further cache invalidation
was needed.

**Decision 3** (`filter_table_accesses()` in `service/graph_queries.py`): a
path that is not `proven` now produces a record instead of nothing.
`is_write` is forced `False` and `access_type` reads `"UNRESOLVED"` unless the
path is `proven` -- the record states that the path reaches the table, not
what it does there (ADR-0015). An Unresolved Dynamic SQL path carries no
`reads`/`writes` of its own (the text is never parsed), so it cannot be
matched by table name; under `access="all"` it is surfaced regardless, once
per table asked about, since the graph genuinely cannot rule it out.
`write_only=True` keeps meaning "proven writes and nothing else" — `UNRESOLVED`
and every read type already fall outside `write_types` — and
`FindByTableResponse` gained `excluded_count`, the number of records that
filter removed.

**Decision 4** (`_prefer_table_match()` in `service/analyze_service.py`):
graph-derived matches now dedupe by Execution Path identity — program, file,
`path_id`, entry method, stored-procedure chain, access type — instead of by
file, via `_table_match_identity()`. An inline C# SQL fact carries no such
identity (no `path_id`/`entry_method`/`sp_chain` of its own), so it keeps the
pre-ticket file-scoped blending rule instead: it joins the response only when
no graph-derived fact for the same file already outranks it
(`tests/test_derived_execution_evidence_reuse_table.py`'s
`test_embedded_sql_and_graph_derived_preference_rule_is_unchanged`, which
predates this ticket, pins that rule in place). This never drops a
graph-derived record — only whether one inline record joins it.

**Measurement (checklist item 7).** Rebuilt the real PUR SQL Execution Graph
straight from the raw stored-procedure/view/function text already saved in
`data/sql_cache/vmsystest07.topmost.com.tw__PUR__dbo.json` (its cached graph
was `graph_version` 3; this environment has no ODBC driver, so this rebuild
via `build_sql_execution_graph()` — the same construction `refresh_sql_cli`
would run — is how a current, `graph_version` 4 graph was obtained without a
live database connection). See
`.scratch/reverse-lookup-drops-proven-writes/ticket-02-record-count-measurement.md`
for the busiest table found, the before/after record counts, and the method.
