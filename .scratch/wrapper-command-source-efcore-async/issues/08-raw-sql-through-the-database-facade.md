# 08 — Raw SQL executed through a context's Database facade resolves its Command Source

**What to build:** A full IQCS refresh reports a created Contract instead of
`onboarding=preflight_failed`, and both the external wrapper registry and the
system catalog carry it afterwards, with no manual step.

This is the whole spec's measured outcome. It arrives here because this ticket
closes the last gap.

A wrapper method that executes raw SQL through a database context's `Database`
facade resolves its Command Source. The recognised calls are `ExecuteSqlRaw`,
`ExecuteSqlInterpolated` and their asynchronous forms. This shape constructs no
command object at all, so every rule built around a command object misses it.
The method is public, its body names an ADO.NET type, and no rule accounts for
it — so it lands in the unclassified set, which is the honest answer today and
the wrong answer after this ticket.

The measured method is `SQLDbContext.usp_ExecCmdGetCountAsync`. It builds a
`FormattableString` from its own command text parameter and passes it to
`ExecuteSqlInterpolatedAsync`. It is the last unclassified method of the shared
assembly. A single unclassified public method blocks Contract creation
completely, so tickets 01, 02 and 07 write nothing without this one.

All four `Execute` forms are recognised together. They share one receiver, one
return semantics, and differ only in whether the string is interpolated or raw.
Recognising one and not the others would need a new ticket the first time
another team uses the raw form — the ticket-per-convention cost this spec exists
to remove.

The deferred `FromSql` forms stay unrecognised. They return a queryable, execute
later, and hang off a `DbSet` rather than the `Database` facade.

**Blocked by:** 06 (the Command Source record must hold a construct with no
command object and no command variable) and 07 (the `context_connection` value
this shape reports; without it the method classifies but the surface still fails
on an empty Connection Behavior Boundary).

**Status:** ready-for-agent

- [ ] A wrapper method that executes raw SQL through a context's `Database` facade is reported as a classified wrapper definition, not as an unclassified public method
- [ ] All four `Execute` forms resolve — raw and interpolated, synchronous and asynchronous
- [ ] The command text is read from the argument the caller supplies, so the target the call site names is traced exactly as it is for a sibling method that does construct a command
- [ ] The execution call itself is reported as the terminal sink, so a Command Source with no command object still states where its command ends up
- [ ] A method carrying a mode argument reports `call_site` command semantics; a method whose mode is fixed in the body reports the fixed mode
- [ ] The method's Connection Behavior Boundary is `context_connection`
- [ ] A method using a deferred `FromSql` form stays unclassified and is named — the unrecognised shape is visible, not silently dropped
- [ ] The real shared assembly under the IQCS checkout reports all seven public methods as classified or delegated, none unclassified, and its proposal passes the completeness check (fixture-gated, skipped when the checkout is absent)
- [ ] A full IQCS refresh reports a created Contract, and both the external wrapper registry and the system catalog carry it afterwards
- [ ] `CONTEXT.md`'s **Command Source** entry names the raw-SQL execution shape beside the command-factory shape
