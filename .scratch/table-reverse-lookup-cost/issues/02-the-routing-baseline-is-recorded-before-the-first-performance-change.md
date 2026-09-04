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

**Status:** done

- [x] A routing observation run is recorded with the service unchanged by any
      ticket in this effort other than 01.
- [x] Every recorded row carries the pre-agent lookup seconds column.
- [x] The Object Kind Ambiguity group's seconds are attributed rather than
      landing wholly in elapsed time.
- [x] The recorded medians for the Object Kind Ambiguity group and the
      table-write group are written down, because ticket 09 compares against
      them.
- [x] The recorded Answer Latency ninetieth percentile is written down.
- [x] The run's configuration is recorded beside it, so ticket 09 can repeat
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

## Implementation note

Run recorded at `llamaindex-spec-rag/evaluation/Impact_analysis/results/table_reverse_lookup_baseline/`
(`routing_observations.csv`, `routing_scores.csv`, `routing_run_config.json`).
Command, from the `llamaindex-spec-rag` repository root:

```
.venv/bin/python -m evaluation.Impact_analysis.routing_baseline \
  --expectations evaluation/Impact_analysis/results/routing_expectations.candidate.json \
  --results-dir evaluation/Impact_analysis/results/table_reverse_lookup_baseline \
  --repetitions 3
```

Ran to completion: 180 new runs, 0 resumed, over about 2h35m wall clock.
`routing_expectations.candidate.json` was used instead of the default
`routing_expectations.json` because its review notice states
`explicit_table_write` and `object_kind_ambiguity` each carry six distinct
objects rather than paraphrases of one — the two shapes ticket 09 compares
against. `--repetitions 3` is the tool's own hard floor:
`run_full_routing_baseline()` raises `ValueError` below it, so the initially
requested single-run pass was not possible without patching the harness, and
that floor was kept rather than weakening the harness's own guardrail.

Before starting, confirmed the service state matches the checklist's
requirement: `git log` in `Impact_analysis_system` has ticket 01's commit
(`4321c04`) at HEAD, and every ticket 03 through 09 in this effort still
reads `**Status:** ready-for-agent` — nothing past 01 has landed.

`routing_baseline.py` always records both agentic modes (4 and 5) per
question; this run wrote 180 rows (30 questions × 2 modes × 3 repetitions).
The reference figures above, and ticket 09's future comparison, are both
scoped to mode 4 alone (the harness's own production default — see
`verify_mode4_answer_latency.py`), which is also the subset the old
pre-column baseline recorded (90 rows, mode 4 only). All figures below are
computed over this run's 90 mode-4 rows, joined to
`routing_expectations.candidate.json` by `question_id` for shape:

- **Object Kind Ambiguity median:** 68.28 s (n=18: 6 questions × 3 reps).
  Every one of the 18 rows carries a populated `pre_agent_lookups_seconds`
  value — the group's seconds are no longer landing wholly in
  `elapsed_seconds`. Across the group, `pre_agent_lookups_seconds` accounts
  for 1115.2 of 1558.7 total elapsed seconds (about 72%); the remainder is
  the clarification round after the ambiguity is detected.
- **Table-write median:** 89.41 s (n=18: 6 questions × 3 reps).
- **Answer Latency (mode 4, all shapes, n=90) ninetieth percentile:** 130.09 s.
  46 of 90 runs finished under thirty seconds.
- **Errors:** 4 of the 90 mode-4 rows hit the harness's 150-second agent
  timeout (`table-write-001`, `table-write-006`, `control-002`,
  `control-003`), each recorded with its `elapsed_seconds` and an `error`
  message rather than being dropped — included in the medians/percentile
  above as-is, matching how a timeout has always been treated in this
  harness's recorded runs.

`routing_run_config.json` for this run: `run_ai=false`,
`scope_lock_policy=full`, `router_model=gpt-5.6-luna`,
`agent_timeout_seconds=150.0`, `repetition_count=3`. This is
`routing_baseline.py`'s own out-of-the-box default (`ROUTING_RUN_AI=False`,
final-answer synthesis forced off) — the same default the docstring's
"run the default baseline" command produces. The pre-column reference run
(`context_assembly_attribution`) instead recorded `run_ai=true` (synthesis
on), which is very likely why its Answer Latency figures ran higher (163.0 s
p90, table-write median 163.2 s) than this run's (130.09 s p90, 89.41 s
median): synthesis time was not part of this run's `elapsed_seconds`. This
is a real, disclosed difference in method, not an error — the spec for this
ticket says explicitly to treat the new run as authoritative where the two
disagree, and ticket 09 repeats this exact command (same expectations file,
same results-dir, same `run_ai` default) rather than the old one, so its
comparison stays apples-to-apples with the numbers recorded here.
