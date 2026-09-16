# 01 — The ADRs and the glossary record the decisions

**What to build:** Three ADRs and one glossary, written before any code uses
their vocabulary. Every later ticket names a field, a status value or a report
column after a term defined here, so the terms settle first and no two tickets
invent a different name for the same thing.

ADR 0027 records that a Delegation Alias sits outside a Contract's behavior
signature. The registry computes the Contract fingerprint from the behavior
signature alone, so aliases never change a fingerprint, and a System that
already reuses a Contract by fingerprint keeps reusing it.

ADR 0028 records that the Command Mode resolves at rating time, and that the
scan stays free of any Contract knowledge. The scan produces facts and the
rating step interprets them. This ADR also records the rejected alternative — a
Contract-aware second scan pass, with its trigger, its refinement marker and its
termination rule — and why the rating-time answer removed the need for it. It
records one accepted risk: the same `true`/`false` convention now lives in the
analyzer host for a local wrapper and in the analysis gateway for an external
wrapper, and the two can drift.

ADR 0029 records that Observed Call Evidence requires at least one record. A
method with no record at all is never cleared, because the scan does not record
a call to another method inside the same project. An absence of records is not
evidence of safety.

The project's existing domain context glossary gains five terms: Delegation
Alias, Observed Argument Facts, Rating-Time Command Mode, Observed Call Evidence
and Global Exclusion Tier. They go into the glossary the project already keeps,
not into a second file.

The glossary already defines a Delegated Method, and states that the finding
never follows a delegation chain. That definition stays true and is not
rewritten. A Delegation Alias is a second, distinct term: the entry derived from
that finding for a Contract, and its derivation is the one step that follows a
chain to its end. The two definitions cross-reference each other.

**Blocked by:** None — can start immediately.

**Status:** done

- [x] ADR 0027 states that a Delegation Alias sits outside the behaviour
      signature, and states the consequence: the Contract Fingerprint does not
      change and cross-System reuse survives
- [x] ADR 0028 states that the Command Mode resolves at rating time and that the
      analyzer host gains no Contract input
- [x] ADR 0028 records the rejected Contract-aware re-scan, including its
      trigger, refinement marker and termination rule, and why none of them is
      needed
- [x] ADR 0028 records the accepted risk that the `true`/`false` convention
      lives in two places
- [x] ADR 0029 states that Observed Call Evidence requires at least one record,
      and states why an absence of records proves nothing
- [x] The project's existing glossary defines Delegation Alias, Observed
      Argument Facts, Rating-Time Command Mode, Observed Call Evidence and
      Global Exclusion Tier
- [x] The existing Delegated Method definition keeps its non-transitive rule,
      and cross-references Delegation Alias for the one step that follows a
      chain
- [x] Each ADR follows the format the existing ADRs use, and takes the next free
      number in the existing sequence
