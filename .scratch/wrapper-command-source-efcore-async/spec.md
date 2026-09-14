# Command Source Recognises a Command Object by Contract, Not by Name

Status: ready-for-agent

## Problem Statement

Five ASP.NET Core Systems were measured — IQCS, RTTalentDB, ETR, EnterpriseApp
and TOPCSCY. Every one of them reaches its database through the same shared
assembly. Each System declares its own context class. Each context class derives
from `SQLDbContext`, a type inside `CommonLibrary.dll`.

`SQLDbContext` exposes seven public database methods. The analyzer classified
**none** of them. Contract Preflight reported the behaviour surface incomplete.
Contract Preflight refused to create a Contract. The refresh command reported
`onboarding=preflight_failed` for all five Systems.

Four separate causes produce that single outcome.

### Cause 1 — A Command Source is recognised by type name

`usp_ExecCmdGetDataSetAsync` obtains its command through
`Database.GetDbConnection().CreateCommand()`. The command object is therefore
declared as `DbCommand`. The recognition rule matched the literal name
`SqlCommand` and nothing else. The rule's sibling — the rule that recognises a
data adapter — has carried a multi-provider name list since it was written. Only
the command rule stayed at one name.

A name list is not a durable answer to this cause. Systems from other teams will
enter this catalog. They carry conventions this team has never seen. Each one
would arrive as a silent empty result, followed by a new ticket. The recognition
rule must ask what a type *is*, not what it is *called*.

The analyzer can already ask that question. It can only ask it where it holds a
compilation. Both the project reader and the wrapper decompiler resolve their
framework types through one shared reference-assembly directory. That directory
held .NET Framework 4.8 only. Every measured repository targets `net6.0` or
`net8.0`. Measured directly against `CommonLibrary.dll`, the decompiler's own
type system reported `DbCommand` as `Unknown`. It could not see that `DbCommand`
implements `IDbCommand`.

### Cause 2 — A delegating method looks like a gap

Three of the seven methods construct no command of their own. Their only
database contact is a call to another method on the same type. The three methods
are `usp_ExecCmdGetFisrtValueAsync`, `usp_ExecCmdGetDataTableAsync` and
`usp_ExecCmdGetJsonObjectAsync`. The analyzer reported them under the same name
as a method whose construct the resolver genuinely failed to recognise. The
completeness check therefore treated a fully-understood delegation as a gap.

### Cause 3 — A command factory carries no connection

A Connection Behavior Boundary states where a wrapper method's connection comes
from. The analyzer reads that connection from two places only. It reads the
second argument of a command constructor. It reads a `Connection` property
assignment. A command obtained from `connection.CreateCommand()` gives neither.
The connection is the *receiver* of the factory call, and the analyzer never
reads that receiver.

Three `SQLDbContext` methods build their command this way. All three therefore
report an empty Connection Behavior Boundary. An empty boundary fails the
completeness check with `connection_behavior_boundary_missing`. Causes 1 and 2
alone leave this cause untouched, so the Contract is still refused.

### Cause 4 — Entity Framework Core's raw-SQL API constructs no command

`usp_ExecCmdGetCountAsync` builds a `FormattableString` and passes it to
`ExecuteSqlInterpolatedAsync`. It constructs no command object at all. Measured
against the real assembly, it is the one method that stays unclassified after
causes 1, 2 and 3 are repaired.

A single unclassified public method blocks Contract creation completely. The
completeness check is all-or-nothing by design. Repairing three of four causes
therefore writes nothing, creates nothing, and leaves the measured outcome
exactly as it is today.

### The measured state today

Tickets 01 to 04 are resolved. Run against the real `CommonLibrary.dll` with
that work in place, the decompiler reports this:

```
classified   (3): usp_ExecCmdGetDataSetAsync
                  usp_ExecCmdGetJsonObjectListAsync
                  usp_ExecCmdGetJsonToTabletListAsync
delegated    (3): usp_ExecCmdGetFisrtValueAsync  -> usp_ExecCmdGetDataTableAsync
                  usp_ExecCmdGetDataTableAsync   -> usp_ExecCmdGetDataSetAsync
                  usp_ExecCmdGetJsonObjectAsync  -> usp_ExecCmdGetJsonObjectListAsync
unclassified (1): usp_ExecCmdGetCountAsync
```

The same proposal fails the completeness check for two reasons:

```
database_behavior_surface_incomplete
unclassified_public_method:SQLDbContext.usp_ExecCmdGetCountAsync(...)
connection_behavior_boundary_missing
```

### Cause 5 — A Contract Transaction commits silently

The refresh path already writes the external wrapper registry and the system
catalog automatically. `analyze_service.refresh_source` returns the Contract
Transaction outcome. The `/refresh` response model does not declare that field,
so the API drops it. `refresh_cli` never prints it either.

An operator therefore cannot tell a committed transaction from a skipped one.
The skip reason is worse than absent. The Contract Transaction outcome defaults
to `not_required` whenever any gate fails. Today's real IQCS state is
"required, but preflight failed", and the operator reads `not_required`.

## Solution

Repair all four classification causes, then make the commit visible.

**Recognise a command object by contract.** A type is a command object when it
implements `IDbCommand`. Every ADO.NET command type in .NET must implement that
interface, whichever provider or team wrote it. The analyzer answers the
contract question when it holds enough type information. Otherwise it falls back
to the existing name comparison, widened to the multi-provider list the data
adapter rule already carries. A degraded answer is narrower, never wrong.

The shared reference-assembly directory gains the `net6.0` and `net8.0`
reference assemblies beside the .NET Framework 4.8 set. Both the project reader
and the wrapper decompiler consume that directory, so both gain the ability
together.

**Report a delegating method as delegated.** A method whose only database contact
is a call to a sibling method on the same type becomes a **Delegated Method** —
a third outcome beside "classified" and "unclassified". A Delegated Method names
the sibling it delegates to. It is not a gap, so the completeness check counts it
as understood.

**Read the connection from the command factory.** When a method obtains its
command from `X.CreateCommand()`, `X` is the connection. This rule runs only
when the two existing rules resolve no connection, so an already-resolved
Connection Behavior Boundary can never change.

The Connection Behavior Boundary gains a third value, `context_connection`. It
states that the connection comes from a database context's own facade. The
actual database follows from the call site's declared receiver type through
Context Connection Registration. `SQLDbContext` is shared by five Systems and
many derived context types, so no single connection belongs to the wrapper.

**Classify Entity Framework Core's raw-SQL execution.** The four `Execute` forms
on a context's `Database` facade become a recognised Command Source shape:
`ExecuteSqlRaw`, `ExecuteSqlInterpolated`, and their asynchronous forms. They
construct no command object, so the rule reads the command text argument and the
execution call itself as the terminal sink.

**Report the Contract Transaction.** The `/refresh` response declares the
Contract Transaction outcome. `refresh_cli` prints one line for it. A skipped
commit names why it was skipped instead of reporting `not_required`.

Together these let all five measured Systems complete automatic Contract
onboarding through the path that already exists, and let an operator see it
happen.

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

### The connection behind a command factory

20. As an analyst, I want a wrapper method that obtains its command from a connection's `CreateCommand` to report that connection as its Connection Behavior Boundary, so that a classified method is not refused for a boundary the analyzer could have read.
21. As a maintainer, I want the command-factory rule to run only when the existing constructor-argument and property-assignment rules resolve nothing, so that an already-resolved Connection Behavior Boundary can never change value.
22. As a reviewer, I want a wrapper whose command factory receiver is a database context's `Database` facade to report `context_connection`, so that the boundary states which Context Connection Registration decides the database.
23. As a reviewer, I want a wrapper whose command factory receiver is a Field-Held Connection to keep reporting `wrapper_connection`, so that two different lookup shapes are never read from one value.
24. As a maintainer, I want `context_connection` to be a distinct third value rather than a reuse of `wrapper_connection`, so that a Contract shared by five Systems does not claim a single connection it does not own.
25. As a reviewer, I want the existing `SQLFunc` and `SQLObject` Contracts to report the same Connection Behavior Boundary they report today, so that widening the connection rule cannot re-fingerprint a Contract that did not change.

### Entity Framework Core's raw-SQL execution

26. As an analyst, I want a wrapper method that executes raw SQL through a context's `Database` facade to resolve its Command Source, so that a method that constructs no command object is not reported as a gap.
27. As an analyst, I want that method's command text to be read from the argument the caller supplies, so that the stored procedure the call site names is traced exactly as it is for every sibling method.
28. As a maintainer, I want all four `Execute` forms on the `Database` facade to be recognised together, so that a team using the raw form rather than the interpolated form needs no new ticket.
29. As a reviewer, I want a method that carries a mode argument to report `call_site` command semantics, so that a method whose caller decides between stored procedure and inline SQL reads the same as its six sibling methods.
30. As a reviewer, I want the execution call itself to be reported as the terminal sink, so that a Command Source with no command object still states where its command ends up.
31. As a maintainer, I want the deferred `FromSql` forms to stay unrecognised, so that a differently-shaped API is not forced into a rule built for immediate execution.

### Reporting the Contract Transaction

32. As an operator, I want the `/refresh` response to carry the Contract Transaction outcome, so that a run that rewrote two registration files says so.
33. As an operator, I want `refresh_cli` to print one line for the Contract Transaction, so that a silent two-file write becomes a visible fact.
34. As an operator, I want a skipped commit to name the reason it was skipped, so that "required but preflight failed" is never reported as "not required".
35. As a reviewer, I want the printed line to carry the status and the contract names only, so that the identifiers and paths a manifest already records do not crowd out the wrapper review rows.
36. As a maintainer, I want the response model to declare the field rather than pass it through untyped, so that a later rename fails a test instead of silently emptying the line.

### The measured outcome

37. As an analyst, I want `SQLDbContext`'s seven public methods to be fully accounted for — classified or delegated, none unclassified — so that Contract Preflight can create a Contract for it.
38. As an analyst, I want the IQCS refresh to report a created Contract rather than `preflight_failed`, so that its `SQLDbContext` calls can bind to semantics.
39. As an analyst, I want the IQCS refresh to record the created Contract in the external wrapper registry and the system catalog without a manual step, so that onboarding needs no hand-edited registration file.
40. As an analyst, I want RTTalentDB, ETR, EnterpriseApp and TOPCSCY to gain the same Contract from the same shared assembly once they are registered as Systems, so that one classifier repair covers five Systems.
41. As a reviewer, I want the Contract created for `CommonLibrary` to be keyed by the same Assembly Revision Boundary rule every other Contract uses, so that a team shipping a different build of the shared assembly gets a separate Contract rather than a silent mismatch.

### Regression safety

42. As a reviewer, I want a WebForms wrapper assembly to classify exactly as it does today, so that widening the recognition rule cannot re-rate existing evidence.
43. As a reviewer, I want the measured Y-DOCs stored-procedure counts to rise or hold, never fall, so that a shared code path change cannot quietly remove evidence.
44. As a reviewer, I want the existing `SQLFunc` and `SQLObject` Contracts to keep their current behaviour signatures byte for byte, so that a Contract Fingerprint that did not need to change does not change.

## Implementation Decisions

### Recognising a command object

- The command-object recognition rule gains a contract check. A type is a
  command object when it implements `IDbCommand`. The check runs whenever the
  analyzer holds type information able to answer it.
- When the contract cannot be checked, the rule falls back to comparing the
  type's short name against a multi-provider list. The list has the same shape
  the data adapter recognition rule already carries. The list gains the abstract
  type name beside the provider-specific ones.
- The two mechanisms answer one question and produce one outcome. The response
  shape records neither of them, because a Command Source resolved either way is
  the same fact.
- The widened rule is shared by both classification paths — local source wrapper
  and decompiled external assembly — with no scope switch. The two paths have
  always shared this code, and the measured evidence applies to both.

### Answering the contract question

- The shared reference-assembly directory enumeration gains the `net6.0` and
  `net8.0` reference-assembly packages. It keeps the .NET Framework 4.8 package
  it already yields. The project reader's framework-reference resolution and the
  wrapper decompiler's assembly resolver consume that one enumeration, so
  neither can be updated without the other.
- The packages arrive through the same download-without-referencing mechanism
  the .NET Framework 4.8 package already uses. The analyzer host's own build is
  unaffected, and a fresh clone needs no manual step.
- A decompiled assembly's methods are re-examined against the reference
  assemblies for the framework that assembly targets. Where that framework has
  no reference assemblies available, the contract check yields no answer, and the
  name fallback decides.
- Type binding over a decompiled assembly is partial by nature. A synthetic
  source built from per-method decompilation will not bind every symbol it names.
  The contract check treats an unbound type as "cannot answer" and hands it to
  the fallback. It never treats an unbound type as "does not implement".

### The Delegated Method

- A method is a Delegated Method when it declares no command construct of its own
  and its only database contact is an invocation of another method declared on
  the same type.
- The rule does not require the method body to consist solely of that call. A
  method that inspects or reshapes the sibling's result is still delegated.
  Measured against the real shared assembly, none of the three delegating
  methods is a bare pass-through.
- A method that has both its own command construct and a sibling call is
  classified by its own Command Source. Delegation is only ever consulted for a
  method that produced no Command Source.
- The delegation record names the sibling method it delegates to. A bare boolean
  would restate what the bucket already says. This codebase reports the reason
  for an absence, and the sibling's name is that reason.
- The behaviour surface completeness check counts a Delegated Method as
  understood. The set of unclassified public methods keeps its current meaning: a
  method the resolver could not account for by any rule.
- Delegation is not followed transitively for the purpose of rating evidence. A
  Delegated Method's own database target is not copied from its sibling. The
  sibling carries its own classified Command Source, and the delegation record
  states where to look.

### The connection behind a command factory

- The connection resolver gains a third rule. When a method's command comes from
  a factory call on an expression, that expression is the connection.
- The new rule runs last. It applies only when the command-constructor argument
  rule and the `Connection` property assignment rule both resolve nothing. An
  already-resolved Connection Behavior Boundary therefore cannot change value,
  by construction rather than by coincidence.
- The Connection Behavior Boundary vocabulary gains `context_connection` beside
  `constructor_connection` and `wrapper_connection`. A factory receiver that is a
  database context's `Database` facade reports `context_connection`. Every other
  factory receiver reports `wrapper_connection`, exactly as a Field-Held
  Connection does today.
- `context_connection` names a real difference. The database follows from the
  call site's declared receiver type through Context Connection Registration, not
  from a connection the wrapper holds. `SQLDbContext` serves five Systems and
  many derived context types, so `wrapper_connection` would record a connection
  that does not exist.
- The value is recorded in the behaviour signature. No code branches on it today,
  so the cost of a third value is the value itself.
- `CONTEXT.md` gains **Connection Behavior Boundary** as a term, defined against
  Context Connection Registration and Field-Held Connection so the three values
  are never conflated.
- An ADR records the decision to add a third value rather than reuse
  `wrapper_connection`. It is hard to reverse, because the value is part of every
  Contract Fingerprint that carries it. It is surprising without context, because
  reusing the existing value is the obvious first implementation. It is the
  result of a real trade-off.

### Entity Framework Core's raw-SQL execution

- The Command Source record is widened first, as a prefactor that changes
  nothing observable. It states where a method's command text comes from and
  where its terminal sink is. A constructed command object bound to a variable
  becomes one way to answer that, not the shape the record requires. The
  resolver's own design already promises that a further construct is one added
  rule; this makes the promise true before the rule that needs it arrives.
- A Command Source shape is then added for raw SQL executed through a database
  context's `Database` facade. The recognised calls are `ExecuteSqlRaw`,
  `ExecuteSqlInterpolated` and their asynchronous forms.
- The shape constructs no command object. The rule therefore reads the command
  text from the argument the caller supplies, and reports the execution call
  itself as the terminal sink.
- Command semantics follow the existing rule. A method that carries a mode
  argument reports `call_site`. A method whose mode is fixed in the body reports
  the fixed mode.
- Its Connection Behavior Boundary is `context_connection`, for the same reason
  the command-factory shape reports it: the receiver is the context's `Database`
  facade.
- The deferred `FromSql` forms stay unrecognised. They return a queryable,
  execute later, and hang off a `DbSet` rather than the `Database` facade. They
  need a differently-shaped rule and belong to their own ticket.

### Reporting the Contract Transaction

- The `/refresh` response model declares the Contract Transaction outcome as a
  typed field. It is not passed through untyped, so a later rename fails a test.
- The Contract Transaction outcome names why a commit was skipped. It reports
  `not_required` only when no Contract needed committing. It names
  `preflight_failed`, `program_scope` or `no_system_id` for the gate that
  actually stopped it.
- `refresh_cli` prints one line carrying the status and the contract names. The
  transaction identifier and the changed file paths stay in the manifest the
  Contract Transaction already writes.

### Domain model

- `CONTEXT.md`'s **Command Source** entry already names the command-factory
  construct. It gains the raw-SQL execution shape beside it.
- `CONTEXT.md` gains **Connection Behavior Boundary** as a new term.
- An ADR records the decision to recognise a command object by contract rather
  than by name. It is hard to reverse, because the fallback list would have to be
  re-grown. It is surprising without context, because a name list is the obvious
  first implementation and one is still present as fallback. It is the result of
  a real trade-off: a name list is simpler and needs no reference assemblies, but
  it silently mis-reports every convention it has not met.

## Testing Decisions

A good test here states an externally observable fact. It states nothing about
how the code reaches that fact. The observable facts are a method's reported
classification, the set of unclassified public methods, a created Contract's
name, a behaviour surface's completeness, and a printed line. Every test that
asserts a method is absent from a classified set also asserts which bucket it
landed in instead. This codebase's failure mode is a silent empty result.

### Seams

Four seams, all of them existing. No new seam is introduced.

**`StaticAnalyzerHost`** is the seam for all classification work. The
decompile-wrapper command reports the classified wrapper definitions, the
delegated methods, the unclassified public methods, and the contract proposal
that Contract Preflight consumes. Reference-assembly availability,
command-object recognition, delegation, Connection Behavior Boundary and
raw-SQL execution are all observable in that one response. No recognition rule
is tested directly.

**`analyze_service.refresh_source`** is the seam for onboarding and commit. It
reports the Contract Transaction outcome, including a skip reason. Contract
creation from a newly complete behaviour surface is observed here, and through
`run_contract_preflight` fed by a host response.

**`RefreshResponse`** is the seam for the response contract. It is the boundary
that drops an undeclared field today.

**`refresh_cli`** is the seam for the printed line. It lives in the
`llamaindex-spec-rag` repository and is exercised through captured output.

### Prior art

- `tests/test_wrapper_decompilation.py` shows the whole pattern the
  classification work needs. It builds a minimal assembly into a temporary
  directory, references it from a temporary project file, runs the host's
  decompile-wrapper command, and asserts on the reported classification and on
  the preflight outcome. It also shows the fixture-gated smoke test against a
  real checked-out assembly.
- `tests/test_refresh_atomic_commit.py` shows the commit pattern. It points the
  registry and catalog paths at a temporary directory and asserts on both files
  after a refresh.
- `tests/test_refresh_decompile_onboarding.py` shows the end-to-end pattern: a
  decompiled proposal flowing through refresh into a committed transaction.
- `tests/test_schemas.py` shows how this repository asserts a response model's
  declared field set.
- `tests/test_semantic_binding_availability.py` shows the project-reader
  pattern: write a minimal project, run the host, assert on the reported
  availability and on the named unresolved references.
- `llamaindex-spec-rag/tests/test_refresh_cli.py` shows the printing pattern: a
  stubbed refresh response, captured output, and an assertion on one line.

### Fixtures

The real `CommonLibrary.dll` is checked out under the IQCS repository. It is the
authoritative fixture for the measured outcome. A fixture-gated test asserts that
its seven methods are fully accounted for and that a Contract is created.

That file is not tracked, so every rule is additionally covered by minimal
assemblies built into temporary directories. Each one is modelled on a real
shape rather than invented:

- a command obtained through `CreateCommand` and declared as the abstract type
- a command type from a provider the analyzer names nowhere
- a type whose name resembles a command type but implements no command contract
- a method delegating to a sibling
- a method delegating while also reshaping the result
- a method with both its own construct and a sibling call
- a method that touches a database type and yields nothing
- a command factory whose receiver is a database context's `Database` facade
- a command factory whose receiver is a Field-Held Connection
- a command constructor that already resolves its connection, plus a factory call
- a method executing raw SQL through the `Database` facade, interpolated and raw
- a method using a deferred `FromSql` form

The prefactor that widens the Command Source record adds no fixture of its own.
Its whole acceptance is that every existing fixture reports what it reports
today.

### Baseline

The existing `SQLFunc` and `SQLObject` classified surfaces are asserted whole
today and stay asserted whole. Their Contract Fingerprints are captured before
the first change and compared after each ticket. The Y-DOCs WebForms counts are
captured and compared the same way.

Measured before this spec: neither `SQLObject.dll` nor `SQLFunc.dll` contains a
single `CreateCommand` call, and all 68 operations across the three registered
Contracts already report `wrapper_connection`. The connection rule change
therefore cannot reach them.

## Out of Scope

- **The deferred `FromSql` API.** `FromSqlRaw` and `FromSqlInterpolated` return a
  queryable, execute later, and hang off a `DbSet`. They need a
  differently-shaped rule and belong to their own ticket.
- **Following a delegation to rate the caller's evidence.** A Delegated Method
  names its sibling. It does not inherit the sibling's database target.
- **Delegation across a type boundary.** Only a call to a method declared on the
  same type counts. A call into another class is not a delegation here.
- **Recognising a connection or a data reader by contract.** Only the command
  object's recognition rule gains a contract check. The ADO.NET type census and
  the data adapter rule keep their current name-based form.
- **Registering the four newly cloned repositories in the catalog.** RTTalentDB,
  ETR, EnterpriseApp and TOPCSCY are not Systems in the catalog today. They
  cannot be refreshed until they are, and the Contract Transaction refuses a
  system identifier the catalog does not hold. Which repositories become Systems
  is a separate decision.
- **Branching on the Connection Behavior Boundary.** The value is recorded in the
  behaviour signature. No consumer reads it to make a decision, and this spec
  adds none.

## Further Notes

The five measured repositories were re-cloned and searched directly for this
spec. One finding reframed the whole ticket: not one of them writes its own
ADO.NET access. RTTalentDB shows a single `SqlCommand` in 382 C# files.
EnterpriseApp and TOPCSCY show none at all. Every one of the five declares
context classes deriving from the same `SQLDbContext` in the same
`CommonLibrary`. What looked like five separate classifier gaps is one gap in one
shared assembly, reached five times.

That evidence argues for the name list and against it at once. Against: five
Systems, one convention, and a single name would have sufficed. For: these five
are one team's Systems, and the catalog is expected to take on other teams'
Systems whose conventions nobody here has seen. A rule that asks what a type
implements needs no foreknowledge of those conventions. A rule that asks what a
type is called needs a ticket per convention. The name list survives only as the
degraded answer for a project the analyzer cannot bind.

The reference-assembly gap was found by measurement, not by reading. The
decompiler's own type system was run against the real `CommonLibrary.dll` and
reported `DbCommand` as an unknown type with no base types at all. Without that
check the contract rule would have been written, merged, and quietly answered
"cannot tell" on every modern assembly it was built for.

Causes 3, 4 and 5 were found the same way, after tickets 01 to 04 had landed. The
real assembly was decompiled and its proposal was fed to the completeness check.
The check named two blockers, not one, and the second — a missing Connection
Behavior Boundary on three already-classified methods — appeared nowhere in this
spec's first draft. An earlier draft also miscounted the delegating methods as
four and named `usp_ExecCmdGetJsonObjectListAsync` among them; measurement shows
three delegating methods, and that method carries its own Command Source.
`usp_ExecCmdGetJsonToTabletListAsync` went unmentioned entirely.

The lesson holds for cause 5 too. The automatic write path was already complete
and already tested end to end. It looked absent only because its result never
reached the operator's screen.
