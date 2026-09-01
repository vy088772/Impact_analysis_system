# 01 — Derived Execution Evidence enters the glossary

**What to build:** A name for the evidence the reverse lookups rebuild on every
request, and a recorded decision explaining why it will be derived once per scope
instead. After this ticket, two people reading the same slow reverse lookup
describe its cause the same way, and a future reader who finds the reuse cannot
mistake it for an unnecessary cache and remove it.

The decision is worth recording because it spends memory to buy latency, and
because it deliberately refuses the tolerant staleness rule used elsewhere in
this repository. That refusal is the part most at risk of being "simplified"
later: an out-of-date object-name index makes a search slower and leaves the
answer alone, whereas out-of-date derived evidence makes the answer wrong, with
nothing in the response to show it.

**Blocked by:** None — can start immediately.

**Status:** done

- [x] `Derived Execution Evidence` is defined in the domain glossary as the rated
      Database Invocations and the Execution Paths built from them, for one
      repository scan and one SQL cache
- [x] The definition states that it is independent of the object a question
      names, and that the name only filters it at the end
- [x] The definition names what its identity depends on, without naming files,
      functions, or storage mechanisms
- [x] The entry carries an `_Avoid_` line, following the existing entries'
      convention, so a second name for the same thing does not appear later
- [x] An ADR records the decision to derive this evidence once per scope rather
      than once per request
- [x] The ADR states the memory-for-latency trade-off, including that the
      retention bound must be justified against the number of systems one
      Cross-system Lookup visits
- [x] The ADR states the asymmetry with the Object Location Index — a stale index
      costs speed, stale Derived Execution Evidence costs correctness — and that
      the freshness check may never be relaxed as an optimisation
- [x] The ADR references the existing Object Location Index decision rather than
      restating it
- [x] `Answer Latency` is referenced as `llamaindex-spec-rag`'s term and is not
      redefined here, following the existing convention for shared cross-
      repository vocabulary
- [x] No implementation detail enters the glossary

**Note:** Glossary entry added to `CONTEXT.md`, placed beside `Object Location
Index` so the two definitions read side by side. Decision recorded as
`docs/adr/0013-derived-execution-evidence-computed-once-per-scope.md`, linking
back to `ADR-0012` for the asymmetry instead of restating it, and linking out to
`llamaindex-spec-rag`'s `CONTEXT.md` for `Answer Latency` instead of redefining
it. This is a documentation-only ticket — no code changed, so no test run applies.
