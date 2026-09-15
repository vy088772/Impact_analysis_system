# A Wrapper Receiver Resolves Through an Interface to Its Local Implementer

Status: ready-for-agent

## Problem Statement

IQCS calls `_utilityService.SqlParam(...)` through `IUtilityService`, a field
typed as an interface. `Services/UtilityService.cs`, in the same repository,
declares `class UtilityService : IUtilityService` and implements `SqlParam`
itself. The analyzer never looks for that class. `wrapper_receiver_type`
resolves to `IUtilityService` — a real, correctly-resolved receiver type — and
because the interface itself declares `SqlParam`,
`InheritsTheInvokedMethod` (`tools/StaticAnalyzerHost/CSharpAnalyzer.cs`)
reports the call as `ReceiverDeclaration("IUtilityService")` rather than as
inherited from somewhere unseen. The call then reaches Contract Preflight as
an unavailable external wrapper receiver with no available implementation
evidence, and is reported `unresolved_contract` /
`no_contract_matches_receiver_type` — the same status a genuinely external,
un-vendored library receives.

A full IQCS refresh (`python -m impact_orch.refresh_cli IQCS`) reports this
outcome for every interface-typed service field in the codebase:
`IUtilityService` (284 calls), `IFileService` (30), `ICommonServices` (11),
and over twenty more — roughly 400 of the refresh's 1128 total wrapper calls,
none of which name a genuinely external assembly. Every one of these
interfaces has exactly one local class implementing it, sitting in
`data/repos/System_Dept_1/IQCS/Services/`.

This was investigated directly against the real IQCS checkout and the real
`CSharpAnalysisGateway`/`StaticAnalyzerHost`, not assumed from the printed
`refresh_cli` output alone. No spec or ADR in this repository deliberately
excludes interface receivers: `docs/adr/`, every `.scratch/*/spec.md`, and the
commit that introduced `declaring_type_unresolved`
(`67dbb22`, "包裝器接收者解析沿繼承鏈找到宣告方法的型別 (ticket 06)") were all
checked, and none discuss interfaces, dependency injection, or an interface's
local implementer. This is a genuine, unaddressed gap in receiver resolution,
not a deliberate boundary.

## Solution

When a wrapper call's receiver resolves to an interface the current scan root
declares, and exactly one local class in that same scan root implements the
interface and itself declares the invoked method — its Local Implementer —
the call is resolved to that class's method the same way a directly-typed
local wrapper already is: source-backed, rated by its own method body, no
external Contract required. An interface with no local implementer is left
exactly as it is reported today. An interface with two or more local
implementers is never guessed between; it is reported as a distinct,
reviewable outcome so the tie is visible rather than silently broken by
declaration order or name similarity.

## User Stories

1. As a system analyst, I want a wrapper call through an interface field to
   resolve to its local implementing class, so that a DI-style service field
   is not treated as an unavailable external wrapper merely because its
   static type is an interface.
2. As a system analyst, I want the resolved call rated from the Local
   Implementer's own method body, so that its Database Invocation evidence is
   exactly as strong as if the field had been typed as the concrete class.
3. As a system analyst, I want an interface with no local implementer left
   exactly as it is reported today, so that a genuinely external interface
   (one whose implementation is vendored in a DLL, or not present in this
   scan root at all) is not silently misclassified as source-backed.
4. As a system analyst, I want an interface with two or more local
   implementers to be reported as a distinct, reviewable outcome rather than
   resolved to any one of them, so that the analyzer never guesses by
   declaration order, file order, or name similarity.
5. As a system analyst, I want the reviewable multi-implementer outcome to
   name every candidate class, so that the ambiguity is resolvable by reading
   the report alone, without re-deriving it from source.
6. As a system analyst, I want an interface implementer search bounded to the
   current scan root, so that a multi-root system never treats an unrelated
   sibling root's class as this root's implementer (mirroring the existing
   Source-wrapper resolution boundary from
   `external-wrapper-refresh-reconciliation`).
7. As a system analyst, I want the interface-to-implementer match to require
   the candidate class to itself declare the called method (not merely
   implement the interface), so that a partial or indirect implementation is
   never mistaken for a full one.
8. As a system analyst, I want a class that implements the interface only
   through a further base class to still count as a valid Local Implementer,
   so that a common "abstract base implements most of the interface, concrete
   subclass fills in the rest" pattern is not silently excluded.
9. As a system maintainer, I want this resolution to run entirely inside the
   existing `CSharpAnalysisGateway`/`StaticAnalyzerHost` boundary, so that no
   second wrapper-classification rule set is introduced alongside the
   existing one.
10. As a system maintainer, I want the new multi-implementer outcome to reuse
    the existing `ambiguous_contract` / `multiple_contracts_match_receiver_type`
    shape and naming convention, so that a reader of `Wrapper Resolution
    Status` finds one family of "N things matched, none chosen" outcomes
    instead of two differently-named ones.
11. As a system maintainer, I want a class already recognised today as a
    directly-typed local wrapper to classify identically whether reached
    directly or through an interface field, so that this feature changes
    receiver *resolution* only, never Database Invocation *rating*.
12. As a system maintainer, I want the existing external-wrapper Contract path
    to remain the only route for a genuinely external, DLL-only interface, so
    that this feature narrows nothing about `external-wrapper-refresh-reconciliation`
    or `automatic-external-wrapper-decompilation` — it only catches calls that
    would otherwise have reached that path in error.
13. As a system operator, I want a full IQCS refresh to report `IUtilityService`,
    `IFileService`, and the rest of IQCS's DI-style service interfaces as
    source-backed wrapper calls, so that the ~400 calls currently reported
    `unresolved_contract` reflect their true, already-available evidence.
14. As a downstream RAG coordinator, I want an interface-resolved wrapper call
    to carry the same response shape as any other source-backed wrapper call,
    so that no consumer needs to special-case "resolved through an interface."
15. As a system analyst, I want this resolution to apply only to a wrapper
    call already classified `source_wrapper`-eligible by today's rules (an
    interface the corpus declares), so that a truly unresolved receiver type
    (nothing declared at all) is untouched.

## Implementation Decisions

- The resolution step lives in `tools/StaticAnalyzerHost/CSharpAnalyzer.cs`,
  beside `ResolveWrapperReceiverType` and `InheritsTheInvokedMethod` — the
  existing boundary that already resolves every other receiver-type shape
  (declaring type, receiver's own declaration). It runs only when that
  existing logic would otherwise produce `ResolvedReceiverType.ReceiverDeclaration`
  for a receiver type whose corpus declaration is an interface, not a class.
- Candidate discovery reuses the existing `AllInterfaces`-based recognition
  pattern already used elsewhere in the host for contract-by-interface
  checks (`CommandContractRecognition.cs`'s `IDbCommand` recognition), applied
  against the corpus's own class declarations, extending the existing
  `GetTypeDeclarationsByName` linear-scan mechanism rather than introducing a
  second type index.
- Exactly one candidate — the Local Implementer — redirects the same
  body/fact-extraction already used for a directly-typed local wrapper class
  to the Local Implementer's method declaration: `WrapperSourceAvailable`
  becomes `true`, and `receiver_implementation_identity` names the concrete
  class. No new extraction logic is written; the existing one is pointed at a
  different declaration.
- Zero candidates: unchanged. The call proceeds exactly as it does today.
- Two or more candidates: a new fact, `wrapper_implementation_candidates`
  (the tied class names), is reported; `WrapperSourceAvailable` stays `false`.
- `code_analyzer/csharp_analysis_gateway.py`'s `reconcile_wrapper` gains one
  new branch: a raw fact carrying `wrapper_implementation_candidates`
  produces `wrapper_kind="source_wrapper"`, `status="ambiguous_implementation"`,
  `selection_source="ambiguous_local_implementation"`,
  `reason="multiple_classes_implement_receiver_type"`, `review_candidate=True`
  — the same shape as the existing `ambiguous_contract` outcome
  (`csharp_analysis_gateway.py`, the explicit-contract multiple-match branch),
  with `candidate_contracts` carrying the tied class names.
- The single-implementer case needs no gateway change: once the host reports
  `wrapper_source_available=true` with the Local Implementer's facts, the
  gateway's existing `if source_available:` branch in `reconcile_wrapper`
  already classifies it `source_wrapper` correctly — this path is already
  tested (`tests/test_csharp_analysis_gateway.py`), just never reached by an
  interface receiver in production today.
- `ambiguous_implementation` joins the existing `Wrapper Resolution Status`
  enum family (`source_wrapper`, `explicit_selected`, `unresolved_contract`,
  `ambiguous_contract`, `receiver_mismatch`, `unresolved_method`,
  `not_applicable`); it does not replace or rename any existing value.
- `Local Implementer` is the new domain term (already recorded in
  `CONTEXT.md`, C# Data Access Analysis section) for the resolved concrete
  class; it is deliberately distinct from `Declaring Receiver Type` (which
  walks *up* an inheritance chain to a base class) and from `Receiver
  Implementation Binding` (`.scratch/unified-database-invocation-classification/spec.md`,
  which disambiguates two same-named concrete classes via construction/assignment
  tracing) — this feature walks *down* from an interface to its implementer,
  a direction neither existing concept covers.

## Testing Decisions

- The highest seam is `CSharpAnalysisGateway`, per this repository's existing
  testing convention (`docs/EXTERNAL_WRAPPER_REFRESH_RECONCILIATION_SPEC.md`'s
  Testing Decisions: "the highest testing seam is `CSharpAnalysisGateway`").
  Gateway tests provide synthetic raw invocation facts — no live source
  needed — for the new `ambiguous_implementation` branch: `_raw_invocation`
  with `wrapper_implementation_candidates` set to two names asserts
  `status == "ambiguous_implementation"`, `review_candidate is True`,
  `reason == "multiple_classes_implement_receiver_type"`. A zero-candidate
  interface receiver (unchanged path) asserts the existing
  `no_contract_matches_receiver_type` outcome is untouched — a regression
  guard for every genuinely external interface and BCL type already in the
  corpus.
- The interface→Local Implementer *matching* itself is new logic inside the
  real Roslyn host and cannot be exercised through a synthetic gateway
  fixture alone, so one real-host test is required, mirroring
  `tests/test_wrapper_receiver_declaring_type.py` exactly: point the real
  `StaticAnalyzerHost` at a real IQCS file that calls
  `_utilityService.SqlParam(...)`, with `Services/UtilityService.cs` in the
  same source root, and assert `wrapper_source_available == True` and
  `receiver_implementation_identity == "UtilityService"` on the resulting raw
  fact. A second small fixture pair (two classes implementing one interface,
  added under a throwaway scan root, not the real IQCS checkout) exercises
  the ambiguous path end to end.
- No new test seam is introduced. Both seams already exist in this
  repository for exactly this class of receiver-resolution change.

## Out of Scope

- Dependency-injection container registration scanning (`AddScoped`,
  `AddTransient`, `AddSingleton`, or any DI-framework-specific resolution).
  This feature is a purely structural match — one interface, one class in the
  same corpus that implements it and declares the method — never a runtime or
  configuration-driven binding.
- Cross-root or cross-repository interface-to-implementer resolution. The
  search is bounded to the current scan root, matching the existing
  Source-wrapper boundary rule.
- Resolving an interface to an implementer defined in a referenced but
  un-scanned project, or in an external DLL. A DLL-only implementer remains
  the external-wrapper-Contract path's concern
  (`automatic-external-wrapper-decompilation`), not this feature's.
- Breaking a multi-implementer tie by any heuristic — declaration order, file
  path, name similarity to the interface, or "most recently modified." Every
  tie is reported, never guessed.
- Changing `Declaring Receiver Type` resolution (the inheritance-chain walk)
  or `Receiver Implementation Binding` (construction/assignment-based overload
  disambiguation) — this feature adds a third, independent resolution rule
  beside them, and does not touch their existing behavior.

## Further Notes

This spec came out of a grilling session that started from the user's own
hypothesis — decompiling `CommonLibrary.dll` for `SQLDbContext` — which turned
out to name a real but *separate* gap (tracked instead as a new ticket in
`.scratch/automatic-external-wrapper-decompilation/issues/`, since that
mechanism already exists and only needed a cache-staleness fix, not new
classification logic). This spec is the other, independent half of that
session's findings: `SQLDbContext` and `IUtilityService` account for roughly
half of IQCS's 1128 wrapper calls between them, and neither one is a
Contract-registry problem — one needed a cache fix, the other needs this
receiver-resolution feature. `IUtilityService` alone (284 calls) is IQCS's
single largest unresolved wrapper receiver.
