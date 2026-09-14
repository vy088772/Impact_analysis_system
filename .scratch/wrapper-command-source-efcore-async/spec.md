# Command Source Recognises a Command Object by Contract, Not by Name

Status: ready-for-agent

## Problem Statement

Five ASP.NET Core Systems were measured — IQCS, RTTalentDB, ETR, EnterpriseApp
and TOPCSCY. Every one of them reaches its database through the same shared
assembly: each declares its own context class deriving from `SQLDbContext`, a
type inside `CommonLibrary.dll`.

`SQLDbContext` exposes seven public database methods. The analyzer classifies
**none** of them. Contract Preflight therefore reports the behaviour surface
incomplete, refuses to create a Contract, and the refresh command reports
`onboarding=preflight_failed` for all five Systems at once.

Two separate causes produce that single outcome:

1. **A Command Source is recognised by type name, not by what the type is.**
   `usp_ExecCmdGetDataSetAsync` obtains its command through
   `Database.GetDbConnection().CreateCommand()`, so the command object is
   declared as `DbCommand`. The recognition rule matches the literal name
   `SqlCommand` and nothing else, so a command object that every other rule in
   the codebase already accepts as an ADO.NET construct is not accepted here.
   The rule's sibling — the one that recognises a data adapter — has carried a
   multi-provider name list since it was written; only the command rule stayed
   at one name.

2. **A method that delegates to a sibling method looks identical to a method
   nobody understood.** Four of the seven methods
   (`usp_ExecCmdGetFisrtValueAsync`, `usp_ExecCmdGetDataTableAsync`,
   `usp_ExecCmdGetJsonObjectAsync`, `usp_ExecCmdGetJsonObjectListAsync`)
   construct no command of their own. Their only database contact is a call to
   another method on the same type. They are reported under the same name as a
   method whose construct the resolver genuinely failed to recognise, so the
   completeness check treats a fully-understood delegation as a gap.

A name list is not a durable answer to the first cause. Systems from other
teams will enter this catalog carrying conventions this team has never seen,
and each one would arrive as a silent empty result followed by a new ticket.
The recognition rule should ask what a type *is*, not what it is *called*.

The analyzer can already ask that question — but only where it holds a
compilation. Both the project reader and the wrapper decompiler resolve their
framework types through one shared reference-assembly directory, and that
directory holds .NET Framework 4.8 only. Every measured repository targets
`net6.0` or `net8.0`. Measured directly against `CommonLibrary.dll`, the
decompiler's own type system reports `DbCommand` as `Unknown` and cannot see
that it implements `IDbCommand`.

## Solution

Recognise a command object by the contract it implements, and say so honestly
when that question cannot be answered.

A type is a command object when it implements `IDbCommand` — the interface
every ADO.NET command type in .NET is required to implement, whichever provider
or team wrote it. When the analyzer holds enough type information to answer
that question, it answers it. When it does not, it falls back to the existing
name comparison, widened to the same multi-provider list the data adapter rule
already carries, so a degraded answer is narrower but never wrong.

To make the contract question answerable at all on a modern project, the shared
reference-assembly directory gains the `net6.0` and `net8.0` reference
assemblies alongside the .NET Framework 4.8 set it already holds. Both the
project reader and the wrapper decompiler consume that directory, so both gain
the ability together.

A method whose only database contact is a call to a sibling method on the same
type becomes a **Delegated Method** — a third outcome beside "classified" and
"unclassified", naming the sibling it delegates to. A Delegated Method is not a
gap: its database behaviour belongs to the method it calls, which is classified
in its own right. The completeness check stops counting it against the
behaviour surface.

Together these let all five measured Systems complete automatic Contract
onboarding through the path that already exists for them, rather than each
needing a manual acceptance.

## User Stories

### Recognising a command object

1. As an analyst, I want a wrapper method that builds its command through a connection's `CreateCommand` to resolve its Command Source, so that a System written against Entity Framework Core's connection is not reported as empty.
2. As an analyst, I want a command object declared as the abstract `DbCommand` type to be recognised as a command object, so that a wrapper that programs against the base type rather than a provider type still answers.
3. As a maintainer, I want a command object from any provider that implements `IDbCommand` to be recognised without naming that provider anywhere in the analyzer, so that a System from another team using a convention this team has never seen is covered on the day it enters the catalog.
4. As a maintainer, I want a type that merely resembles a command type by name but implements no command contract to stay unrecognised when the contract can be checked, so that a coincidental name never manufactures a Command Source.
5. As a maintainer, I want the recognition rule to fall back to a name comparison when the contract cannot be checked, so that a project the analyzer cannot bind still resolves the command shapes it has always resolved.
6. As a maintainer, I want that fallback name list to name the same providers the data adapter rule already names, so that the two sibling rules stop disagreeing about which providers exist.
7. As a reviewer, I want a Command Source resolved by contract and one resolved by name fallback to be indistinguishable in the result, so that this change adds no new axis to an already wide response shape.

### Answering the contract question

8. As a maintainer, I want the shared reference-assembly directory to carry the `net6.0` and `net8.0` reference assemblies, so that a type declared by a modern framework can be resolved at all.
9. As a maintainer, I want the project reader and the wrapper decompiler to keep resolving framework types through one shared directory, so that the two paths can never disagree about which framework a type came from.
10. As a maintainer, I want a decompiled wrapper assembly's methods to be examined with the framework types its own target framework declares, so that the contract question is answered against the right framework rather than whichever one happened to be downloaded.
11. As a reviewer, I want an assembly whose target framework has no reference assemblies available to report that its Command Sources were resolved by name fallback, so that a narrower answer is visible rather than silent.
12. As a maintainer, I want the reference assemblies to be obtained the same way the existing .NET Framework set is obtained, so that a fresh clone needs no extra manual setup step.

### The Delegated Method

13. As an analyst, I want a wrapper method whose only database contact is a call to a sibling method on the same type to be reported as a Delegated Method, so that a helper that reshapes another method's result is not mistaken for a gap.
14. As an analyst, I want a Delegated Method to name the sibling method it delegates to, so that its database behaviour can be traced to the method that actually carries it.
15. As a reviewer, I want a method that has both its own command construct and a sibling call to be classified by its own Command Source, so that adding delegation never re-rates a method that was already classified.
16. As a reviewer, I want a Delegated Method that also contains unrelated logic to still be reported as delegated, so that a helper doing a null check around its sibling call is not demoted to a gap over the null check.
17. As a maintainer, I want a Delegated Method to count as understood by the behaviour surface completeness check, so that a fully-traced delegation never blocks automatic Contract onboarding.
18. As a maintainer, I want a method that touches a database type but yields neither a Command Source nor a delegation to stay unclassified, so that a real gap keeps blocking onboarding exactly as it does today.
19. As a reviewer, I want a Delegated Method and an unclassified method to be reported under different names, so that two different facts are never read from one bucket.

### The measured outcome

20. As an analyst, I want `SQLDbContext`'s seven public methods to be fully accounted for — classified or delegated, none unclassified — so that Contract Preflight can create a Contract for it.
21. As an analyst, I want the IQCS refresh to report a created Contract rather than `preflight_failed`, so that its 259 `SQLDbContext` calls can bind to semantics.
22. As an analyst, I want RTTalentDB, ETR, EnterpriseApp and TOPCSCY to gain the same Contract from the same shared assembly, so that one classifier repair covers five Systems.
23. As a reviewer, I want the Contract created for `CommonLibrary` to be keyed by the same Assembly Revision Boundary rule every other Contract uses, so that a team shipping a different build of the shared assembly gets a separate Contract rather than a silent mismatch.

### Regression safety

24. As a reviewer, I want a WebForms wrapper assembly to classify exactly as it does today, so that widening the recognition rule cannot re-rate existing evidence.
25. As a reviewer, I want the measured Y-DOCs stored-procedure counts to rise or hold, never fall, so that a shared code path change cannot quietly remove evidence.
26. As a reviewer, I want the existing `SQLFunc` and `SQLObject` Contracts to keep their current behaviour signatures byte for byte, so that a Contract Fingerprint that did not need to change does not change.

## Implementation Decisions

### Recognising a command object

- The command-object recognition rule gains a contract check: a type is a
  command object when it implements `IDbCommand`. The check runs whenever the
  analyzer holds type information able to answer it.
- When the contract cannot be checked, the rule falls back to comparing the
  type's short name against a multi-provider list — the same list shape the
  data adapter recognition rule already carries. The list gains the abstract
  type name alongside the provider-specific ones.
- The two mechanisms answer one question and produce one outcome. Nothing in
  the response shape records which of the two answered, because a Command
  Source resolved either way is the same fact.
- The widened rule is shared by both classification paths — local source
  wrapper and decompiled external assembly — with no scope switch. The two
  paths have always shared this code, and the measured evidence applies to both.
- Entity Framework Core's high-level raw-SQL methods (`ExecuteSqlInterpolated`,
  `ExecuteSqlRaw` and their asynchronous forms) construct no command object at
  all and are a structurally different shape. They are out of scope here.

### Answering the contract question

- The shared reference-assembly directory enumeration gains the `net6.0` and
  `net8.0` reference-assembly packages beside the .NET Framework 4.8 package it
  already yields. Both the project reader's framework-reference resolution and
  the wrapper decompiler's assembly resolver consume that one enumeration, so
  neither can be updated without the other.
- The packages are obtained through the same download-without-referencing
  mechanism the .NET Framework 4.8 package already uses, so the analyzer host's
  own build is unaffected and a fresh clone needs no manual step.
- A decompiled assembly's methods are re-examined against the reference
  assemblies for the framework that assembly targets. Where that framework has
  no reference assemblies available, the contract check yields no answer and the
  name fallback decides — the existing, unchanged behaviour.
- Type binding over a decompiled assembly is partial by nature: a synthetic
  source built from per-method decompilation will not bind every symbol it
  names. The contract check treats an unbound type as "cannot answer" and hands
  it to the fallback, never as "does not implement".

### The Delegated Method

- A method is a Delegated Method when it declares no command construct of its
  own and its only database contact is an invocation of another method declared
  on the same type.
- The rule does not require the method body to consist solely of that call. A
  method that inspects or reshapes the sibling's result is still delegated —
  measured against the real shared assembly, none of the four delegating
  methods is a bare pass-through.
- A method that has both its own command construct and a sibling call is
  classified by its own Command Source. Delegation is only ever consulted for a
  method that produced no Command Source.
- The delegation record names the sibling method it delegates to. A bare
  boolean would restate what the bucket already says; this codebase reports the
  reason for an absence, and the sibling's name is that reason.
- The behaviour surface completeness check counts a Delegated Method as
  understood. The set of unclassified public methods — the set that blocks
  Contract creation — keeps its current meaning: a method the resolver could
  not account for by any rule.
- Delegation is not followed transitively for the purpose of rating evidence. A
  Delegated Method's own database target is not copied from its sibling; the
  sibling carries its own classified Command Source, and the delegation record
  states where to look.

### Domain model

- `CONTEXT.md`'s **Command Source** entry is amended: recognition is by
  implemented contract first, by name second, and the entry stops implying that
  an explicit construction of one named type is the only recognised construct.
- `CONTEXT.md` gains **Delegated Method** as a new term, defined against
  "unclassified public method" so the two are never conflated.
- An ADR records the decision to recognise a command object by contract rather
  than by name: it is hard to reverse (the fallback list would have to be
  re-grown), surprising without context (a name list is the obvious first
  implementation, and one is still present as fallback), and the result of a
  real trade-off (a name list is simpler and needs no reference assemblies, but
  silently mis-reports every convention it has not met).

## Testing Decisions

A good test here states an externally observable fact and nothing about how the
code reaches it: a method's reported classification, the set of unclassified
public methods, a created Contract's name, a behaviour surface's completeness.
Every test that asserts a method is absent from a classified set also asserts
which bucket it landed in instead, because this codebase's failure mode is a
silent empty result.

### Seams

One existing seam, no new ones. **`StaticAnalyzerHost`** is the seam for all of
this work: the decompile-wrapper command reports the classified wrapper
definitions, the unclassified public methods, and the contract proposal that
Contract Preflight consumes. Reference-assembly availability, command-object
recognition and delegation are all observable in that one response. Neither the
recognition rule nor the delegation rule is tested directly.

Contract creation — that the newly complete behaviour surface actually produces
a Contract — is observed through `run_contract_preflight` fed by that response,
which is the pattern `tests/test_wrapper_decompilation.py` already uses.

### Prior art

- `tests/test_wrapper_decompilation.py` shows the whole pattern this work
  needs: build a minimal assembly into a temporary directory, reference it from
  a temporary project file, run the host's decompile-wrapper command, assert on
  the reported classification and on the preflight outcome. It also shows the
  fixture-gated smoke test against a real checked-out assembly.
- `tests/test_semantic_binding_availability.py` shows the project-reader
  pattern: write a minimal project, run the host, assert on the reported
  availability and on the named unresolved references.

### Fixtures

The real `CommonLibrary.dll` is checked out under the IQCS repository and is
the authoritative fixture for the measured outcome — a fixture-gated test
asserts its seven methods are fully accounted for and that a Contract is
created. Because that file is not tracked, every rule is additionally covered
by minimal assemblies built into temporary directories, modelled on the real
shapes rather than invented: a command obtained through `CreateCommand` and
declared as the abstract type, a command type from a provider the analyzer
names nowhere, a type whose name resembles a command type but implements no
command contract, a method delegating to a sibling, a method delegating while
also reshaping the result, a method with both its own construct and a sibling
call, and a method that touches a database type and yields nothing.

### Baseline

The existing `SQLFunc` and `SQLObject` classified surfaces are asserted whole
today and stay asserted whole. The Y-DOCs WebForms counts are captured before
the first change and compared after each ticket.

## Out of Scope

- **Entity Framework Core's high-level raw-SQL API.** `ExecuteSqlInterpolated`,
  `ExecuteSqlRaw` and their asynchronous forms construct no command object and
  need a differently-shaped rule. One method of the measured shared assembly
  uses this form and stays unclassified, with its reason named. It belongs to
  its own ticket.
- **Following a delegation to rate the caller's evidence.** A Delegated Method
  names its sibling; it does not inherit the sibling's database target.
- **Delegation across a type boundary.** Only a call to a method declared on the
  same type counts. A call into another class is not a delegation here.
- **Recognising a connection or a data reader by contract.** Only the command
  object's recognition rule changes. The ADO.NET type census and the data
  adapter rule keep their current name-based form.
- **Registering the four newly cloned repositories in the catalog.** Which
  repositories become Systems is a separate decision.

## Further Notes

The five measured repositories were re-cloned and searched directly for this
spec. The finding that reframed the whole ticket: not one of them writes its
own ADO.NET access. RTTalentDB shows a single `SqlCommand` in 382 C# files;
EnterpriseApp and TOPCSCY show none at all; every one of the five declares
context classes deriving from the same `SQLDbContext` in the same
`CommonLibrary`. What looked like five separate classifier gaps is one gap in
one shared assembly, reached five times.

That evidence argues for the name list and against it at once. Against: five
systems, one convention, and a single name would have sufficed. For: these five
are one team's systems, and the catalog is expected to take on other teams'
systems whose conventions nobody here has seen. A rule that asks what a type
implements needs no foreknowledge of those conventions; a rule that asks what a
type is called needs a ticket per convention. The name list survives only as
the degraded answer for a project the analyzer cannot bind.

The reference-assembly gap was found by measurement, not by reading: the
decompiler's own type system was run against the real `CommonLibrary.dll` and
reported `DbCommand` as an unknown type with no base types at all. Without that
check the contract rule would have been written, merged, and quietly answered
"cannot tell" on every modern assembly it was built for.
