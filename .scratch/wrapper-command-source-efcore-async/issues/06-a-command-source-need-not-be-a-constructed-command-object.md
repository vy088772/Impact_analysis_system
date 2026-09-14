# 06 — A Command Source need not be a constructed command object

**What to build:** Nothing observable changes. Every wrapper method classifies
exactly as it does today, with the same command semantics, the same terminal
sink and the same Connection Behavior Boundary. This ticket makes the next one
possible.

The Command Source resolver already states the shape this work needs: every
construct that can supply a command text and a terminal sink is recognised by
exactly one rule, and a further construct is one added rule rather than a change
to the classification flow around it. The record the rules produce does not yet
keep that promise. It carries a command object construction and requires a
command variable, and the classification flow reads the command text out of that
construction's first argument.

Ticket 08's construct has neither. Raw SQL executed through a database context's
`Database` facade constructs no command object and binds no command variable;
its command text is an argument of the execution call itself. Added as the
resolver stands, it would force a branch through the classification flow — the
exact change the resolver's own design forbids.

So the promise is made true first. A Command Source describes where a method's
command text comes from and where its terminal sink is. A constructed command
object bound to a variable becomes one way to answer that, not the only shape
the record can hold.

Make the change easy, then make the easy change. The acceptance is that nothing
moved.

**Blocked by:** None — can start immediately.

**Status:** resolved

- [x] A Command Source states where a method's command text comes from and where its terminal sink is, without requiring a constructed command object bound to a variable
- [x] The explicit command object rule, the declared command variable rule and the data adapter rule each classify exactly what they classify today
- [x] The real shared assembly under the IQCS checkout reports byte for byte the same classified, delegated and unclassified sets it reports today (fixture-gated, skipped when the checkout is absent)
- [x] The existing `SQLFunc` and `SQLObject` classified surfaces are asserted whole and unchanged, and their Contract Fingerprints are unchanged byte for byte
- [x] The measured Y-DOCs stored-procedure counts hold — this ticket may not move a single one
- [x] A new construct can be added as one further rule, without a branch in the classification flow around it

## Note

`tools/StaticAnalyzerHost/CSharpAnalyzer.cs`, inside `WrapperAnalyzer`'s nested
`CommandSourceResolver` and its `CreateDefinition` consumer:

- `CommandSource` drops its `Creation` field (an `ObjectCreationExpressionSyntax?`) and gains two
  explicit fields in its place: `CommandTextExpression` (`ExpressionSyntax?`) and
  `ConnectionExpression` (`string?`, already trimmed to text — matching how `CreateDefinition`
  always consumed it). Each rule now states its own command text and connection directly at the
  point it builds its `CommandSource`, instead of `CreateDefinition` reaching back into a
  `Creation.ArgumentList.Arguments[0]`/`[1]` to derive them generically. `Creation` had no other
  reader anywhere in the file (checked directly) — every one of its two uses was that same
  derivation — so removing it deletes a field rather than replacing it with a narrower one.
- `ResolveCommandObjectSources` (the explicit command object rule) now computes
  `creation.ArgumentList?.Arguments.ElementAtOrDefault(0)?.Expression` and
  `...ElementAtOrDefault(1)?.Expression?.ToString().Trim()` itself, at the same call site, with the
  same nullable-chain shape `CreateDefinition` used before — byte-identical values for every
  existing shape.
- `ResolveDataAdapterSources` (the data adapter rule) already knows its `arguments` list has
  exactly two elements by the point it yields (the `Count: 2` guard above it), so it reads
  `arguments.Value[0].Expression` / `arguments.Value[1].Expression.ToString().Trim()` directly —
  same values as the generic derivation produced for an adapter's own `creation`, since an
  adapter's two-argument constructor and a command's constructor share the same
  (text, connection) argument shape.
- `ResolveDeclaredCommandSources` (the declared command variable rule, e.g.
  `DbCommand cmd = connection.CreateCommand();`) passes `null` for both new fields, exactly as the
  old `Creation: null` already produced for it — no observable change, stated directly instead of
  derived.
- `CreateDefinition` reads `commandSource.CommandTextExpression` / `commandSource.ConnectionExpression`
  in place of the two `commandSource.Creation?.ArgumentList?...` lines. Same two local variables,
  same downstream use (literal check, parameter-name matching, property-assignment fallback,
  constructor-connection-parameter lookup) — untouched.
- The `if (commandSource.VariableName is null) return null;` early return is deleted from
  `CreateDefinition`. Traced every remaining read of the `commandVariable` local it guarded: there
  was exactly one, the guard itself — nothing downstream in `CreateDefinition` used it. Of the
  three existing rules, only the explicit command object rule can ever produce a null
  `VariableName` (an object creation bound to no simple variable, e.g. a fluent
  `new SqlCommand(...).ExecuteNonQuery()` or a bare `return new SqlCommand(...)`); the declared
  variable rule and the data adapter rule each already guarantee a non-null one before yielding
  (`variable.Identifier.Text` is never null; the adapter rule's own `if (variable is null) continue;`).
  For that one rule, a null `VariableName` already left `ResolveTerminalSinks` returning no
  invocations and `CommandPropertyReceiver` as `""` (matching no real assignment) before this
  change — the guard's removal lets such a method fall through to a `WrapperDefinition` with
  `TerminalSink: null` / `ReachesStoredProcedureSink: false` instead of no `WrapperDefinition` at
  all, a state the type already represents for other reasons (a command built but never executed).
  No fixture in this repository's test suite or under the checked-out System_Dept_1 assemblies
  exercises a variable-less explicit command construction (checked by grep across `tests/` and by
  the unchanged fixture-gated results below), so this is unreached by every measured case; it
  exists to let ticket 08's raw-SQL rule reach `CreateDefinition` without a further branch there.
- Net effect: `CommandSource` states a construct's command text and terminal sink directly: a
  future rule with no command object and no bound variable (ticket 08's raw-SQL-through-`Database`
  shape) supplies its own `CommandTextExpression` and its own `ResolveTerminalSinks` closure and
  needs no change to `CreateDefinition` or to any of the three existing rules — the resolver's own
  documented promise ("a further construct is one added rule, not a change to the classification
  flow around it") now holds for a construct with neither a command object nor a variable, not only
  for one with a command object bound to no variable.
- Verification: `dotnet build` on `tools/StaticAnalyzerHost` — 0 warnings, 0 errors. Full Python
  test suite run twice, once against this change and once against the unmodified baseline
  (`git stash`), excluding the same two live-ODBC-only scripts ticket 04's note excluded
  (`tests/test_search_roles.py`, `tests/test_sp_tables.py`): both runs report the identical
  `890 passed, 12 failed, 1 skipped` and the identical 12 `FAILED` test IDs byte for byte — the
  failures are pre-existing (live SQL Server/ODBC connectivity this sandbox lacks; e.g.
  `test_external_wrapper_discovery.py`'s `assert 'unresolved' == 'proven'`), none newly introduced.
  The fixture-gated real-`CommonLibrary.dll` tests under the checked-out
  `data/repos/System_Dept_1/IQCS` fixture, and the fixture-gated `SQLFunc`/`SQLObject`/Y-DOCs
  whole-surface assertions in `tests/test_command_object_recognition.py`,
  `tests/test_delegated_method.py` and `tests/test_wrapper_decompilation.py`, all ran (the
  checkout is present) and passed unchanged — the measured classified/delegated/unclassified sets,
  Contract Fingerprints and stored-procedure counts this ticket's acceptance criteria name are
  confirmed byte for byte rather than assumed.
