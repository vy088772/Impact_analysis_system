# 06 — A tool proposes exclusion candidates with their evidence

**What to build:** A maintainer approves a list instead of reading source code.
A new tool reads a scan result and the exclusion registry, and proposes the
entries a maintainer might add. It reports only the candidates that the
automatic rules did not already decide, so the list holds the decisions that
need a person.

Each candidate carries its evidence: the call count, and whether any System ever
resolved that receiver type and method name. A maintainer judges a candidate
from the report alone.

The tool chooses a tier for each candidate. It proposes the Global Exclusion
Tier when the receiver type is empty or names a known framework type. It
proposes the System's own tier otherwise. A maintainer confirms a placement
instead of deciding it.

The tool emits a registry fragment that a maintainer pastes directly into the
registry. The tool only reads. It never edits the registry itself.

**Blocked by:** 04 — Observed Call Evidence clears a method that touches no
database. 05 — One exclusion decision serves every System.

**Status:** done

**Note:** `service/exclusion_candidates.py` is the pure report builder (prior art:
`service/coverage_report.py`). `scan_review_candidates()` groups a scan's rated
invocations by `(receiver_type, method_name)`, counting only calls still marked
`wrapper_review_candidate` — a call Observed Call Evidence (ticket 04) cleared or an
existing exclusion entry in either tier (ticket 05) already covers is rated
`not_applicable` and `CSharpAnalysisGateway._resolve_one()` returns `None` for it,
so it never becomes a rated invocation at all and never reaches this function.
`scan_resolved_pairs()` collects every pair some System's evidence actually
resolved (`wrapper_review_candidate=False` on a real wrapper kind), which is the
cross-System "ever resolved" evidence. `propose_exclusion_candidates()` groups by
`(tier, pair)`, not by pair alone: a pair qualifying for the Global Exclusion Tier
(empty receiver type, or a receiver type `known_framework_receiver_types()` already
finds under `_global`) folds every System that reported it into one candidate with
a summed call count, matching ticket 05's "one exclusion decision serves every
System" — a pair kept in a System's own tier stays scoped to that System.
`render_exclusion_fragment()` emits `{tier: [{receiver_type, method_name, reason}]}`
— exactly the shape of `config/wrapper_review_exclusions.json`'s own `"systems"`
value, so a maintainer pastes each tier's list straight in. `code_analyzer/
csharp_analysis_gateway.py` gains two small public additions: `wrapper_review_exclusion_key()`
(the casefold-pair identity, now shared by the registry loader and this tool
instead of two independent copies) and `known_framework_receiver_types()` (reads
the receiver types already recorded under `_global` — no second hardcoded list).
`tools/propose_wrapper_review_exclusions.py` is the read-only CLI, mirroring
`tools/coverage_report.py`'s cached-scan pattern (`scan_store.get_or_scan(refresh=False)`);
it never calls anything that writes `config/wrapper_review_exclusions.json`.

Reviewed via `/code-review` (Standards + Spec axes, parallel sub-agents). Spec axis
found one real bug, now fixed: candidates were originally grouped per System before
tier assignment, so a global-eligible pair seen in two Systems emitted two separate
candidates and two duplicate entries in one tier's fragment list — violates "pastes
it without editing its shape" and ticket 05's own point. Fixed by grouping on
`(tier, pair)` instead of `(system, pair)`; regression test added
(`test_a_global_eligible_pair_seen_in_two_systems_is_one_candidate_not_two`).
Standards axis found only judgement-call smells (no standards doc exists in this
repo): fixed two — the duplicated casefold-pair key logic (now the shared
`wrapper_review_exclusion_key()` above) and an inlined `"proposed_pending_review"`
literal (now the module constant `PROPOSED_PENDING_REVIEW_REASON`, matching
`coverage_report.py`'s own named-reason-code convention). Left as a judgement call,
same as ticket 04's own review did for a similar finding: `tools/
propose_wrapper_review_exclusions.py`'s `measure_root_invocations()`/`main()` are
structurally very close to `tools/coverage_report.py`'s `measure_root()`/`main()`
— extracting a shared CLI scaffold would touch an already-shipped, unrelated file
for no behavior change, so it stays deferred.

Full suite: `python3 -m pytest tests/ --ignore=tests/test_search_roles.py
--ignore=tests/test_sp_tables.py` — 1010 passed, 11 failed; the failing set is
byte-identical (same 11 test names) to a `git stash -u` run against the unmodified
base commit (`c61e272`, ticket 05) — pre-existing, unrelated to this ticket.

- [x] The tool reports no candidate that Observed Call Evidence already cleared
- [x] The tool reports no candidate that an existing exclusion entry already
      covers, in either tier
- [x] Each candidate carries its call count and whether any System ever resolved
      that receiver type and method name
- [x] The tool proposes the global tier for a candidate whose receiver type is
      empty or names a known framework type
- [x] The tool proposes the System's own tier for every other candidate
- [x] The emitted fragment matches the registry format, and a maintainer pastes
      it without editing its shape
- [x] The tool writes nothing to the registry, and running it twice changes no
      file
