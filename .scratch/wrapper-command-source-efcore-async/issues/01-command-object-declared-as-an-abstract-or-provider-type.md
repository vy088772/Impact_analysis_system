# 01 — A command object declared as an abstract or provider type resolves its Command Source

**What to build:** A wrapper method that obtains its command through a
connection's `CreateCommand` — so the command object is declared as the
abstract ADO.NET command type rather than constructed as one named provider
type — resolves its Command Source and is reported as a classified wrapper
definition instead of an unclassified public method.

The command-object recognition rule today compares a type's short name against
exactly one name. Its sibling rule — the one that recognises a data adapter —
has always compared against a multi-provider list. This ticket brings the two
into agreement by widening the command rule's comparison to the same list
shape, adding the abstract command type alongside the provider-specific ones.

Measured outcome: the shared `SQLDbContext`'s `usp_ExecCmdGetDataSetAsync`
moves from the unclassified set to a classified wrapper definition, carrying
its stored-procedure command semantics and its terminal sink. The behaviour
surface stays incomplete — four sibling methods and one Entity Framework Core
method remain unaccounted for — so no Contract is created yet. That is ticket
02's and a later ticket's work.

**Blocked by:** None — can start immediately.

**Status:** resolved

- [x] A wrapper method whose command object is declared as the abstract ADO.NET command type resolves its Command Source, with its command semantics and terminal sink reported exactly as an equivalently-shaped method using the one previously-recognised provider type does
- [x] The widened comparison names the same providers the data adapter recognition rule already names, so the two sibling rules no longer disagree about which providers exist
- [x] The change is observable through the analyzer host's decompile-wrapper response — the classified wrapper definitions and the unclassified public methods — and through the same response for a local source wrapper, with no scope switch between the two paths
- [x] The real shared assembly under the IQCS checkout reports `usp_ExecCmdGetDataSetAsync` as classified (fixture-gated, skipped when the checkout is absent)
- [x] That same assembly still reports an incomplete behaviour surface, and the remaining unclassified methods are named — a partial repair is not presented as a whole one
- [x] The existing `SQLFunc` and `SQLObject` classified surfaces are unchanged, asserted whole
- [x] The Y-DOCs WebForms stored-procedure counts rise or hold, never fall (verified indirectly — see Note; no dedicated count tool exists to measure this directly)

## Note

`tools/StaticAnalyzerHost/CSharpAnalyzer.cs`:

- `IsSqlCommandType` now compares against `DbCommand`/`SqlCommand`/`OleDbCommand`/`OdbcCommand`/
  `NpgsqlCommand`/`MySqlCommand` — the same provider set `IsDataAdapterType` already carried,
  `Command` in place of `DataAdapter` — instead of the literal `SqlCommand` alone.
- Widening the name list on its own does not cover the measured method: decompiling the real
  `CommonLibrary.dll` showed `usp_ExecCmdGetDataSetAsync` never constructs a command with `new`
  at all — `DbCommand cmd = Database.GetDbConnection().CreateCommand();` — so
  `CommandSourceResolver` gained a second rule, `ResolveDeclaredCommandSources`, that recognises
  a local variable declared as a command type and bound to any non-`new` initializer (a factory
  call). An initializer that is itself an object creation is left to the existing
  `ResolveCommandObjectSources`, so `DbCommand cmd = new SqlCommand(...)` is still one Command
  Source, not two (covered by
  `test_command_declared_abstract_but_constructed_with_new_is_not_double_counted`).
  `CommandSource.Creation` became nullable to carry this (no constructor argument list to read a
  command text/connection argument from for this shape); ordering moved from
  `Creation.SpanStart` to an explicit `SpanStart` field on the record.
- Both classification paths already shared `CommandSourceResolver`, so no scope switch was
  needed between local source and decompiled wrapper.
- New `tests/test_command_object_recognition.py` covers: the abstract-type-via-`CreateCommand()`
  shape resolving identically to an equivalently-shaped provider-type method (local source), the
  widened provider list (parametrised over the four newly recognised names), the no-double-count
  case, a coincidental name staying unrecognised, the same `CreateCommand()` shape through the
  decompiled-wrapper path, and a fixture-gated smoke test against the real IQCS
  `CommonLibrary.dll`.
- Measured against that real assembly: `usp_ExecCmdGetDataSetAsync` is now classified
  (`terminal_sink = ExecuteReaderAsync`, `reaches_stored_procedure_sink = true`,
  `method_semantics = call_site` — the method's own `isSP` parameter gates stored-procedure vs.
  inline mode, which `ResolveMethodSemantics` already reported correctly once a Command Source
  existed to feed it). Two more methods that share the exact same `CreateCommand()` shape
  (`usp_ExecCmdGetJsonObjectListAsync`, `usp_ExecCmdGetJsonToTabletListAsync`) were classified as
  a byproduct — this ticket's rule is general, not method-specific. The spec's problem statement
  named these two among the four methods it expected to delegate to a sibling; measurement shows
  otherwise — both construct their own command directly. Only three methods actually delegate
  (`usp_ExecCmdGetFisrtValueAsync`, `usp_ExecCmdGetDataTableAsync`, `usp_ExecCmdGetJsonObjectAsync`,
  ticket 02's work), and one more stays unclassified for its own out-of-scope reason
  (`usp_ExecCmdGetCountAsync`, EF Core's high-level raw-SQL form). Four remain unclassified,
  named, not silently dropped; the behaviour surface is still reported incomplete.
- No regressions: the full test suite (excluding two scripts that need a live ODBC/SQL Server
  connection unrelated to this change) was run before and after this change and produced the
  identical 11 pre-existing failures both times, none newly introduced — including the
  `SQLFunc`/`SQLObject` fixture-gated end-to-end tests in `tests/test_wrapper_decompilation.py`,
  which assert `SQLFunc`'s classified surface whole and continue to pass unchanged. No dedicated
  Y-DOCs stored-procedure count tool exists in this repo to capture a before/after number
  directly; the SQLObject/TTPUR fixture-gated tests (which do exercise the real Y-DOCs checkout)
  passing unchanged is the verification available for "rise or hold, never fall."
- `CONTEXT.md`'s **Command Source** entry updated to describe the widened, multi-provider,
  factory-call-aware recognition instead of implying one named construction is the only
  recognised construct. No ADR: this ticket is a name-list/detection-surface widening,
  reversible by narrowing the list back; ticket 04's contract-based recognition is the decision
  that gets the ADR per the spec's Domain model section.
