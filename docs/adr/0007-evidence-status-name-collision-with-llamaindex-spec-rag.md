# Evidence Status Is Two Distinct Concepts Across This Service and `llamaindex-spec-rag`

**Status:** Accepted
**Date:** 2026-08-18

## Context

This service's `CONTEXT.md` defines Evidence Status as the confidence state of one Database Invocation: `proven`, `likely`, `unresolved`, or `not_applicable`. It rates available execution and target evidence for a single invocation. It is independent of contract selection status.

`llamaindex-spec-rag`'s `CONTEXT.md` defines its own Evidence Status as the explicit state of a relationship or conclusion: `proven`, `partial`, `ambiguous`, or `unresolved`. It rates a per-path or per-query conclusion, not a per-invocation fact.

Both glossaries use the identical term "Evidence Status." Their value sets partially overlap (`proven` and `unresolved` appear in both), which raises the risk that a contributor or an architecture review treats them as one shared concept, or migrates a value or a rule from one system into the other.

No prior ADR in either repository records that this name collision is coincidental rather than a shared design.

## Decision

Evidence Status in this service (`Impact_analysis_system`) and Evidence Status in `llamaindex-spec-rag` are two distinct, unrelated concepts that happen to share a name:

- This service's Evidence Status rates one Database Invocation's execution and target evidence. It answers "how confident is this system in one invocation's database fact?"
- `llamaindex-spec-rag`'s Evidence Status rates one path's or query's conclusion. It answers "how confident is this system in one retrieval-and-reasoning conclusion?"

Neither definition governs the other. A value, a transition rule, or a promotion rule for one repo's Evidence Status must not be assumed to apply to the other repo's Evidence Status. A future merge, alignment, or shared-module proposal between the two must treat this as a name collision to resolve, not an existing shared contract to preserve.

## Consequences

Each repo's `CONTEXT.md` keeps its own independent Evidence Status definition. This service's entry and `llamaindex-spec-rag`'s entry each link to this ADR instead of re-explaining the distinction inline.

A future contributor reading both glossaries side by side has an explicit pointer that the shared name is coincidental. A future architecture review that considers unifying the two concepts must treat that as a new design decision, not a cleanup of an existing duplication.
