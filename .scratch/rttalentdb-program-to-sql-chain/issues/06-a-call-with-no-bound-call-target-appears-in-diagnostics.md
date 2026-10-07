# 06 — A call with no Bound Call Target appears in diagnostics

**What to build:** When a call has no Bound Call Target, the forward chain
stops that branch and tells the user why. A user who sees no stored
procedure can then tell "no database access" from "the analysis could not
follow this call".

Two cases give no Bound Call Target: an interface with no Local Implementer,
and an interface with two or more (`ambiguous_implementation`). The chain
does not guess an implementation. The chain `diagnostics` lists the caller
method, the call, and the reason. For `ambiguous_implementation`, it names
every candidate class.

See ADR-0044.

**Blocked by:** 05

**Status:** ready-for-agent

- [ ] A call through an interface with no Local Implementer appears in
      `diagnostics` with its reason
- [ ] A call through an interface with two Local Implementers appears in
      `diagnostics` as `ambiguous_implementation` and names both classes
- [ ] The chain does not follow either implementer of an ambiguous interface
- [ ] The RTTalentDB interface with two implementers appears in the
      `diagnostics` of each action that calls it
