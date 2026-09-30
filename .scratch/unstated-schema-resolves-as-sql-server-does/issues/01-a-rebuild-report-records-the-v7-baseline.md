# 01 — A rebuild report records the v7 baseline

**What to build:** An operator runs one tool, with no SQL Server connection, and reads per cache what the graph holds: references that state no schema (by schema source once the field exists), CTE names read as tables, `UPDATE` or `DELETE` writes to an alias, and remaining Unproven Schema marks. The tool runs now, on the seven local v7 caches, so that ticket 09 can compare the rebuilt graphs with this baseline.

See "Testing Decisions" (the rebuild report) and the Problem Statement in the spec.

**Blocked by:** None — can start immediately.

**Status:** done

- [x] The tool reads each SQL cache through the cache store's listing and opens no connection.
- [x] Per cache it counts: references with an empty schema, references by schema source (all `written` or empty on a v7 graph), CTE names read as tables, writes whose target is an alias of the statement's `FROM` clause, and targets that carry the Unproven Schema mark.
- [x] The CTE and alias counts read each statement's text through the relationship's source location, as the fact-finding in the grilling session did.
- [x] A test covers each count over a hand-built cache from the shared fixture module.
- [x] The tool's output for the seven local v7 caches is recorded in this ticket's notes, with the date. Expected scale: about 9845 references that resolve, 231 CTE reads, 330 alias writes.
- [x] The whole suite shows no new failure.

## Comments

Files this ticket changed (other tickets run in parallel; these are the only ones):

- `tools/rebuild_report.py` (new): the report tool. `python tools/rebuild_report.py [--cache-root DIR] [--json]`.
- `tests/test_rebuild_report.py` (new): 14 tests over hand-built caches from `tests/sql_cache_fixtures.py`.
- No shared file changed: not the fixture module, not the graph builder, not the analyzer host.

How the tool counts:

- It reads through `sql_cache_store.list_caches()` and `load_cached()`. It opens no connection. A cache that the store does not trust reports `invalid_cache`.
- Later tickets: after ticket 09 raises `GRAPH_VERSION` to 8, `load_cached()` rejects a v7 cache. Run the tool on the v7 caches before ticket 09, and keep the output below as the baseline.
- `empty_schema_references`: `reads`, `writes`, and `calls` relationships whose target has an empty schema. A call target with no node reads its schema from the node id.
- `references_by_schema_source`: the same relationships, grouped by the relationship's `schema_source` field. The field does not exist yet (ticket 04 adds it). Until then, a target with a schema counts as `written`, and one with none counts as `""`.
- `unproven_schema_targets`: distinct target nodes with an empty schema. This includes `#temp` nodes.
- `cte_reads` and `alias_writes`: they cut the statement text from the relationship's `source_location` (`start_offset`, `length`) and the module definition. They count distinct (operation, target) pairs. A CTE read is a `reads` relationship whose target name a `WITH name AS (` or `, name AS (` in that text defines. An alias write is a `writes` relationship of an `UPDATE` or a `DELETE` whose target name is a `FROM`/`JOIN`/comma alias of another object in that text. Both counts are regex approximations, not a SQL parser.
- Counting relationships (254 CTE reads) and counting distinct (operation, target) pairs (231) differ. The graph builder adds one relationship for each mention of a name, so a name read twice in one statement gives two. The spec counts 231, so the tool counts pairs.

**v7 baseline, 2026-09-30** (`python tools/rebuild_report.py`, seven local caches, all `graph_version 7`):

| Cache | empty schema | by source | CTE reads | alias writes | unproven targets |
|---|---|---|---|---|---|
| EFNETDB | 0 | (none) | 0 | 0 | 0 |
| ETON | 199 | empty 199, written 81 | 0 | 0 | 36 |
| PUR | 12092 | empty 12092, written 4893 | 199 | 184 | 937 |
| Response | 96 | empty 96, written 156 | 0 | 0 | 14 |
| STC | 214 | empty 214, written 33 | 0 | 1 | 26 |
| SysErrorRecord | 12 | empty 12, written 6 | 0 | 0 | 3 |
| eFinance | 404 | empty 404, written 2443 | 32 | 145 | 91 |
| **Total** | **13017** | **empty 13017, written 7612** | **231** | **330** | **1107** |

The CTE total (231) and the alias total (330) match the spec. The empty-schema total (13017) counts relationships. The spec's 9845 counts the ones that the listing resolves, and 3107 unlisted names. The two figures agree in scale: this tool does not apply the rule, so it does not split them.

Verification: `pytest tests/test_rebuild_report.py` gives 14 passed. The whole suite (with `test_search_roles.py` and `test_sp_tables.py` ignored, as both need a live SQL Server at collection) shows 16 failures, the same 16 that a clean checkout shows. Ticket 09 compares the rebuilt caches with this table.

**Whole-feature review, 2026-09-30** (`/code-review` from `b865587` to `154ad57`, then the fixes).

- `tools/rebuild_report.py` reads a relationship with no `schema_source` through `schema_resolution.recorded_source()`. A target with no schema then counts as `unresolved`, not as `""`. The v7 baseline table above keeps its `empty` label: it is a record of that run.
- The tool reads the module collections from the graph builder (`MODULE_COLLECTIONS`). It holds no list of its own.
- The CTE regex misses a CTE name that follows a comment (`), --comment` then `List2(...) as`). PUR holds 3 such reads. Ticket 09 counts them.
