# 02 — A method that delegates to a sibling is reported as delegated, not as a gap

**What to build:** A wrapper method that constructs no command of its own, and
whose only database contact is a call to another method declared on the same
type, is reported as a **Delegated Method** naming the sibling it delegates to
— a third outcome beside "classified" and "unclassified".

Today such a method lands in the same bucket as a method whose construct the
resolver genuinely failed to understand. Two different facts are read from one
bucket: a fully-traced delegation blocks Contract creation exactly as an
unexplained gap does.

A Delegated Method counts as understood. The set of unclassified public methods
— the set that blocks Contract creation — keeps its current meaning: a method
the resolver could not account for by any rule.

Measured outcome: the shared `SQLDbContext`'s four delegating methods
(`usp_ExecCmdGetFisrtValueAsync`, `usp_ExecCmdGetDataTableAsync`,
`usp_ExecCmdGetJsonObjectAsync`, `usp_ExecCmdGetJsonObjectListAsync`) move out
of the unclassified set and name the sibling each one calls.

**Blocked by:** None — can start immediately.

**Status:** resolved

- [x] A method with no command construct of its own, whose only database contact is a call to a method declared on the same type, is reported as delegated and names that sibling method
- [x] A delegating method that also inspects or reshapes the sibling's result is still reported as delegated — the rule does not require a bare pass-through, because none of the real methods is one
- [x] A method that has both its own command construct and a sibling call is classified by its own Command Source; delegation is consulted only for a method that produced no Command Source
- [x] A method that touches a database type and yields neither a Command Source nor a delegation stays unclassified, exactly as it does today
- [x] A Delegated Method and an unclassified method are reported under different names, and the behaviour surface completeness check counts a Delegated Method as understood
- [x] A Delegated Method does not inherit its sibling's database target; the delegation record states where to look, and nothing more
- [x] The real shared assembly under the IQCS checkout reports its delegating methods as delegated, each naming its sibling (fixture-gated, skipped when the checkout is absent)
- [x] `CONTEXT.md` gains **Delegated Method**, defined against "unclassified public method" so the two can never be conflated
- [x] The existing `SQLFunc` and `SQLObject` classified surfaces are unchanged, asserted whole — neither assembly gains a delegated method it did not have

## Note

`tools/StaticAnalyzerHost/CSharpAnalyzer.cs` (`WrapperAnalyzer`):

- New `DelegatedMethod(MethodIdentity, DelegatesTo)` record and `GetDelegatedMethods(root,
  definitions)`: scans the same "no Command Source, touches an ADO.NET type" population
  `GetUnclassifiedPublicMethods` used to report whole, and resolves the single, unambiguous
  invocation of a method declared on the same type (`Foo(...)` or `this.Foo(...)`, a recursive
  self-call excluded). Zero or two-or-more distinct sibling calls both yield no delegation —
  ambiguity is not guessed at, it stays a gap.
- `GetUnclassifiedPublicMethods` gained a `delegatedMethods` parameter and now excludes those
  identities too, so "unclassified" keeps its exact current meaning: neither classified nor
  delegated. `DecompiledWrapperClassifier.Classify` computes delegation once and threads it to
  both.
- `DecompiledWrapperClassification` gained a `DelegatedMethods` field; `Program.cs`'s
  `decompile-wrapper` response gained a top-level `delegated_methods` array
  (`{method_identity, delegates_to}` — nothing else, so delegation can never be mistaken for
  inherited evidence). `public_database_operations_complete` and `unclassified_public_methods`
  already derive from `UnclassifiedPublicMethods`, so both correctly count a Delegated Method as
  understood with no separate wiring.
- New `tests/test_delegated_method.py` covers all six shapes with a stand-in fixture
  (delegate-and-reshape, both-own-and-sibling classified by its own source, touches-but-calls-no-
  sibling stays unclassified, two-distinct-siblings stays unclassified), the delegation record's
  exact two-key shape, and fixture-gated smoke tests against the real `CommonLibrary.dll`,
  `SQLFunc.dll`, and `SQLObject.dll`.
- Measured against the real assembly: three methods delegate —
  `usp_ExecCmdGetFisrtValueAsync` → `usp_ExecCmdGetDataTableAsync` →
  `usp_ExecCmdGetDataSetAsync`, and `usp_ExecCmdGetJsonObjectAsync` →
  `usp_ExecCmdGetJsonObjectListAsync` — not the four this ticket's own problem statement named.
  Ticket 01's Note already flagged this: `usp_ExecCmdGetJsonObjectListAsync` constructs its own
  `DbCommand` directly (measured, not guessed) and was classified by ticket 01, not delegated
  here. Only `usp_ExecCmdGetCountAsync` (EF Core's high-level raw-SQL form, its own out-of-scope
  ticket) remains unclassified; `SQLDbContext`'s seven public methods are now fully accounted
  for otherwise. `tests/test_command_object_recognition.py`'s ticket-01 fixture test was updated
  to match (its `REMAINING_UNCLASSIFIED_METHODS` constant shrank from four names to the one that
  is still genuinely out of scope).
- `SQLFunc`/`SQLObject` measured to gain zero delegated methods, confirmed by a fixture-gated
  test each; the existing whole-surface assertions in `tests/test_wrapper_decompilation.py`
  continue to pass unchanged.
- `CONTEXT.md` gained a **Delegated Method** entry beside **Command Source**, defined against
  "unclassified public method" per the acceptance criterion.
- Full test suite run before and after (excluding two scripts needing a live SQL Server/ODBC
  connection, unrelated to this change): 876 passed, the same 11 pre-existing failures both
  times, none newly introduced.

### Post-review follow-up

`/code-review` (Standards axis) flagged `GetUnclassifiedPublicMethods` and `GetDelegatedMethods`
as a near-identical walk (Duplicated Code, judgement call) and `IsSqlCommandType`/
`IsDataAdapterType` as two separately-spelled provider lists that could drift apart again
(Repeated Switches, judgement call). Both addressed:

- Extracted `FindUnclassifiedCandidates` — the one walk over "public, ADO.NET-touching,
  not-yet-classified" methods that both `GetDelegatedMethods` and `GetUnclassifiedPublicMethods`
  now derive from, so the two outcomes can no longer drift on which methods they decide between.
- Extracted `AdoNetProviderPrefixes` (`Db`/`Sql`/`OleDb`/`Odbc`/`Npgsql`/`MySql`) as the one list
  `IsSqlCommandType` and `IsDataAdapterType` both build their comparison from.

The review's third finding (Primitive Obsession — three parallel identity collections instead
of one value type for the three-way outcome) was left as-is: the review itself called it "not
clearly wrong," and CONTEXT.md's **Delegated Method** entry already states the "never conflated"
invariant the finding worried about losing. Introducing a new type for three call sites is the
kind of generality the spec's own testing conventions warn against reaching for speculatively.

Re-verified after the refactor: full test suite (876 passed, same 11 pre-existing failures) and
the real `CommonLibrary.dll`/`SQLFunc.dll`/`SQLObject.dll` fixture-gated tests, unchanged output.

The Spec axis found no missing/wrong requirements, only that ticket 01's Y-DOCs-count checkbox
read more certain than its own Note supported — fixed by annotating that checkbox inline (see
ticket 01) rather than by changing any code, since the underlying claim was already true and
already honestly caveated in prose.
