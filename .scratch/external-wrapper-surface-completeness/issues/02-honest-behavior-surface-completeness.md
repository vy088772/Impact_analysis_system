# 02 — Report the public database behavior surface honestly

**What to build:** A maintainer can trust the completeness claim of an Implementation Snapshot. When the decompiler cannot classify a public method that touches a database type, the snapshot reports an incomplete surface, and Contract Preflight rejects it.

Today the decompiler reports this completeness as a constant true value. It never compares its output against the assembly's real public method set. An incomplete contract therefore reaches the Contract Lifecycle Status `accepted` with no signal.

Compute the completeness from the assembly's public method set. Assign each public method one of three states:

- **classified** — a Command Source resolved, and the method has a mode and a terminal sink;
- **non-database** — the method body touches no ADO.NET type;
- **unclassified** — the method body touches an ADO.NET type, but no Command Source resolved.

The snapshot validation already rejects an incomplete public database operation surface, and it already skips a non-database operation. Reuse both. Add no new validation rule.

**Blocked by:** 01 — without the data adapter rule, the fixture assembly holds an unclassified method, so this ticket would reject the contract that the system depends on today.

**Status:** ready-for-agent

- [ ] Every public method of a decompiled assembly receives one of the three states.
- [ ] A public method whose body touches no ADO.NET type takes the state non-database.
- [ ] A public method whose body touches an ADO.NET type but yields no Command Source takes the state unclassified.
- [ ] The snapshot reports a complete public database behavior surface only when no public method is unclassified.
- [ ] The snapshot carries the method identity of every unclassified method.
- [ ] Contract Preflight rejects a snapshot whose public database behavior surface is incomplete.
- [ ] The rejection reason names the unclassified methods.
- [ ] A non-database method never blocks contract acceptance.
- [ ] The fixture assembly reports a complete public database behavior surface.
- [ ] A test builds a snapshot that holds an unclassified public method, and asserts that Contract Preflight rejects it.
