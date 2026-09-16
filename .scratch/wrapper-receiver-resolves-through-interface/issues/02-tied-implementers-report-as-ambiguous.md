# 02 — An interface implemented by two or more local classes reports a distinct, reviewable ambiguous outcome

**What to build:** When an interface-typed wrapper receiver has two or more
local classes in the current scan root that both implement it and declare the
called method, the call reports a new, distinct Wrapper Resolution Status —
`ambiguous_implementation` — naming every tied candidate class, instead of
the unchanged/unresolved outcome ticket 01 left this case with. Nobody breaks
the tie by declaration order, file order, or name similarity; the tie is
reported so it can be resolved by a human reading the report alone.

**Blocked by:** 01 — needs the candidate-discovery logic that finds every
local implementer of an interface; this ticket only changes what happens when
that search finds more than one.

**Status:** done

- [x] An interface with two or more local implementing classes (each
      declaring the called method) reports `ambiguous_implementation`, naming
      every tied candidate class by identity
- [x] `ambiguous_implementation` is reported as a review-worthy outcome (the
      same review-candidate treatment the existing `ambiguous_contract`
      outcome already receives), never silently passed through as resolved
      evidence
- [x] The reported reason names the situation explicitly (multiple local
      classes implement the receiver type), distinguishable from every other
      existing unresolved/ambiguous reason
- [x] An interface with exactly one local implementer (ticket 01's case) is
      unaffected by this ticket — it still resolves source-backed, never
      routed through the new ambiguous outcome
- [x] A synthetic test fixture with two candidate implementers asserts the
      `ambiguous_implementation` outcome and its named candidates, without
      requiring a real multi-implementer fixture in the real IQCS checkout
- [x] A second small real- or synthetic-source fixture pair (two classes
      implementing one interface) exercises the ambiguous path end to end,
      confirming the candidate names surface all the way to the reported
      outcome

**Notes:**

Implemented across the two seams the spec's Implementation Decisions named:

- `tools/StaticAnalyzerHost/CSharpAnalyzer.cs` — ticket 01's
  `ResolveLocalImplementers`/`FindLocalImplementers` already discovered every
  tied candidate; it just discarded the list down to `null` whenever the
  count was not exactly 1. `CreateUnavailableCandidate` now also keeps the
  full list when `localImplementers.Count >= 2` (`tiedImplementers`) and
  passes it to `CreateUnavailableInvocation`, which threads the tied class
  names into a new `WrapperImplementationCandidates` record field on
  `DirectSqlInvocation`. `Program.cs`'s existing `JsonNamingPolicy
  .SnakeCaseLower` serializes this to `wrapper_implementation_candidates`
  with no extra mapping code. The new field was appended at the end of the
  record (not inserted where it conceptually belongs, beside
  `ReceiverImplementationIdentity`) because a sibling method,
  `CreateUnavailableSourceCandidate`, constructs the same record with
  positional arguments — inserting mid-list broke seven of its positional
  slots on the first build attempt; appending avoids that fragility entirely.
- `code_analyzer/csharp_analysis_gateway.py`'s `reconcile_wrapper` gained one
  new branch, placed beside (not inside) the existing `if source_available:`
  block — a tied-candidate fact is never `wrapper_source_available=true` —
  and before the explicit-contract handling that would otherwise silently
  reclassify it as a plain `unresolved_contract`. It reuses the existing
  `candidate_contracts` field (the same one `ambiguous_contract` already
  populates) rather than inventing a new one, exactly as the spec's
  Implementation Decisions specify.
- `CONTEXT.md`'s `Wrapper Resolution Status` glossary entry gained
  `ambiguous_implementation` in its own enumerated example list — the `Local
  Implementer` entry ticket 01 wrote already named this status, but the
  status family's own entry hadn't caught up.

One real gap found during the Spec-axis `/code-review` pass (Standards +
Spec, both sub-agents given the diff independently): two production status
sets and one operator-facing doc table hardcoded the "review-worthy /
unresolved" status vocabulary and would have silently under-counted the new
outcome forever, never emitting a hard error to say so —
`tools/discover_external_wrappers.py`'s `totals.unresolved` counter,
`service/analyze_service.py`'s `unresolved_statuses` set (feeding its own
`totals` dict), and `docs/進階手冊.md`'s CLI status table. None of these are
named in this ticket's checklist or in spec.md's Implementation/Testing
Decisions, and the per-observation `review_candidate`/`wrapper_review_candidate`
flag this ticket sets was already correct everywhere it matters (confirmed:
`analyze_service.py`'s `review_items` list, the one place review-worthiness
actually gates behavior, filters on that flag, not on the hardcoded set) — so
this was a redundant summary-count gap, not a correctness bug in reconciliation
itself. Fixed anyway, since the spec's own User Stories 4/5 ask for this
outcome to be "resolvable by reading the report alone," and a silently
undercounted total works against that. All three were one-line additions.

Standards-axis review found no hard violations; only a judgement-call note
that the candidate-name normalization idiom in `reconcile_wrapper`
(stringify → strip → drop empties → tuple) repeats a shape already used
twice elsewhere in the same file for `explicit_names`/
`selected_candidate_names` — pre-existing duplication this ticket's new
branch follows rather than introduces, left as-is rather than extracted,
since fixing it would have touched code outside this ticket's diff.

New test file: `tests/test_wrapper_receiver_ambiguous_implementation.py` (4
tests) — two gateway-only synthetic-fact tests (the ambiguous branch itself,
and a zero-candidate regression guard), one `@requires_dotnet` real-host
end-to-end test (two tied classes under a throwaway scan root, run through
the real `StaticAnalyzerHost` and then `reconcile_wrapper`, confirming the
candidate names survive the host→gateway boundary), and one
single-implementer-unaffected regression check. Regression check:
`tests/test_wrapper_receiver_local_implementer.py` (ticket 01, 7 tests) and
`tests/test_wrapper_receiver_declaring_type.py` (ticket 06, 6 tests) both
still pass unchanged. Full suite:
`python3 -m pytest tests/ --ignore=tests/test_search_roles.py
--ignore=tests/test_sp_tables.py` — 956 passed, 10 failed; every one of the
10 failures confirmed present and identical on the pre-change commit
(`git stash` before/after comparison, same assertions, same error messages,
all involving the same unrelated `SQLObject`/`OrdersDb` external-contract
fixture ticket 01's own notes already identified) — pre-existing, not caused
by this change.
