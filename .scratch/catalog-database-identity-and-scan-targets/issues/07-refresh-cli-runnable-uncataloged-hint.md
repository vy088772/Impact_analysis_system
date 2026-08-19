# 07 — The Uncataloged-Database Hint Names Its Server and Actually Runs

**What to build:** An analyst who copies the hint the source-refresh command prints runs the right command, on the right host, without going hunting for which server the Database is on. The hint becomes a directly runnable direct-targeting scan command with both values filled in, plus a follow-up line about registering the Database afterwards. Two same-named Databases on different servers stop being reported as one line with their counts added together.

**Blocked by:** None — can start immediately.

**Status:** resolved

- [x] Each Uncataloged Database in the source-refresh command's unresolved summary prints a directly runnable scan command using direct server/database targeting, with both values filled in.
- [x] A second line instructs the operator to register that Database under that server afterwards, keeping the scan and the cataloging visible as separate steps.
- [x] Uncataloged results are aggregated by the `(server, database)` pair. Two Databases sharing a name on different servers report as two lines with their own call counts, never as one line with the counts summed.
- [x] Each distinct pair prints once regardless of how many invocations hit it, preserving today's deduplication behaviour.
- [x] The server value is read from the field the refresh response already carries on its wrapper observations. ~~This ticket requires no change to the analysis service~~ — see note below, this one turned out not to hold.
- [x] The source-refresh command still writes to neither catalog file and still triggers no live scan. The hint remains a suggestion a human acts on.
- [x] The existing assertions on the hint text are updated to the new wording rather than deleted.
- [x] Tests cover: the two-line hint with server and database filled in; two same-named Databases on different servers reported as separate lines with separate counts; and one entry per pair regardless of how many invocations hit it.

## Note

The claim "no change to the analysis service" did not hold as written. Verified
empirically: `DbInvocation.server` was already populated correctly by the
gateway, but `wrapper_observation_fields()` (`code_analyzer/csharp_analysis_gateway.py`
in `Impact_analysis_system`) never projected `evidence.server` into the dict
`/refresh`'s `wrapper_summary.review_items` actually returns — the field
simply was not being sent. Fixed with a one-line addition
(`"server": evidence.server if evidence is not None else None,`) right next
to the existing `"database": database,` line, plus a regression test in
`tests/test_csharp_analysis_gateway.py`
(`test_uncataloged_database_observation_carries_its_server`). Deliberately did
**not** add `server` to `WRAPPER_EVIDENCE_FIELDS`, since that tuple also feeds
`/analyze`'s and `/path_evidence`'s response shapes — widening it would have
expanded those schemas too, beyond this ticket's stated scope. Confirmed via
`_wrapper_projection_fields`/`_invocation_response_fields` in
`service/analyze_service.py` that `/refresh`'s `wrapper_summary` path (a raw
dict spread, no field-list filtering) is the only path affected.

On the `llamaindex-spec-rag` side: `refresh_cli._uncataloged_database_calls`
now keys its aggregation dict by `(server, database)` tuples instead of a bare
database-name string, and `_print_uncataloged_database_hints` prints two lines
per distinct pair — a runnable `refresh_sql_cli --server \`<server>\`
--database \`<database>\`` command, then a registration reminder line.
`docs/adr/0002-new-database-scanning-is-explicit.md` updated to describe the
new two-line, pair-keyed hint instead of quoting the old one-line text.
