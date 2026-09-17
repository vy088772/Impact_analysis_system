# The sqldbcontext Contract Resolves Its Real Calls

Status: ready-for-agent

## Problem Statement

`accepted-contract-resolves-its-calls` shipped three mechanisms so an accepted
Contract resolves the calls it describes: Rating-Time Command Mode, Delegation
Alias, and Observed Call Evidence. All three are proven correct — but only
against a Contract fixture built with the true parameter types. Against the
real, on-disk `sqldbcontext` Contract in the registry, they still do nothing.

The accepted `sqldbcontext` Contract declares `usp_ExecCmdGetDataSetAsync`,
`usp_ExecCmdGetCountAsync`, and `usp_ExecCmdGetDataTableAsync`'s second
parameter as `Microsoft.EntityFrameworkCore.SqlParameter[]?`. The true type,
confirmed directly against `CommonLibrary.dll` with the current decompiler, is
`Microsoft.Data.SqlClient.SqlParameter[]`. This is a stale decompilation-cache
artifact from before the current decompiler existed — no
`"EntityFrameworkCore"` string exists anywhere in the analyzer host today. The
strict method-identity/parameter-type match a call site's method name is
checked against rejects all three real call sites for this reason alone, with
or without the three mechanisms above.

A maintainer who runs a refresh against the real IQCS checkout today still
gets `unresolved_contract` for these three methods. The Executed Procedure
Name share `accepted-contract-resolves-its-calls` set out to raise from 0.9%
to 30% or more has never actually been measured against the real registry —
only against a fixture built to sidestep this exact defect. Two prior tickets
(`02-command-mode-resolves-at-rating-time`, `03-a-delegating-method-matches-through-an-alias`)
found this defect, recorded it, and deferred it on the maintainer's own
instruction. This spec is that deferred fix.

Separately, a code review of the same prior work found one more thing worth
recording accurately: `accepted-contract-resolves-its-calls` promised the
analyzer host records Observed Argument Facts "from the syntax alone." The
shipped code also performs semantic binding — the same binding the analyzer
host already uses elsewhere for a wrapper call's own method identity — to read
an omitted trailing optional argument's declared default value. This was a
correct, load-bearing, tightly-guarded addition (only a uniquely bound symbol
is trusted; it reads no Contract), but the written decision never caught up to
it. A reader of the spec and ADR-0028 today would not learn this.

## Solution

Two independent corrections, neither touching the three mechanisms
`accepted-contract-resolves-its-calls` already shipped.

**Re-decompile and re-accept `sqldbcontext`.** A fresh decompilation of
`SQLDbContext` against the current decompiler produces the true parameter
types. Because an accepted Contract is immutable, the result lands as a new,
separate registry entry — never an in-place edit of `sqldbcontext` — named by
this registry's existing fingerprint-suffix collision convention. The
receiver-type name `SQLDbContext` therefore now resolves, through the
System's own selector, to the new entry instead of the stale one.

**Correct the written record for the semantic-binding refinement.** The
decision that the analyzer host reads no Contract, and gains no Contract
input channel, still holds exactly as ADR-0028 recorded it — semantic binding
to a referenced assembly's own metadata is not a Contract read. What needs
correcting is narrower: the "syntax alone" phrase overstated the mechanism.
ADR-0028 gains a short amendment (this registry's own precedent for revising
a decision without erasing it, e.g. ADR-0006 amending ADR-0005) stating the
refinement and the guard around it. `accepted-contract-resolves-its-calls`'s
own Implementation Decisions prose is corrected in place to match, since a
spec — unlike an ADR — is not this repo's immutable decision ledger.

Neither correction touches `SQLFunc` or `SQLObject`. Both carry the same
`skipped_stale_cache_schema` result the prior tickets already named as a
separate piece of follow-up work, not this one.

## User Stories

1. As a maintainer, I want the accepted `sqldbcontext` Contract's parameter
   types to match what the current decompiler reads from `CommonLibrary.dll`
   today, so that the strict method-identity/parameter-type match stops
   rejecting the real call sites.
2. As a maintainer, I want `usp_ExecCmdGetDataSetAsync` and
   `usp_ExecCmdGetCountAsync` to resolve against the real, on-disk registry,
   not only a test fixture, so that Rating-Time Command Mode's own acceptance
   claim is actually true for IQCS.
3. As a maintainer, I want `usp_ExecCmdGetDataTableAsync` to resolve against
   the real, on-disk registry, so that Delegation Alias's own acceptance claim
   is actually true for IQCS.
4. As a maintainer, I want to re-measure the Executed Procedure Name share for
   IQCS after this fix, so that I know whether the 0.9%→30% goal
   `accepted-contract-resolves-its-calls` set is actually met, not merely
   proven in principle.
5. As a maintainer, I want the re-decompiled result committed as a new
   registry entry, never an in-place rewrite of `sqldbcontext`, so that an
   already-accepted Contract's immutability guarantee holds.
6. As a maintainer, I want the new entry's name chosen by this registry's
   existing fingerprint-suffix convention, so that I invent no new naming
   scheme for a case the convention already covers.
7. As a maintainer, I want IQCS's own wrapper-contract selector repointed at
   the new entry's name, so that a future refresh actually reaches it.
8. As a maintainer, I want that repoint to happen without disturbing any
   other System, so that onboarding IQCS's fix carries no blast radius for a
   System that does not yet exist in the catalog.
9. As a maintainer, I want to know, before this work starts, whether any
   System other than IQCS currently selects `sqldbcontext`, so that I know
   the true blast radius rather than assuming it from the Contract's
   receiver-type name alone.
10. As a maintainer, I want the re-decompile to run against the real, already
    -cloned IQCS checkout, so that no separate onboarding step is needed
    first.
11. As a maintainer, I want the refresh call that triggers the re-decompile to
    name `SQLDbContext` explicitly, so that it is never mistaken for a
    cold-start onboarding attempt with no selector at all.
12. As a maintainer, I want the refresh call to avoid any step that requires a
    live database connection, so that the fix does not depend on
    infrastructure this specific piece of work does not need.
13. As a maintainer, I want the attempt to stop and report plainly if a step
    it does need — such as syncing the real checkout to its declared branch —
    cannot complete, so that a partial, silently-wrong result is never
    committed.
14. As an agent picking up this work, I want the external system catalog's
    edit scoped to the one line naming IQCS's contract, so that no other
    System's entry in that file is touched.
15. As an agent picking up this work, I want to leave the commit of that
    external catalog edit to its own repository's owner, so that a change to
    a repository this one does not own is never committed on someone else's
    behalf.
16. As a maintainer, I want the two pre-existing, unrelated test failures this
    work's own investigation turned up — one about `SQLObject` wrapper
    resolution, one about a cold-start onboarding attempt with no explicit
    selector — left exactly as found, so that this spec's own scope stays
    the one defect it names.
17. As an agent picking up this work, I want a real-checkout test that proves
    the fix against the actual, post-fix registry entry, not a fixture, so
    that the fixture-based tests `accepted-contract-resolves-its-calls`
    already shipped are not mistaken for having proven this.
18. As an agent picking up this work, I want that test to assert on the
    Executed Procedure Name each of the three affected calls resolves to, so
    that a passing test genuinely means what a maintainer running the real
    refresh would see.
19. As an agent picking up this work, I want a test asserting the original
    `sqldbcontext` entry is byte-for-byte unchanged after the new entry
    lands, so that the immutability guarantee is checked, not assumed.
20. As a reader of ADR-0028, I want the amendment to state plainly that
    semantic binding to a referenced assembly's own metadata is not a
    Contract read, so that the "no Contract input channel" guarantee this
    ADR exists to protect is never mistaken for broken.
21. As a reader of `accepted-contract-resolves-its-calls`, I want its
    Implementation Decisions section corrected to describe the semantic
    -binding refinement accurately, so that the written spec and the shipped
    code no longer disagree.
22. As a maintainer, I want this spec to change no behavior in Rating-Time
    Command Mode, Delegation Alias, or Observed Call Evidence themselves, so
    that a defect in one Contract's stale data is never fixed by touching the
    mechanisms that read every Contract.

## Implementation Decisions

- The fix is scoped to the `sqldbcontext` receiver type alone. `SQLFunc` and
  `SQLObject`'s own `skipped_stale_cache_schema` results are separate,
  already-named follow-up work and are not touched here.
- Before the re-decompile runs, confirm which Systems in the external system
  catalog currently select `sqldbcontext` by name. Only a System actually
  found there is in scope for the repoint; the fix assumes no other System
  until this check says otherwise.
- The re-decompile is triggered as an explicit, named request against
  `SQLDbContext` — the same mechanism the analyzer host already exposes for a
  maintainer to bypass a cached attempt for one receiver type only (see the
  Contract Fingerprint / decompile-onboarding ADRs already in this registry).
  It is never triggered as a bare, selector-less refresh, since that path is
  a different, already-broken feature this spec does not touch (see Out of
  Scope).
- The refresh call this triggers must not depend on a live database
  connection. Whatever database-scoped step the refresh path would otherwise
  perform is skipped or given no database for this call.
- If syncing the real checkout to its declared branch cannot complete (for
  example, no network reachability to the source control host), the attempt
  stops and reports exactly where it stopped. No fallback guess is made.
- Contract acceptance for the fresh decompilation result follows this
  registry's existing accept path unchanged: an existing accepted entry is
  never mutated in place; a fingerprint mismatch against `sqldbcontext`
  produces a new entry named by the existing fingerprint-suffix collision
  convention.
- The external system catalog's entry for each System found in scope has its
  `wrapper_contract` field repointed from `sqldbcontext` to the new entry's
  name. No other field on that entry, and no other System's entry, is
  touched.
- The catalog file lives in a separate repository this one does not own. The
  edit is made in that repository's working tree; committing it there is left
  to that repository's own owner.
- ADR-0028 gains an amendment recording the semantic-binding refinement,
  following this registry's existing precedent for amending a decision
  without erasing it. The amendment states: an omitted trailing optional
  argument's declared default value is read via semantic binding to the
  referenced assembly's own metadata, guarded so that only a uniquely bound
  symbol (no candidate ambiguity) is trusted; an unresolved or ambiguous
  binding leaves the argument's position unrecorded. This is not a Contract
  read, and the "no Contract input channel" guarantee ADR-0028 recorded is
  unaffected.
- `accepted-contract-resolves-its-calls`'s own Implementation Decisions
  section is corrected in place: the "from the syntax alone" phrasing is
  replaced with wording that names the semantic-binding refinement and points
  at the ADR-0028 amendment for the full guard description.

## Testing Decisions

A good test here states an outcome a maintainer can observe against the real
system, not against a fixture built to sidestep the very defect being fixed.

**The main seam is a real-checkout test run against the real, post-fix
registry entry.** One test scans the real IQCS checkout and asserts that
`usp_ExecCmdGetDataSetAsync`, `usp_ExecCmdGetCountAsync`, and
`usp_ExecCmdGetDataTableAsync` each resolve to their real Executed Procedure
Name. This is the one seam this spec needs: it is the same real-checkout
technique `accepted-contract-resolves-its-calls` already used for exactly
this class of change, now pointed at the real registry entry instead of a
fixture. It supersedes nothing the fixture-based tests already prove about
the three mechanisms themselves — it proves the data this one Contract
carries is now correct.

**One narrow seam covers the immutability guarantee.** A test reads the
registry directly after the fix lands and asserts the original `sqldbcontext`
entry is unchanged, and that the new entry carries a different name and a
different Contract Fingerprint. Prior art: the existing Contract migration
test's own fingerprint-unchanged assertion.

**The acceptance measurement** is the existing coverage report, re-run
against the real, fixed registry. IQCS's Executed Procedure Name share is
measured, not assumed, and the result is recorded regardless of whether it
clears 30% — this spec's job is to make the number real, not to guarantee its
value.

**No test is needed for the ADR-0028 amendment or the spec-text correction.**
Both are documentation-only changes; prior art is `01-adrs-and-glossary-record-the-decisions`,
which shipped with no test of its own.

## Out of Scope

- **The two pre-existing, unrelated test failures this work's own
  investigation found.** One is about `SQLObject` wrapper-contract
  resolution (a different receiver type, unaffected by anything in this
  spec). The other is a cold-start Contract-onboarding attempt that names no
  explicit selector, which reports `not_attempted` for a reason unrelated to
  stale parameter types. Neither is touched, diagnosed further, or fixed
  here.
- **`SQLFunc` and `SQLObject`'s own stale-decompilation-cache defect.**
  Already named as separate follow-up work by the tickets that found it.
- **Any change to Rating-Time Command Mode, Delegation Alias, or Observed
  Call Evidence.** All three already work correctly; this spec fixes the one
  Contract's data, not the mechanisms that read it.
- **Onboarding `EnterpriseApp`, `RTTalentDB`, or `TOPCSCY`.** Carried over
  from `accepted-contract-resolves-its-calls`: these Systems are not
  registered in the catalog today, and registering them is separate work.
- **Unifying the Command Mode rule that lives in two places**, and any other
  accepted risk `accepted-contract-resolves-its-calls`'s own ADRs already
  recorded. Nothing here revisits those trade-offs.

## Further Notes

**This is a deferred fix, not new work.** Tickets 02 and 03 of
`accepted-contract-resolves-its-calls` found this exact defect, asked the
maintainer directly whether to fix it immediately, and recorded the
maintainer's own choice to defer it. This spec exists because that decision
has now been revisited and reversed, on the record, not because the earlier
decision was wrong when it was made.

**The blast radius question has a real answer, not an assumed one.** Whoever
picks up this spec should check the external system catalog directly rather
than trusting the Contract's receiver-type name — a same-named receiver in a
different System can carry a different Contract Fingerprint entirely (this is
exactly what the fingerprint-suffix collision convention exists for), so
"who selects `sqldbcontext` today" is a question with a concrete, checkable
answer, not a guess from the name alone.

**The environment this work runs in may not have every dependency this
repository's full test suite assumes.** A live SQL Server ODBC driver may not
be present; the re-decompile and re-accept path does not need one, and should
be run in a way that avoids depending on one. Network reachability to the
source control host that owns the real checkout is a separate, genuine
dependency this spec's fix does need — if it is not available, the correct
behavior is to stop and report that plainly, per the Implementation
Decisions above.
