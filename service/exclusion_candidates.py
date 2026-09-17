"""The Exclusion Candidate Tool: a maintainer approves a list instead of reading source code.

A rated scan already tells the whole story for a wrapper call still in review: its
receiver type, its method name, how many calls share that pair, and whether the
gateway ever resolved that exact pair to a real database call somewhere else. This
module turns those facts into a proposal -- one entry per (tier, pair) the
automatic rules did not already decide -- and a registry fragment shaped exactly
like the file a maintainer edits by hand.

This module builds the report only. It never reads configuration and never scans:
the caller hands it each System's already-rated invocations and the receiver types
the Global Exclusion Tier already covers, so the same proposal logic runs against a
live scan or a captured one without knowing which it was given. It never writes
anything either -- the caller decides what, if anything, to do with the fragment.
"""
from __future__ import annotations

from collections import OrderedDict
from typing import Any, Dict, Iterable, List, Mapping, Tuple

from code_analyzer.csharp_analysis_gateway import (
    DbInvocation,
    GLOBAL_EXCLUSION_TIER_KEY,
    wrapper_review_exclusion_key,
)

# A candidate's identity: the exact (receiver type, method name) pair, casefolded --
# the same shape and the same case-fold rule the exclusion registry itself keys on
# (`wrapper_review_exclusion_key`), so a proposal and a hand-written entry are never
# treated as two different things.
_CandidateKey = Tuple[str, str]

# A proposal has not been reviewed yet, so it carries a placeholder reason rather
# than a decision -- a maintainer replaces this before an entry is trusted the way
# every reviewed entry beside it already is.
PROPOSED_PENDING_REVIEW_REASON = "proposed_pending_review"


def scan_review_candidates(
    invocations: Iterable[DbInvocation],
) -> Dict[_CandidateKey, Dict[str, Any]]:
    """Group one scan's still-unresolved wrapper calls by receiver type and method name.

    Only a call still marked ``wrapper_review_candidate`` is counted. Observed Call
    Evidence and any existing exclusion entry, in either tier, already cleared every
    other wrapper call to ``not_applicable`` before it ever became a rated
    invocation -- the gateway drops such a call entirely rather than rating it -- so
    this function never has to re-check either rule or the registry itself.
    """
    grouped: Dict[_CandidateKey, Dict[str, Any]] = {}
    for invocation in invocations:
        if not invocation.wrapper_review_candidate:
            continue
        method_name = str(invocation.wrapper_method or "").strip()
        if not method_name:
            continue
        receiver_type = str(invocation.wrapper_receiver_type or "").strip()
        key = wrapper_review_exclusion_key(receiver_type, method_name)
        entry = grouped.setdefault(
            key,
            {"receiver_type": receiver_type, "method_name": method_name, "call_count": 0},
        )
        entry["call_count"] += 1
    return grouped


def scan_resolved_pairs(invocations: Iterable[DbInvocation]) -> set[_CandidateKey]:
    """Every (receiver type, method name) pair this scan resolved to a real wrapper call.

    A rated invocation with a wrapper kind and ``wrapper_review_candidate=False`` is
    a call the gateway actually reached a real answer for (``source_wrapper``,
    ``explicit_selected``, ...), not one no rule ever looked at -- a call the
    registry or Observed Call Evidence cleared never becomes a rated invocation at
    all, so ``wrapper_status`` here is never ``not_applicable``. A plain direct
    ADO.NET call carries no wrapper kind and never enters this set.
    """
    resolved: set[_CandidateKey] = set()
    for invocation in invocations:
        if not invocation.wrapper_kind or invocation.wrapper_review_candidate:
            continue
        method_name = str(invocation.wrapper_method or "").strip()
        if not method_name:
            continue
        receiver_type = str(invocation.wrapper_receiver_type or "").strip()
        resolved.add(wrapper_review_exclusion_key(receiver_type, method_name))
    return resolved


def propose_exclusion_candidates(
    invocations_by_system: Mapping[str, Iterable[DbInvocation]],
    *,
    known_framework_receiver_types: Iterable[str] = (),
) -> List[Dict[str, Any]]:
    """Propose one candidate per (tier, pair) a rule did not already decide.

    ``invocations_by_system`` maps a System id to that System's rated invocations
    (for example the merged values of ``coverage_report.rate_scan_invocations``'s
    result). The tool proposes the Global Exclusion Tier when a candidate's receiver
    type is empty or already known as framework behaviour; it proposes the System's
    own tier -- the System the candidate was observed in -- otherwise. A maintainer
    confirms the placement instead of deciding it.

    A pair that qualifies for the global tier is one decision, not one per System
    that happened to see it (ticket 05's own point): every System reporting that
    exact pair folds into a single candidate here, its call count summed and its
    ``systems`` list naming every System that saw it. A pair kept in a System's own
    tier is scoped to that System by definition, so it never merges with the same
    pair observed in a different System.
    """
    framework_types = {
        str(receiver_type).strip().casefold()
        for receiver_type in known_framework_receiver_types
        if str(receiver_type).strip()
    }

    resolved_pairs: set[_CandidateKey] = set()
    grouped: "OrderedDict[Tuple[str, _CandidateKey], Dict[str, Any]]" = OrderedDict()
    for system_id, invocations in invocations_by_system.items():
        system_id = str(system_id)
        invocations = list(invocations)
        resolved_pairs |= scan_resolved_pairs(invocations)
        for key, entry in scan_review_candidates(invocations).items():
            receiver_key, _method_key = key
            tier = (
                GLOBAL_EXCLUSION_TIER_KEY
                if not receiver_key or receiver_key in framework_types
                else system_id
            )
            group_key = (tier, key)
            candidate = grouped.get(group_key)
            if candidate is None:
                candidate = {
                    "tier": tier,
                    "receiver_type": entry["receiver_type"],
                    "method_name": entry["method_name"],
                    "call_count": 0,
                    "systems": [],
                }
                grouped[group_key] = candidate
            candidate["call_count"] += entry["call_count"]
            if system_id not in candidate["systems"]:
                candidate["systems"].append(system_id)

    candidates: List[Dict[str, Any]] = []
    for (_tier, key), candidate in grouped.items():
        candidate["resolved_elsewhere"] = key in resolved_pairs
        candidates.append(candidate)

    candidates.sort(
        key=lambda candidate: (
            candidate["tier"] != GLOBAL_EXCLUSION_TIER_KEY,
            str(candidate["tier"]).casefold(),
            str(candidate["receiver_type"]).casefold(),
            str(candidate["method_name"]).casefold(),
        )
    )
    return candidates


def render_exclusion_fragment(
    candidates: Iterable[Mapping[str, Any]],
) -> Dict[str, List[Dict[str, str]]]:
    """Group proposed candidates into a fragment shaped like the registry's own tiers.

    Each emitted entry carries exactly the three keys a real registry entry has --
    ``receiver_type``, ``method_name``, ``reason`` -- so a maintainer pastes an
    approved entry straight into the matching tier's list in
    ``config/wrapper_review_exclusions.json`` without editing its shape. The call
    count and cross-System evidence live in the candidate report, not here: a pasted
    entry should read exactly like every hand-written one beside it. Every candidate
    already names exactly one tier (``propose_exclusion_candidates`` folds a global
    pair seen in several Systems into one candidate), so this never emits two
    entries for the same pair in the same tier.
    """
    by_tier: "OrderedDict[str, List[Dict[str, str]]]" = OrderedDict()
    for candidate in candidates:
        tier = str(candidate.get("tier") or "").strip()
        method_name = str(candidate.get("method_name") or "").strip()
        if not tier or not method_name:
            continue
        by_tier.setdefault(tier, []).append(
            {
                "receiver_type": str(candidate.get("receiver_type") or ""),
                "method_name": method_name,
                "reason": PROPOSED_PENDING_REVIEW_REASON,
            }
        )
    return dict(by_tier)
