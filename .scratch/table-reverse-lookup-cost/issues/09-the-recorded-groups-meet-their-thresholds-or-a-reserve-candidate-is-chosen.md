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

**Status:** done

- [x] A routing observation run is recorded with every landed ticket in place,
      using the configuration ticket 02 recorded.
- [x] The Object Kind Ambiguity group's median is compared against 10 seconds.
- [x] The table-write group's median is compared against 45 seconds.
- [x] A cold scope and a warm scope are measured and reported separately.
- [x] The per-phase figures are recorded, so a missed criterion points at a
      step.
- [x] The Answer Latency ninetieth percentile is recorded beside the group
      medians, without being treated as this effort's criterion.
- [x] The result is written down beside the baseline, so the comparison
      survives the session that produced it.
- [x] If the Object Kind Ambiguity criterion fails, the reserve candidate is
      raised as its own decision, naming what it changes about Retained
      Interpretation. — not triggered: the criterion passed (see Notes).
- [x] If the table-write criterion fails, it is handed to the agent-round and
      context-assembly efforts rather than reopened here. — not triggered: the
      criterion passed (see Notes).

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

## Implementation note

**Decision: both criteria passed. No reserve candidate raised, nothing handed
to `agent-round-waste` or `context-assembly-cost`.**

| Group | Scope | n | Median | Threshold | Result |
|---|---|---|---|---|---|
| Object Kind Ambiguity | cold | 6 | 8.53 s | ≤ 10 s | pass |
| Object Kind Ambiguity | warm | 12 | 7.83 s | ≤ 10 s | pass |
| explicit_table_write | cold | 6 | 32.99 s | ≤ 45 s | pass |
| explicit_table_write | warm | 12 | 30.36 s | ≤ 45 s | pass |

Both groups fell under threshold in both scope states, against ticket 02's
baseline of 68.28 s (Object Kind Ambiguity) and 89.41 s (table-write).

Per-phase medians (seconds; a phase with 0 populated rows is marked n/a — the
harness leaves an unrun phase blank, not zero):

| Phase | OKA cold | OKA warm | table-write cold | table-write warm |
|---|---|---|---|---|
| pre_agent_lookups_seconds | 0.75 (n=6) | 0.76 (n=12) | n/a (n=0) | n/a (n=0) |
| classification_seconds | n/a (n=0) | n/a (n=0) | n/a (n=0) | n/a (n=0) |
| tool_calls_seconds | 5.15 (n=4) | 5.05 (n=8) | 20.14 (n=6) | 17.03 (n=12) |
| agent_rounds_seconds | 5.43 (n=4) | 5.94 (n=8) | 8.20 (n=6) | 9.02 (n=12) |
| context_assembly_seconds | 0.46 (n=2) | 0.62 (n=4) | 1.51 (n=6) | 1.54 (n=12) |
| synthesis_seconds | n/a (n=0) | n/a (n=0) | n/a (n=0) | n/a (n=0) |

`synthesis_seconds` is n/a throughout because `run_ai=false` in this run's
configuration (matching ticket 02) — final-answer synthesis never ran, same
as the baseline.

Answer Latency (mode 4, all shapes, n=90), recorded for trend only, not as
this effort's criterion: ninetieth percentile **30.80 s**, 78 of 90 runs under
thirty seconds, 0 errors/timeouts. Against ticket 02's baseline (130.09 s p90,
46/90 under thirty seconds, 4 timeouts), latency dropped sharply even though
no ticket in this effort targets Answer Latency directly — the removed
lookup cost also shortened the runs that used to blow past the 150-second
agent timeout.

**Method for producing a cold scope, repeatably:** rather than running the
full baseline twice (once cold, once warm), a single run supplies both, split
by `repetition_index`. `run_full_routing_baseline()` iterates
`for repetition_index in range(repetitions): for expectation in
raw_expectations: ...` — the outer loop is repetition, so every question is
asked once (repetition 0) before any question is asked a second time. Clearing
ticket 06's disk store and ticket 07's in-memory retention immediately before
the run starts means repetition 0's rows are each a scope's first-ever
derivation (cold), and repetition 1 and 2's rows reuse what repetition 0
already derived and retained (warm). This needed the service process itself
restarted, not just the stores emptied — since ticket 06, evidence survives a
restart, so restart alone no longer clears it, and the in-memory retention
(`analyze_service._rated_invocations_retention`, an `OrderedDict`) has no
admin endpoint to clear without restarting the process. Concretely, before
starting the run: stopped the running `uvicorn service.api:app` process,
deleted every file under `data/derived_execution_evidence/` (leaving the
directory itself), and restarted `uvicorn service.api:app --host 127.0.0.1
--port 8800 --reload`. The SQL cache (ticket 08) was left untouched — the
spec names only "the stored file and the retained entry" for the cold/warm
split, and the SQL cache is a separately bounded cache the split isn't
measuring.

**Deviation from ticket 02's command, agreed with the requester before
running:** `routing_baseline.py` hardcodes
`AGENTIC_ROUTING_MODES = (4, 5)` in `routing_observation.py` with no flag to
run mode 4 alone, and always runs both modes per question. Since both
tickets' criteria are scored from the mode-4 subset only (ticket 02's own
note says so explicitly), this run skipped mode 5 to halve the wall-clock
cost, using a small driver that overrides the name only inside the already
imported `routing_baseline` module, leaving the shared
`routing_observation.AGENTIC_ROUTING_MODES` and every other caller
untouched:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path("/Users/topmost/yuhsienTseng/llamaindex-spec-rag")))

from evaluation.Impact_analysis import routing_baseline as rb

rb.AGENTIC_ROUTING_MODES = (4,)

if __name__ == "__main__":
    raise SystemExit(rb.main(sys.argv[1:]))
```

Run command, from the `llamaindex-spec-rag` repository root, using the exact
expectations file ticket 02 used (confirmed unchanged since that run: it was
last touched by `07f7f78`, before ticket 02's baseline):

```
.venv/bin/python <the driver script above> \
  --expectations evaluation/Impact_analysis/results/routing_expectations.candidate.json \
  --results-dir evaluation/Impact_analysis/results/table_reverse_lookup_landed \
  --repetitions 3
```

Ran to completion: 90 new runs (30 questions × mode 4 × 3 repetitions), 0
resumed, 0 errors. Recorded at
`llamaindex-spec-rag/evaluation/Impact_analysis/results/table_reverse_lookup_landed/`
(`routing_observations.csv`, `routing_scores.csv`, `routing_run_config.json`).
`routing_run_config.json` for this run matches ticket 02's exactly:
`run_ai=false`, `scope_lock_policy=full`, `router_model=gpt-5.6-luna`,
`agent_timeout_seconds=150.0`, `repetition_count=3`. As with ticket 02's own
CSVs, the raw observation and score CSVs stay uncommitted in
`llamaindex-spec-rag` (repo-wide `*.csv` is gitignored there); only this
note and the run configuration are durable.

Before starting, confirmed every ticket this one is blocked by (03, 04, 06,
07, 08) reads `**Status:** done`, and that nothing else in this effort had
landed since ticket 02's baseline other than those five.
