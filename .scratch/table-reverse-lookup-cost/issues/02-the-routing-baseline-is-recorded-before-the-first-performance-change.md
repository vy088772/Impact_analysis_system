# 02 — The routing baseline is recorded before the first performance change

**What to build:** A recorded routing baseline that carries the pre-agent
lookup seconds, captured while the service still has every cost this effort
intends to remove. Every later claim in this effort is compared against it.

This baseline cannot be recaptured later. Once the first performance ticket
lands, the starting point is gone. The existing recorded run in
`context_assembly_attribution` predates the pre-agent lookup column, which is
why its Object Kind Ambiguity group shows 54.6 seconds with every phase-cost
field empty. A baseline without that column cannot attribute the largest
number in the slowest group.

The work is performed in the companion repository, `llamaindex-spec-rag`,
where the routing observation lives. The field it needs is already implemented
there.

**Blocked by:** 01 — Every table reverse lookup records the table and the scope
it asked about.

**Status:** ready-for-agent

- [ ] A routing observation run is recorded with the service unchanged by any
      ticket in this effort other than 01.
- [ ] Every recorded row carries the pre-agent lookup seconds column.
- [ ] The Object Kind Ambiguity group's seconds are attributed rather than
      landing wholly in elapsed time.
- [ ] The recorded medians for the Object Kind Ambiguity group and the
      table-write group are written down, because ticket 09 compares against
      them.
- [ ] The recorded Answer Latency ninetieth percentile is written down.
- [ ] The run's configuration is recorded beside it, so ticket 09 can repeat
      the same run.

## Notes

Executed in `llamaindex-spec-rag`, under `evaluation/Impact_analysis/`. The
ticket is filed here because this effort owns the comparison it enables.

Prior baselines and their configuration are stored per run under
`evaluation/Impact_analysis/results/`. Follow that layout; do not overwrite an
existing recorded run.

The reference figures from the pre-column run, for orientation only: Object
Kind Ambiguity median 54.6 seconds, table-write median 163.2 seconds, Answer
Latency ninetieth percentile 163.0 seconds, twenty of ninety runs under thirty
seconds. Treat the new run as authoritative where the two disagree.
