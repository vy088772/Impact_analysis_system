# Optional-Parameter-Aware Overload Selection

Status: ready-for-agent

## Problem Statement

`/find_by_sp` answers "which programs call this stored procedure?". For the
`Y-Docs_TTPUR` System it answers "none" for 107 stored procedures that 266 C#
call sites do call. The answer is empty, authoritative-looking, and wrong.

The loss happens during overload selection. The `SQLObject` wrapper is an
external assembly, so its semantics come from a Contract built by decompiling
the DLL. Two of its overloads matter here:

```
CreateDataSet(string, SqlParameter[], int ExecLimitTime = ...)          inline_sql
CreateDataSet(string, SqlParameter[], string CmdType, int Exec = ...)   call_site
```

The application writes `obj.CreateDataSet("[dbo].[usp_X]", par, "SP")` — three
arguments. C# binds that to the second overload, because `ExecLimitTime` has a
default. The gateway binds it to the first, because it compares argument count
to `method_arity` and nothing else. The Contract then declares the call inline
SQL, the stored-procedure name is never extracted, and `find_by_sp` drops the
invocation before it can even become a diagnostic.

The decompiler already reports `required_parameter_count` for every wrapper
method. The Implementation Snapshot drops it, so the registry cannot express
"this overload accepts three arguments even though it declares four" — and no
downstream reader can recover a fact the format cannot state.

## Solution

An Implementation Snapshot Operation carries its **Required Parameter Count**,
the registry keeps it, and overload selection uses it: a call with `N`
arguments can bind to an overload when `required <= N <= method_arity`. An
overload that does not declare a Required Parameter Count keeps today's strict
equality, so a registry written before this change behaves exactly as it does
now.

Relaxing the count alone leaves the two overloads above *both* applicable to a
three-argument call, which is a tie the mode-blind matcher reports as
`ambiguous_overload` — honest, but still no answer. A second rule breaks that
tie on facts the registry already carries: **Mode Argument Carriage**. When the
call site resolved a command-type mode, an overload can only be the observed
one if it has a string parameter, inside the observed argument count and other
than the command-text parameter, able to have carried that mode argument. The
`int` overload has none, so it cannot explain the observed `"SP"`; the
`string CmdType` overload can. When exactly one overload survives, it is the
selected one; otherwise the tie stands and is reported as it is today.

## User Stories

1. As an analyst, I want `find_by_sp` to find a program that calls the stored procedure through a wrapper overload with optional trailing parameters, so that a default argument does not hide a real caller.
2. As an analyst, I want an overload tie that cannot be broken to stay reported as a tie, so that a guess is never dressed up as an answer.
3. As a reviewer, I want a registry written before this change to select overloads exactly as it does today, so that the change cannot silently re-rate existing evidence.
4. As a reviewer, I want the Required Parameter Count to come from the decompiler rather than be inferred from parameter names or types, so that the fact is observed, not guessed.
5. As a reviewer, I want Mode Argument Carriage to narrow only when the call site actually passed a command-type argument, so that overloads which never see a mode argument are untouched.
6. As a reviewer, I want narrowing that leaves zero or several overloads to change nothing, so that the rule can only ever turn a tie into a decision, never a decision into a different decision.
9. As a reviewer, I want an overload that cannot be judged for carriage to abandon the narrowing rather than lose it, so that an entry saying too little never hands the tie to its sibling.
7. As a maintainer, I want the Required Parameter Count inside the behavior signature, so that an assembly whose optional parameters changed produces a different Contract fingerprint instead of silently reusing the old one.
8. As an operator, I want the fix to take effect after the refresh I already run, so that I do not have to learn a second command.

## Implementation Decisions

### Required Parameter Count

The count of parameters a caller must supply for one wrapper method — its
arity minus its trailing optional parameters. `WrapperAnalyzer.WrapperDefinition`
already computes it; `ImplementationSnapshotOperation` now carries it too, so
it survives into the registry.

It joins the canonical behavior signature. That changes the fingerprint of
every contract rebuilt after this change, which is correct: an overload set
whose binding rules are now known in more detail is a different behavior
surface, and Contract Preflight mints a new revision for it exactly as it does
for any other surface change.

### Mode Argument Carriage

Whether one overload has a parameter that could have received the call site's
command-type mode argument. An overload that declares a `command_type`
argument role carries the mode when that role's index is inside the observed
argument count and the parameter there is a string. An overload that declares
no such role carries it only if some other string parameter, inside the
observed argument count and not the command-text parameter, could have taken
it.

This is C# binding, not preference: a string literal has no conversion to
`int`, so an overload whose only spare parameter is numeric cannot be the one
the compiler chose.

An overload that does not declare enough to be judged — no parameter types, no
argument roles, or roles that never name the command-text parameter — answers
"cannot say", which is not the same as "carries nothing". One such overload in
the tied set abandons the narrowing entirely: a survivor picked because a
sibling said too little would be a decision made on missing evidence.

### Observing the mode argument

Narrowing runs only when the scan says the call really passed a command-type
argument, reported per invocation as `command_type_argument_observed`.

The existing `wrapper_mode` cannot answer that question. The scanner also sets
it from the method name alone — `ExeProcRead` is `stored_procedure`,
`CreateReader` is `inline_sql`, whatever the arguments say — and falls back to
`inline_sql` for `CreateTable`/`CreateDataSet` when it finds no mode argument
at all. A reader of `wrapper_mode` therefore cannot tell a mode that was
observed from one that was assumed, and gating on it would narrow ties on calls
carrying no mode argument. The new fact is a raw scan fact, so it costs a scan
cache version bump; a cache written before it simply never narrows.

### What this does not fix

A call that passes a bare procedure name as inline SQL text —
`CreateTable("[dbo].[usp_X]", "SP")`, where the DLL's two-argument overload
really does treat the second argument as a table name — still resolves to
`inline_sql`, and correctly so. Five call sites and three stored procedures in
`Y-Docs_TTPUR` are in that shape. Recovering them means recognising a bare
procedure name inside inline SQL text, which is a separate change.
