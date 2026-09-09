# 02 — An SDK-style project with no source files reports unavailable

**What to build:** A maintainer reading Semantic Binding Availability can trust it. Today an
SDK-style project reports `available` while holding an empty compilation,
because the project reader finds no explicit source items and no explicit
references, and an empty unresolved list reads as success.

Every ASP.NET Core project in the catalog is SDK-style, so every one of them
currently claims a semantic model it does not have. This is the failure mode the
codebase exists to prevent: a degraded analysis that looks like a confident one.

This is a correctness fix on its own. It lands whether or not the rest of the
MVC/Core work proceeds.

**Blocked by:** None (can start immediately).

**Status:** done

- [x] A project that yields no source files reports `unavailable_reference_resolution_failed`, never `available`.
- [x] The report names why, so a maintainer can tell an unreadable project from an empty one.
- [x] An old-style project that legitimately declares source files is unaffected.
- [x] A scan root holding no project file still reports `unavailable_no_project_file`, unchanged.
- [x] Running the analyzer over a real ASP.NET Core repository reports unavailable for its project, where it reported available before.

## Note

Fixed in `tools/StaticAnalyzerHost/ProjectCompilation.cs`, in `ProjectCompilationResolver.ResolveProject`.
The check runs right after `ProjectFileReader.Read`, before reference resolution: when
`description.CompileItems.Count == 0`, the method returns
`unavailable_reference_resolution_failed` with the reason
`no_compile_items: project declares no <Compile> source items`, instead of falling through to
an empty, `available` compilation.

The root cause: `ProjectFileReader.Read` only reads explicit `<Compile Include>` items (the
old-style project shape). An SDK-style project (every ASP.NET Core project in the catalog)
declares no explicit `<Compile>` items — its source files come from implicit globbing, which
this reader does not understand yet (that is Ticket 05). Zero source files plus zero explicit
references both read as "nothing unresolved", so the project fell through to `available` while
holding an empty compilation.

The check is skipped when `overrideSyntaxTrees` is not null. `ResolveProject` has a second
caller, `ResolveCompilationForAnalysis` (Ticket 06, used by the `csharp` command), which globs
`.cs` files itself and passes its own already-parsed syntax trees in. Those are real source, so
an empty explicit `<Compile>` list there does not mean an empty compilation. The first version of
this fix missed that guard and would have forced every ASP.NET Core project back onto the
syntax-only wrapper-binding path in that command too — caught in code review before commit and
corrected: `tools/StaticAnalyzerHost/ProjectCompilation.cs:111` now reads
`if (overrideSyntaxTrees is null && description.CompileItems.Count == 0)`.

Verified:
- New test `test_semantic_binding_reports_unavailable_for_sdk_style_project_with_no_source_files`
  in `tests/test_semantic_binding_availability.py`, red before the fix, green after. It asserts
  the specific `no_compile_items` reason, not just that some reason is present.
- All 12 tests in `tests/test_semantic_binding_availability.py` pass, including the old-style
  "declares source files" cases and the no-project-file case — both unaffected.
- Manually ran the analyzer against the real `data/repos/System_Dept_1/IQCS/IQCS.csproj`
  (an SDK-style ASP.NET Core project): now reports `unavailable_reference_resolution_failed`
  with `no_compile_items: ...`, where it reported `available` before this fix.
- Ran `tests/test_csharp_analysis_gateway.py`, `test_semantic_overload_resolution.py`,
  `test_wrapper_decompilation.py`, and `test_program_refresh.py` (the suites nearest
  `ResolveCompilationForAnalysis` and this reporting path): 208 passed, 5 failed. All 5 failures
  reproduce identically against the pre-fix code (confirmed via `git stash`), so they are
  unrelated to this change.
- A full `pytest -q` run also shows 14 pre-existing/flaky failures elsewhere in the suite
  (Windows path/encoding/line-ending issues, none touching semantic binding or project
  compilation), likewise reproduced against the pre-fix code.
