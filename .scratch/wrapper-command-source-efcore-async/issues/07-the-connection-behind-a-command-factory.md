# 07 — The connection behind a command factory is read from the factory's receiver

**What to build:** A wrapper method that obtains its command from
`connection.CreateCommand()` reports that connection as its Connection Behavior
Boundary, instead of reporting an empty boundary.

Ticket 01 made the command factory a recognised Command Source. It did not carry
the connection across. The connection resolver reads a connection from two
places only: the second argument of a command constructor, and a `Connection`
property assignment. A factory call gives neither. The connection is the
*receiver* of the factory call, and the resolver never reads that receiver.

The consequence is measured. All three classified `SQLDbContext` methods build
their command this way, so all three report an empty Connection Behavior
Boundary, and the proposal fails the completeness check with
`connection_behavior_boundary_missing`. Tickets 01 and 02 together still leave
the Contract refused.

The boundary vocabulary also gains a third value. A factory receiver that is a
database context's `Database` facade reports `context_connection`. The database
follows from the call site's declared receiver type through Context Connection
Registration — `SQLDbContext` serves five Systems and many derived context
types, so no single connection belongs to the wrapper. Every other factory
receiver reports `wrapper_connection`, exactly as a Field-Held Connection does
today.

The new rule runs last, only when both existing rules resolve nothing. An
already-resolved boundary therefore cannot change value by construction, not by
coincidence. Measured before this ticket: neither `SQLObject.dll` nor
`SQLFunc.dll` contains a single `CreateCommand` call, and all 68 operations
across the three registered Contracts already report `wrapper_connection`.

`CONTEXT.md` already defines **Connection Behavior Boundary** with its two
existing values. This ticket adds the third to that entry.

**Blocked by:** None — can start immediately.

**Status:** resolved

- [x] A wrapper method whose command comes from a factory call on a connection expression reports that connection as its Connection Behavior Boundary, observable through the analyzer host's decompile-wrapper response
- [x] A factory receiver that is a database context's `Database` facade reports `context_connection`
- [x] A factory receiver that is a Field-Held Connection reports `wrapper_connection`, so the two lookup shapes are never read from one value
- [x] A method that already resolves its connection through a command constructor argument or a `Connection` property assignment reports exactly the value it reports today, even when its body also contains a factory call
- [x] The real shared assembly under the IQCS checkout reports a non-empty Connection Behavior Boundary for all three of its classified methods, and its proposal no longer fails with `connection_behavior_boundary_missing` (fixture-gated, skipped when the checkout is absent)
- [x] That same assembly still reports an incomplete behaviour surface naming `usp_ExecCmdGetCountAsync` — a partial repair is not presented as a whole one
- [x] The existing `SQLFunc` and `SQLObject` Contract Fingerprints are unchanged, byte for byte
- [x] `CONTEXT.md`'s **Connection Behavior Boundary** entry gains `context_connection`, defined against Context Connection Registration and Field-Held Connection
- [x] An ADR records the decision to add a third value rather than reuse `wrapper_connection`

## Note

`tools/StaticAnalyzerHost/CSharpAnalyzer.cs`, inside `WrapperAnalyzer`'s nested
`CommandSourceResolver` and `CreateDefinition`; `tools/StaticAnalyzerHost/WrapperDecompiler.cs`'s
`ToOperation`:

- `CommandSource` gains two fields: `FactoryConnectionExpression` (`string?`, the factory call's
  receiver text, already trimmed) and `FactoryConnectionIsContextFacade` (`bool`). Only
  `ResolveDeclaredCommandSources` (the factory-obtained-command rule) ever sets them —
  `ResolveCommandObjectSources` and `ResolveDataAdapterSources` always pass `null, false`, since
  neither rule's construct is a factory call. One new private helper, `ResolveFactoryConnection`,
  computes both from the declared variable's initializer in a single match: it matches only an
  invocation whose method is literally named `CreateCommand` (the one factory shape a receiver is
  known to be a connection for), returning `(null, false)` otherwise, and otherwise returns the
  matched receiver's text alongside whether that same receiver reaches a database context's own
  `Database` facade.
- Facade recognition is purely structural (no semantic model), matching how every other rule in
  this resolver classifies a construct — but it has to recognise two different shapes for the
  same source-level call, because `DatabaseFacade.GetDbConnection()` is actually an EF Core
  *extension* method. Written in source, `Database.GetDbConnection()` parses as a fluent
  instance-call (`InvocationExpressionSyntax` receiver = `Database`). Decompiled from a real
  assembly, the same call reconstructs as its true static shape,
  `RelationalDatabaseFacadeExtensions.GetDbConnection(((DbContext)this).Database)` — the facade is
  the invocation's one *argument*, not its receiver. `IsDatabaseFacadeConnectionExpression`
  checks both: the facade itself (`IsDatabaseFacadeExpression` — a bare `Database` identifier or
  any member access ending in `.Database`, whatever the receiver, so `this.Database`,
  `x.Database` and `((DbContext)this).Database` all match uniformly), or a `GetDbConnection()`
  call whose receiver *or* one argument is the facade. Measured directly against the real
  `CommonLibrary.dll`: all three classified `SQLDbContext` methods decompile to the static-argument
  shape, not the fluent one — the argument-shape branch is not a defensive extra, it is the one
  the measured evidence actually needs.
- In `CreateDefinition`, the fallback sits directly after the existing `Connection`
  property-assignment loop: `if (string.IsNullOrWhiteSpace(connectionExpression) &&
  !string.IsNullOrWhiteSpace(commandSource.FactoryConnectionExpression)) { connectionExpression =
  commandSource.FactoryConnectionExpression; connectionIsContextConnection =
  commandSource.FactoryConnectionIsContextFacade; }`. Because `FactoryConnectionExpression` is
  non-null only for the declared-command-source rule's own `CommandSource`, a method whose first
  Command Source is an explicit command object or a data adapter never reaches this branch at
  all — the constructor-argument and property-assignment rules keep deciding those methods
  exactly as before, whether or not some other, unrelated variable in the same method body
  happens to be obtained through a factory call.
- `WrapperDefinition` gains one field, `ConnectionIsContextConnection` (`bool`, default `false`
  so the one other construction site, `WrapperDecompiler.BuildTranslationProblemDefinition`,
  needed no change). `WrapperDecompiler.ToOperation` reads it only after the existing
  `ConstructorConnectionParameterIndex >= 0` and empty-`ConnectionExpression` checks both fall
  through, choosing `context_connection` over `wrapper_connection` — the vocabulary's first two
  values are computed exactly as before; this is a third `?:` arm, not a rewritten one.
- Verification: `dotnet build` on `tools/StaticAnalyzerHost` — 0 warnings, 0 errors. New
  `tests/test_connection_behavior_boundary.py` (7 tests, all passing) covers: a Field-Held
  Connection factory reporting `wrapper_connection`; a `Database`-facade factory reporting
  `context_connection`; a factory-initialized Command Source whose `Connection` is also assigned
  explicitly keeping that explicit value, never the factory receiver; an explicit
  constructor-argument connection staying `constructor_connection` untouched by the new rule; and
  three fixture-gated tests against the real checkout present in this environment
  (`data/repos/System_Dept_1`). The fixture-gated tests are not merely written and skipped here —
  they ran and passed: all three classified `SQLDbContext` methods now report
  `context_connection`, `validate_implementation_snapshot` no longer names
  `connection_behavior_boundary_missing`, `usp_ExecCmdGetCountAsync` still names itself as the one
  remaining unclassified method, and `SQLFunc`/`SQLObject` report `wrapper_connection` for every
  operation.
- Regression: ran `tests/test_command_object_recognition.py`, `test_delegated_method.py`,
  `test_wrapper_decompilation.py`, `test_wrapper_receiver_declaring_type.py`,
  `test_refresh_contract_preflight.py`, `test_refresh_decompile_onboarding.py`,
  `test_external_wrapper_contract_identity.py` and `test_contract_acceptance.py` — 109 passed.
  Ran the full suite once against this change (897 passed, 12 failed, 1 skipped) and once against
  the unmodified baseline via `git stash` (12 failed, all others not run) — the same 12 `FAILED`
  test IDs fail identically on both, pre-existing Windows/live-connectivity artifacts (CRLF vs LF
  on a re-serialized fixture, a `Path` string double-escaped by `repr`, live SQL
  Server/ODBC-dependent assertions), none newly introduced. `compute_contract_fingerprint` on
  `SQLFunc` and `SQLObject`'s decompiled snapshots produced byte-identical SHA-256 hashes with and
  without this change (`885452ff…` and `4195c73e…` respectively) — the acceptance criterion was
  measured, not assumed.
