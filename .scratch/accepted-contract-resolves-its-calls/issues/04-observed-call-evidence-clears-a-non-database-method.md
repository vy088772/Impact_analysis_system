# 04 — Observed Call Evidence clears a method that touches no database

**What to build:** The analyzer clears a wrapper call by itself when the
evidence proves that the method it reaches touches no database. A maintainer
writes no exclusion entry for such a method, and the rule serves every System at
once.

The gateway classifies a wrapper call as `not_applicable` when two conditions
hold together. First, the call resolved to a Local Implementer. Second, the scan
holds at least one Database Invocation record for that implementer's method, and
every such record names no database receiver type.

The rule requires at least one record. A method that holds no record at all
stays in review. The scan does not record a call to another method inside the
same project, so an absence of records proves nothing. In the IQCS checkout
`ViewPath` touches no database and holds no record, and `GetListFromSysParam`
reaches a database through a second method and also holds no record. The two
look identical to this rule, so the rule clears neither.

This rule needs facts from across the whole scan, and the rating step builds one
gateway for each source file. The rating step therefore builds one index first.
The index names every class and method that touches a database receiver type.
The rating step passes that index to each gateway, so the classification stays
in the same place as every other wrapper status. This ticket adds no call graph
to the analyzer host.

Once the rule clears `SqlParam`, the hand-written exclusion entry for it becomes
redundant, and this ticket removes it. The `ViewPath` entry stays.

**Blocked by:** 01 — The ADRs and the glossary record the decisions.

**Status:** done

- [x] The rating step builds one index of every class and method that touches a
      database receiver type, and passes it to each gateway
- [x] `IUtilityService.SqlParam` (233 calls) reports `not_applicable` without any
      exclusion entry, because its implementer holds two records and neither
      names a database receiver type
- [x] `IUtilityService.GetListFromSysParam` (14 calls) stays in review, because
      its implementer holds no record at all
- [x] `IUtilityService.GetMstCodes` is never cleared, because its implementer
      holds a record that names a database receiver type
- [x] `IUtilityService.ViewPath` stays in review, and its hand-written exclusion
      entry still applies
- [x] The hand-written `SqlParam` exclusion entry is removed, and `SqlParam`
      still reports `not_applicable`
- [x] The analyzer host is unchanged by this ticket

**Notes:**

Implemented entirely in Python, matching the spec's own boundary (no call graph, no
analyzer-host change):

- **`code_analyzer/csharp_analysis_gateway.py`** — `build_observed_call_evidence_index(raw_by_file,
  external_wrapper_contracts)` is the new whole-scan index: it walks every raw Database
  Invocation record across every file, keys each one by `(class_name, method_name)` via the
  new `_observed_call_evidence_key` helper, and folds in whether that record names a
  "database receiver type" via `_record_names_database_receiver_type`. A key absent from the
  returned dict means zero records exist for that class/method (ADR-0029: stays in review); a
  key present and mapped to `False` means records exist and none touched a database (clears);
  `True` means at least one record did (never clears). `CSharpAnalysisGateway.__init__` gains
  an `observed_call_evidence_index` parameter (default `{}`, so every existing caller and test
  is unaffected), and `_observed_call_evidence_clears(implementation_identity, wrapper_method)`
  is the gateway-side lookup `reconcile_wrapper` calls.
- **"Database receiver type" is defined generically, not hardcoded to IQCS.**
  `_known_database_receiver_types` builds its recognition set purely from the union of every
  registered external wrapper Contract's own `receiver_types` (e.g. `SQLDbContext`, `SQLFunc`,
  `SQLObject` from `config/external_wrapper_contracts.json`) — the same registry ticket 05's
  Global Exclusion Tier already treats as cross-System. No System name, no `SqlParam`/
  `ViewPath` string, and no native ADO.NET type name (`SqlCommand`, `SqlConnection`, ...)
  appears anywhere in this recognition logic, so the rule serves every System the registry
  already covers, with zero per-System tuning.
  - This does mean the rule cannot recognize a genuinely raw ADO.NET receiver type (a
    `SqlCommand` construction, say) as "touching a database" on its own — only Contract-
    registered receiver types are known. This is safe rather than a gap: see the next point.
- **The new branch only ever fires where the call would otherwise stay
  `wrapper_mode_unresolved` forever.** In `reconcile_wrapper`'s `source_available` branch, the
  check sits after `source_mode()` computes `mode_reason`, and only intervenes when
  `mode_reason == "wrapper_mode_unresolved"` — i.e. the Local Implementer's own method never
  reached a real terminal sink (no `WrapperDefinition` exists for it, ticket 01's own finding
  for `SqlParam`). A Local Implementer method that *did* reach a real sink already resolves to
  `fixed_inline_sql`/`fixed_stored_procedure` via the existing `WrapperDefinition` reuse
  mechanism (ticket 01), so `mode_reason` is never `wrapper_mode_unresolved` for it and this
  rule never gets a chance to reconsider it — regardless of whether the sink's own native
  ADO.NET receiver type is in the "known database receiver types" set. Proven directly by
  `tests/test_observed_call_evidence.py::test_a_local_implementer_that_already_reaches_a_terminal_sink_is_never_reconsidered`.
- **`service/analyze_service.py`** — both rating-step loops that build one
  `CSharpAnalysisGateway` per source file (`_rated_execution_invocations`, used for
  execution-path/derived-evidence rating, and `reconcile_refresh_wrappers`, used for the
  `/refresh` wrapper review report) now call `build_observed_call_evidence_index` once — from
  the whole scan's `db_invocations`, before the per-file loop — and pass the same index into
  every gateway construction inside that loop. `reconcile_refresh_wrappers` builds the index
  once per `scan` (inside its `for scan in scans:` loop), matching the same scan-root boundary
  ticket 01's Local Implementer search already respects for a multi-root System.
- **`service/coverage_report.py`** — `rate_scan_invocations` (the function behind
  `python -m tools.coverage_report`, the spec's own acceptance measurement) gets the same
  treatment: one index built from the whole scan before its per-file loop.
- **`config/wrapper_review_exclusions.json`** — the hand-written `SqlParam` entry for `IQCS`
  is removed (redundant now that the rule clears it by itself); the `ViewPath` entry stays,
  since `ViewPath` holds zero records and the rule can never clear it.

**A real-checkout example the spec didn't name, confirmed as a side effect.** Every other
`IUtilityService` method whose own body only calls non-database BCL/framework methods (for
example `AddModelError`/`RemoveModelError`/`GetAllUnderPropertyName`, which call
`ModelStateDictionary`/`List` methods) is cleared by the same rule the first time some caller
reaches them through the interface with an otherwise-unresolved mode — exactly the "the rule
serves every System at once" outcome the spec asks for, not a special case for the four named
methods.

**Testing.** New file `tests/test_observed_call_evidence.py` (8 tests). Real-checkout tests
scan the real IQCS files this ticket names — `Services/UtilityService.cs` for the Local
Implementer's own records, and three different real caller files
(`Services/HomeService.cs` for `SqlParam`, `Controllers/VehNGAprController.cs` for
`GetListFromSysParam`, `Controllers/HomeController.cs` for `ViewPath`) — building the index
from both files together each time, since this rule's whole reason for existing is that the
implementer and the call site commonly live in different files. `GetMstCodes` has no real call
site through `IUtilityService` anywhere in the IQCS checkout, so it uses a synthetic call-site
fact shaped exactly like the real, ticket-01-resolved facts the other three tests show (the
same technique tickets 02/03 used for their own gaps), against the real `UtilityService.cs`
scan for the implementer-side record. One test proves the whole-scan index is built from every
file's facts together (not one file's own facts alone). One test proves the terminal-sink
safety guard directly. One reads `config/wrapper_review_exclusions.json` to confirm `SqlParam`
is gone and `ViewPath` stays. One drives `coverage_report.rate_scan_invocations` end-to-end
with synthetic multi-file records to prove the index is actually wired through the rating
step, not just callable in isolation.

Ran `/code-review` (Standards + Spec axes, parallel sub-agents). Spec: no discrepancies found
against the ticket, ADR-0029, and the parent spec's Implementation/Testing Decisions. Standards:
no documented standard exists in this repo (no `CODING_STANDARDS.md`/`CONTRIBUTING.md`) to
violate; three baseline-smell judgement calls were raised — a duplicated class/method key
normalization (fixed here by extracting `_observed_call_evidence_key`, reused by both the index
builder and the gateway-side lookup), a growing parameter list on
`CSharpAnalysisGateway.__init__` (left as-is: consistent with the class's existing shape before
this ticket, and a `RatingConfig`-style consolidation would touch every existing call site for
no behavior change), and the same three-line index-build-and-wire pattern repeated at three
call sites (left as-is: it mirrors the pre-existing pattern this repo already uses for
`contract_registry`/`wrapper_review_exclusions`, and each site is independently commented).

Full suite: `python3 -m pytest tests/ --ignore=tests/test_search_roles.py
--ignore=tests/test_sp_tables.py` — 987 passed, 11 failed; the failing set is byte-identical
(same 11 test names) to a `git stash` run against the unmodified base commit (`ea2a9da`,
ticket 03) — pre-existing, unrelated to this ticket. `git diff --stat -- tools/StaticAnalyzerHost`
is empty: the analyzer host is untouched, as the ticket's own last bullet requires. C# host not
rebuilt this ticket (no C# file changed).
