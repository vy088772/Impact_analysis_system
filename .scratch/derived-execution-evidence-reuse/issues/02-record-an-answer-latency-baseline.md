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

**Status:** ready-for-agent

- [ ] A baseline run is recorded against the current service, with no service
      behaviour changed first
- [ ] The run covers the table-naming question shape, and its observations stay
      distinguishable from the other question shapes
- [ ] The run uses the caller repository's existing latency measurement entry
      point; no measurement code is added to this repository
- [ ] The recorded routing baseline artifacts are not overwritten
- [ ] The result is written down together with the service state it measured — at
      minimum which repository scans and SQL caches were present, and whether the
      service process was freshly started or already warm
- [ ] Per-question elapsed times are retained, not only an aggregate, so a later
      run can be compared question by question
- [ ] At least one question is measured three times, because three near-identical
      timings are the specific evidence that nothing is reused today
