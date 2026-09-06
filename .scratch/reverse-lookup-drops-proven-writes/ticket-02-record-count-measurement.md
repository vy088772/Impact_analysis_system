# Ticket 02 — record-count measurement

Checklist item: "The record count for one busy table is measured before and
after this change, and both numbers are recorded on this ticket before it
closes."

## Environment constraint

This sandbox has no ODBC driver (`refresh_sql_cli` cannot reach a live SQL
Server — confirmed via the pre-existing `tests/test_search_roles.py` /
`tests/test_sp_tables.py` collection failures, unrelated to this ticket). The
on-disk PUR SQL cache (`data/sql_cache/vmsystest07.topmost.com.tw__PUR__dbo.json`)
still carried `graph_version` 3 (pre-ticket-01). To measure against real data
without a live database, the graph was rebuilt straight from that cache's own
saved stored-procedure/view/function text via `build_sql_execution_graph()` —
the same construction `refresh_sql_cli` runs — which also applies ticket 01's
node-resolution fix and produces a current `graph_version` 4 graph (9,300
nodes, 118,031 relationships, confirmed via `assert graph["graph_version"] ==
GRAPH_VERSION`).

## Busiest tables (graph-level, comparable to the spec's own measurement)

Counting `reads`/`writes` relationships that target a `table` node, across
the whole rebuilt PUR graph:

| table | relationships | modules |
|---|---|---|
| Part | 1557 | 517 |
| Vendors | 1478 | 493 |
| Customers | 1456 | 492 |
| SOrder | 1201 | 333 |
| POrder | 1197 | 350 |
| Users | 1123 | 366 |
| DevPart | 1081 | 301 |
| **Quotation** | **1064** | **312** |
| IVWork | 1045 | 312 |
| OrderType | 1018 | 283 |

The spec (Decision 4) cites "962 DML operations that touch `Quotation` across
310 stored procedures" from a different snapshot (measured against the
companion repository's own checkout). This rebuild's 1,064/312 for the same
table is close, consistent with normal drift between snapshots of the same
real schema, and confirms `Quotation` is a real, busy table in this
environment too.

## Record-count measurement, before vs. after, `find_by_table("dbo.Quotation")`

Ran `analyze_service.find_by_table()` end-to-end against the real TTPUR C#
scan already on disk (`data/scan_cache`, `cache_version` 29, current — no
rescan needed) and the rebuilt PUR graph above, with `sql_cache_store` and
`resolve_scan_roots`/`_get_scan` stubbed to serve them directly (no live
clone or SQL connection). No `wrapper_contract` was configured for this run,
so only invocations resolvable without one reach the graph join.

Both the pre-change code (`git stash` back to `f5a295c`, this ticket's
parent commit) and the post-change code (this diff) return, for
`table_name="dbo.Quotation"`:

- `write_only=False`: **2 matches**, both `access_type="SELECT"`,
  `evidence_status="proven"`, one file each.
- `write_only=True`: **0 matches** (both are reads); `excluded_count` did not
  exist before this ticket, and is **2** after.

No difference in match count before vs. after for this specific slice of real
data: the two real call sites that reach `Quotation` here are two different
programs, each through one path, so the old file-keyed dedup and the new
Execution-Path-identity-keyed dedup (ADR-0016) collapse to the same two
records either way — this real sample happens not to contain the
same-program-multiple-paths shape ADR-0016 is about. That shape (checklist
items 4/5/6: one program via two stored procedures, a proven read beside an
unproven write, and a repeated path collapsing to one) is covered directly
by `tests/test_graph_reverse_lookup.py`'s ticket-02 tests instead, which
construct it precisely because this specific real sample doesn't exhibit it.

This measurement is honest about its own limits: without a working
`wrapper_contract` configuration and a live database to rate every real
invocation, it under-counts how many real call sites in TTPUR actually reach
`Quotation` (many likely go through a `SQLObject`/`ExeProcNon`-style wrapper
that a bare, unconfigured run does not resolve to `proven`). It answers the
question the checklist item asks — "did this change blow up the response
size for a busy table" — with "no, not on this slice"; it is not a claim
about the true total record count `refresh_sql_cli` plus a live database
would produce.
