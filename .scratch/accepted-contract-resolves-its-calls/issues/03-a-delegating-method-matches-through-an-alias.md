# 03 — A delegating method matches its Contract through an alias

**What to build:** A call to a method that only forwards to another method
matches the Contract, and resolves the same way the method it forwards to
resolves.

The decompiler already finds these relations and records them in the
decompilation cache. It must now write each one into the Contract as a
Delegation Alias. An alias names one method and points to the operation that
does the work.

The decompiler flattens a delegation chain before it writes an alias. An alias
always points to the operation that performs the work, never to another alias.
`SQLDbContext` carries a two-step chain today: `usp_ExecCmdGetFisrtValueAsync`
forwards to `usp_ExecCmdGetDataTableAsync`, which forwards to
`usp_ExecCmdGetDataSetAsync`. All three aliases point to the last of them.

The alias collection sits outside the behavior signature, so the Contract
fingerprint does not change. A System that already matched this Contract by
fingerprint keeps reusing it.

A migration adds the missing aliases to the Contracts already in the registry.
It reads the cached decompilation result and does not decompile any assembly
again. It walks every Contract in the registry, not one named Contract.
`SQLDbContext` carries three delegations today, and `SQLFunc` and `SQLObject`
carry none.

The call site match consults the alias collection only when the method name
matches no operation directly. A direct match always wins.

A call matched through an alias reports the method name that the source code
uses. The gateway records the alias that produced the match beside that name, so
a maintainer can trace how the analyzer reached its answer and can still search
the repository for the reported name.

**Blocked by:** 01 — The ADRs and the glossary record the decisions. 02 — The
Command Mode resolves at rating time.

**Status:** ready-for-agent

- [ ] A decompiled Contract carries a Delegation Alias for each delegating
      method the decompiler finds
- [ ] A two-step delegation chain flattens: every alias points to the operation
      that performs the work, never to another alias
- [ ] The alias collection sits outside the behavior signature, and the Contract
      fingerprint is byte-identical before and after the aliases arrive
- [ ] A migration adds the three missing aliases to the `sqldbcontext` Contract
      already in the registry, reading the cached decompilation result
- [ ] The migration walks every Contract in the registry, and leaves `SQLFunc`
      and `SQLObject` unchanged because they carry no delegation
- [ ] A method name that matches an operation directly never consults an alias
- [ ] `usp_ExecCmdGetDataTableAsync` (196 calls) in the IQCS checkout resolves
      its Executed Procedure Name
- [ ] A review line for an alias-matched call names
      `usp_ExecCmdGetDataTableAsync`, the name the source code uses, and records
      the alias separately
- [ ] The Executed Procedure Name share for IQCS reaches 30% or more, measured
      by the existing coverage report
- [ ] `SQLDbContext` calls no longer appear in the unresolved review list
