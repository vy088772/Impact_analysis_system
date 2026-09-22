# 02 — Remove the FK cascade table from the orchestrator

**What to build:** The orchestrator no longer asks for a FK cascade table, and
no longer reads one. An analyst who runs the command line sees the outline, the
stored procedures and the real tables, with no cascade table line. The prompt
for the AI and the prompt for the agent hold the same three facts and no cascade
line.

The grounding step no longer adds cascade table names to its allowlist. The
allowlist is the set of names that the hallucination check accepts as real. A
master table used to add up to 50 unrelated names to that set, which let an
invented answer pass. After this ticket the check rejects a table name that the
program does not touch.

The orchestrator removes the cascade depth setting and the matching entry from
the environment file. The environment file comment says today that the resolver
queries the database when the cache is absent. That statement is wrong, because
ADR-0011 removed that query. Remove the comment with the entry.

The merge step unions two fields across caches today. After this ticket it
unions the stored procedure names only. The forward chain merge loses the
cascade key for the same reason.

**Blocked by:** None — can start immediately. This ticket does not gate ticket
01, and ticket 01 does not gate this one. The service ignores an unknown request
field, and every consumer reads the response field with a safe default.

**Status:** ready-for-agent

- [ ] The command line output holds no cascade table line.
- [ ] The prompt for the AI holds no cascade table line.
- [ ] The prompt for the agent holds no cascade table line.
- [ ] The grounding allowlist holds only the tables that the program really reads or writes.
- [ ] The orchestrator sends no cascade depth to either endpoint.
- [ ] The configuration and the environment file declare no cascade depth.
- [ ] The merge step unions the stored procedure names only.
- [ ] The two tests that used the cascade field as a cache marker use the stored procedure names instead, and keep their coverage.
- [ ] The whole test suite of this repository passes.
