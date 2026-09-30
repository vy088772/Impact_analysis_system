# 01 — A rebuild report records the v7 baseline

**What to build:** An operator runs one tool, with no SQL Server connection, and reads per cache what the graph holds: references that state no schema (by schema source once the field exists), CTE names read as tables, `UPDATE` or `DELETE` writes to an alias, and remaining Unproven Schema marks. The tool runs now, on the seven local v7 caches, so that ticket 09 can compare the rebuilt graphs with this baseline.

See "Testing Decisions" (the rebuild report) and the Problem Statement in the spec.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] The tool reads each SQL cache through the cache store's listing and opens no connection.
- [ ] Per cache it counts: references with an empty schema, references by schema source (all `written` or empty on a v7 graph), CTE names read as tables, writes whose target is an alias of the statement's `FROM` clause, and targets that carry the Unproven Schema mark.
- [ ] The CTE and alias counts read each statement's text through the relationship's source location, as the fact-finding in the grilling session did.
- [ ] A test covers each count over a hand-built cache from the shared fixture module.
- [ ] The tool's output for the seven local v7 caches is recorded in this ticket's notes, with the date. Expected scale: about 9845 references that resolve, 231 CTE reads, 330 alias writes.
- [ ] The whole suite shows no new failure.
