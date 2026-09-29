# 12 — The documents record the decisions

**Spec issue:** 8

**What to build:** A future reader finds why one cache holds one Database, why
the index states its own version, and why an unproven schema marks one
Execution Path. The glossary defines each new term once.

See "Documents" in the spec.

**Blocked by:** 11

**Status:** ready-for-agent

- [ ] ADR-0033 records that one SQL cache holds one Database, and why one cache per schema was rejected.
- [ ] ADR-0034, "The Object Location Index States Its Own Format Version; an Incomplete One Is Absent", exists.
- [ ] ADR-0012 gains an `Amended by ADR 0034` note in the form ADR-0004 uses.
- [ ] ADR-0035, "An Unproven Schema Marks One Execution Path; It Does Not Multiply It", states its reasons and its two rejected alternatives. ADR-0015 and ADR-0016 gain no note.
- [ ] `CONTEXT.md` gains a Canonical Object Identity entry that carries the two-bucket lookup rule.
- [ ] `CONTEXT.md` gains an Unproven Schema entry that names `unproven_schema`.
- [ ] `CONTEXT.md` gains a test fixture entry that names the check.
- [ ] `CONTEXT.md` gains a C# Scan Result entry that states it is not a Scan Record.
- [ ] The Database Invocation entry gains the sentence that one entry method through one call site is one Database Invocation, whichever SQL cache reports it.
- [ ] The cache store docstring that states schemas collapse to one key is corrected.
