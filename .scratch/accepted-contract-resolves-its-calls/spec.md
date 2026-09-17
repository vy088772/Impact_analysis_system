# An Accepted Contract Resolves Its Calls

Status: ready-for-agent

## Problem Statement

A maintainer runs `python -m impact_orch.refresh_cli IQCS`. The refresh prints
1128 wrapper review lines. Every line reports `unresolved_contract`. The
maintainer cannot tell which stored procedure each program calls.

The refresh already did the hard part. It decompiled `CommonLibrary.dll`, it
built a Contract for the `SQLDbContext` type, and it accepted that Contract
into the registry. The Contract carries `status: accepted` and
`evidence_kind: decompiled_auto`. The Contract resolves no call at all. IQCS
still measures an Executed Procedure Name share of 0.9% (8 of 862 Database
Invocations).

Two separate causes produce that result. Both are verified against the real
IQCS checkout, the real scan cache and the real decompilation cache.

**Cause one — the Contract omits the method the code actually calls.** The
Contract lists four methods. `usp_ExecCmdGetDataTableAsync` is not one of them,
and 196 calls use that name. The decompiler did examine the method. It found
that the method only calls `usp_ExecCmdGetDataSetAsync` and does no database
work itself. The decompiler recorded that relation in the decompilation cache
as a delegated method. It did not write that relation into the Contract. The
call site match reads the Contract only. The delegating name therefore matches
nothing. The decompiler recorded three such relations, and one of them is a
two-step chain: `usp_ExecCmdGetFisrtValueAsync` delegates to
`usp_ExecCmdGetDataTableAsync`, which delegates to `usp_ExecCmdGetDataSetAsync`.

**Cause two — a listed method still resolves nothing.** The Contract does list
`usp_ExecCmdGetDataSetAsync`, and 62 calls use that name. Those calls also stay
unresolved. The Contract gives the method the Command Mode `call_site`. A
`call_site` Command Mode means that the call site decides between an inline SQL
command and a stored procedure. The third argument, `isSP`, carries that
decision. The analyzer decides the Command Mode during the scan, and it decides
it from a fixed list of method names. `usp_ExecCmd*` names are not on that list,
so every such call records its Command Mode as `unknown`. The analyzer host
accepts no Contract input during a scan. A Contract that arrives after the scan
therefore cannot change the cached result. Re-running the measurement against
the same cache repeats the same `unknown` for ever.

The 259 affected calls already carry their stored procedure name. The scan
traced each name to a literal string, for example
`[dbo].[usp_IQCMgmt_Com_WorstItemsQry]`. Only the Command Mode is missing.

**A third problem makes the report hard to read.** Many of the 1128 review
lines are not database calls at all. `IUtilityService.SqlParam` accounts for 233
of them, and that method only builds one `SqlParameter` object.
`IUtilityService.ViewPath` accounts for 32 more, and that method only builds a
file path string. The maintainer removes such lines by hand, one System at a
time, in the wrapper review exclusion registry. The maintainer expects to
manage about one hundred Systems. Manual curation for each System does not
scale.

## Solution

Three changes, each independent of the others.

**Rating-Time Command Mode.** The scan records Observed Argument Facts for every
argument of a wrapper call: the kind of the argument, its literal value, and the
reason that the value stayed unresolved. The scan records these facts without
any knowledge of a Contract. The rating step then reads the Contract, finds the
mode argument by its declared index, and decides the Command Mode from the
recorded value. A Contract accepted today therefore resolves calls in a scan
captured yesterday. No second scan pass, and no trigger, is necessary.

**Delegation Alias.** The decompiler writes each delegated method into the
Contract as a Delegation Alias. An alias names one method and points to the
operation that does the work. A migration adds the missing aliases to the
Contracts that already exist. The call site match consults an alias when the
method name matches no operation directly.

**Observed Call Evidence.** The analysis gateway classifies a wrapper call as
`not_applicable` by itself when the evidence proves that the Local Implementer
touches no database. This removes a whole class of review noise from every
System at once, and it needs no entry in any exclusion registry.

The remaining noise, which no rule can decide, keeps a curated registry. That
registry gains a Global Exclusion Tier, so a decision that holds for every
System is reviewed once instead of one hundred times. A new tool proposes
candidates for that registry, with supporting evidence, so a maintainer
approves a list instead of reading source code.

## User Stories

1. As a maintainer, I want an accepted Contract to resolve the calls it
   describes, so that accepting a Contract produces a visible result.
2. As a maintainer, I want a Contract accepted today to apply to a scan
   captured yesterday, so that I do not re-scan every System to benefit from it.
3. As a maintainer, I want the analyzer to decide the Command Mode from the
   argument the Contract names, so that a wrapper outside the fixed name list
   still resolves.
4. As a maintainer, I want the scan to record each argument's literal value, so
   that the rating step can read a value the scan did not interpret.
5. As a maintainer, I want the scan to record why an argument stayed
   unresolved, so that a traced value and an untraceable variable never read the
   same.
6. As a maintainer, I want an argument that holds a variable to stay
   unresolved, so that the analyzer never guesses a Command Mode.
7. As a maintainer, I want the rating step to use the convention the analyzer
   already uses, so that a local wrapper and an external wrapper agree on what
   `true` means.
8. As a maintainer, I want a call to a delegating method to match the Contract,
   so that the most-used method in the codebase resolves.
9. As a maintainer, I want the decompiler to write its delegation finding into
   the Contract, so that the finding survives outside the decompilation cache.
10. As a maintainer, I want a delegation chain flattened to its final target, so
    that one lookup answers the match and no chain can loop.
11. As a maintainer, I want the Contract fingerprint to stay the same after the
    aliases arrive, so that another System still reuses the same Contract.
12. As a maintainer, I want the migration to read the cached decompilation
    result, so that adding aliases does not decompile the assembly again.
13. As a maintainer, I want the migration to cover every Contract, so that a
    Contract added later needs no second migration.
14. As a maintainer, I want a review line to name the method the source code
    calls, so that I can search for that name in the repository.
15. As a maintainer, I want the alias that produced a match recorded, so that I
    can trace how the analyzer reached its answer.
16. As a maintainer, I want the analyzer to clear a method that provably touches
    no database, so that I write no exclusion entry for it.
17. As a maintainer, I want the analyzer to keep a method in review when the
    evidence is incomplete, so that it never hides a real database call.
18. As a maintainer, I want a method that reaches a database through another
    method to stay in review, so that an indirect call is never cleared by
    mistake.
19. As a maintainer, I want one exclusion decision to serve every System, so
    that a framework method is reviewed once.
20. As a maintainer, I want a System to override a global exclusion decision, so
    that a name that means something different in one System stays correct.
21. As a maintainer, I want a tool to propose exclusion candidates, so that I
    approve a list instead of reading source code.
22. As a maintainer, I want each proposal to carry its evidence, so that I judge
    it without opening the repository.
23. As a maintainer, I want the tool to choose the tier for each proposal, so
    that I confirm a placement instead of deciding it.
24. As a maintainer, I want the tool to emit a registry fragment, so that I
    paste the approved result instead of writing it by hand.
25. As a maintainer, I want an exclusion entry removed once a rule covers it, so
    that the registry holds only the decisions a rule cannot make.
26. As a maintainer, I want the Executed Procedure Name share to rise above 30%
    for IQCS, so that I can confirm the change worked.
27. As a maintainer, I want to measure the result after each step, so that I
    know which change produced which gain.
28. As a maintainer, I want `SQLDbContext` calls to leave the unresolved review
    list, so that the list shows only the work that remains.
29. As a maintainer, I want the reverse lookup by table name to keep working
    during all of this, so that my main task is never blocked.
30. As an agent, I want the decisions recorded as ADRs before the code changes,
    so that I use the settled vocabulary in the code.
31. As an agent, I want a glossary entry for each new term, so that a later
    reader understands a field name without reading the commit.
32. As a maintainer, I want the change to serve any System that uses the same
    shared library, so that onboarding another System needs no new work.

## Implementation Decisions

### Rating-Time Command Mode

- The analyzer host records Observed Argument Facts on a wrapper call. For each
  argument it records three things: the kind of the argument, the literal value
  when one exists, and the reason that the value stayed unresolved. This mirrors
  the three fields the command text argument already uses.
- The analyzer host records these facts from the syntax at each call site,
  with one refinement: an omitted trailing optional argument's declared
  default value is read via semantic binding to the referenced assembly's own
  metadata, guarded so that only a uniquely bound symbol is trusted (see
  ADR-0030 for the full guard description). This is not a Contract read. The
  analyzer host still reads no Contract, and still gains no Contract input
  channel. The scan produces facts. The rating step interprets them. This
  boundary already holds elsewhere in the system, and this change keeps it.
- The existing command text fields stay exactly as they are. The command text
  argument is not folded into the new structure. That path works and carries
  tests, and a rewrite buys nothing.
- The analysis gateway decides the Command Mode during rating. It reads the
  Contract's argument roles, finds the mode argument by index, and reads the
  recorded value for that index.
- The gateway applies the convention the analyzer host already applies for a
  local wrapper: `true`, `"SP"` and `"StoredProcedure"` mean a stored procedure,
  and `false` means an inline SQL command. The Contract records no value
  mapping, and the Contract schema does not change for this.
- The same rule lives in two places after this change: in the analyzer host for
  a local wrapper, and in the gateway for an external wrapper. The risk that the
  two drift apart. ADR 0028 records that risk. Unifying the two rules is a
  larger change, and this spec leaves it out.
- An argument that holds a variable, an expression or a call stays unresolved.
  The gateway then keeps the Command Mode unresolved. It never falls back to a
  default.
- The scan output gains a field, so the scan cache version rises by one. Every
  existing cache becomes invalid, and each System re-scans on its next refresh.
  This is the mechanism that already exists for a scan schema change. This
  change adds no refinement marker, no second pass and no trigger.

### Delegation Alias

- A Contract gains a Delegation Alias collection. An alias maps one method name
  to the operation that performs the work.
- The alias collection sits outside the behavior signature. The Contract
  registry computes the Contract fingerprint from the behavior signature, so the
  fingerprint does not change when aliases arrive. A System that already matched this Contract by
  fingerprint continues to reuse it.
- The decompiler flattens a delegation chain before it writes an alias. An alias
  always points to the operation that does the work, never to another alias. One
  lookup therefore answers a match, and no chain can loop.
- A migration adds the missing aliases to the Contracts already in the registry.
  The migration reads the cached decompilation result. It does not decompile the
  assembly again.
- The migration walks every Contract in the registry, not one named Contract.
  Only `SQLDbContext` carries delegations today. `SQLFunc` and `SQLObject` carry
  none. The migration also covers a Contract that arrives later, so nobody
  writes a second migration.
- The call site match consults the alias collection only when the method name
  matches no operation directly. A direct match always wins.
- A call matched through an alias reports the method name that the source code
  uses. The gateway records the alias that produced the match beside that name
  as provenance. A review line therefore names a symbol that the maintainer can
  search for.

### Observed Call Evidence

- The gateway classifies a wrapper call as `not_applicable` when two conditions
  hold together: the call resolved to a Local Implementer, and the scan holds at
  least one Database Invocation record for that implementer's method, and every
  such record names no database receiver type.
- The rule requires at least one record. The rule clears no method that holds
  no record. The scan does not record a call to another method inside the same
  project, so an absence of records proves nothing. A method that reaches a
  database through a second method carries no record of its own, and it looks
  the same as a method that does nothing. Such a method stays in review.
- This rule needs facts from across the whole scan, and the rating step builds
  one gateway for each source file. The rating step therefore builds one index
  first. The index names every class and method that touches a database
  receiver type. The rating step passes that index to each gateway. The
  classification stays in the same place as every other wrapper status.
- The analyzer host does not change for this rule. This change adds no call
  graph.

### Wrapper Review Exclusion Registry

- The registry gains a Global Exclusion Tier under the key `_global`. An entry
  there applies to every System.
- A System's own entry wins over a global entry for the same receiver type and
  method name. This leaves an escape route for a name that means something
  different in one System.
- The framework entries already recorded for one System move to the global
  tier. Those entries describe framework behavior, and framework behavior does
  not change between Systems.
- A maintainer removes the `SqlParam` entry recorded for IQCS once Observed Call
  Evidence clears that method by rule. The `ViewPath` entry stays, because that
  method carries no record and the rule cannot clear it.

### Exclusion Candidate Tool

- A new tool reads a scan result and the registry, and proposes exclusion
  candidates. It reports only the candidates that the automatic rules did not
  already decide.
- The tool emits a registry fragment that a maintainer pastes directly. It also
  emits supporting evidence for each candidate: the call count, and whether any
  System ever resolved that receiver and method.
- The tool proposes the global tier when the receiver type is empty or names a
  known framework type. It proposes the System's own tier otherwise.
- The tool only reads. It never edits the registry.

### Sequence

The work lands in this order, and the result is measured between the steps.

1. The ADRs and the glossary.
2. Rating-Time Command Mode. Expected result: `usp_ExecCmdGetDataSetAsync` (62
   calls) and `usp_ExecCmdGetCountAsync` (1 call) resolve. The Executed
   Procedure Name share for IQCS reaches about 7%.
3. Delegation Alias. Expected result: `usp_ExecCmdGetDataTableAsync` (196 calls)
   resolves. The share reaches 30% or more.
4. Observed Call Evidence, the Global Exclusion Tier and the candidate tool.

## Testing Decisions

A good test states an outcome that a maintainer can observe. It asserts on the
resolved Executed Procedure Name, on a review status, or on a registry
fragment. It does not assert on the shape of an internal call.

**The main seam is the rating step over a scan of the real IQCS checkout.** One
test scans once and asserts twice: that the scan recorded the Observed Argument
Facts, and that the rating step resolved the Executed Procedure Name for the
affected calls. This seam covers the Command Mode change, the Delegation Alias
change and the Observed Call Evidence rule, and it is the same path that
produces the acceptance measurement. Prior art: the existing Local Implementer
test drives the real analyzer host against the real IQCS checkout for exactly
this class of change.

**Three narrow seams cover the parts the main seam cannot isolate.**

- The Contract migration. The test feeds a cached decompilation result and
  asserts three results: the three aliases arrive, the two-step chain flattens
  to its final target, and the Contract fingerprint does not change. The
  fingerprint assertion guards the cross-System reuse promise.
- The exclusion registry loader. The test asserts that a global entry applies to
  any System, and that a System's own entry wins for the same receiver type and
  method name.
- The candidate tool's report builder. The test asserts the shape of the emitted
  fragment and the tier chosen for each candidate. Prior art: the coverage
  report builds its report through a function that a test calls directly.

**Synthetic cases hang off the main seam's modules, and open no new seam.**

- An argument that holds a variable keeps the Command Mode unresolved.
- An argument with the literal `false` produces an inline SQL command.
- An argument with the literal `true` produces a stored procedure.
- A method with two records, neither naming a database receiver type, is
  cleared. `SqlParam` is the real example.
- A method with no record at all stays in review. `GetListFromSysParam` is the
  real example, and it reaches a database through a second method.
- A method with one record that names a database receiver type is never
  cleared. `GetMstCodes` is the real example.

**The acceptance measurement** is the existing coverage report. IQCS must move
from an Executed Procedure Name share of 0.9% (8 of 862) to 30% or more, and
`SQLDbContext` calls must leave the unresolved review list.

## Out of Scope

- **A Contract-aware re-scan.** An earlier plan gave the analyzer host a
  Contract input channel and ran a second scan pass after a Contract was
  accepted. That plan also needed a refinement marker, a termination rule and a
  new report line. Rating-Time Command Mode removes the need for all of it, so
  this spec builds none of it.
- **A call graph inside the analyzer host.** A call graph would let the Observed
  Call Evidence rule follow a chain of calls between methods, and it would clear
  `ViewPath` as well. The rule ships without it, and a method it cannot decide
  stays in review. A later spec considers a call graph only if the remaining
  review noise justifies it.
- **A value mapping field on the Contract.** The Contract does not record that
  `true` means a stored procedure. The gateway reuses the existing convention
  instead.
- **One shared Command Mode implementation.** The rule stays in two places. A
  single implementation would move the local wrapper path into the rating step,
  and that is a larger change.
- **Folding the command text argument into the Observed Argument Facts.** The
  command text keeps its own fields.
- **Onboarding other Systems.** `EnterpriseApp`, `RTTalentDB` and `TOPCSCY` use
  the same shared library but are not registered Systems today. This change
  makes them benefit automatically when they are registered. Registering them is
  separate work.
- **Raising the Resolved Connection Source share.** That share stays at its
  current level, and its main reason code is a separate problem.

## Further Notes

**Three ADRs record the decisions, and they are written before the code
changes.**

- ADR 0027 — a Delegation Alias sits outside the behavior signature, so the
  Contract fingerprint stays stable and cross-System reuse survives.
- ADR 0028 — the Command Mode resolves at rating time, and the scan stays free
  of Contract knowledge. This ADR also records the accepted risk that the rule
  now lives in two places.
- ADR 0029 — Observed Call Evidence requires at least one record. An absence of
  records is not evidence of safety.

**The project's existing domain context glossary gains five terms**: Delegation
Alias, Observed Argument Facts, Rating-Time Command Mode, Observed Call Evidence
and the Global Exclusion Tier. The terms go into the glossary the project
already keeps, not into a second file, so one vocabulary serves the whole
repository.

**Delegation Alias and Delegated Method are two terms, not one.** The glossary
already defines a Delegated Method as the decompiler's raw finding, and states
that the finding never follows a delegation chain. That stays true. A Delegation
Alias is the entry derived from that finding for a Contract, and the derivation
is the one step that follows a chain to its end. The two definitions
cross-reference each other.

**Every number in this spec was measured, not estimated.** The call counts, the
0.9% share, the four Contract methods, the three delegations and the two-step
chain all come from the real IQCS scan cache, the real decompilation cache and
the real Contract registry.

**The reverse lookup by table name does not depend on any of this.** That lookup
matches a table name against cached scan text. It keeps working at every step,
so the maintainer's main task is never blocked while this work lands.
