# 02 — Record an Answer Latency baseline before anything changes

**What to build:** A recorded before measurement, taken against the service
exactly as it stands, so every later claim in this effort is a comparison rather
than an assertion. Once behaviour changes this measurement can never be taken
again, which is why it comes before the work rather than after it.

The measurement covers the table-naming question shape specifically. That is the
population this effort exists for, and a run that averages it together with the
faster population would hide the effect the work is meant to have.

The caller repository already has a latency measurement entry point that runs a
single agentic routing mode, accepts fewer than three repetitions, and can force
final answer synthesis on. This ticket uses it and adds no measurement code to
this repository.

**Blocked by:** None — can start immediately.

**Status:** done

- [x] A baseline run is recorded against the current service, with no service
      behaviour changed first
- [x] The run covers the table-naming question shape, and its observations stay
      distinguishable from the other question shapes
- [x] The run uses the caller repository's existing latency measurement entry
      point; no measurement code is added to this repository
- [x] The recorded routing baseline artifacts are not overwritten
- [x] The result is written down together with the service state it measured — at
      minimum which repository scans and SQL caches were present, and whether the
      service process was freshly started or already warm
- [x] Per-question elapsed times are retained, not only an aggregate, so a later
      run can be compared question by question
- [x] At least one question is measured three times, because three near-identical
      timings are the specific evidence that nothing is reused today

**Note:** The measurement used `llamaindex-spec-rag`'s existing latency entry
point:
`python -m evaluation.Impact_analysis.latency_measurement --mode 4
--repetitions 3 --synthesis`.

Its loader requires the full reviewed expectation set. The run therefore
covers all 30 questions, not only the table-naming shape. The `question_id`
prefix `table-write-` marks the six table-naming questions. It keeps them
distinguishable from the other 24 questions.

The run wrote 90 observations with zero errors. They live in
`llamaindex-spec-rag/evaluation/Impact_analysis/results/latency/`, a new
directory. The recorded routing baseline in
`evaluation/Impact_analysis/results/` kept its original 180 rows and
timestamps. The run did not touch it.

Service state at measurement time: five repository scans were present,
covering System_Dept_1's Response, ATV, TTPUR, Notification, and STC
projects, saved 2026-08-19 and 2026-08-21. Five SQL caches were present, for
databases ETON, PUR, Response, STC, and SysErrorRecord on
`vmsystest07.topmost.com.tw`, saved 2026-08-21. Table `ManifestNew` lives in
the ETON cache. The measurement process itself started fresh. The on-disk
scan and SQL caches already existed from earlier sessions and were not
rebuilt.

Table-naming population (18 observations — three repetitions of each of
`table-write-001` through `table-write-006`): median 85.9 seconds, range
16.1–152.6 seconds. Only 1 of 18 observations finished under 30 seconds.
Per-question elapsed times, in seconds:
- table-write-001: 81.9, 72.9, 77.0
- table-write-002: 92.8, 16.1, 75.8
- table-write-003: 105.3, 140.6, 104.6
- table-write-004: 92.3, 56.1, 89.8
- table-write-005: 96.0, 60.3, 152.6
- table-write-006: 103.1, 68.6, 69.3

No question's three repeats converge. This matches the spec's premise that
nothing is reused today.

The other 72 observations span the remaining four shapes. Their median is
70.0 seconds. This is higher than the 15.2-second median that `spec.md`'s
Further Notes cites from the phase-1 routing baseline. One difference
explains the gap: this run enables `--synthesis`, and the phase-1 baseline
did not. Every other run setting matches. A later after-measurement must
also enable `--synthesis`, so the comparison stays valid.

Raw data:
`llamaindex-spec-rag/evaluation/Impact_analysis/results/latency/routing_observations.csv`
and `routing_run_config.json`. Neither file lives in this repository.
