# 08 — Raw SQL executed through a context's Database facade resolves its Command Source

**What to build:** A full IQCS refresh reports a created Contract instead of
`onboarding=preflight_failed`, and both the external wrapper registry and the
system catalog carry it afterwards, with no manual step.

This is the whole spec's measured outcome. It arrives here because this ticket
closes the last gap.

A wrapper method that executes raw SQL through a database context's `Database`
facade resolves its Command Source. The recognised calls are `ExecuteSqlRaw`,
`ExecuteSqlInterpolated` and their asynchronous forms. This shape constructs no
command object at all, so every rule built around a command object misses it.
The method is public, its body names an ADO.NET type, and no rule accounts for
it — so it lands in the unclassified set, which is the honest answer today and
the wrong answer after this ticket.

The measured method is `SQLDbContext.usp_ExecCmdGetCountAsync`. It builds a
`FormattableString` from its own command text parameter and passes it to
`ExecuteSqlInterpolatedAsync`. It is the last unclassified method of the shared
assembly. A single unclassified public method blocks Contract creation
completely, so tickets 01, 02 and 07 write nothing without this one.

All four `Execute` forms are recognised together. They share one receiver, one
return semantics, and differ only in whether the string is interpolated or raw.
Recognising one and not the others would need a new ticket the first time
another team uses the raw form — the ticket-per-convention cost this spec exists
to remove.

The deferred `FromSql` forms stay unrecognised. They return a queryable, execute
later, and hang off a `DbSet` rather than the `Database` facade.

**Blocked by:** 06 (the Command Source record must hold a construct with no
command object and no command variable) and 07 (the `context_connection` value
this shape reports; without it the method classifies but the surface still fails
on an empty Connection Behavior Boundary).

**Status:** resolved

- [x] A wrapper method that executes raw SQL through a context's `Database` facade is reported as a classified wrapper definition, not as an unclassified public method
- [x] All four `Execute` forms resolve — raw and interpolated, synchronous and asynchronous
- [x] The command text is read from the argument the caller supplies, so the target the call site names is traced exactly as it is for a sibling method that does construct a command
- [x] The execution call itself is reported as the terminal sink, so a Command Source with no command object still states where its command ends up
- [x] A method carrying a mode argument reports `call_site` command semantics; a method whose mode is fixed in the body reports the fixed mode
- [x] The method's Connection Behavior Boundary is `context_connection`
- [x] A method using a deferred `FromSql` form stays unclassified and is named — the unrecognised shape is visible, not silently dropped
- [x] The real shared assembly under the IQCS checkout reports all seven public methods as classified or delegated, none unclassified, and its proposal passes the completeness check (fixture-gated, skipped when the checkout is absent)
- [x] A full IQCS refresh reports a created Contract, and both the external wrapper registry and the system catalog carry it afterwards
- [x] `CONTEXT.md`'s **Command Source** entry names the raw-SQL execution shape beside the command-factory shape

## Note

`tools/StaticAnalyzerHost/CSharpAnalyzer.cs`, inside `WrapperAnalyzer`'s nested
`CommandSourceResolver` and its `CreateDefinition` consumer:

- `CommandSourceResolver` gains a fourth rule, `ResolveRawSqlExecutionSources`, matching a call to
  `ExecuteSqlRaw`, `ExecuteSqlRawAsync`, `ExecuteSqlInterpolated` or `ExecuteSqlInterpolatedAsync`
  on a database context's own `Database` facade — both the source-level fluent shape
  (`Database.ExecuteSqlRawAsync(sql, ...)`) and the decompiled static-extension-method shape
  (`RelationalDatabaseFacadeExtensions.ExecuteSqlRawAsync(Database, sql, ...)`, the facade as the
  invocation's first argument rather than its receiver) — the same source/decompiled duality
  ticket 07's `IsDatabaseFacadeConnectionExpression` already resolves for `GetDbConnection()`,
  reused here via the existing `IsDatabaseFacadeExpression` helper. The deferred `FromSqlRaw`/
  `FromSqlInterpolated` forms are not in the matched name list, so they stay unrecognised exactly
  as the spec requires — a method using one still surfaces through the existing
  `IsAdoNetType`-gated unclassified-candidate check, unchanged.
- The new rule's `CommandSource` carries no command object and binds no variable
  (`VariableName: null`, `CommandPropertyReceiver: ""`) — ticket 06's widened record shape is what
  makes this possible without touching `CreateDefinition`'s classification flow. Its own terminal
  sink closure returns the execution call invocation itself. Its connection is reported through the
  same last-resort mechanism ticket 07 added for a command factory's receiver:
  `FactoryConnectionExpression` is set to the facade expression's text and
  `FactoryConnectionIsContextFacade` to `true` unconditionally, so `CreateDefinition`'s existing
  fallback (`connectionExpression`/`connectionIsContextConnection` set only when nothing else
  resolved a connection) reports `context_connection` for it with no new branch.
- Command text is read from the execution call's own SQL-text argument, then traced back through
  `ResolveUltimateCommandTextExpression` — a small, bounded (five-hop) syntax-only walk that undoes
  one indirection per hop: an interpolated string's single interpolation hole, a
  `*.Create(text, ...)` call's own first argument (the `FormattableStringFactory.Create` shape the
  real measured method's `FormattableString` construction decompiles to), or a local variable's own
  declaration initializer. This is not a generic addition to the other three rules — each keeps
  reading its command text exactly as before; only this rule's own `CommandTextExpression` is
  computed this way, per ticket 06's "a further construct is one added rule" promise. Measured
  directly against the real method: the execution call's argument is a local `FormattableString`
  built from `FormattableStringFactory.Create(text, ...)`, where `text` is a further local assigned
  from the method's own `sqlCmd` parameter at its declaration — four hops, within the five-hop
  bound, correctly resolving to `sqlCmd` and reporting `command_text` at argument index 0, exactly
  as a sibling method that assigns `cmd.CommandText = sqlCmd` directly.
- A raw-SQL Command Source has no `CommandType` property to read a mode from, so
  `ResolveMethodSemantics`'s existing property-assignment-driven resolution would always answer
  `fixed_inline_sql` regardless of any mode-shaped parameter — the wrong answer for the real
  method's `isSP`-guarded shape. `CommandSource` gains one further optional field,
  `ResolveOwnModeSemantics` (`Func<MethodDeclarationSyntax, (string? ModeParameter, string
  Semantics)>?`, defaulting to `null`), that a rule with no `CommandType` to read supplies instead.
  `CreateDefinition` reads it when present, in place of `FindModeParameter`/
  `ResolveMethodSemantics`; every one of the three existing rules leaves it `null` and keeps
  resolving exactly as before. The raw-SQL rule's own `ResolveRawSqlMethodSemantics` finds a
  boolean parameter guarding a conditional (an `if` or a ternary) that reassigns some local before
  the method returns, reusing the existing `FindModeParameterFromCondition` helper directly
  (accessible unqualified from the nested `CommandSourceResolver`, per C#'s nested-class access
  rule) — present, it reports `call_site`; absent, `fixed_inline_sql`. Measured directly: the real
  method's `if (isSP) { text = "exec " + sqlCmd + " "; }` matches this pattern on the same `isSP`
  parameter its six sibling methods guard their own `CommandType.StoredProcedure` assignment with,
  so it reports `call_site` and `command_type` at argument index 2, matching its siblings exactly.
- Net effect: `usp_ExecCmdGetCountAsync` — the one unclassified public method blocking Contract
  creation for all five measured Systems — now classifies with `command_text` at index 0,
  `command_type` at index 2, `call_site` semantics, `context_connection`, and
  `ExecuteSqlInterpolatedAsync` as its terminal sink. All seven `SQLDbContext` public methods are
  now accounted for, and a full IQCS refresh reports a created Contract, committed to both the
  external wrapper registry and the system catalog with no manual step — the spec's whole measured
  outcome.
- `CONTEXT.md`'s **Command Source** entry gains the raw-SQL execution shape beside the
  command-factory shape, naming its command-text tracing, its terminal sink, its
  `context_connection` boundary, and the excluded deferred `FromSql` forms.
- New `tests/test_raw_sql_execution_command_source.py` (10 tests, all passing): all four `Execute`
  forms resolve and each names its own execution call as terminal sink; command text traces to the
  caller's argument; a mode-argument method reports `call_site` (modelled directly on the real
  `isSP`-guarded, `FormattableStringFactory.Create`-wrapped shape, exercising the same tracing and
  mode detection the real method needs); a method with no mode argument reports the fixed,
  inline-SQL mode; the deferred `FromSqlRaw`/`FromSqlInterpolated` forms stay unclassified and
  named (not silently dropped); a fixture-gated test against the real `CommonLibrary.dll` confirms
  all seven public methods are classified or delegated, none unclassified, and the proposal passes
  `validate_implementation_snapshot`; a further fixture-gated test drives a full `refresh_source`
  call against the real IQCS checkout (network-free, via the same `resolve_scan_roots`/`get_or_scan`
  monkeypatch indirection `test_refresh_decompile_onboarding.py`'s real-SQLFunc test already uses)
  with temporary registry/catalog files, and confirms `contract_transaction.status == "committed"`
  and that both files carry the new contract afterwards.
- Three pre-existing fixture-gated tests from tickets 04, 02 and 07
  (`test_command_object_recognition.py::test_real_sqldbcontext_usp_execcmdgetdatasetasync_becomes_classified`,
  `test_delegated_method.py::test_real_sqldbcontext_delegating_methods_are_reported_as_delegated`,
  `test_connection_behavior_boundary.py::test_real_sqldbcontext_methods_report_context_connection_boundary`)
  asserted the real IQCS surface was still incomplete, naming `usp_ExecCmdGetCountAsync` as the one
  remaining unclassified method — true before this ticket, and each test said so explicitly. Updated
  to assert what is now measured: the surface is complete and nothing stays unclassified; one of the
  three (`test_connection_behavior_boundary.py`) additionally gains `usp_ExecCmdGetCountAsync` to
  its set of methods asserted to report `context_connection`, since it now does.
- Verification: `dotnet build` on `tools/StaticAnalyzerHost` — 0 warnings, 0 errors. Ran
  `test_raw_sql_execution_command_source.py` together with the targeted regression set
  (`test_command_object_recognition.py`, `test_delegated_method.py`, `test_wrapper_decompilation.py`,
  `test_wrapper_receiver_declaring_type.py`, `test_connection_behavior_boundary.py`,
  `test_refresh_contract_preflight.py`, `test_refresh_decompile_onboarding.py`,
  `test_external_wrapper_contract_identity.py`, `test_contract_acceptance.py`) — 126 passed. Ran the
  full suite once against this change and once against the unmodified baseline (`git stash -u`,
  rebuilding the pre-ticket-08 `StaticAnalyzerHost.dll` for that run) — `897 passed, 12 failed, 1
  skipped` on baseline and `907 passed, 12 failed, 1 skipped` on this change (10 more passing: the
  new test file), with the identical 12 `FAILED` test IDs on both runs, byte for byte — pre-existing
  Windows/live-connectivity artifacts (CRLF vs LF on a re-serialized fixture, a `Path` string
  double-escaped by `repr`, live SQL Server/ODBC-dependent assertions), none newly introduced.
  `SQLFunc`/`SQLObject`'s decompiled snapshots (24 and 22 operations respectively) produced
  byte-identical SHA-256 hashes with and without this change — the baseline acceptance criterion was
  measured, not assumed.
