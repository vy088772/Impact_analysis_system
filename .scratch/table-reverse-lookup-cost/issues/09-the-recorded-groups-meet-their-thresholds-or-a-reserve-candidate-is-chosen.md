# 09 — The recorded groups meet their thresholds, or a reserve candidate is chosen

**What to build:** A recorded comparison that says whether this effort achieved
what it set out to achieve, and a decision that follows from it. The comparison
is measured, not estimated, and it separates the two cases the earlier tickets
serve differently.

Two criteria decide it, both against the medians ticket 02 recorded:

- the Object Kind Ambiguity group falls to 10 seconds or less;
- the table-write group falls to 45 seconds or less.

A cold scope and a warm scope are measured separately. Ticket 06 helps only a
scope somebody already derived, so a run that measures only warm scopes would
credit disk storage with a saving it did not make. Clear the stored file and
the retained entry before a cold measurement.

The measurement is per phase, not end to end only. A single total cannot say
which ticket produced a result, and the reserve decision below depends on
knowing that.

Then the decision. If the Object Kind Ambiguity criterion fails, the reserve
candidate is the one held in the spec: answer that probe from the graph and the
invocation names, without building Execution Paths at all. It needs its own
decision first, because it changes which evidence proves that the table reading
matched, and because the count of related programs is part of the Retained
Interpretation term itself.

If the table-write criterion fails, no candidate in this effort applies. What
remains in that group is agent rounds, tool calls and synthesis, and those
belong to `agent-round-waste` and `context-assembly-cost`. Hand it over rather
than reopening a candidate that cannot reach it.

**Blocked by:** 03, 04, 06, 07, 08.

**Status:** ready-for-agent

- [ ] A routing observation run is recorded with every landed ticket in place,
      using the configuration ticket 02 recorded.
- [ ] The Object Kind Ambiguity group's median is compared against 10 seconds.
- [ ] The table-write group's median is compared against 45 seconds.
- [ ] A cold scope and a warm scope are measured and reported separately.
- [ ] The per-phase figures are recorded, so a missed criterion points at a
      step.
- [ ] The Answer Latency ninetieth percentile is recorded beside the group
      medians, without being treated as this effort's criterion.
- [ ] The result is written down beside the baseline, so the comparison
      survives the session that produced it.
- [ ] If the Object Kind Ambiguity criterion fails, the reserve candidate is
      raised as its own decision, naming what it changes about Retained
      Interpretation.
- [ ] If the table-write criterion fails, it is handed to the agent-round and
      context-assembly efforts rather than reopened here.

## Notes

Executed in `llamaindex-spec-rag`, under `evaluation/Impact_analysis/`. Filed
here because this effort owns the criteria.

Answer Latency's recorded target is a ninetieth percentile under thirty
seconds, and this effort does not promise it. The baseline's stored-procedure
group sits at 52.7 seconds and its control group at 69.6 seconds, both
dominated by agent rounds and synthesis, which no ticket here touches. Record
the percentile for the trend; do not judge this effort by it.

Producing a cold scope repeatably is the awkward part of this ticket. Decide
how before measuring, and record the method beside the numbers, so a later run
can be compared with this one.

The reserve candidate's precondition is recorded in the spec's Out of Scope
section and in
`llamaindex-spec-rag/.scratch/agent-round-waste/filter-table-accesses-measurements.md`.
Read both before raising it. The count it would change is pinned by a shipped
specification and by seven tests.
