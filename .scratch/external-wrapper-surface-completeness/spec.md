## Problem Statement

A maintainer refreshes the system `STC`. The refresh reports 21 review candidates out of 40 observation groups. The maintainer cannot tell which of these results need action, and which are correct.

Two distinct defects cause this noise.

First, the External Wrapper Contract for the receiver `SQLFunc` is incomplete. The assembly `SQLFunc.dll` declares three public `CreateTable` overloads. The contract holds only two of them. Production source code calls the missing overload. That call therefore gets the Evidence Status `unresolved`, with the reason `overload_not_found`. The contract nevertheless reports a complete database behavior surface, and it holds the Contract Lifecycle Status `accepted`. The maintainer has no signal that the contract is incomplete.

Second, the call-site analyzer cannot identify which overload a call invokes. The analyzer reports only an argument count for each call to an external wrapper. Twenty Database Invocations match two contract overloads each by argument count alone. The analyzer marks them `ambiguous_overload`. The database evidence is still rated `proven`, but the exact overload identity stays unknown, and each call stays in the review list forever.

## Solution

Deliver two phases.

Phase 1 makes the wrapper decompiler find every public database operation in an assembly. When the decompiler cannot classify a public method that touches a database type, it reports the behavior surface as incomplete. Contract validation then rejects the Implementation Snapshot, instead of accepting a snapshot with a silent gap.

Phase 2 gives the call-site analyzer a Roslyn semantic model. The analyzer builds a compilation from the project's source files, its reference assemblies, and its referenced external assemblies. The semantic model binds each wrapper call to one exact method symbol. The analyzer then reports the full method identity and the parameter types, not only an argument count.

After both phases, a call to a known external wrapper resolves to one overload. The review list holds only the calls that need real human judgement.

## User Stories

1. As a maintainer, I want the wrapper decompiler to classify a wrapper method that builds its command through a data adapter, so that the contract covers every database operation the assembly offers.
2. As a maintainer, I want the decompiler to treat the command text argument of a data adapter constructor as a Command Source, so that a method without an explicit command object still gets a mode and a terminal sink.
3. As a maintainer, I want the decompiler to keep its current classification for a wrapper method that builds an explicit command object, so that the change adds coverage and removes none.
4. As a maintainer, I want the decompiler to record every public method it cannot classify, so that no method disappears from the result without a trace.
5. As a maintainer, I want the decompiler to mark a public method that touches no database type as a non-database operation, so that a utility method does not block contract acceptance.
6. As a maintainer, I want the decompiler to mark a public method that touches a database type but yields no Command Source as unclassified, so that the gap becomes a visible fact.
7. As a maintainer, I want the decompiler to compute the completeness of the public database behavior surface from the assembly's real public method set, so that the completeness claim is honest.
8. As a maintainer, I want Contract Preflight to reject an Implementation Snapshot with an incomplete database behavior surface, so that an incomplete contract never reaches the Contract Lifecycle Status `accepted`.
9. As a maintainer, I want the rejection reason to name the unclassified methods, so that I can decide whether the analyzer needs a new Command Source rule.
10. As a maintainer, I want Contract Preflight to compare an existing contract name without regard to letter case, so that a new revision does not create a second registry entry that differs only by case.
11. As a maintainer, I want the contract registry to hold one entry per contract identity, so that selector lookup never discards an entry through a case collision.
12. As a maintainer, I want to remove the proven incomplete `sqlfunc` contract from the registry, so that no system can bind to it again.
13. As a maintainer, I want to clear the Wrapper Contract Selector for `STC` and refresh once, so that Contract Onboarding builds a complete contract from the current assembly.
14. As a maintainer, I want the refresh to write the new selector back to the system catalog, so that later refreshes reuse the new contract.
15. As an analysis user, I want the call to the previously missing `CreateTable` overload to hold the Evidence Status `proven`, so that its Database Invocation carries a mode and a terminal sink.
16. As a maintainer, I want the call-site analyzer to build one compilation for each scanned project, so that a semantic model can bind wrapper calls.
17. As a maintainer, I want the analyzer to take the reference assembly list from the project file, so that the compilation holds the exact references the project declares.
18. As a maintainer, I want the analyzer to add the project's referenced external assemblies to the compilation, so that the semantic model can bind a call to an external wrapper.
19. As a maintainer, I want the analyzer to fall back to its current syntax-only behavior when no project file exists, so that a source tree without a project file still produces results.
20. As a maintainer, I want the analyzer to report that the semantic model was unavailable, so that a degraded result never looks like a confident result.
21. As a maintainer, I want the analyzer to accept a bound symbol only when the compiler resolved it without ambiguity, so that the system never adopts a compiler guess.
22. As a maintainer, I want the analyzer to reject a bound symbol whose containing assembly differs from the contract's assembly identity, so that a call binds to the exact assembly the contract describes.
23. As a maintainer, I want the analyzer to fall back to argument-count matching when the semantic model produces no confident symbol, so that the result is never worse than today's result.
24. As an analysis user, I want a call to `CreateReader` with a parameter array argument to resolve to the array overload, so that the review list drops that call.
25. As an analysis user, I want a call to `ExeProcRead` with a parameter array argument to resolve to the array overload, so that the review list drops that call.
26. As an analysis user, I want the review list to hold only calls with a real unresolved fact, so that I can act on every entry it shows.
27. As a maintainer, I want the wrapper summary to report how many calls the semantic model resolved, so that I can measure the effect of the change.
28. As a maintainer, I want an end-to-end test that runs the real analyzer host against the real `SQLFunc.dll`, so that a future change cannot silently drop a public method again.
29. As a maintainer, I want a test that asserts an incomplete behavior surface blocks contract acceptance, so that the validation rule stays enforced.
30. As a maintainer, I want a test that asserts a case-different contract name reuses one registry entry, so that the registry keeps one entry per identity.
31. As a maintainer, I want a test that asserts an unconfident symbol falls back to argument-count matching, so that the no-guess rule stays enforced.
32. As a maintainer, I want the tests that need the .NET toolchain to skip cleanly when it is absent, so that the suite still runs in a minimal environment.

## Implementation Decisions

### Phase 1 — Honest Contract completeness

**Command Source.** Introduce this Technical Name for the ADO.NET construct that supplies a wrapper method's command text and terminal sink. The decompiler currently recognizes exactly one Command Source: an explicit command object construction. Replace this single hard-coded check with a named resolver that holds a set of rules.

Implement two rules in this phase:

- an explicit command object construction (the current behavior, unchanged);
- a data adapter construction that takes a command text argument and a connection argument.

A data adapter construction that takes an existing command object is not a new Command Source. That command object is already covered by the first rule.

The second rule yields the mode `inline_sql` unless the method assigns a stored-procedure command type. The terminal sink comes from the adapter's fill call, exactly as today.

Structure the resolver so that a later rule is one added entry, not a change to the surrounding classification flow.

**Public method census.** The decompiler currently reports the completeness of the public database behavior surface as a constant true value. Replace this constant with a computed value.

Compute it from the assembly's public method set, not from the set of methods that classification produced. Assign each public method one of three states:

- **classified** — the resolver found a Command Source, and the method has a mode and a terminal sink;
- **non-database** — the method body touches no ADO.NET type;
- **unclassified** — the method body touches an ADO.NET type, but the resolver found no Command Source.

Report the behavior surface as complete only when no public method is unclassified. Carry the unclassified method identities in the Implementation Snapshot.

The existing snapshot validation already rejects a snapshot whose public database operation surface is incomplete. It also already skips a non-database operation. Reuse both. Add no new validation rule.

**Registry name comparison.** Contract Preflight compares a proposed contract name against existing registry entries with a case-sensitive test. Contract acceptance compares the same thing without regard to letter case. Make Contract Preflight match contract acceptance. This prevents a registry that holds two entries whose names differ only by case, which selector lookup would then collapse into one.

**Re-onboarding procedure.** A valid Wrapper Contract Selector disables decompilation for the whole refresh. A pinned system therefore never re-examines its assembly. Use this manual procedure once, after the code changes land:

1. Back up the contract registry and the system catalog.
2. Remove the incomplete `sqlfunc` entry from the registry.
3. Clear the `wrapper_contract` value for `STC` in the system catalog.
4. Refresh `STC` once.
5. Confirm that Contract Onboarding created a contract that holds three `CreateTable` overloads.

### Phase 2 — Semantic binding at the call site

**Compilation boundary.** Build one compilation for each project file found under a scan root. Take the source file list and the reference list from the project file. Resolve each framework reference against the .NET Framework reference assembly package. Resolve each external assembly reference against the project's output directory.

When a scan root holds no project file, skip compilation and use the current syntax-only path.

**Semantic Binding Availability.** Introduce this Technical Name for the state of the semantic model for one scanned project. It holds one of three values: `available`, `unavailable_no_project_file`, or `unavailable_reference_resolution_failed`.

Report this state in the refresh output. Never let an unavailable semantic model silently reduce the analysis to the syntax-only path without this record.

**Symbol acceptance rule.** Accept a bound method symbol only when both conditions hold:

- the compiler returned one resolved symbol, and returned no candidate set;
- the symbol's containing assembly identity equals the assembly identity that the contract records.

A candidate set means the compiler could not choose. Never adopt a candidate. When the rule rejects a symbol, fall back to the current argument-count path, which yields `ambiguous_overload` where the count is not decisive.

**Reported facts.** When the rule accepts a symbol, report the full method identity and the fully qualified parameter types for the call. The existing contract matching path already prefers a method identity over an argument count, and already compares parameter types. Reuse it unchanged.

**Ordering.** Phase 2 does not replace the contract mechanism. A semantic model proves which overload a call invokes. It cannot prove what that overload does. The mode and the terminal sink still come only from decompiling the assembly. Phase 1 therefore stays required.

## Testing Decisions

A good test here asserts an externally visible fact. It asserts a classification result, an Evidence Status, a completeness verdict, or a registry shape. It does not assert an internal call order, a helper name, or an intermediate structure.

**Seam 1 — analyzer host, end to end.** Prior art: the existing decompilation test that runs the real analyzer host against the real `SQLFunc.dll` and asserts the classified definitions. It already guards itself with a skip marker when the local fixture checkout is absent. Add to this seam:

- the decompiled definition set holds all three `CreateTable` overloads;
- the two-argument `CreateTable` overload carries the mode `inline_sql` and the terminal sink `Fill`;
- the snapshot reports a complete public database behavior surface for this assembly;
- a call to the two-argument `CreateTable` overload yields the Evidence Status `proven`;
- a call to `CreateReader` with a parameter array argument resolves to the array overload.

This seam is the primary one. The defect this spec fixes occurred entirely on the producing side. A test that only exercises the validating side would repeat the mistake.

**Seam 2 — CSharpAnalysisGateway.** Prior art: the existing gateway tests that build a gateway with a synthesized contract and assert the classification of one invocation. Add to this seam:

- an observed call that carries full parameter types selects one overload;
- an observed call that carries only an argument count still yields `ambiguous_overload`;
- an observed symbol whose assembly identity differs from the contract's identity is rejected;
- a recorded unavailable semantic model appears in the result.

**Seam 3 — Contract Preflight.** Prior art: the existing preflight tests that stage proposals against a registry and assert the resulting contract names and lifecycle statuses. Add to this seam:

- a proposal whose name differs from an existing entry only by letter case reuses or versions that entry, and never adds a second entry;
- a snapshot with an unclassified public method fails preflight, and the failure reason names that method.

**Toolchain guard.** The tests in Seam 1 need the .NET toolchain and the local fixture checkout. Follow the existing skip marker pattern. Do not weaken the assertions to make them run without the toolchain.

## Out of Scope

- Revalidating a pinned Wrapper Contract Selector against a changed assembly. Today a bound contract is never re-examined, so a replaced assembly goes unnoticed. This is a real defect of the same family, and it needs its own spec.
- Removing committed transaction artifacts from the contract transaction directory. That directory grows without any cleanup step, and no production code reads its recovery manifests. This is a separate maintenance issue.
- Matching a type identity by its trailing segments. A short type name must never bind to a fully qualified contract type by suffix comparison. This would let two unrelated assemblies appear equal.
- Adding further Command Source rules beyond the two this spec names. Add a rule when evidence shows a real wrapper needs it.
- Changing the `Y-Docs_TTPUR` system, whose selector value is empty, or any other system's selector.

## Further Notes

**Evidence for the defect.** The assembly declares `CreateTable(String, String)`, `CreateTable(String, SqlParameter, String)`, and `CreateTable(String, SqlParameter[], String)`. The contract holds only the last two. The two-argument overload builds its command through a data adapter constructor that takes the command text and the connection. Its body constructs no command object. The classifier drops any method whose body constructs no command object, and it drops it without a record. The sibling method `ExeTable(String, String)` survives, because its body does construct a command object.

The refresh output for `STC` reported `unresolved:2` and 21 review candidates. The missing overload accounts for one unresolved invocation. The table facts for that call survive, because the analyzer extracts them from the inline SQL text. The damage is a downgraded Evidence Status and permanent review noise, not a lost table relation.

**Architecture note.** The analyzer host today performs no semantic analysis. It builds no compilation, and it uses no semantic model. Phase 2 introduces both. This is the largest architectural change in this spec.

**Suggested Architecture Decision Records.** Two decisions here meet the bar for an ADR:

1. Define the completeness of a Verified Implementation Snapshot against the assembly's public method set, rather than against the classifier's output set.
2. Introduce a compilation and a semantic model into the C# analysis host, and define the rule that decides when to trust a bound symbol.

Write both after the change lands.
