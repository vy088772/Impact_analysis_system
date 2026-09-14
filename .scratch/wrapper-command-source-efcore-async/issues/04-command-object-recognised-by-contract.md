# 04 — A command object is recognised by the contract it implements, with the name list as fallback

**What to build:** A type is recognised as a command object when it implements
`IDbCommand` — the interface every ADO.NET command type in .NET is required to
implement, whichever provider or team wrote it. A System from another team,
using a convention nobody here has seen, is covered on the day it enters the
catalog, without that convention being named anywhere in the analyzer.

When the analyzer cannot answer the contract question — an assembly whose
framework has no reference assemblies, or a symbol a partially-bound synthetic
source could not resolve — the rule falls back to the widened name comparison
ticket 01 delivered. A degraded answer is narrower, never wrong. An unbound
type is treated as "cannot answer", never as "does not implement".

The two mechanisms answer one question and produce one outcome. Nothing in the
response records which of the two answered: a Command Source resolved either
way is the same fact.

**Blocked by:** 01 (the widened name list this falls back to), 03 (the
reference assemblies that make the contract question answerable at all).

**Status:** ready-for-agent

- [ ] A command type from a provider named nowhere in the analyzer resolves its Command Source, because it implements the command contract
- [ ] A type whose name resembles a command type but implements no command contract stays unrecognised when the contract can be checked, so a coincidental name never manufactures a Command Source
- [ ] When the contract cannot be checked, the name comparison decides, and a project the analyzer cannot bind resolves exactly the command shapes it resolved before this ticket
- [ ] A Command Source resolved by contract and one resolved by name fallback are indistinguishable in the reported result — no new axis is added to the response shape
- [ ] The rule is shared by the local source wrapper path and the decompiled external assembly path with no scope switch
- [ ] The real shared assembly under the IQCS checkout reports its seven public methods fully accounted for — classified or delegated — except the one Entity Framework Core high-level raw-SQL method, which stays unclassified and names its reason (fixture-gated, skipped when the checkout is absent)
- [ ] `CONTEXT.md`'s **Command Source** entry is amended: recognition is by implemented contract first and by name second, and it stops implying that constructing one named type is the only recognised construct
- [ ] An ADR records the decision to recognise a command object by contract rather than by name, including the trade-off against the simpler name list that needs no reference assemblies
- [ ] The existing `SQLFunc` and `SQLObject` behaviour signatures are byte-for-byte unchanged, so a Contract Fingerprint that did not need to change does not change
- [ ] The Y-DOCs WebForms stored-procedure counts rise or hold, never fall
