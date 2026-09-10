# 09 — A connection string held in a field resolves the same way

**What to build:** A raw ADO.NET call whose connection comes from a field on the calling class
resolves its Resolved Connection Source, so a system that never uses a database
context still answers.

One measured repository is written entirely this way: a controller reads a named
connection string into a field in its constructor, and thirty-five calls open a
connection from that field. Ticket 08 covers the context-type shape; this ticket
covers the field-held shape, using the same per-project lookup table.

**Blocked by:** 08.

**Status:** ready-for-agent

- [ ] A field assigned a named connection string resolves calls that open a connection from that field.
- [ ] The field's connection resolves through the same Project Connection Scope as every other lookup in that project.
- [ ] A field assigned from the root configuration namespace resolves to nothing and names why, matching ticket 08's rule.
- [ ] A field whose assigned value cannot be traced stays unresolved and names why.
- [ ] The measured repository built in this style resolves the connection for its raw ADO.NET calls.
