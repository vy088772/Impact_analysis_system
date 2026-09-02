# Required Parameter Count Joins the Contract Behavior Signature

**Status:** Accepted
**Date:** 2026-09-02

## Context

An external wrapper's semantics reach the gateway as a Contract, and one Contract holds one entry per overload. Overload selection matched a call to an entry by comparing the call's argument count to the entry's `method_arity`, and by nothing else.

C# does not bind calls that way. A method whose trailing parameters have default values accepts fewer arguments than it declares. `SQLObject.CreateDataSet(string, SqlParameter[], string CmdType, int ExecLimitTime = ...)` declares four parameters and requires three, so `CreateDataSet(sp, par, "SP")` binds to it — while the count-only rule bound that call to the sibling `CreateDataSet(string, SqlParameter[], int)`, whose semantics are `inline_sql`. The Contract then declared a stored-procedure call to be inline SQL, no procedure name was extracted, and `/find_by_sp` dropped the invocation before it could become a diagnostic. In `Y-Docs_TTPUR` that silently removed 107 stored procedures from every reverse lookup.

The decompiler had computed the required count all along; `ImplementationSnapshotOperation` did not carry it, so the registry had no field in which to say it. Nothing downstream can recover a fact the format cannot state.

## Decision

Required Parameter Count is part of an Implementation Snapshot operation, and therefore part of the canonical behavior signature the Contract Fingerprint is computed from.

Putting it in the signature is the point of the decision, not a side effect. ADR-0006 makes the fingerprint this system's sole notion of Contract identity. Two assemblies whose overloads agree on every declared parameter but disagree on which of them are optional bind the same call to different methods, with different command semantics — they are two behavior surfaces, and a fingerprint that could not tell them apart would let one be reused for the other. Every Contract rebuilt after this change therefore gets a new fingerprint and, through Contract Preflight, a new immutable revision. That is the same path any other behavior-surface change already takes.

An operation that reports no Required Parameter Count is compared by exact argument count, exactly as before. A registry written before this change selects overloads unchanged; the fix arrives when its Contract is rebuilt, not when this code ships.

## Consequences

- A rebuilt Contract is a new revision under a new name. The Wrapper Contract Selector for the affected System has to be repointed at it, by refresh-time onboarding or by explicit acceptance. Until it is, the old revision stays in force and the old selection stands — visibly, under its own name, rather than as a silent partial upgrade.
- Relaxing the count admits overload sets that the count alone cannot separate: both `CreateDataSet` siblings above admit a three-argument call. Those ties are broken by Mode Argument Carriage (see `CONTEXT.md`), and only when exactly one overload survives; otherwise the tie is reported as a tie, as it is today.
- The analyzer host applies the same admissibility rule to wrappers whose source it can read (`CSharpAnalyzer.ResolveWrapperOverload`). The two paths tie-break differently on purpose — only the host has the call site's argument types — and each now says so where it decides.
