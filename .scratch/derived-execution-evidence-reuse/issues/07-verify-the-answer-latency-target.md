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

**Status:** ready-for-agent

- [ ] The same questions from the baseline are re-run with the same measurement
      entry point and the same repetition pattern
- [ ] The comparison is per question, not only in aggregate
- [ ] Repetitions within one question are compared for divergence, and a flat set
      of timings is reported as reuse not taking effect in the running service
- [ ] The result is stated against the recorded target — ninetieth percentile
      under thirty seconds — for the table-naming question shape
- [ ] A miss is reported as a miss, together with what the remaining time appears
      to be spent on, and is never presented as a partial success
- [ ] The measurement records whether the service process was warm or freshly
      started, since the first request in a process still pays for the derivation
- [ ] The recorded routing baseline artifacts remain untouched
- [ ] The finding is written into this effort's tickets rather than only reported
      in conversation, so the next effort starts from the measurement
