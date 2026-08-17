# 02 — Report the public database behavior surface honestly

**What to build:** A maintainer can trust the completeness claim of an Implementation Snapshot. When the decompiler cannot classify a public method that touches a database type, the snapshot reports an incomplete surface, and Contract Preflight rejects it.

Today the decompiler reports this completeness as a constant true value. It never compares its output against the assembly's real public method set. An incomplete contract therefore reaches the Contract Lifecycle Status `accepted` with no signal.

Compute the completeness from the assembly's public method set. Assign each public method one of three states:

- **classified** — a Command Source resolved, and the method has a mode and a terminal sink;
- **non-database** — the method body touches no ADO.NET type;
- **unclassified** — the method body touches an ADO.NET type, but no Command Source resolved.

The snapshot validation already rejects an incomplete public database operation surface, and it already skips a non-database operation. Reuse both. Add no new validation rule.

**Blocked by:** 01 — without the data adapter rule, the fixture assembly holds an unclassified method, so this ticket would reject the contract that the system depends on today.

**Status:** resolved

- [x] Every public method of a decompiled assembly receives one of the three states.
- [x] A public method whose body touches no ADO.NET type takes the state non-database.
- [x] A public method whose body touches an ADO.NET type but yields no Command Source takes the state unclassified.
- [x] The snapshot reports a complete public database behavior surface only when no public method is unclassified.
- [x] The snapshot carries the method identity of every unclassified method.
- [x] Contract Preflight rejects a snapshot whose public database behavior surface is incomplete.
- [x] The rejection reason names the unclassified methods.
- [x] A non-database method never blocks contract acceptance.
- [x] The fixture assembly reports a complete public database behavior surface.
- [x] A test builds a snapshot that holds an unclassified public method, and asserts that Contract Preflight rejects it.

## Answer

Replaced the decompiler's constant `PublicDatabaseOperationsComplete = true` with a computed
public method census, and wired the result all the way through to Contract Preflight's rejection
reason.

- `WrapperAnalyzer.GetUnclassifiedPublicMethods` (`CSharpAnalyzer.cs`) walks the decompiled
  receiver type's own public methods (its flat, namespace-less synthetic root — deliberately not
  `DescendantNodes()`, so a compiler-generated nested type a decompiled method body happens to
  carry along is never mistaken for one of the receiver's own public methods). A method already
  present in the Command Source-classified `WrapperDefinition` set is classified; among the rest,
  a method whose body names no ADO.NET type (`CSharpAnalyzer.IsAdoNetType` — commands, connections,
  data adapters, data readers, parameters, transactions, across the common ADO.NET providers) is
  non-database and never blocks acceptance; a method whose body does name one is unclassified.
- `WrapperDecompiler.cs` threads the unclassified list through `DecompiledWrapperClassification`
  into the `DecompiledImplementationSnapshot`: `PublicDatabaseOperationsComplete` is now
  `UnclassifiedPublicMethods.Count == 0`, and the snapshot carries `unclassified_public_methods`
  (the method identities) alongside it.
- `external_wrapper_contracts.validate_implementation_snapshot` already rejected
  `public_database_operations_complete is False` with the reason
  `database_behavior_surface_incomplete`; unchanged. It now additionally appends one
  `unclassified_public_method:<method identity>` reason per unclassified method, so Contract
  Preflight's rejection names the gap instead of only flagging that one exists. No new validation
  rule; the non-database skip Contract Preflight already applied is untouched.

Result on the fixture: `SQLFunc.dll` still reports a complete public database behavior surface
(`unclassified_public_methods == []`) — verified against the real DLL, not just asserted.

Validation:

- `dotnet build tools/StaticAnalyzerHost/StaticAnalyzerHost.csproj` passed.
- Ticket tests: `tests/test_wrapper_decompilation.py::test_decompile_wrapper_reports_unclassified_public_method_and_preflight_rejects_it`
  compiles a throwaway fixture DLL (stand-in ADO.NET-shaped types, no external package needed)
  whose one method builds a data adapter and fills it inline, bound to no variable — the exact
  case ticket 01 left unresolved — and asserts the real analyzer host reports it unclassified,
  `public_database_operations_complete` false, and Contract Preflight rejecting with the named
  reason. `tests/test_refresh_contract_preflight.py` gained the Seam 3 pair (validation-level and
  preflight-level) asserting a hand-built snapshot with an unclassified method is rejected and
  named. The existing SQLFunc.dll end-to-end test now also asserts
  `public_database_operations_complete is True` and `unclassified_public_methods == []` directly.
- Applicable full suite: 366 passed, 11 pre-existing failures (same 11 on a clean HEAD with this
  change stashed — unrelated: missing ODBC driver and pre-existing gateway/discovery failures).
  `tests/test_search_roles.py` and `tests/test_sp_tables.py` still cannot collect on this machine
  for the same reason noted in ticket 01.
