# 11 — A call graph node is one bound method, so overloads stay apart

**What to build:** ADR-0044 says "A node is one bound method". Ticket 05 made
a node one class-qualified method name (`Class.Method`). So all the
overloads of one method share one node. A call to `Save(int)` also reaches
the stored procedures of `Save(string)` in the same class.

Give each node the signature of its method, as the host binds it. The node
key then comes from three records, and all three must carry the same
signature:

- each method span (`MethodSourceSpan`),
- each Bound Call Target (`CallSite`),
- each Database Invocation, through the method that holds it.

A Database Invocation carries only the method name now. The wrapper path
already has a bound `wrapper_method_identity` with parameter types; reuse
that format if it fits.

See ADR-0044 and the overload note of ticket 05.

**Blocked by:** None. Ticket 05 is done.

**Status:** needs-triage

- [ ] A call to one overload reaches only the stored procedures of that
      overload
- [ ] An action that calls two overloads reaches the stored procedures of
      both
- [ ] An invocation, a span and a call target of one overload give one key
- [ ] The scan cache version rises, and the notes record the rescan

**Notes:**

- Source: the Spec axis of the code review of ticket 05 (2026-10-07). The user
  chose to keep the ticket 05 node and to fix the overload in a new ticket.
- Same review, same cause: two classes with one simple name in two namespaces
  also share one node. A method of a `record` or a `struct` has the class
  `""` in its span, so a call into it gives no edge. Decide in triage if this
  ticket also takes these two, or if they get their own ticket.
- `call_graph_node` in `code_analyzer/models.py` is the one place that builds
  the key now.
- Measure first: count the RTTalentDB nodes that hold two or more overloads.
  If the count is 0, record it and lower the priority.
