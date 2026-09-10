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

**Status:** ready-for-agent

- [ ] A Database Invocation whose receiver is a registered context type reports its `{server, database}`.
- [ ] A Database Invocation whose receiver's declared type is absent from the composition root's registrations resolves to nothing and reports `context_type_not_registered`.
- [ ] A Database Invocation whose receiver's declared type cannot be read resolves to nothing and reports a reason distinct from the one above.
- [ ] A type whose name ends in `Context` but which carries no Database Invocation is never reported.
- [ ] The reason names the receiver's declared type, never the type its wrapper Contract is keyed on.
- [ ] No Database Invocation in a measured Core repository is left with neither a resolved connection nor a reason.
- [ ] Across the four measured Core repositories, `context_type_not_registered` falls from twenty-four reports to zero.
- [ ] The `Web.config` path reports as it does today, verified against the WebForms system.

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
