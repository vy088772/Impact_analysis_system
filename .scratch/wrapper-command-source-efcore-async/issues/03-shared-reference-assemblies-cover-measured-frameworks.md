# 03 — The shared reference assemblies cover the frameworks the measured Systems target

**What to build:** The analyzer resolves a framework type declared by a modern
.NET assembly. Today both the project reader and the wrapper decompiler resolve
their framework types through one shared reference-assembly directory
enumeration, and that enumeration yields .NET Framework 4.8 only. Every
measured repository targets `net6.0` or `net8.0`. Run against the real shared
`CommonLibrary.dll`, the decompiler's own type system reports the abstract
ADO.NET command type as an unknown type with no base types at all — it cannot
answer any question about what that type implements.

This ticket makes the question answerable. The shared enumeration gains the
`net6.0` and `net8.0` reference-assembly sets beside the .NET Framework 4.8 set
it already yields, obtained the same download-without-referencing way, so a
fresh clone needs no manual setup step and the analyzer host's own build is
unaffected. A decompiled assembly is examined against the reference assemblies
for the framework that assembly itself targets, not whichever set happened to
be present.

**This ticket changes no classification on its own.** Its outcome is that a
framework type resolves where it previously did not — the capability ticket 04
consumes. It is sequenced separately because merging it into 04 would make one
ticket too large to land in a single pass.

**Blocked by:** None — can start immediately.

**Status:** resolved

- [x] The abstract ADO.NET command type resolves to a known type, with its implemented interfaces visible, when examined from an assembly targeting `net6.0` or `net8.0`
- [x] The same type keeps resolving as it does today when examined from a .NET Framework assembly — the existing set is added to, never replaced
- [x] The project reader and the wrapper decompiler still resolve framework types through one shared enumeration, so neither can be updated without the other
- [x] A decompiled assembly is examined against the reference assemblies for the framework it targets, and an assembly whose target framework has no reference assemblies available degrades rather than failing
- [x] The reference assemblies are obtained by the same mechanism the existing .NET Framework set uses; the analyzer host's own build still succeeds with no new runtime dependency
- [x] No reported classification changes: the existing `SQLFunc` and `SQLObject` classified surfaces are asserted whole and unchanged, and the real shared assembly's classified and unclassified sets are exactly what ticket 01 and ticket 02 left them

## Note

`tools/StaticAnalyzerHost/WrapperDecompiler.cs` / `StaticAnalyzerHost.csproj`:

- The shared enumeration (`WrapperAssemblyDecompiler.ReferenceAssemblyDirectories`) stays exactly
  as it was for the .NET Framework set — the project reader's `ResolveFrameworkReference` still
  calls it unchanged, and every old-style (non-SDK) project this analyzer reads always targets
  .NET Framework, so that path never needed to change.
- New `ReferenceAssemblyDirectoriesForAssembly(PEFile)` decides which set a *decompiled* assembly
  is examined against, from the assembly's own detected target framework —
  `ICSharpCode.Decompiler.Metadata.DotNetCorePathFinderExtensions.DetectTargetFrameworkId`, already
  shipped in the `ICSharpCode.Decompiler` package this project references, needed no new
  dependency. Measured against the real fixtures: `CommonLibrary.dll` reports
  `.NETCoreApp,Version=v6.0`; `SQLFunc.dll` reports `.NETFramework,Version=v4.5`; `SQLObject.dll`
  reports `.NETFramework,Version=v4.0`. Detection failing outright, and a `.NETFramework,*` id of
  any version, both map to the one existing net48 set — the exact unconditional behaviour every
  decompiled assembly got before this ticket, for a Framework version or a detection failure this
  analyzer's real fixtures have never hit alike, so neither case can regress from "resolves against
  net48" to "resolves against nothing." Only a `.NETCoreApp,Version=v6.0`/`v8.0` id maps to its own
  new set; only an id detection *does* report, that names some other framework this analyzer
  carries no set for (a future net7.0/9.0, .NET Standard, ...), yields no search directories —
  `Decompile`/`AssemblyDefinesType` still complete for that assembly, with the affected external
  types left unresolved, rather than examining it against a Framework set that could answer a
  base-type question wrong instead of correctly declining to answer.
- `StaticAnalyzerHost.csproj` gained `<PackageDownload Include="Microsoft.NETCore.App.Ref"
  Version="[6.0.36];[8.0.29]" />` beside the existing net48 line — downloaded, never referenced,
  same mechanism. `Microsoft.NETCore.App.Ref` ships `ref/net6.0` and `ref/net8.0` under its
  version directory, the same package-root-then-version-directory shape
  `DirectoriesForPackage` already walked for the net48 package, so no new traversal logic was
  needed. This project's own net8.0 build separately triggers an implicit download of the same
  package at the same 8.0.29 version for its own compile-time references, which NuGet flags as a
  duplicate `PackageDownload` item (`NU1505`) against the explicit one above; suppressed in the
  `PropertyGroup` with a comment, since relying on that implicit, TargetFramework-coincidental
  download instead of an explicit one would silently stop supplying net8.0 reference assemblies
  the day this host project's own `TargetFramework` ever moves off net8.0.
- Fresh-clone check: deleted `~/.nuget/packages/microsoft.netcore.app.ref` entirely and rebuilt —
  both `6.0.36` and `8.0.29` were re-downloaded automatically, no manual step, matching the
  existing net48 package's behavior.
- Measured, not guessed, that this ticket makes the question ticket 04 needs answerable, for
  **both** named frameworks, not just one: with a resolver carrying only the pre-ticket net48
  search directory, resolving `System.Data.Common.DbCommand` against the real `CommonLibrary.dll`
  (net6.0) returns an unresolved type (`Kind=Unknown`, zero direct base types) — exactly the
  "unknown type with no base types at all" the ticket describes. Adding the net6.0 set resolves it
  fully: `Kind=Class`, 4 direct base types (`System.ComponentModel.Component`,
  `System.Data.IDbCommand`, `System.IDisposable`, `System.IAsyncDisposable`), 8 counting inherited
  ones. Repeated against a from-scratch net8.0 class library referencing
  `Microsoft.Data.SqlClient` and declaring a method that obtains its command through
  `SqlConnection.CreateCommand()` (this repo has no real net8.0 wrapper fixture): same result,
  `Kind=Unknown` before the net8.0 set and `Kind=Class` with the same 4 direct base types after —
  and that net8.0 DLL decompiles cleanly end-to-end through the real `decompile-wrapper` command
  (`translation_problem_methods: []`). `System.Data.IDbCommand` — the exact contract ticket 04
  checks for — is visible among the resolved base types for both frameworks. No permanent test
  asserts this directly: nothing in today's reported output names a type's base types or
  interfaces (that surface is ticket 04's own addition), so per this repo's "assert the externally
  observable fact" testing convention there is no externally observable fact yet to pin a test to.
  Ticket 04's own acceptance criteria will make this fact observable through classification, at
  which point it gets a real test.
- No classification change, confirmed rather than assumed: the real `SQLDbContext` decompile
  response is byte-for-byte the same set of classified/delegated/unclassified methods ticket 02
  left (re-ran `decompile-wrapper` against the IQCS fixture directly and diffed the shape by eye);
  `tests/test_command_object_recognition.py`'s and `tests/test_delegated_method.py`'s
  fixture-gated real-assembly tests, and `tests/test_wrapper_decompilation.py`'s whole-surface
  `SQLFunc`/`SQLObject` assertions, all pass unchanged.
- Full test suite run before this change (`git stash`) and after, excluding the two scripts that
  need a live ODBC/SQL Server connection unrelated to this ticket: identical 876 passed, the same
  11 pre-existing failures both times (same test names), none newly introduced.
- No `CONTEXT.md`/ADR change: this ticket makes no classification decision of its own to record —
  ticket 04 owns both the **Command Source** amendment and the ADR, per the spec's own sequencing.

### Post-review follow-up

`/code-review` (Spec axis) flagged two things, both addressed:

- **Real regression risk (fixed):** the first cut gated the net48 fallback on
  `targetFrameworkId.StartsWith(".NETFramework")` and returned no search directories whenever
  `DetectTargetFrameworkId` failed to report anything at all — a real behaviour change from the
  pre-ticket unconditional net48 default, for any .NET Framework assembly detection cannot name
  (none of this repo's fixtures hit that case, but the acceptance criterion's "never replaced"
  is an unconditional guarantee, not one scoped to fixtures observed so far). Fixed: detection
  failure now falls back to the net48 set exactly like a `.NETFramework` id does, and only an id
  detection *does* report, naming a framework outside both the Framework and net6.0/net8.0 sets,
  degrades to no search directories. Re-verified: full suite still 876 passed / same 11
  pre-existing failures.
- **Net8.0 asserted, not demonstrated (fixed):** the original Note's measured evidence covered
  only `CommonLibrary.dll` (net6.0) — no fixture or scratch check had touched a real net8.0
  assembly's reference-assembly resolution path. Addressed by building a throwaway net8.0 class
  library against real `Microsoft.Data.SqlClient`/`System.Data.Common` types and repeating the
  same before/after `DbCommand` resolution measurement (see above) — now both named frameworks
  are demonstrated, not just asserted.

The review's third finding (`<NoWarn>` suppressing `NU1505` project-wide rather than only for the
one known duplicate) was left as-is: MSBuild's `NoWarn` has no narrower per-item scope to suppress
into, the duplicate is real and harmless (this project's own net8.0 build implicitly requests the
same package version the explicit line also requests), and dropping the explicit line to avoid the
warning would leave net8.0 reference-assembly provisioning silently dependent on that coincidence
instead of stated outright — the spec's own "obtained the same download-without-referencing way"
wants the explicit line to stay.
