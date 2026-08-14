# 06 — Resolve a wrapper overload from a bound symbol

**What to build:** A call to an external wrapper resolves to one exact overload. The review list holds only the calls that carry a real unresolved fact, so a maintainer can act on every entry it shows.

Today the analyzer reports only an argument count for a call to an external wrapper. Two contract overloads that share an argument count therefore both match, and the analyzer marks the call `ambiguous_overload`. Twenty calls in one system sit in the review list for this reason alone.

Use the semantic model from the previous ticket to bind each wrapper call to one method symbol. Report the full method identity and the fully qualified parameter types. The contract matching path already prefers a method identity over an argument count, and it already compares parameter types. Reuse it unchanged.

This system refuses to guess. A candidate set means the compiler could not choose, so never adopt a candidate from it.

**Blocked by:** 05.

**Status:** ready-for-agent

- [ ] The analyzer accepts a bound method symbol only when the compiler returned one resolved symbol and returned no candidate set.
- [ ] The analyzer rejects a symbol whose containing assembly identity differs from the assembly identity that the contract records.
- [ ] An accepted symbol supplies the full method identity and the fully qualified parameter types for the call.
- [ ] A rejected symbol falls back to the argument-count path, so the result is never worse than the result before this ticket.
- [ ] A `CreateReader` call that passes a parameter array argument resolves to the parameter array overload.
- [ ] An `ExeProcRead` call that passes a parameter array argument resolves to the parameter array overload.
- [ ] A refresh of `STC` reports no `ambiguous_overload` review candidate for these calls.
- [ ] The wrapper summary reports how many calls the semantic model resolved.
- [ ] A test asserts that a call whose symbol the compiler could not resolve falls back to the argument-count path.
- [ ] A test asserts that a symbol from an unexpected assembly identity is rejected.
