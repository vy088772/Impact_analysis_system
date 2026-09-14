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

**Status:** resolved

- [x] A command type from a provider named nowhere in the analyzer resolves its Command Source, because it implements the command contract
- [x] A type whose name resembles a command type but implements no command contract stays unrecognised when the contract can be checked, so a coincidental name never manufactures a Command Source
- [x] When the contract cannot be checked, the name comparison decides, and a project the analyzer cannot bind resolves exactly the command shapes it resolved before this ticket
- [x] A Command Source resolved by contract and one resolved by name fallback are indistinguishable in the reported result — no new axis is added to the response shape
- [x] The rule is shared by the local source wrapper path and the decompiled external assembly path with no scope switch
- [x] The real shared assembly under the IQCS checkout reports its seven public methods fully accounted for — classified or delegated — except the one Entity Framework Core high-level raw-SQL method, which stays unclassified and names its reason (fixture-gated, skipped when the checkout is absent)
- [x] `CONTEXT.md`'s **Command Source** entry is amended: recognition is by implemented contract first and by name second, and it stops implying that constructing one named type is the only recognised construct
- [x] An ADR records the decision to recognise a command object by contract rather than by name, including the trade-off against the simpler name list that needs no reference assemblies
- [x] The existing `SQLFunc` and `SQLObject` behaviour signatures are byte-for-byte unchanged, so a Contract Fingerprint that did not need to change does not change
- [x] The Y-DOCs WebForms stored-procedure counts rise or hold, never fall

## Note

New `tools/StaticAnalyzerHost/CommandContractRecognition.cs`, edits to
`tools/StaticAnalyzerHost/CSharpAnalyzer.cs` and `tools/StaticAnalyzerHost/WrapperDecompiler.cs`:

- `ICommandContractChecker.ImplementsCommandContract(TypeSyntax)` returns `true`/`false` when it
  can answer whether a syntactic type reference implements `System.Data.IDbCommand`, `null` when
  it cannot. `CommandContractChecks.IsCommandContractType(type, checker)` is the one place that
  ties a checker and the existing widened name comparison (`CSharpAnalyzer.IsSqlCommandType`)
  into a single outcome: `checker?.ImplementsCommandContract(type) ?? IsSqlCommandType(type)`.
  Only `CommandSourceResolver`'s two command-object rules (`ResolveCommandObjectSources`,
  `ResolveDeclaredCommandSources`) call it; the data adapter rule is unchanged and untouched, per
  spec ("only the command object's recognition rule changes").
- Two implementations, one per classification path, both feeding the same `CommandSourceResolver`
  with no scope switch:
  - `RoslynCommandContractChecker` (local source path): wraps the real project `CSharpCompilation`
    `ProjectCompilationResolver.ResolveCompilationForAnalysis` already builds. Resolves a type
    reference via `semanticModel.GetSymbolInfo(type).Symbol as ITypeSymbol` — **not**
    `GetTypeInfo(type).Type`. Measured, not assumed: for a `TypeSyntax` that is the `Type` of an
    `ObjectCreationExpressionSyntax` (e.g. `new FooProviderCommand()`), `GetTypeInfo` on that
    child node returned a null/error type even though the constructor itself resolved cleanly
    (`GetSymbolInfo` on the same node, and on the whole creation expression, both named the exact
    constructor symbol; `_compilation.GetDiagnostics()` held nothing) — that binding happens as
    part of the creation expression's own overload resolution, not independently of it.
    `GetSymbolInfo` resolves the plain type reference directly and was correct in every shape
    tested (object creation, variable declaration, local class, resolvable-only-by-self-reference).
  - `MetadataNameCommandContractChecker` (decompiled path): wraps a metadata-only
    `Compilation` `WrapperAssemblyDecompiler.Decompile` now also builds
    (`BuildContractCompilation`), referencing the decompiled assembly's own file, the reference
    assemblies for its detected target framework (ticket 03's own enumeration, unchanged), and
    every assembly it directly references, resolved through the same `UniversalAssemblyResolver`
    the decompile itself already used. No source is compiled into it — it exists only for
    `Compilation.GetTypeByMetadataName` lookups. A decompiled type is re-parsed from independently
    stringified per-method source with no semantic model of its own, so this resolves a name
    syntactically: as a fully-qualified name when it contains a dot, otherwise under the global
    namespace and then under every namespace the decompiled source's own hoisted `using`
    directives name (mirroring ordinary C# lookup). A name found under two different candidate
    namespaces answers "cannot tell" rather than guessing.
  - Both report `null` — not `false` — for an unresolved reference, a syntax tree outside the
    compilation, or a resolved-but-error-kind symbol. Measured: a wrapper assembly referencing a
    provider type from an assembly deliberately not shipped alongside it (`<Private>false</Private>`,
    then never copied into the decompiled csproj's own directory) still decompiles into ordinary
    syntax (real ADO.NET types resolve; only genuinely unresolvable external references degrade),
    and the name fallback then classifies it exactly as ticket 01 always did.
- `CommandSourceResolver.Resolve(method, checker)` threads the checker into
  `ResolveCommandObjectSources`/`ResolveDeclaredCommandSources`; `CreateDefinition` and both
  `WrapperAnalyzer.GetDefinitions` overloads gained an optional `ICommandContractChecker?
  checker = null` parameter, defaulting to the exact pre-ticket name-only behaviour everywhere
  a checker isn't threaded through. A new `GetDefinitions(sourceRoots, checker)` overload keeps
  the existing memoised, cached path for the common `checker is null` case (used by every other
  caller inside `CSharpAnalyzer.cs` that resolves wrapper definitions for an unrelated purpose —
  Dapper/EF call detection, used-wrapper-identity computation) and only takes the uncached path,
  same as the decompiled path always did, when a real checker is supplied.
- `WrapperAnalyzer.Analyze` (the local source wrapper path's own call-site resolution) builds a
  `RoslynCommandContractChecker` whenever its own `CSharpCompilation?` parameter is non-null —
  which happens only when `ProjectCompilationResolver.ResolveCompilationForAnalysis` found exactly
  one project file across the given scan roots and it built successfully. Every existing test in
  `tests/test_command_object_recognition.py`/`tests/test_delegated_method.py` analyzes one bare
  temporary `.cs` file with no project file at all (`host.analyze_csharp`/`decompile_wrapper`), so
  `compilation` was always null for them before this ticket and stays null now — zero behaviour
  change for the whole existing local-source suite, confirmed by it passing unchanged.
- `DecompiledWrapperClassifier.Classify` builds a `MetadataNameCommandContractChecker` from the
  new `WrapperDecompilationResult.ContractCompilation`/`ImportedNamespaces` fields (both default
  to `null`/absent on every existing `Failed(...)` construction, so a decompile failure is
  unaffected) and passes it to `GetDefinitions`.
- New `tests/test_command_object_recognized_by_contract.py` covers, against real built assemblies
  (`Microsoft.NET.Sdk` net8.0 classlibs referencing only the BCL — no ADO.NET package needed,
  since `System.Data.Common.DbCommand`/`DbConnection`/`IDbCommand` ship in the framework itself):
  - A provider named nowhere in the analyzer (`FooProviderCommand : DbCommand`) resolves its
    Command Source through both the decompiled path and, separately, the local source path (a
    real `.csproj` analyzed via `analyze_csharp_files(..., source_roots=[...])`), demonstrating
    criterion 5 concretely rather than only structurally.
  - A coincidental name (`SqlCommand`, a plain class implementing no interface) declared inside
    the decompiled assembly itself — so the contract question *is* answerable — stays
    unclassified, landing in `unclassified_public_methods` rather than being silently dropped.
  - A wrapper referencing a provider assembly (`NpgsqlCommand`/`NpgsqlConnection`) that is never
    shipped alongside the decompiled DLL still resolves its Command Source, by name fallback.
- Rewrote the two pre-existing stand-in fixtures this ticket's own semantics obsoleted:
  `tests/test_command_object_recognition.py::_build_create_command_dll` and
  `tests/test_delegated_method.py::_build_delegation_shapes_dll` each declared their own
  same-file `DbCommand`/`SqlConnection` classes sharing a real ADO.NET name but implementing no
  contract — exactly the shape criterion 2 now correctly refuses to recognise once the contract
  can be checked. Both rewritten to real `System.Data.Common.DbCommand`/`DbConnection` subclasses
  (a `FakeCommand`/`SqlConnection` pair), keeping every acceptance-tested shape (abstract type via
  `CreateCommand()`, both-own-and-sibling classification, delegation with reshaping, ambiguous
  sibling calls) but now genuinely exercising the contract path instead of a name-only coincidence
  the type no longer represents. All previously-passing assertions in both files hold unchanged
  after the rewrite.
- Real IQCS fixture: unaffected observably. `usp_ExecCmdGetDataSetAsync`'s command is declared as
  the abstract `DbCommand` type, which the name list (widened in ticket 01) already recognises
  syntactically — ticket 03's reference assemblies made the *contract* question answerable for
  this exact case, but the name fallback already answered it correctly before this ticket, so
  ticket 04 changes nothing observable for the five measured Systems. This ticket's value is for a
  System not yet in the catalog, using a provider convention this team has never named — exactly
  what the new synthetic fixtures demonstrate. `tests/test_command_object_recognition.py`'s and
  `tests/test_delegated_method.py`'s fixture-gated real-`CommonLibrary.dll` tests both re-ran
  unchanged and pass: six of seven `SQLDbContext` public methods classified or delegated, one
  (`usp_ExecCmdGetCountAsync`, EF Core's high-level raw-SQL form) still unclassified for its own
  out-of-scope reason — the full acceptance criterion, already satisfied as of ticket 02, holds.
- `SQLFunc`/`SQLObject`: `tests/test_wrapper_decompilation.py`'s whole-surface assertions and
  `tests/test_delegated_method.py`'s fixture-gated `test_real_sqlfunc_gains_no_delegated_method`/
  `test_real_sqlobject_gains_no_delegated_method` all pass unchanged — byte-for-byte, confirmed
  rather than assumed. No dedicated Y-DOCs stored-procedure count tool exists in this repo (same
  gap tickets 01/03 noted); the SQLObject/TTPUR fixture-gated test exercising the real Y-DOCs
  checkout passing unchanged is the verification available for "rise or hold, never fall."
- `CONTEXT.md`'s **Command Source** entry amended to state contract-first, name-second
  recognition and drop the "not one named type alone" phrasing that only ever described the
  *name* list, not the recognition question itself.
- New `docs/adr/0024-a-command-object-is-recognised-by-contract-not-by-name.md` records the
  decision, the alternatives considered (grow the name list forever; recognise by a naming
  convention/suffix instead of a full name), and the trade-off: the name list is demoted to a
  fallback, never deleted, so a project the analyzer cannot bind keeps resolving exactly what it
  resolved before.
- Full test suite run once at the end, excluding the two scripts that need a live ODBC/SQL Server
  connection unrelated to this ticket (`tests/test_search_roles.py`, `tests/test_sp_tables.py`,
  which fail at collection time in this sandbox regardless of this change): 880 passed, 11
  pre-existing failures, none newly introduced by this ticket — none of the 11 failing test files
  reference `CommandSource`/`decompile_wrapper`/`wrapper_source_available`/`IsSqlCommandType` at
  all (checked directly); each failure observed is either database-connectivity-shaped
  (`assert 'unresolved' == 'proven'` against a live SQL cache this sandbox has no ODBC driver for)
  or otherwise in an unrelated area (connection tracking, wrapper contract reconciliation, graph
  reverse lookup, formal output migration) this ticket's diff never touches.
