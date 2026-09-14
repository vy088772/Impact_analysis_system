# A Command Object Is Recognised By Contract, Not By Name

**Status:** Accepted
**Date:** 2026-09-14

## Context

Five ASP.NET Core Systems — IQCS, RTTalentDB, ETR, EnterpriseApp and TOPCSCY — all reach their database through the same shared assembly, `CommonLibrary.dll`. That assembly's `SQLDbContext` exposes seven public database methods. Before ticket 01, the analyzer classified none of them, because its command-object recognition rule compared a type's short name against exactly one literal (`SqlCommand`), and `SQLDbContext` obtains its command through `Database.GetDbConnection().CreateCommand()` — a call declared to return the abstract ADO.NET command type, not the one name the rule knew.

Ticket 01 widened that name comparison to a multi-provider list, matching the sibling data-adapter rule's shape. That widening was measured, not assumed: it resolved the specific methods present in the real shared assembly today. But a name list is a list of what this team has already seen. The catalog exists to take on other teams' Systems, and each of those carries its own ADO.NET convention — a provider this team has never named, wrapped in a type this team has never seen. Under a name-only rule, every one of those arrives as a silent empty result, followed by a new ticket to add one more name.

The real fix was available in principle from the start: every ADO.NET command type in .NET, from every provider, is contractually required to implement `System.Data.IDbCommand`. A rule that asks "does this type implement the command contract?" needs no foreknowledge of what that type is called. It was not implemented first because the analyzer could not yet answer that question on the assemblies that mattered: measured directly, the wrapper decompiler's own type system reported the abstract command type as `Unknown`, with no base types at all, when resolving it against `CommonLibrary.dll` — a net6.0 assembly examined with only .NET Framework 4.8 reference assemblies on hand. Ticket 03 closed that gap by adding net6.0 and net8.0 reference assemblies to the shared enumeration both the project reader and the wrapper decompiler already draw from.

## Decision

A type is a command object when it implements `IDbCommand`. The command-object recognition rules — an explicit `new` construction and a factory-obtained local declared as a command type — ask this question first, whenever the analyzer holds enough type information to answer it:

- For the local source wrapper path, that means a real project compilation exists and the type's own syntax tree is part of it; the compiler's semantic model answers via `IDbCommand`'s presence among the type's (possibly inherited) interfaces.
- For the decompiled external assembly path, that means a metadata-only compilation built from the decompiled assembly's own resolved references — the reference assemblies for its target framework, the assembly itself, and every assembly it directly references — can name the type by metadata name and inspect its interfaces.

When neither can answer — no project compilation at all, a framework with no reference assemblies on hand, or a reference the decompiler's resolver could not locate on disk — the rule falls back to the existing widened name comparison unchanged. Nothing in the reported result records which of the two mechanisms decided: a Command Source resolved by contract and one resolved by name are the same fact, because the response shape this analyzer emits is already wide enough without a new axis that answers a question nobody downstream asked.

An unbound type is always treated as "cannot answer," never as "does not implement." Type binding over a decompiled, per-method re-parsed source is partial by nature — a synthetic class built by concatenating independently decompiled method bodies will not bind every symbol it names — and a rule that mistook an unresolved reference for a definite "no" would silently narrow what this analyzer had always resolved by name, exactly the regression the fallback exists to prevent.

## Alternatives considered

**Keep growing the name list.** Simpler, and needs no reference assemblies at all — the fallback already is this alternative, kept for exactly the case where contract-checking cannot run. Rejected as the *only* mechanism because it does not generalise: five Systems already converged on one shared assembly and one convention; the catalog's own purpose is to take on Systems this team has not seen, each arriving with its own convention. A name list answers "what has this team already met," not "what does this type do."

**Recognise the contract by convention (e.g. any type whose name ends in `Command`).** Rejected: this is the name list already, wearing a suffix instead of a full name, and made no more honest by the disguise — it still manufactures a Command Source from a coincidental name, which is exactly the failure ticket 04's own acceptance criteria rule out.

## Consequences

A command type from a provider named nowhere in this analyzer is recognised the day it enters the catalog, without a ticket. A type that merely resembles a command type by name (`SqlCommand` declared as some unrelated local class) no longer manufactures a Command Source when the contract can be checked — a real behaviour change from name-only matching, deliberately: the two ticket-01 fixtures that exercised this exact stand-in-name shape were rewritten to construct real `System.Data.Common.DbCommand`/`DbConnection` subclasses, because a coincidental name is no longer a fact this analyzer treats as true when it can check.

The trade-off is reversible in the direction that matters: the name list never leaves. It is demoted to a fallback, not deleted, so a project the analyzer cannot bind — no compilation, no resolvable reference assemblies — resolves exactly the command shapes it has always resolved. Growing the fallback list for a genuinely unresolvable project remains available, and cheap, exactly as before.
