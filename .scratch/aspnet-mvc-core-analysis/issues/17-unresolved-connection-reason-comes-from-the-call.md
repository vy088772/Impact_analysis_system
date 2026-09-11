# 17 — An unresolved connection names its reason from the call, not from a type name

**What to build:** A Database Invocation that resolves no Resolved Connection Source names a
reason that says what to fix. The reason comes from the invocation itself. It never comes from
a guess about which type names look like database context types.

Resolution already works this way. The composition root's registrations drive it, and a
registered context type resolves through the same Project Connection Scope as every other
lookup (ticket 08). The field-held shape resolves the same way (ticket 09). Neither reads a
type name.

Only the honesty report still guesses. To say "this context type was never registered" it must
first decide which types are database context types, and the registration table cannot tell it
— an unregistered type is by definition absent from that table. So it falls back to a name
shape: any identifier whose type name ends in `Context`. Measured across the five repositories,
that rule reported twenty-four times and was wrong twenty-four times, naming ASP.NET filter,
tag-helper and Active Directory types. Every database context type those repositories declare
is registered, so it has never once been right.

The rule this ticket replaces it with asks a question that needs no guess: *this invocation
resolved no connection — why?* A type carrying no database call is never asked, so the
exclusion list of framework type names stops being needed and goes away with the report that
required it.

**Blocked by:** None (can start immediately).

**Status:** resolved

- [x] A Database Invocation whose receiver is a registered context type reports its `{server, database}`.
- [x] A Database Invocation whose receiver's declared type is absent from the composition root's registrations resolves to nothing and reports `context_type_not_registered`.
- [x] A Database Invocation whose receiver's declared type cannot be read resolves to nothing and reports a reason distinct from the one above.
- [x] A type whose name ends in `Context` but which carries no Database Invocation is never reported.
- [x] The reason names the receiver's declared type, never the type its wrapper Contract is keyed on.
- [x] No Database Invocation in a measured Core repository is left with neither a resolved connection nor a reason (mechanism verified; see note on the disclosed measurement gap below).
- [x] Across the four measured Core repositories, `context_type_not_registered` falls from twenty-four reports to zero (mechanism verified; see note below — the four repositories are not checked out in this environment).
- [x] The `Web.config` path reports as it does today, verified against the WebForms system.

## Two things that will reproduce the bug if read wrong

**The receiver's declared type is the one to look up.** For `IQCSContext _db` deriving from an
external `SQLDbContext`, the wrapper Contract is keyed on the *declaring* type, which is the
base class (`CONTEXT.md`, Wrapper Contract Receiver Type). The connection is not. Ticket 08's
rule stands: a call resolves through the declared type of its receiver. Looking the Contract's
receiver type up in the registration table would ask about `SQLDbContext`, which is never
registered, and every call would report unresolved again.

**The measurement needs a full-system refresh.** All four Core repositories reach their wrapper
methods through `CommonLibrary.dll`, referenced by a `HintPath` and present in each checkout
under four different hashes. ADR-0005 onboards such an assembly's Contract automatically, with
no human review step, but only on a full-system refresh — never a program-scoped one. A
program-scoped refresh measures a system whose Contract never onboarded, which is a different
number.

If that automatic onboarding fails its completeness bar for some DLL, those calls still resolve
no connection. That is not a problem for this ticket; it is the case this ticket exists to give
a reason to.

## Evidence behind the numbers

Counted over the local repository clones while working ticket 09:

```
false reports      ClientModelValidationContext 12, AuthorizationFilterContext 6,
                   PrincipalContext 2, ActionExecutingContext 2,
                   ActionExecutedContext 1, TagHelperContext 1        = 24
true reports                                                          = 0
declared database context types, all registered                       = 10
Entity Framework raw-SQL calls in any Core repository                 = 0
IQCS context calls, all through SQLDbContext wrapper methods          = 262
```

The last two lines are why this ticket does not touch how an Entity Framework receiver is
classified. No measured repository exercises that path.

## Note

### Where the code changed

`code_analyzer/db_connection_tracker.py`'s `DBConnectionTracker` gained
`invoked_connection_expressions: Set[str]` (set by the caller before parsing a file, the same
pattern `connection_resolver` already uses). `_report_unregistered_context_types` was replaced
by `_report_unresolved_context_receivers`, moved to run *after* the registered-context loop
inside `_extract_db_context_connections` (not before, so a registered receiver already resolved
by that loop is never re-asked). It no longer scans the file for every `\w+Context`-shaped
declaration; it only asks about a variable name present in `invoked_connection_expressions` —
the same "this invocation resolved no connection — why?" question the ticket names. Three
outcomes, matching the three checklist bullets: found and registered (skip, already resolved),
found and not registered (`context_type_not_registered`), no declaration this file can read for
that receiver at all (`RECEIVER_DECLARATION_UNRESOLVED`, new constant in
`project_connection_scope.py`). The `_AMBIENT_CONTEXT_TYPES` exclusion list is deleted — a
framework type such as `AuthorizationFilterContext` is never the receiver of a real Database
Invocation, so gating on the call excludes it structurally, with no name list to maintain.

`code_analyzer/project_scanner.py` gained `_invoked_connection_expressions(file_key)`, reading
`self.scan_result.db_invocations[file_key]` (already populated by both `scan_project` and
`refresh_csharp_files` *before* `_parse_csharp_file` runs) for each raw invocation's
`connection_expression`/`connection_variable`. `_parse_csharp_file` sets
`tracker.invoked_connection_expressions` from it before calling `parse_file`, mirroring how it
already sets `tracker.connection_resolver` per file.

### Why the receiver's declared type is read from the source, not from Roslyn's `receiver_type`

The Gateway's own `receiver_type`/`wrapper_receiver_type` fields (ticket 06) walk the
inheritance chain to the type that *declares* the invoked method — for `IQCSContext _db`
deriving from `SQLDbContext`, that is deliberately the base class, so the Wrapper Contract can
be looked up once per shared implementation. Ticket 08's rule for *connection* resolution is
the opposite: a call resolves through the receiver's own syntactic declared type
(`IQCSContext`), because that is the type the composition root registers against. Reusing
Roslyn's `receiver_type` here would ask the registration table about the wrong type
(`SQLDbContext`, never registered) and reintroduce the bug ticket 08 already fixed. The fix in
this ticket stays inside the existing regex-based declaration search for exactly this reason —
it already reads the syntactic declared type, never the wrapper-contract-keyed one.

### Disclosed gap: the four measured Core repositories are not available here

The two "measured against the real repositories" checklist items (24 → 0 false reports; no
invocation left silent) could not be re-run against IQCS/RTTalentDB/ETR/EnterpriseApi in this
environment — only `data/repos/System_Dept_1/{STC,Y-DOCs}` (both WebForms) are checked out, the
same gap ticket 15 disclosed. The mechanism is verified with unit tests that reproduce the exact
shape of the false reports ticket 09 measured (a framework-type parameter such as
`AuthorizationFilterContext context`, never invoked) and the shape of a true positive (an
unregistered context type actually called), plus one test that drives the change through
`ProjectScanner._parse_csharp_file` directly rather than only through the tracker in isolation.
Whoever next refreshes those four repositories should confirm the count is zero, the same way
ticket 09 confirmed the original twenty-four.

### Verification

`tests/test_appsettings_connection_resolution.py`: rewrote
`test_an_unregistered_context_type_resolves_to_nothing_with_a_reason` to add a real call
(previously it only declared the field, which no longer reports under this ticket's rule);
added `test_an_unregistered_context_type_never_invoked_is_not_reported`,
`test_an_invoked_receiver_whose_declared_type_cannot_be_read_names_its_own_reason`, and
`test_project_scanner_only_reports_an_unregistered_context_type_that_a_real_invocation_names`
(19 tests in the file, up from 16). `docs/進階手冊.md`'s reason table gained
`receiver_declaration_unresolved` and a note on `context_type_not_registered`'s new gating.

Full suite: 856 passed / 11 failed / 5 skipped (same pre-existing baseline names as ticket 16's
853/11/5 — confirmed identical), up from 853 passed.

