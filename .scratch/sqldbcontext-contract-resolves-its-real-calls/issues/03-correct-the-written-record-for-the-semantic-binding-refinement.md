# 03 — Correct the written record for the semantic-binding refinement

**What to build:** ADR-0028 and `accepted-contract-resolves-its-calls`'s own
Implementation Decisions section are corrected to describe, accurately, a
refinement the shipped code already contains: an omitted trailing optional
argument's declared default value is read via semantic binding to the
referenced assembly's own metadata — the same binding the analyzer host
already uses elsewhere for a wrapper call's own method identity — guarded so
that only a uniquely bound symbol (no candidate ambiguity) is trusted. This is
not a Contract read, and ADR-0028's "no Contract input channel" guarantee is
unaffected; only the "from the syntax alone" phrasing overstated the
mechanism. No code changes accompany this ticket.

**Blocked by:** None — independent of tickets 01 and 02, can start
immediately or run in parallel.

**Status:** ready-for-agent

- [ ] ADR-0028 gains a dated amendment (following the ADR-0006-amends-ADR-0005
      precedent) stating the semantic-binding refinement and its guard.
- [ ] The amendment states plainly that semantic binding to a referenced
      assembly's own metadata is not a Contract read, so ADR-0028's original
      guarantee is not mistaken for broken.
- [ ] `accepted-contract-resolves-its-calls`'s own Implementation Decisions
      section no longer states the analyzer host records these facts "from
      the syntax alone" without qualification; the corrected text points at
      the ADR-0028 amendment for the full guard description.
- [ ] No production code changes accompany this ticket.
