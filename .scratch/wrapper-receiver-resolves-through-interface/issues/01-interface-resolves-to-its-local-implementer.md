# 01 — An interface-typed wrapper receiver resolves to its unique local implementer

**What to build:** A wrapper call made through an interface-typed receiver
(e.g. a DI-style service field declared as `IUtilityService`) resolves to the
one local class in the current scan root that implements the interface and
declares the called method — its Local Implementer — and is rated exactly as
a directly-typed local wrapper already is: source-backed, from its own method
body, no external Contract required. An interface with no local implementer
is left exactly as it is reported today. An interface with two or more local
implementers is, for this ticket, also left exactly as it is reported today —
ticket 02 turns that case into a distinct, reviewable outcome; this ticket
must not guess between them.

**Blocked by:** None — can start immediately.

**Status:** done

- [x] A wrapper call through an interface with exactly one local implementing
      class in the current scan root — where that class itself declares the
      called method — is reported source-backed, carrying the implementer's
      identity, method semantics, and command/terminal-sink facts, the same
      as a directly-typed local wrapper reaching the same method
- [x] An interface with zero local implementing classes in the current scan
      root reports exactly the outcome it reports today — this ticket adds no
      new status for that case
- [x] An interface with two or more local implementing classes in the current
      scan root reports exactly the outcome it reports today (unchanged for
      now; ticket 02 replaces this with a distinct reviewable outcome) — never
      resolved to any one of them by declaration order, file order, or name
      similarity
- [x] The implementer search is bounded to the current scan root: a class in
      an unrelated sibling root of a multi-root system is never treated as a
      match
- [x] A class that implements the interface only through a further base class
      still counts as a valid Local Implementer, provided it (or that base)
      declares the called method
- [x] A class already recognised today as a directly-typed local wrapper
      classifies identically whether reached directly or through an interface
      field reaching the same method
- [x] A genuinely external, DLL-only interface (no implementer anywhere in
      the current scan root) is unaffected — its existing external-wrapper
      Contract path is unchanged
- [x] A real end-to-end test resolves a real interface-typed field call
      against its real local implementer, verifying source-backed evidence is
      produced from the implementer's own method body, not from the
      interface's declaration

**Notes:**

Implemented in `tools/StaticAnalyzerHost/CSharpAnalyzer.cs`, inside
`WrapperAnalyzer`, exactly where the spec's Implementation Decisions placed
it: beside `ResolveWrapperReceiverType`/`InheritsTheInvokedMethod`, reached
from `CreateUnavailableCandidate` (the path that already builds the
"unavailable external wrapper" fact for `IUtilityService`-shaped calls).
`ResolveLocalImplementers` is the entry point — runs only when the resolved
receiver type names a corpus-declared `InterfaceDeclarationSyntax` — and
delegates to `FindLocalImplementers` (scans `ClassDeclarationSyntax` nodes
across `sourceRoots`, one evaluation per class identity so a `partial` class
is never double-counted) and its two transitive-walk helpers,
`ImplementsInterfaceTransitively`/`DeclaresMethodTransitively` (both walk a
class's base-list, by simple name via the existing `GetTypeDeclarationsByName`
index, to let a further base class in the same corpus satisfy either check —
covers the "abstract base implements most of the interface" pattern). Exactly
one match flips `WrapperSourceAvailable` to `true` and sets
`ReceiverImplementationIdentity` to the class's simple name;
`CreateUnavailableInvocation` gained two new parameters
(`localImplementer`, `localWrapperDefinition` — see the redirect paragraph
below) and otherwise builds the same fact it always did. Zero or
two-or-more matches leave the call exactly as before — no gateway change was
needed, confirming the spec's own read of
`csharp_analysis_gateway.reconcile_wrapper`'s existing `if source_available:`
branch.

This went through one review pass (`/code-review`, Standards + Spec axes,
both sub-agents given the diff independently) before being marked done, and
the diff above already reflects the fixes that pass produced:

- **Performance.** The reviewer flagged that `FindLocalImplementers`'s outer
  scan walked every `ClassDeclarationSyntax` in `sourceRoots` from scratch on
  every unresolved call site — exactly the pattern `GetClassDeclarations`'s
  own doc comment warns cost "three and a half minutes" before it was
  indexed, and this ticket's own numbers put ~400 such call sites in one
  IQCS refresh. Fixed by adding `GetAllClassDeclarations`, memoized on root
  identity the same way `_definitionsCache`/`_knownTypeIdentitiesCache`
  already are, so the walk runs once per scan root, not once per call.
- **Duplication.** Two small helpers were extracted after the reviewer
  pointed out the same two shapes repeated three ways:
  `PartialDeclarationsIncludingSelf` (the "gather every `partial` +
  self-if-missing" block, previously copy-pasted in
  `DeclaresMethodTransitively` and the old `BaseListNames`) and `ShouldVisit`
  (the cycle-guard shape shared by `FindLocalImplementers`,
  `ImplementsInterfaceTransitively`, and `DeclaresMethodTransitively`).
- **Naming.** `ResolveLocalImplementer` (singular) returned a list that could
  legitimately hold two-or-more entries — inconsistent with its own callee,
  `FindLocalImplementers` (plural), for the identical return shape. Renamed
  to `ResolveLocalImplementers`.
- **A real gap, not just a style note.** The Spec-axis review caught that the
  facts this method attached stopped at `WrapperSourceAvailable` and
  `ReceiverImplementationIdentity` — the checklist above promises "method
  semantics, and command/terminal-sink facts, the same as a directly-typed
  local wrapper," and the original diff never supplied them even when they
  were available. Fixed: `CreateUnavailableCandidate` now looks up whether
  the Local Implementer's own method already has a scanned
  `WrapperDefinition` (`wrappers.FirstOrDefault(w => w.MethodName ==
  methodName && w.TypeIdentity == localImplementer.TypeIdentity)`) and, when
  one exists, reuses its `MethodSemantics`/`TerminalSink`/
  `ReachesStoredProcedureSink`/`MethodIdentity`/`ParameterTypes`/
  `AssemblyIdentity`/`AssemblyRevision`/`UnresolvedReason` verbatim — the
  exact same fields a directly-typed local wrapper reaching that class
  already reports, no new extraction. Verified end to end with a new test,
  `test_local_implementer_reached_through_two_base_hops_reuses_its_wrapper_definition`:
  a two-hop base-class chain where the pre-existing `ReceiverTypeMayBeWrapper`
  mechanism (the single-hop check `IsSourceWrapperInvocation` already used,
  unrelated to this ticket) cannot see through the middle class to the
  interface, so this ticket's own transitive walk is what reaches the
  Local Implementer and its `WrapperDefinition` at all.

One real discovery during implementation, worth recording because it revised
my own first read of the spec: `IUtilityService.SqlParam` never becomes a
`WrapperDefinition` (it only builds a `SqlParameter`, never touches
`SqlCommand`/`DbCommand`), so the "redirect to the same
`WrapperDefinition`-driven extraction a directly-typed wrapper already uses"
framing in the spec's Implementation Decisions does not literally apply to
this method — a directly-typed `UtilityService _utility` field produces
`wrapper_source_available: false` for this exact call *today*, confirmed by
probing the real host before writing any fix. What actually classifies the
call `source_wrapper` in the Python gateway is only two raw facts —
`wrapper_source_available: true` and a resolvable
`receiver_implementation_identity` — not a terminal-sink match, per
`reconcile_wrapper`'s `if source_available:` branch (checked directly against
source, `code_analyzer/csharp_analysis_gateway.py:2210`). The implementation
here supplies exactly those two facts from the existing "unavailable
candidate" extraction pipeline (unchanged otherwise) rather than trying to
retrofit `SqlParam` into `WrapperDefinition`/`CommandSourceResolver`, which
would have been a much larger, out-of-scope change to "reaches a terminal
sink" classification. This matches the ticket's own real-host test target
(`wrapper_source_available == True`, `receiver_implementation_identity ==
"UtilityService"` for `_utility.SqlParam(...)` in `HomeService.cs`) exactly.

A second thing the spec's prose didn't spell out but the acceptance criteria
implied: an *abstract* base class that implements the interface and declares
the method must never itself be reported as the Local Implementer (a DI
container can never construct one) — only a concrete subclass reached through
it can be. Added an explicit `abstract`-modifier guard in
`FindLocalImplementers` after a synthetic test confirmed that without it, an
abstract-base + concrete-subclass pair was wrongly read as two tied
candidates.

Two deliberate departures from the spec's exact Implementation Decisions
wording, both verified against the real host rather than assumed, and both
raised (correctly) by the Spec-axis review — kept as departures, not
"fixed," because reverting either one would reopen the exact bug this ticket
closes:

- **"Runs only when ... `ReceiverDeclaration`."** With a real compilation
  available (`dotnet` is present in every environment this was verified in,
  and IQCS refreshes always have one), the compiler binds an interface-typed
  receiver's call to the interface's own declared method, so
  `ResolveWrapperReceiverType` reports `ResolvedReceiverType.Declaring`
  instead — confirmed directly against the real IQCS checkout, where
  `_utility.SqlParam(...)`'s `wrapper_receiver_type_provenance` is
  `"declaring_type"`, never `"receiver_declaration"`. Gating on
  `ReceiverDeclaration` alone would mean this feature never fires against
  real IQCS at all — the ~400-call motivating case from the spec's own
  Further Notes. `ResolveLocalImplementers` therefore gates on "does the
  resolved receiver type name a corpus interface," not on which of the two
  provenances produced it; both name the same interface.
- **"Reuses the existing `AllInterfaces`-based recognition pattern."** That
  pattern (`CommandContractRecognition.cs`) is Roslyn-symbol-based —
  `ITypeSymbol.AllInterfaces` — built for decompiled/BCL types against a
  live semantic model. This ticket's search had to stay syntax-only to match
  the file's own established idiom for exactly this kind of receiver-type
  check (`InheritsTheInvokedMethod`, `ReceiverTypeMayBeWrapper` — both
  string/BaseList-based, both already working with no compilation) and to
  keep working in the no-compilation synthetic tests below.
  `ImplementsInterfaceTransitively` is a hand-written BaseList walk instead.
  The other half of the same decision — extending `GetTypeDeclarationsByName`
  rather than building a second type index — is honored as written.

Verified against the real IQCS checkout
(`data/repos/System_Dept_1/IQCS/Services/HomeService.cs`'s
`_utility.SqlParam("UserID", 1)` call, `IUtilityService` →
`Services/UtilityService.cs`) and against seven synthetic scan-root fixtures
(zero implementers, two tied implementers, a sibling-root implementer outside
the scan root, an abstract-base-mediated implementer with no
`WrapperDefinition` anywhere, a same-class-either-way parity check against a
method that *does* reach a terminal sink, and the two-hop base-class
`WrapperDefinition`-redirect case above). New test file:
`tests/test_wrapper_receiver_local_implementer.py` (7 tests, all passing).
Regression check: `tests/test_wrapper_receiver_declaring_type.py` (ticket 06,
6 tests) still passes unchanged. Full suite:
`python3 -m pytest tests/ --ignore=tests/test_search_roles.py
--ignore=tests/test_sp_tables.py` — 952 passed, 10 failed; every one of the 10
failures was independently confirmed present on the unmodified base commit
(`git stash` before/after comparison, same assertions, same error messages,
all involving an unrelated `SQLObject`/`OrdersDb` external-contract fixture)
— pre-existing, not caused by this change. The two ignored files
(`test_search_roles.py`, `test_sp_tables.py`) fail at collection time in this
environment because no ODBC driver is installed for a live SQL Server
connection; unrelated to this ticket.

Ticket 02 (the `ambiguous_implementation` outcome for two-or-more
implementers) was left untouched — it is blocked by this ticket and is its
own piece of work.
