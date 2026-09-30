# 10 — A call path to an unresolved procedure carries the Unproven Schema mark

**What to build:** An analyst follows a program into a procedure call that no listed procedure answers. The Execution Path for that call already exists (`called_procedure_not_in_graph`), but it carries no `unproven_schema` risk flag. The path builder reads the `schema_source` of the `calls` relationship (`unresolved`) and adds the flag to that one path. A call that resolves to `sys` (source `system`) is proven and carries no flag.

See user story 9 in the spec, and ticket 05, which left this box open.

**Blocked by:** 05 — An unqualified call reaches one procedure (done).

**Status:** ready-for-agent

- [ ] A failing path builder test comes first: a call with `schema_source` `unresolved` gives one path with `unproven_schema` in `risk_flags`.
- [ ] A call with source `system` gives one path and no `unproven_schema` flag.
- [ ] A call to a listed procedure keeps its paths and gains no flag.
- [ ] The golden `path_id` test stays unedited and passes.
- [ ] The whole suite shows no new failure.

**Notes:**

- Check that `stored_procedure:sys.name` (no node) is tolerated by every consumer of a `calls` target; ticket 05 verified only the path builder.
