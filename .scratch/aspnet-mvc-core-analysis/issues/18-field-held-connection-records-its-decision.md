# 18 — Field-Held Connection records its decision as an ADR

**What to build:** The rule that decides where a Resolved Connection Source attaches is written
down as an ADR, and the glossary entry cites it.

Ticket 09 made a call with a real alternative. A raw ADO.NET call opens its connection from a
field, so the connection could attach to the field or to the connection variable at the call
site. It attaches to the call-site variable, because that is the variable a Database Invocation
records — a reason attached only to the field is never found by the reader holding the
invocation.

That choice has a consequence a future reader will not expect: the tracker keys connections by
variable name across one file, so two methods each holding a `con` share one entry, and one
call site resolving must not settle another. Ticket 09 hit that as a live defect and fixed it.

`CONTEXT.md` records the rule but cites no ADR, while every neighbour in that section does.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] An ADR records the decision, the alternative it rejected, and the reason it rejected it.
- [ ] The ADR states that one call site resolving does not settle another that shares its variable name.
- [ ] The glossary entry for Field-Held Connection cites the ADR, as its neighbours do.
