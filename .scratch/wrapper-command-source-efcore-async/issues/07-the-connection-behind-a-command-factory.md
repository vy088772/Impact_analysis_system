# 07 — The connection behind a command factory is read from the factory's receiver

**What to build:** A wrapper method that obtains its command from
`connection.CreateCommand()` reports that connection as its Connection Behavior
Boundary, instead of reporting an empty boundary.

Ticket 01 made the command factory a recognised Command Source. It did not carry
the connection across. The connection resolver reads a connection from two
places only: the second argument of a command constructor, and a `Connection`
property assignment. A factory call gives neither. The connection is the
*receiver* of the factory call, and the resolver never reads that receiver.

The consequence is measured. All three classified `SQLDbContext` methods build
their command this way, so all three report an empty Connection Behavior
Boundary, and the proposal fails the completeness check with
`connection_behavior_boundary_missing`. Tickets 01 and 02 together still leave
the Contract refused.

The boundary vocabulary also gains a third value. A factory receiver that is a
database context's `Database` facade reports `context_connection`. The database
follows from the call site's declared receiver type through Context Connection
Registration — `SQLDbContext` serves five Systems and many derived context
types, so no single connection belongs to the wrapper. Every other factory
receiver reports `wrapper_connection`, exactly as a Field-Held Connection does
today.

The new rule runs last, only when both existing rules resolve nothing. An
already-resolved boundary therefore cannot change value by construction, not by
coincidence. Measured before this ticket: neither `SQLObject.dll` nor
`SQLFunc.dll` contains a single `CreateCommand` call, and all 68 operations
across the three registered Contracts already report `wrapper_connection`.

`CONTEXT.md` already defines **Connection Behavior Boundary** with its two
existing values. This ticket adds the third to that entry.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] A wrapper method whose command comes from a factory call on a connection expression reports that connection as its Connection Behavior Boundary, observable through the analyzer host's decompile-wrapper response
- [ ] A factory receiver that is a database context's `Database` facade reports `context_connection`
- [ ] A factory receiver that is a Field-Held Connection reports `wrapper_connection`, so the two lookup shapes are never read from one value
- [ ] A method that already resolves its connection through a command constructor argument or a `Connection` property assignment reports exactly the value it reports today, even when its body also contains a factory call
- [ ] The real shared assembly under the IQCS checkout reports a non-empty Connection Behavior Boundary for all three of its classified methods, and its proposal no longer fails with `connection_behavior_boundary_missing` (fixture-gated, skipped when the checkout is absent)
- [ ] That same assembly still reports an incomplete behaviour surface naming `usp_ExecCmdGetCountAsync` — a partial repair is not presented as a whole one
- [ ] The existing `SQLFunc` and `SQLObject` Contract Fingerprints are unchanged, byte for byte
- [ ] `CONTEXT.md`'s **Connection Behavior Boundary** entry gains `context_connection`, defined against Context Connection Registration and Field-Held Connection
- [ ] An ADR records the decision to add a third value rather than reuse `wrapper_connection`
