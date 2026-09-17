"""Ticket 06: a tool proposes exclusion candidates with their evidence.

Every test asserts on what a maintainer would read off the report -- a candidate's
call count, whether some System ever resolved the same pair, the tier chosen for
it, and the shape of the pasteable fragment -- never on how the gateway reached its
verdict. That belongs to the tests already covering the registry loader (ticket 05)
and Observed Call Evidence (ticket 04); this module only has to trust the flag both
of those already set (`wrapper_review_candidate`).
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from code_analyzer.csharp_analysis_gateway import (  # noqa: E402
    DbInvocation,
    GLOBAL_EXCLUSION_TIER_KEY,
    InvocationEvidence,
    InvocationSourceSpan,
)
from service import exclusion_candidates  # noqa: E402


def _invocation(**overrides) -> DbInvocation:
    """One rated Database Invocation, defaulted to a still-unresolved wrapper call."""
    base = dict(
        class_name="OrderService",
        method_name="Save",
        database=None,
        procedure_name=None,
        evidence=InvocationEvidence.UNRESOLVED,
        source=InvocationSourceSpan("OrderService.cs", 0, 10),
        wrapper_kind="external_wrapper",
        wrapper_status="unresolved_contract",
        wrapper_review_candidate=True,
        wrapper_receiver_type="SQLDbContext",
        wrapper_method="ExecProc",
    )
    base.update(overrides)
    return DbInvocation(**base)


def test_a_still_unresolved_call_becomes_one_candidate_with_its_call_count() -> None:
    invocations = [_invocation(), _invocation(class_name="OtherCaller")]

    grouped = exclusion_candidates.scan_review_candidates(invocations)

    assert grouped[("sqldbcontext", "execproc")]["call_count"] == 2
    assert grouped[("sqldbcontext", "execproc")]["receiver_type"] == "SQLDbContext"
    assert grouped[("sqldbcontext", "execproc")]["method_name"] == "ExecProc"


def test_a_call_a_rule_or_the_registry_already_cleared_never_becomes_a_candidate() -> None:
    """`not_applicable` is the shared shape both Observed Call Evidence (ticket 04)
    and an existing exclusion entry, in either tier (ticket 05), leave behind. This
    function does not need to know which rule produced it."""
    cleared = _invocation(wrapper_status="not_applicable", wrapper_review_candidate=False)

    grouped = exclusion_candidates.scan_review_candidates([cleared])

    assert grouped == {}


def test_a_direct_call_with_no_wrapper_method_is_never_a_candidate() -> None:
    direct_call = _invocation(wrapper_kind="", wrapper_status="", wrapper_review_candidate=False, wrapper_method="", wrapper_receiver_type="")

    grouped = exclusion_candidates.scan_review_candidates([direct_call])

    assert grouped == {}


def test_a_resolved_call_is_recorded_in_the_resolved_pairs_set() -> None:
    resolved = _invocation(wrapper_status="source_wrapper", wrapper_review_candidate=False)

    pairs = exclusion_candidates.scan_resolved_pairs([resolved])

    assert ("sqldbcontext", "execproc") in pairs


def test_a_still_unresolved_call_is_not_a_resolved_pair() -> None:
    pairs = exclusion_candidates.scan_resolved_pairs([_invocation()])

    assert pairs == set()


def test_empty_receiver_type_proposes_the_global_tier() -> None:
    candidates = exclusion_candidates.propose_exclusion_candidates(
        {"IQCS": [_invocation(wrapper_receiver_type="", wrapper_method="Add")]}
    )

    assert candidates[0]["tier"] == GLOBAL_EXCLUSION_TIER_KEY


def test_a_known_framework_receiver_type_proposes_the_global_tier() -> None:
    candidates = exclusion_candidates.propose_exclusion_candidates(
        {"IQCS": [_invocation(wrapper_receiver_type="DataTable", wrapper_method="Select")]},
        known_framework_receiver_types=["DataTable"],
    )

    assert candidates[0]["tier"] == GLOBAL_EXCLUSION_TIER_KEY


def test_every_other_candidate_proposes_the_systems_own_tier() -> None:
    candidates = exclusion_candidates.propose_exclusion_candidates(
        {"IQCS": [_invocation(wrapper_receiver_type="IUtilityService", wrapper_method="GetListFromSysParam")]},
        known_framework_receiver_types=["DataTable"],
    )

    assert candidates[0]["tier"] == "IQCS"


def test_a_candidate_reports_whether_any_system_ever_resolved_the_same_pair() -> None:
    """STC never resolves `SQLDbContext.ExecProc`, but IQCS's scan proves the exact
    same receiver/method pair really is a database wrapper call somewhere -- a
    maintainer weighs that fact when judging STC's candidate. `SQLDbContext` is not
    a known framework type here, so the pair stays in STC's own tier and IQCS's
    resolved call never merges into it."""
    candidates = exclusion_candidates.propose_exclusion_candidates(
        {
            "STC": [_invocation()],
            "IQCS": [_invocation(wrapper_status="explicit_selected", wrapper_review_candidate=False)],
        }
    )

    assert len(candidates) == 1
    stc_candidate = candidates[0]
    assert stc_candidate["tier"] == "STC"
    assert stc_candidate["systems"] == ["STC"]
    assert stc_candidate["resolved_elsewhere"] is True
    assert stc_candidate["call_count"] == 1


def test_a_global_eligible_pair_seen_in_two_systems_is_one_candidate_not_two() -> None:
    """Ticket 05's point applies here too: a decision that holds for every System is
    reviewed once. Two Systems both reporting the same empty-receiver-type call must
    fold into one global candidate with a summed call count, not two rows that would
    become two duplicate entries in the pasted fragment."""
    candidates = exclusion_candidates.propose_exclusion_candidates(
        {
            "IQCS": [_invocation(wrapper_receiver_type="", wrapper_method="Format")] * 2,
            "STC": [_invocation(wrapper_receiver_type="", wrapper_method="Format")],
        }
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["tier"] == GLOBAL_EXCLUSION_TIER_KEY
    assert candidate["call_count"] == 3
    assert sorted(candidate["systems"]) == ["IQCS", "STC"]

    fragment = exclusion_candidates.render_exclusion_fragment(candidates)
    assert fragment[GLOBAL_EXCLUSION_TIER_KEY] == [
        {"receiver_type": "", "method_name": "Format", "reason": "proposed_pending_review"}
    ]


def test_a_candidate_with_no_resolution_anywhere_reports_that_too() -> None:
    candidates = exclusion_candidates.propose_exclusion_candidates({"STC": [_invocation()]})

    assert candidates[0]["resolved_elsewhere"] is False


def test_the_fragment_matches_the_registry_format_and_groups_by_tier() -> None:
    candidates = exclusion_candidates.propose_exclusion_candidates(
        {
            "IQCS": [
                _invocation(wrapper_receiver_type="", wrapper_method="Add"),
                _invocation(wrapper_receiver_type="IUtilityService", wrapper_method="GetListFromSysParam"),
            ]
        }
    )

    fragment = exclusion_candidates.render_exclusion_fragment(candidates)

    assert fragment[GLOBAL_EXCLUSION_TIER_KEY] == [
        {"receiver_type": "", "method_name": "Add", "reason": "proposed_pending_review"}
    ]
    assert fragment["IQCS"] == [
        {
            "receiver_type": "IUtilityService",
            "method_name": "GetListFromSysParam",
            "reason": "proposed_pending_review",
        }
    ]
    for entries in fragment.values():
        for entry in entries:
            assert set(entry.keys()) == {"receiver_type", "method_name", "reason"}


def test_no_candidates_renders_an_empty_fragment() -> None:
    assert exclusion_candidates.render_exclusion_fragment([]) == {}
