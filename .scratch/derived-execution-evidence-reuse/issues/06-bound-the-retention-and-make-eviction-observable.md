# 06 — Bound the retention and make eviction observable

**What to build:** A stated, justified limit on how much Derived Execution
Evidence is retained at once, and a trace whenever that limit forces something
out.

Two systems carry repository scans today and any limit would do. The catalog is
expected to reach roughly one hundred systems, each declaring around four
Databases. A single Cross-system Lookup visits every system once before coming
back to the first, so a limit below the number of systems visited would evict
every derivation before the next question could reuse it. The reuse would then
buy nothing while still costing the memory it took to build, and nothing in the
service's behaviour would say so — it would simply be slow again, and the obvious
conclusion would be that the reuse never worked.

That silent failure is what this ticket exists to prevent. The number matters
less than writing it down against the thing that determines it, and than making
the moment it is crossed visible.

**Blocked by:** 05 (there is nothing to bound until both halves are retained).

**Status:** ready-for-agent

- [ ] Retention has an explicit limit rather than growing without bound
- [ ] The limit is documented against the number of systems one Cross-system
      Lookup visits, including the reasoning that a smaller limit evicts entries
      before they can be reused and makes the reuse worthless
- [ ] The limit is adjustable without a code change, so a growing catalog does
      not need an edit to raise it
- [ ] Reaching the limit and evicting is recorded observably, so a service whose
      reuse has stopped working reports it instead of merely being slow
- [ ] Eviction never changes an answer: an evicted scope derives again on its next
      request and returns the same result
- [ ] Exceeding the limit is exercised by a test that asserts the eviction, the
      record of it, and the unchanged answer
- [ ] The pre-existing unbounded in-memory retention of repository scans and SQL
      caches is left alone; this ticket bounds only what this effort introduced,
      and notes the pre-existing risk rather than silently changing it
