# 02 — Decompile a referenced external wrapper DLL into classified facts

**What to build:** `StaticAnalyzerHost` gains the ability to take a wrapper receiver type that is unresolved against local source and the active contract registry, trace it to a concrete `.csproj` `<Reference>`/`HintPath` entry, decompile the referenced DLL with `ICSharpCode.Decompiler` (a build-time NuGet reference, no runtime download), and run the resulting syntax tree through the same `WrapperAnalyzer`/`CommandType`/terminal-sink classification logic already used for local wrapper source. Each classified snapshot carries an assembly identity computed as the SHA-256 hash of the DLL's raw bytes (not `AssemblyName`/`Version`). This only ever runs for a receiver traceable to a concrete `.csproj` reference — it never scans a directory for arbitrary DLLs, and a receiver that cannot be traced this way remains a review candidate.

**Blocked by:** 01.

**Status:** ready-for-agent

- [ ] Given a receiver type, the host resolves the exact DLL path from the referencing project's `.csproj` `<Reference>`/`HintPath` entries, with no directory scanning
- [ ] A receiver type that cannot be traced to a `.csproj` reference (e.g. dynamically loaded/reflection-only) is left as a review candidate, not a best-effort decompile
- [ ] The DLL is decompiled to a C# syntax tree and classified through the existing `WrapperAnalyzer`/`CreateDefinition()` pipeline, producing the same shape of per-method facts (method identity, argument roles, `CommandType`/terminal sink) as local source
- [ ] `SqlDataAdapter.Fill` remains a distinct terminal sink from `ExecuteReader` for decompiled input, exactly as for local source
- [ ] Two methods with similar names but different fixed `CommandType` semantics are classified distinctly (no name-based merging)
- [ ] Assembly identity is the SHA-256 hash of the DLL's raw bytes; two byte-identical DLLs produce the same identity, any other byte sequence produces a different one regardless of `AssemblyVersion`
- [ ] A decompiler-reported translation problem for a method (unresolved IL construct, missing body, or equivalent error marker) is captured as a fact on that method's classification, not silently dropped
- [ ] End-to-end smoke test: decompiling the checked-in `data/repos/System_Dept_1/STC/STC/bin/SQLFunc.dll` through the real `StaticAnalyzerHost` classifies `CreateAdapter` as fixed stored-procedure and `CreateAdapterTsql` as fixed inline text, and keeps `SqlDataAdapter.Fill`-based methods distinct from `ExecuteReader`-based ones
