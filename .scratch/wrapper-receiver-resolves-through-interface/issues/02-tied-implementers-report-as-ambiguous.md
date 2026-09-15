# 02 — An interface implemented by two or more local classes reports a distinct, reviewable ambiguous outcome

**What to build:** When an interface-typed wrapper receiver has two or more
local classes in the current scan root that both implement it and declare the
called method, the call reports a new, distinct Wrapper Resolution Status —
`ambiguous_implementation` — naming every tied candidate class, instead of
the unchanged/unresolved outcome ticket 01 left this case with. Nobody breaks
the tie by declaration order, file order, or name similarity; the tie is
reported so it can be resolved by a human reading the report alone.

**Blocked by:** 01 — needs the candidate-discovery logic that finds every
local implementer of an interface; this ticket only changes what happens when
that search finds more than one.

**Status:** ready-for-agent

- [ ] An interface with two or more local implementing classes (each
      declaring the called method) reports `ambiguous_implementation`, naming
      every tied candidate class by identity
- [ ] `ambiguous_implementation` is reported as a review-worthy outcome (the
      same review-candidate treatment the existing `ambiguous_contract`
      outcome already receives), never silently passed through as resolved
      evidence
- [ ] The reported reason names the situation explicitly (multiple local
      classes implement the receiver type), distinguishable from every other
      existing unresolved/ambiguous reason
- [ ] An interface with exactly one local implementer (ticket 01's case) is
      unaffected by this ticket — it still resolves source-backed, never
      routed through the new ambiguous outcome
- [ ] A synthetic test fixture with two candidate implementers asserts the
      `ambiguous_implementation` outcome and its named candidates, without
      requiring a real multi-implementer fixture in the real IQCS checkout
- [ ] A second small real- or synthetic-source fixture pair (two classes
      implementing one interface) exercises the ambiguous path end to end,
      confirming the candidate names surface all the way to the reported
      outcome
