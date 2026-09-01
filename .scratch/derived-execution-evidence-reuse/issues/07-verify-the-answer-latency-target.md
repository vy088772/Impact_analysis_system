# 07 — Verify the Answer Latency target for table-naming questions

**What to build:** The after measurement, compared question by question against
the recorded baseline, and a plain statement of whether the target was met.

Answer Latency is the only acceptance measure for this effort. A service-side
timing that improved while the analyst's wait did not is the outcome most worth
not mistaking for success, which is why no second, service-side metric was
introduced anywhere in this effort.

The specific signal to look for is divergence within one question's repetitions.
The baseline recorded three near-identical timings for the same question, which
is the direct evidence that nothing was reused. If reuse is working, the first
repetition still pays for the derivation and the later ones do not, so those
timings must separate. If they stay flat, the reuse is not taking effect in the
running service regardless of what any unit test asserts.

A miss is reported as a miss. It is information about where the remaining time
is, and the next place to look is already known: the companion effort that keeps
an irrelevant repository scan from being touched at all.

**Blocked by:** 06.

**Status:** done

- [x] The same questions from the baseline are re-run with the same measurement
      entry point and the same repetition pattern
- [x] The comparison is per question, not only in aggregate
- [x] Repetitions within one question are compared for divergence, and a flat set
      of timings is reported as reuse not taking effect in the running service
- [x] The result is stated against the recorded target — ninetieth percentile
      under thirty seconds — for the table-naming question shape
- [x] A miss is reported as a miss, together with what the remaining time appears
      to be spent on, and is never presented as a partial success
- [x] The measurement records whether the service process was warm or freshly
      started, since the first request in a process still pays for the derivation
- [x] The recorded routing baseline artifacts remain untouched
- [x] The finding is written into this effort's tickets rather than only reported
      in conversation, so the next effort starts from the measurement

**Note:** The after measurement used the same entry point, the same command, and
the same repetition pattern as the baseline:
`python -m evaluation.Impact_analysis.latency_measurement --mode 4
--repetitions 3 --synthesis`, with
`--results-dir evaluation/Impact_analysis/results/latency_after`. It ran on
2026-09-01 from 17:55:39 to 19:05:29 and wrote 90 observations with zero
errors. The recorded run configuration matches the baseline's exactly, field
for field.

Service state: the service process was **freshly started**. The `uvicorn
--reload` worker restarted at 17:55, and the run began 39 seconds later. No
request reached the process between the restart and the first measured
question. The on-disk repository scans and SQL caches were the same five and
five the baseline names. A partial two-row file from an aborted 14:23 run
already sat in `latency_after/`. It moved to
`aborted_partial_20260901_1423.routing_observations.csv` and did not enter this
run's data.

**Verdict: the target was missed.** The table-naming ninetieth percentile is
**82.2 seconds** against a target of under thirty seconds. Four of the eighteen
observations finished under thirty seconds, against one of eighteen in the
baseline. The median moved from 85.9 to 72.2 seconds. This is a miss, not a
partial success.

Per question, in seconds by repetition:

| question | before | after |
| --- | --- | --- |
| table-write-001 | 81.9, 72.9, 77.0 | 74.6, 69.2, 59.0 |
| table-write-002 | 92.8, 16.1, 75.8 | 71.2, 3.5, 3.7 |
| table-write-003 | 105.3, 140.6, 104.6 | 73.2, 100.5, 74.3 |
| table-write-004 | 92.3, 56.1, 89.8 | 61.0, 76.5, 14.7 |
| table-write-005 | 96.0, 60.3, 152.6 | 56.0, 75.0, 75.6 |
| table-write-006 | 103.1, 68.6, 69.3 | 74.6, 95.5, 14.7 |

Divergence within one question is the signal this ticket asked for, and the
Answer Latency timings mostly do **not** show it. Only `table-write-002`
separates cleanly: 71.2 seconds first, then 3.5 and 3.7. Three questions stay
flat across all three repetitions (001, 003, 005). Two drop only on their third
repetition (004, 006). Read by this ticket's own rule, a flat set reports reuse
as not taking effect in the running service.

The run log contradicts that reading, and both facts belong in the record. The
same log times each service call individually. `find_by_table` took 0.95 seconds
on its first call in the fresh process, then a median of 0.32 seconds across the
remaining seventeen. `find_by_sp` took 1.37 seconds first, then a median of 0.09
seconds across the remaining thirty-five. The derivation is genuinely reused in
the running service. It saves roughly half a second to one and a half seconds
per question, which is invisible inside a seventy-second answer. The Answer
Latency repetitions are flat because the saving is too small to see, not because
the reuse failed. That distinction does not soften the verdict: the analyst's
wait did not reach the target.

**Where the remaining time goes.** The run log splits each answer into the
routing-and-tools phase and the final answer synthesis phase. Fourteen of the
eighteen table-naming runs logged both phases:

- routing and every service call: median 18.1 seconds, range 13.8–26.4
- final answer synthesis: median 54.8 seconds, range 39.1–84.7

Final answer synthesis alone exceeds the thirty-second target by a wide margin.
The four fastest observations (3.5, 3.7, 14.7, 14.7 seconds) are exactly the
four runs that never entered synthesis, because the agent answered directly from
`search_specs_by_table`. Every service call this effort touched is already
sub-second.

**The next place to look is not where this ticket assumed.** This ticket named
the companion effort that keeps an irrelevant repository scan from being touched
at all. That scan is `analyze_system`. It ran 49 times across the whole
seventy-minute run, at a median of 0.58 seconds and a ninetieth percentile of
1.39 seconds, for 43.5 seconds of the entire run combined. Removing it
completely would recover well under one second per question. It cannot close a
fifty-second gap. The remaining time is the final answer synthesis call, and any
next effort aimed at Answer Latency has to start there.

**One caveat on the improvement that did appear.** The other four question
shapes moved from a median of 70.0 to 31.0 seconds — a larger drop than the
table-naming shape got, in a population this effort did not target. Both runs
happened on the same day, roughly four hours apart, against the same model. This
measurement cannot separate the change's effect from day-to-day model latency
variance. The table-naming median improvement of 13.7 seconds should be read
with the same doubt, and is not claimed as this effort's result.

Baseline artifacts are untouched. The recorded routing baseline
(`evaluation/Impact_analysis/results/routing_observations.csv`,
`routing_scores.csv`, `routing_run_config.json`) keeps its 180 rows and its
2026-08-27 timestamps. The baseline latency data in `results/latency/` keeps its
2026-09-01 12:44 timestamps. The after run wrote only into
`results/latency_after/`. Neither directory lives in this repository; the
observation CSVs are covered by the caller repository's `.gitignore`, so only
`latency_after/routing_run_config.json` is committed there, matching how the
baseline was handled.
