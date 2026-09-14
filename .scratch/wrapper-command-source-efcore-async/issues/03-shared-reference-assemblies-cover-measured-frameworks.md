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

**Status:** ready-for-agent

- [ ] The abstract ADO.NET command type resolves to a known type, with its implemented interfaces visible, when examined from an assembly targeting `net6.0` or `net8.0`
- [ ] The same type keeps resolving as it does today when examined from a .NET Framework assembly — the existing set is added to, never replaced
- [ ] The project reader and the wrapper decompiler still resolve framework types through one shared enumeration, so neither can be updated without the other
- [ ] A decompiled assembly is examined against the reference assemblies for the framework it targets, and an assembly whose target framework has no reference assemblies available degrades rather than failing
- [ ] The reference assemblies are obtained by the same mechanism the existing .NET Framework set uses; the analyzer host's own build still succeeds with no new runtime dependency
- [ ] No reported classification changes: the existing `SQLFunc` and `SQLObject` classified surfaces are asserted whole and unchanged, and the real shared assembly's classified and unclassified sets are exactly what ticket 01 and ticket 02 left them
