# 05 — SDK-style projects compile

**What to build:** An ASP.NET Core project gets a real semantic model, so every later ticket that
needs a receiver's declared type has one to ask.

The project reader learns the SDK-style form: source files come from implicit
globbing with removal items honoured, and references come from package
references resolved through the project's restore assets. When a project has no
restore assets, the refresh restores it once. When no .NET SDK is available, or
the restore fails, the project says so rather than pretending.

One measured repository already carries restore assets and must report available
without any restore being run. Another carries none and must report available
only after one.

**Blocked by:** 02.

**Status:** done

- [x] An SDK-style project's source files are discovered by implicit globbing.
- [x] A removal item excludes the files it names, so an excluded directory contributes no source.
- [x] Package references resolve through the project's restore assets.
- [x] A project that already carries restore assets reports `available` with no restore run.
- [x] A project with no restore assets is restored once, then reports `available`.
- [x] When no .NET SDK is available, the project reports `unavailable_reference_resolution_failed` and names the cause.
- [x] When a restore fails, the project reports `unavailable_reference_resolution_failed` and names the cause.
- [x] A project reference stays unresolved, and the referencing project reports `unavailable_reference_resolution_failed` naming it.
- [x] Old-style project handling is unchanged, verified against the existing WebForms project that reports `available` today.

## Note

### Where the code is

Three new files beside the existing `ProjectCompilation.cs`, split the way `PackageRestorer.cs`
already sits beside it — one reason to change per file:

- `tools/StaticAnalyzerHost/SdkProjectReader.cs` — `MsBuildItemPattern` (glob matching),
  `SdkProjectReader` (implicit globbing, removal items, package reference list),
  `SdkImplicitUsings`.
- `tools/StaticAnalyzerHost/RestoreAssets.cs` — `RestoreAssetsReader`, which turns
  `obj/project.assets.json` into a reference list, and `AssemblySet`, which resolves conflicts
  between two assemblies of the same name.
- `tools/StaticAnalyzerHost/SdkPackageRestorer.cs` — `DotnetSdk` (locating an SDK) and
  `SdkPackageRestorer` (running one restore).

`ProjectCompilation.cs` gains `ProjectXml` (one loaded project file plus its XML namespace, so no
reader carries both halves around), and `ProjectFileReader.Read` now branches once into
`ReadOldStyle` or `ReadSdkStyle` instead of asking "is this SDK-style?" at every field.
`ResolveProject` branches once more into `ResolveOldStyleReferences` or `ResolveSdkStyleReferences`.

### How references resolve

Everything an SDK-style project needs is inside its own restore assets, so nothing here guesses at
a NuGet layout or hunts through a .NET installation:

- **Package assemblies**: `targets/<tfm>/<Id>/<Version>/compile` names the exact compile-time
  assembly, `libraries/<Id>/<Version>/path` names the folder, and `packageFolders` names the roots.
  A compile item ending in `_._` is NuGet's "no compile-time assembly" marker and names no file.
- **Framework assemblies**: a framework reference resolves to a targeting pack, which arrives one
  of two ways. A pack the installed SDK does not ship is downloaded during restore, and the assets
  pin its version as a download dependency named `<framework reference>.Ref`. A pack the SDK does
  ship sits in the installation, which the assets name through `runtimeIdentifierGraphPath`.

**Assembly conflict resolution was not optional.** A targeting pack and a package both ship
`Microsoft.Extensions.Logging`, and a package may still ship a .NET Standard facade for a framework
assembly. Handing Roslyn both copies made every type in them ambiguous: measured on IQCS, **49,781
compiler errors**, `System.Void` itself among the types that stopped resolving. `AssemblySet` keeps
one file per assembly name and lets the higher assembly version win, which is the rule MSBuild's
own conflict resolution follows. Preferring the targeting pack unconditionally is *wrong* — it
leaves EF Core 7 packages compiling against `Microsoft.Extensions.*` 6.0 and produces CS1705.

### Two things beyond the bullet list

**1. Implicit usings (`SdkImplicitUsings`).** Not in the acceptance criteria, and kept anyway,
because without them the ticket's own goal — "a real semantic model, so every later ticket that
needs a receiver's declared type has one to ask" — is not met. The .NET SDK generates the global
usings file at *build* time, so it exists nowhere in a clone and nowhere this reader could find it.
Every measured ASP.NET Core project enables `ImplicitUsings`, and their source relies on it:
`IQCS/Interfaces/IDefMonthlyQryService.cs` declares `Task<object> Query(...)` with no using
directive above it at all. Measured, with the rest of this ticket in place:

| Project | Errors without implicit usings | Errors with |
| --- | --- | --- |
| IQCS | 2848 | 1 |
| RTTalentDB | 1786 | 1 |

The one remaining error in each is CS8805 (top-level statements in a compilation built as a
library). It does not affect symbol binding, and setting `OutputKind` from `<OutputType>` was left
out of scope.

**This is the one part of the ticket with no automated test**, and deliberately so rather than by
oversight: Semantic Binding Availability reports reference resolution, never compiler diagnostics,
so no surface this ticket owns can observe it. Ticket 06 binds a wrapper call to a symbol; that is
where a test can assert a symbol actually binds, and it should.

**2. `source_file_count`** joins each reported entry. Without it, "source files are discovered by
implicit globbing" and "a removal item excludes the files it names" have no observable outcome at
all — both produce `available` either way. An SDK-style project names none of its source files, so
the count is the only place a maintainer sees what the model holds. The host contract version
stays 2: the field is additive and the Python client reads entries by key.

### Behaviour that changed for old-style projects

One, deliberately: an unresolved `<ProjectReference>` now settles the answer *before* any reference
resolution runs. Nothing below could have changed that answer, and a project already known
unavailable must never pay for a package restore — up to 600 seconds of one, in the SDK-style case.
The old-style project-reference test is unaffected, because it asserts the project reference is
named, not what else is.

Everything else old-style is untouched: `mscorlib` is still added implicitly (and must *not* be
added to an SDK-style project, whose own framework references already declare every built-in type),
bare `<Reference>` items still resolve against the .NET Framework reference assemblies, and the
`packages.config` restore path is unchanged.

### Tests

Ten added to `tests/test_semantic_binding_availability.py`, red before the change:

- `test_sdk_style_source_files_come_from_implicit_globbing` — a file in a subdirectory counts,
  `bin` and `obj` never do.
- `test_sdk_style_removal_item_excludes_the_directory_it_names` — `<Compile Remove="HisFiles\**" />`,
  the real IQCS shape.
- `test_sdk_style_package_references_resolve_through_restore_assets`
- `test_sdk_style_project_carrying_restore_assets_is_not_restored_again` — proof is behavioural:
  the package exists on no feed, while hand-written assets resolve it to a real assembly. A restore
  would have failed, so `available` means none ran. The assets file is asserted byte-identical after.
- `test_sdk_style_project_without_restore_assets_is_restored_once`
- `test_sdk_style_project_names_the_cause_when_no_dotnet_sdk_is_available` — runs the real host
  binary with `DOTNET_ROOT` pointing at a directory holding no .NET. It builds the command line
  itself rather than going through `StaticAnalyzerHost.semantic_binding_availability`, so that a
  test-only `env` parameter never enters the production client.
- `test_sdk_style_project_names_the_cause_when_restore_fails`
- `test_sdk_style_project_reference_stays_unresolved`
- `test_semantic_binding_reports_available_for_real_iqcs_project`
- `test_semantic_binding_reports_each_project_of_the_real_rttalentdb_repository`

The ticket-02 test kept its assertions and had its docstring corrected: an SDK-style project no
longer reports `no_compile_items` for lacking explicit items, so that test now has to hold no
source file at all for the case to arise. The reason text changed to
`no_compile_items: project contributes no C# source file`, which is true of both project shapes.

### Verified

Measured against the real repositories, run through the host's `semantic-binding` command:

| Repository | Result |
| --- | --- |
| IQCS (1 project, net6.0) | `available`, 267 source files, 1 compiler error |
| ETR (1 project, net6.0) | `available`, 50 source files |
| RTTalentDB (3 projects, net8.0) | 2 `available` (376 and 5 files); `RTTalentDBMailJobApp` `unavailable_reference_resolution_failed` naming `RTTalentDBMailJobAPI` |
| EnterpriseApi (6 projects, net8.0) | all 6 `available` |

RTTalentDB compiles with 1 error over 376 files despite 50 of its 56 controllers using C# 12
primary constructors — the pinned Roslyn 4.9.2 parses them.

- `pytest tests/test_semantic_binding_availability.py`: 22 passed.
- `pytest`: 705 passed, 12 failed. All 12 reproduce identically against the pre-change code
  (confirmed by stashing this work and rebuilding the host), and none touch semantic binding or
  project compilation. They are the same 12 ticket 01 recorded.

### Left undone

`CONTEXT.md` does not yet carry the terms this ticket introduces — *SDK-style project*, *restore
assets*, *implicit globbing* — and its **Semantic Binding Availability** entry does not mention
`source_file_count`. `docs/agents/domain.md` asks for those to be recorded. They were left out
because `CONTEXT.md` currently holds an uncommitted block of MVC vocabulary belonging to earlier
work in this feature, and git commits whole files: writing the glossary here would have swept that
work into this commit under this ticket's message. The glossary update belongs with whichever
commit lands that block.
