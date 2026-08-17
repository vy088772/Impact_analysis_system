# 06 — Resolve a wrapper overload from a bound symbol

**What to build:** A call to an external wrapper resolves to one exact overload. The review list holds only the calls that carry a real unresolved fact, so a maintainer can act on every entry it shows.

Today the analyzer reports only an argument count for a call to an external wrapper. Two contract overloads that share an argument count therefore both match, and the analyzer marks the call `ambiguous_overload`. Twenty calls in one system sit in the review list for this reason alone.

Use the semantic model from the previous ticket to bind each wrapper call to one method symbol. Report the full method identity and the fully qualified parameter types. The contract matching path already prefers a method identity over an argument count, and it already compares parameter types. Reuse it unchanged.

This system refuses to guess. A candidate set means the compiler could not choose, so never adopt a candidate from it.

**Blocked by:** 05.

**Status:** resolved

- [x] The analyzer accepts a bound method symbol only when the compiler returned one resolved symbol and returned no candidate set.
- [x] The analyzer rejects a symbol whose containing assembly identity differs from the assembly identity that the contract records.
- [x] An accepted symbol supplies the full method identity and the fully qualified parameter types for the call.
- [x] A rejected symbol falls back to the argument-count path, so the result is never worse than the result before this ticket.
- [x] A `CreateReader` call that passes a parameter array argument resolves to the parameter array overload.
- [x] An `ExeProcRead` call that passes a parameter array argument resolves to the parameter array overload.
- [x] A refresh of `STC` reports no `ambiguous_overload` review candidate for these calls.
- [x] The wrapper summary reports how many calls the semantic model resolved.
- [x] A test asserts that a call whose symbol the compiler could not resolve falls back to the argument-count path.
- [x] A test asserts that a symbol from an unexpected assembly identity is rejected.

## Answer

**C# host (`tools/StaticAnalyzerHost`).** The `csharp` command now builds a Roslyn compilation
too, not just the separate `semantic-binding` command ticket 05 added.
`ProjectCompilationResolver.ResolveCompilationForAnalysis` (`ProjectCompilation.cs`) reuses the
project reference resolution ticket 05 wrote, but builds the compilation from the *exact same*
parsed syntax trees `CSharpAnalyzer` already uses as analysis context, instead of re-parsing —
Roslyn's semantic APIs require a queried node to belong to a tree the compilation actually
holds. It returns `null` (syntax-only fallback) unless exactly one project resolves across the
given scan roots. `Program.AnalyzeCSharp` wires this in and threads the optional
`CSharpCompilation?` down through `CSharpAnalyzer.Analyze` → `WrapperAnalyzer.Analyze` →
`CreateUnavailableCandidate` (the path that previously reported only an argument count for a
call to an unrecognized external wrapper method).

`WrapperAnalyzer.TryResolveBoundWrapperSymbol` implements the symbol acceptance rule directly:
accepts a bound symbol only when `SemanticModel.GetSymbolInfo(call).Symbol` is a non-null
`IMethodSymbol` **and** `CandidateSymbols` is empty (a non-empty candidate set means overload
resolution failed to choose — never adopt a candidate). An accepted symbol's parameter types are
rendered via a `SymbolDisplayFormat` that matches the existing contract's identity convention
exactly (`string`, `System.Data.SqlClient.SqlParameter[]`, no `global::`), and its containing
assembly is hashed (SHA256, same as `WrapperAssemblyDecompiler.TryGetAssemblyIdentity`) via the
`MetadataReference` Roslyn resolved it from. These facts populate the same
`WrapperMethodIdentity`/`WrapperParameterTypes`/`WrapperAssemblyIdentity` fields the
`source_wrapper` path already used for a different call kind, so nothing downstream needed a new
field to consume them.

**Real bug found and fixed along the way:** an old-style (non-SDK) `.csproj` never lists
`mscorlib` as an explicit `<Reference>` (`csc.exe` adds it implicitly). Ticket 05 never needed
it — it only checked whether declared references resolve as files. This ticket is the first to
actually query the semantic model, and without `mscorlib` every built-in type (`object`,
`string`, ...) failed to bind, so every call site came back as an unresolvable compiler error
regardless of argument types. `ProjectCompilationResolver.ResolveProject` now resolves and adds
it unconditionally, the same way it resolves every other framework reference.

**Python gateway (`code_analyzer/csharp_analysis_gateway.py`).** `reconcile_wrapper`'s
external-wrapper branch now runs the observed bound identity through
`_semantic_bound_method_facts(raw, method_facts, contract)` before calling the (unchanged)
`_wrapper_contract_method`: it discards the bound identity and parameter types entirely — never
just the identity — whenever the call's own bound assembly identity is known and differs from
the contract's own recorded assembly identity (read via `_contract_assembly_identity`, which
checks a top-level field first, then the Implementation Snapshot — the accepted-contract shape
records it only on the snapshot). A discarded identity falls through to the pre-existing
argument-count path unchanged, so the result is never worse than before this ticket.

**Answer field explaining the counter.** `WrapperReconciliation` gained a `semantic_binding_accepted`
field, set exactly where `_semantic_bound_method_facts` accepts or rejects a binding. The wrapper
summary's new `totals["semantic_binding_resolved"]` counter (`service/analyze_service.py`) reads
this reconciled, gateway-computed field — not the raw call-site record — so a call whose bound
symbol was rejected for an assembly mismatch is never counted as "resolved" even though the raw
record still carries the rejected identity as a fact.

**Verification.** Ran a two-axis (Standards + Spec) review against the diff via parallel
sub-agents. Standards found only judgement-call code-duplication (fixed: extracted
`_contract_snapshot_field`, shared by `_contract_assembly_identity` and
`_contract_identity_facts`) and a minor naming nit (addressed with a clarifying comment); no
hard violations. Spec found two real gaps, both fixed: (1) the multi-contract-name
disambiguation loop (`explicit_contract` given as a list, multiple receiver-type matches) called
`_wrapper_contract_method` with the raw bound identity unfiltered by the assembly check — now
routes through the same shared `_semantic_bound_method_facts` gate per candidate contract; (2)
the summary counter counted a rejected binding as "resolved" because it read the raw record
instead of the gateway's verdict — fixed as described above, with a dedicated regression test
(`test_semantic_bound_method_facts_rejects_mismatched_assembly`) exercising the shared helper
directly so neither call site can silently stop routing through it.

Ran the real host end-to-end against the real `STC.csproj`/`SQLFunc.dll` fixtures
(`tests/test_semantic_overload_resolution.py`): a `CreateReader`/`ExeProcRead` call passing a
`SqlParameter[]` argument (e.g. `ApprovalQry.aspx.cs:65`, `CusAppQryDetail.aspx.cs:103`) now
resolves to `SQLFunc.CreateReader(string,System.Data.SqlClient.SqlParameter[])` /
`SQLFunc.ExeProcRead(string,System.Data.SqlClient.SqlParameter[])` respectively, with an assembly
identity matching `config/external_wrapper_contracts.json`'s recorded one exactly. Fed through
the real gateway with the real `sqlfunc` contract, both resolve to `explicit_selected` (not
`ambiguous_overload`), and a synthetic `reconcile_refresh_wrappers` refresh over these real
records reports zero `ambiguous_overload` observations for either method with
`totals["semantic_binding_resolved"] > 0`.

Full test suite: 380 passed, the same 11 pre-existing, environment-specific failures as on a
clean `HEAD` checkout (verified via `git stash` + rebuild) — missing ODBC driver, a hardcoded
Windows path fixture, and a `sqlobject` contract registry entry an earlier ticket's cleanup
removed from `config/external_wrapper_contracts.json`. None of the 11 are new or related to this
ticket.
