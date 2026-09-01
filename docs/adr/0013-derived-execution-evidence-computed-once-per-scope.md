# Derived Execution Evidence Is Computed Once per Scope, Not Once per Request

**Status:** Accepted
**Date:** 2026-09-01

## Context

`/find_by_sp` and `/find_by_table` answer a reverse-lookup question by rating every Database
Invocation and building every Execution Path for the repository scan and SQL Cache Identity
under review, then filtering that evidence down to the object the question names. Today this
rating and building work repeats on every request, even when two requests in a row ask about
the same repository scan and the same SQL Cache Identity and differ only in the object name.

This work is the dominant cost of a slow reverse lookup. `llamaindex-spec-rag`'s
[Answer Latency](../../../llamaindex-spec-rag/CONTEXT.md) target — a ninetieth percentile under
thirty seconds, counted from question to visible answer — is spent disproportionately here, on
evidence that the object name never actually narrows until the last step.

Ticket 01 ([issue 01](../../.scratch/derived-execution-evidence-reuse/issues/01-derived-execution-evidence-enters-the-glossary.md))
named this evidence Derived Execution Evidence and recorded its glossary entry. This ADR records
the decision that motivated naming it: derive it once per scope and reuse it, rather than
rebuild it on every request.

## Decision

Derived Execution Evidence is derived once per (repository scan, SQL Cache Identity) scope and
held for reuse by every request that scope answers, until the scope's inputs change. A request
that names an object no longer triggers its own rating-and-building pass; it filters the
scope's already-derived evidence by name.

This spends memory to buy latency. The retention bound for how long, and how much, derived
evidence is kept must be justified against the number of systems one Cross-system Lookup
visits — a bound sized for a single-system question will not hold once a lookup fans out across
several systems' scopes at once, and a bound picked without that number in mind is not a
considered choice.

This decision deliberately does not extend the tolerant-staleness rule this repository already
applies elsewhere. [ADR-0012](0012-object-location-index-authoritative-pruning.md) established
that a stale Object Location Index degrades to slow, never to wrong, because a stale index can
only fail to prune — the caller falls back to reading the cache in full. Derived Execution
Evidence carries no equivalent fallback: an out-of-date rating or path is not the whole truth
read the slow way, it is a wrong answer presented as a good one, with nothing in the response to
mark it as such. The freshness check that invalidates a scope's derived evidence when either
input changes may never be relaxed as a latency optimisation — doing so would trade a
detectable slow path for an undetectable wrong one, which is the opposite of what ADR-0012
decided for the index.

## Consequences

- A reverse lookup's cost now scales with how often a scope's inputs change, not with how many
  requests ask about that scope. Two back-to-back requests against the same repository scan and
  SQL Cache Identity share one derivation.
- The retention bound is a capacity-planning decision, not a fixed constant: it must be
  revisited whenever the number of systems a single Cross-system Lookup can span changes.
- Any future proposal to relax, widen, or skip the freshness check for Derived Execution
  Evidence — for latency, for memory, or for implementation convenience — is a reversal of this
  ADR and needs its own decision record, not a quiet code change.
- This ADR does not restate `Object Location Index` or `Answer Latency`; the former is defined
  in this repository's `CONTEXT.md` and decided in ADR-0012, the latter is `llamaindex-spec-rag`'s
  term and stays defined only there.
