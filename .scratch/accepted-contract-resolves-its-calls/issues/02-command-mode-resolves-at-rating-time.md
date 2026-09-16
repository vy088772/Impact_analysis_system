# 02 — The Command Mode resolves at rating time

**What to build:** A Contract that names its mode argument resolves the calls
that pass a value for it, even when the scan that captured those calls ran
before the Contract existed.

The scan records Observed Argument Facts for every argument of a wrapper call:
the kind of the argument, its literal value when one exists, and the reason the
value stayed unresolved. The scan records these facts from the syntax alone. The
analyzer host reads no Contract and gains no Contract input channel.

The analysis gateway then decides the Command Mode during rating. It reads the
Contract's argument roles, finds the mode argument by its declared index, and
reads the recorded value for that index. It applies the convention the analyzer
host already applies to a local wrapper: `true`, `"SP"` and `"StoredProcedure"`
mean a stored procedure, and `false` means an inline SQL command. The Contract
schema does not change.

An argument that holds a variable, an expression or a call stays unresolved, and
the Command Mode stays unresolved with it. The gateway never falls back to a
default.

The scan output gains a field, so the scan cache version rises by one. Every
existing cache becomes invalid, and each System re-scans on its next refresh.
This is the mechanism that already exists for a scan schema change. This ticket
adds no refinement marker, no second scan pass and no trigger.

The existing command text fields stay exactly as they are. This ticket does not
fold the command text argument into the new structure.

**Blocked by:** 01 — The ADRs and the glossary record the decisions.

**Status:** ready-for-agent

- [ ] A scan of a wrapper call records, for each argument, its kind, its literal
      value when one exists, and the reason it stayed unresolved
- [ ] The analyzer host reads no Contract during a scan, and gains no command
      line option or input channel for one
- [ ] A call whose mode argument holds the literal `true` rates as a stored
      procedure; `"SP"` and `"StoredProcedure"` behave the same way
- [ ] A call whose mode argument holds the literal `false` rates as an inline
      SQL command
- [ ] A call whose mode argument holds a variable keeps an unresolved Command
      Mode, and the invocation names the reason
- [ ] `usp_ExecCmdGetDataSetAsync` (62 calls) and `usp_ExecCmdGetCountAsync`
      (1 call) in the IQCS checkout resolve their Executed Procedure Name
- [ ] The Executed Procedure Name share for IQCS reaches about 7%, measured by
      the existing coverage report
- [ ] The scan cache version rises by one, and a stale cache reports itself as
      stale rather than serving the old shape
- [ ] The existing command text fields are unchanged, and their tests still pass
