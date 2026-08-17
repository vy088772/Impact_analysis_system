# 05 — Build a compilation per project and report Semantic Binding Availability

**What to build:** A maintainer can see whether the analyzer had a semantic model for each scanned project. The analyzer builds a compilation from the project's own declarations, and it reports the result of that attempt. Classification results do not change yet.

The analysis host performs no semantic analysis today. It builds no compilation, and it uses no semantic model. It reads syntax trees alone. This ticket adds the compilation and the reporting, and nothing else. It is the tracer bullet for the next ticket.

Introduce **Semantic Binding Availability** as the named state of the semantic model for one scanned project. It holds one of three values: `available`, `unavailable_no_project_file`, or `unavailable_reference_resolution_failed`.

A degraded analysis must never look like a confident analysis. Report the state, and never fall back in silence.

**Blocked by:** 04 — the contract side must be correct and verified before the call-site side changes, so that a later result difference has one cause and not two.

**Status:** resolved

- [x] The analyzer builds one compilation for each project file found under a scan root.
- [x] The compilation takes its source file list and its reference list from the project file.
- [x] A framework reference resolves against the .NET Framework reference assembly package.
- [x] An external assembly reference resolves against the project output directory.
- [x] A scan root that holds no project file yields the state `unavailable_no_project_file`, and the analyzer uses the syntax-only path.
- [x] A reference that fails to resolve yields the state `unavailable_reference_resolution_failed`, and the analyzer uses the syntax-only path.
- [x] The refresh output reports the Semantic Binding Availability for each scanned project.
- [x] Every classification result stays identical to the result before this ticket.
- [x] The analyzer builds one compilation for each project, and not one for each file.
- [x] A test asserts that a scan root without a project file reports `unavailable_no_project_file`.

## Answer

Added a new `semantic-binding` command to StaticAnalyzerHost (`tools/StaticAnalyzerHost/ProjectCompilation.cs`),
kept entirely separate from the existing `csharp` command so no existing classification path is
touched at all.

**`ProjectCompilationResolver.Resolve`** finds every `*.csproj` under a scan root and builds one
Roslyn `CSharpCompilation` per project file (never per source file — verified by a dedicated
test). A scan root with no project file yields exactly one `unavailable_no_project_file` entry
(naming no project file, since there is none).

**`ProjectFileReader`** reads the source file list from `<Compile Include>` and the reference list
from `<Reference Include>`/`<HintPath>` — the same old-style (non-SDK) `.csproj` shape
`AssemblyReferenceResolver` already parses for the wrapper decompiler (confirmed against the real
`STC.csproj` fixture: bare `<Reference Include="System" />` for framework assemblies,
`<HintPath>bin\SQLFunc.dll</HintPath>` for external ones).

**Reference resolution**: a framework reference (no `HintPath`) resolves against the same
downloaded `.NET Framework reference assembly package` directories the wrapper decompiler already
uses (`WrapperAssemblyDecompiler.ReferenceAssemblyDirectories()`, widened from `private` to
`internal` for reuse). An external reference (`HintPath` present) resolves relative to the
project's own directory — the project's output/bin directory in every real fixture (`bin\SQLFunc.dll`,
`bin\DataCheck.dll`). A `<ProjectReference>` (added after the first code-review pass — see below)
is treated as unresolved rather than silently dropped, since building another project's project
file too is out of scope for this ticket.

Any unresolved reference (framework, external, or project) fails the whole project's attempt with
`unavailable_reference_resolution_failed` and names every reference that could not be resolved.

**Python side**: `StaticAnalyzerHost.semantic_binding_availability(scan_roots)` calls the new host
command once per scan (not once per file batch, since Semantic Binding Availability is a per-project
fact, not a per-file one). `ProjectScanner.scan_project()`/`refresh_csharp_files()` populate a new
`ProjectScanResult.semantic_binding_availability` field; `_merge_scans` concatenates it across scan
roots; `refresh_source()` surfaces it in its output dict under the same key. `scan_store._CACHE_VERSION`
bumped to 28 so an old on-disk scan cache (with no such field) is honestly re-scanned rather than
silently reporting nothing.

**Verification**: ran `/code-review`-equivalent two-axis review (Standards + Spec) against the diff.
Standards axis found only judgement-call smells consistent with existing local convention (no fixes
needed). Spec axis found one real gap — `<ProjectReference>` items were silently ignored, which could
let a project with an unresolvable project dependency get reported `available` — fixed as described
above, with a regression test (`test_semantic_binding_reports_unavailable_for_unresolved_project_reference`).

Ran the real host against the real `STC.csproj` fixture end-to-end: reports `available` with no
unresolved references (all 24 `<Compile>` items exist on disk; both `SQLFunc`/`DataCheck` external
references and every bare framework reference resolve). Full test suite (`372 passed`, the same
`11` pre-existing, environment-specific failures as on a clean `HEAD` checkout — verified via
`git stash -u` + rebuild, unrelated to this ticket: missing ODBC driver, a hardcoded Windows path
fixture, and an already-empty `sqlobject` contract registry entry from an earlier ticket).

Added a `CONTEXT.md` glossary entry for the new Technical Name **Semantic Binding Availability**,
following the existing entry format (matches the precedent set for **Command Source** in an
earlier ticket of this same spec).
