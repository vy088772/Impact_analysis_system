"""Refresh-time contract selector normalization and staged onboarding."""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from code_analyzer.external_wrapper_contracts import (
    ContractSnapshotError,
    versioned_contract_from_proposal,
)
from .contract_registry import (
    DEFAULT_CATALOG_PATH,
    DEFAULT_REGISTRY_PATH,
    _registry_entries,
    _registry_payload,
    find_casefold,
    load_contract_registry,
    taken_contract_name,
    unused_revision_name,
)


SelectorValue = str | list[str] | tuple[str, ...] | None

_SNAPSHOT_KEYS = (
    "implementation_snapshot",
    "verified_implementation_snapshot",
    "snapshot",
    "source_implementation_snapshot",
    "source_snapshot",
)
_PROPOSAL_KEYS = (
    "contract_preflight_proposal",
    "contract_proposal",
    "wrapper_contract_proposal",
    "implementation_proposal",
    "verified_implementation_evidence",
)

@dataclass(frozen=True)
class ContractSelector:
    """Normalized selector state used by refresh-time contract preflight."""

    status: str
    original: Any = None
    candidates: tuple[str, ...] = ()
    reason: str = ""


@dataclass(frozen=True)
class ContractPreflightResult:
    """Reviewable in-memory contract interpretation for one refresh."""

    selector: ContractSelector
    onboarding_status: str
    formal_selector: SelectorValue = None
    staged_selector: SelectorValue = None
    formal_registry: dict[str, Any] | None = None
    staged_registry: dict[str, Any] | None = None
    reason: str = ""
    proposals: tuple[dict[str, Any], ...] = ()
    review_candidates: tuple[dict[str, Any], ...] = ()

    @property
    def failed(self) -> bool:
        return self.onboarding_status == "preflight_failed"

    def to_dict(self) -> dict[str, Any]:
        staged_registry = copy.deepcopy(self.staged_registry or {"contracts": {}})
        return {
            "selector_status": self.selector.status,
            "selector_original": copy.deepcopy(self.selector.original),
            "selector_candidates": list(self.selector.candidates),
            "selector_diagnostic": self.selector.reason,
            "contract_onboarding_status": self.onboarding_status,
            "preflight_status": "failed" if self.failed else "ready",
            "contract_preflight_failed": self.failed,
            "contract_preflight_reason": self.reason,
            "formal_selector": _serialize_selector(self.formal_selector),
            "staged_selector": _serialize_selector(self.staged_selector),
            "staged_contracts": sorted(
                str(name)
                for name in _registry_entries(staged_registry)
            ),
            "staged_registry": staged_registry,
            "proposals": [copy.deepcopy(dict(item)) for item in self.proposals],
            "review_candidates": [
                copy.deepcopy(dict(item)) for item in self.review_candidates
            ],
        }


def load_system_contract_selector(
    system_id: str,
    path: Path | str = DEFAULT_CATALOG_PATH,
) -> Any:
    """Read one system's selector from the shared system catalog."""
    normalized_system = str(system_id or "").strip()
    if not normalized_system:
        return None
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    systems = payload.get("systems") if isinstance(payload, Mapping) else None
    if not isinstance(systems, list):
        return None
    for system in systems:
        if not isinstance(system, Mapping):
            continue
        if str(system.get("system_id") or "").strip() == normalized_system:
            return copy.deepcopy(system.get("wrapper_contract"))
    return None


def normalize_contract_selector(
    selector: Any,
    registry: Mapping[str, Any],
) -> ContractSelector:
    """Normalize a string or array selector without applying a partial value."""
    entries = _registry_entries(registry)
    by_name = {name.casefold(): name for name in entries if name.strip()}

    if selector is None:
        return ContractSelector("unspecified", selector)
    if isinstance(selector, str):
        value = selector.strip()
        if not value:
            return ContractSelector("unspecified", selector)
        canonical = by_name.get(value.casefold())
        if canonical is None:
            return ContractSelector(
                "unspecified",
                selector,
                reason="selector_contract_not_found",
            )
        return ContractSelector("valid", selector, (canonical,))
    if isinstance(selector, (list, tuple)):
        if any(not isinstance(item, str) for item in selector):
            return ContractSelector(
                "unspecified",
                selector,
                reason="selector_type_invalid",
            )
        values = [item.strip() for item in selector]
        if not values:
            return ContractSelector("unspecified", selector)
        if all(not value for value in values):
            return ContractSelector("unspecified", selector)
        if any(not value for value in values):
            return ContractSelector(
                "unspecified",
                selector,
                reason="selector_contract_not_found",
            )
        candidates: list[str] = []
        missing = False
        for value in values:
            canonical = by_name.get(value.casefold())
            if canonical is None:
                missing = True
                continue
            if canonical.casefold() not in {item.casefold() for item in candidates}:
                candidates.append(canonical)
        if missing or not candidates:
            return ContractSelector(
                "unspecified",
                selector,
                reason="selector_contract_not_found",
            )
        candidates.sort(key=str.casefold)
        return ContractSelector("valid", selector, tuple(candidates))
    return ContractSelector("unspecified", selector, reason="selector_type_invalid")


def _serialize_selector(selector: SelectorValue) -> SelectorValue:
    if isinstance(selector, tuple):
        return list(selector)
    return selector


def _as_mappings(value: Any) -> list[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        return [value]
    if isinstance(value, (list, tuple)):
        return [item for item in value if isinstance(item, Mapping)]
    return []


def _first_mapping(source: Mapping[str, Any], keys: tuple[str, ...]) -> Mapping[str, Any] | None:
    for key in keys:
        value = source.get(key)
        if isinstance(value, Mapping):
            return value
    return None


def _snapshot_from_proposal(proposal: Mapping[str, Any]) -> Mapping[str, Any] | None:
    nested = proposal.get("contract")
    candidates = [proposal]
    if isinstance(nested, Mapping):
        candidates.insert(0, nested)
    for candidate in candidates:
        snapshot = _first_mapping(candidate, _SNAPSHOT_KEYS)
        if snapshot is not None:
            return snapshot
        if all(
            key in candidate
            for key in (
                "artifact_identity",
                "assembly_identity",
                "assembly_revision",
                "behavior_surface_unit",
            )
        ):
            return candidate
    return None


def _binding_value(source: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = source.get(key)
        if isinstance(value, Mapping):
            nested = _binding_value(value, *keys)
            if nested:
                return nested
        elif value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _slug(value: str) -> str:
    result = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-_.")
    return result.casefold() or "contract"


def _proposal_with_context(
    proposal: Mapping[str, Any],
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    candidate = copy.deepcopy(dict(proposal))
    context = context or {}
    nested = candidate.get("contract")
    if isinstance(nested, Mapping):
        merged = copy.deepcopy(dict(nested))
        merged.update(candidate)
        candidate = merged
    snapshot = _snapshot_from_proposal(candidate)
    if snapshot is not None:
        candidate["implementation_snapshot"] = copy.deepcopy(dict(snapshot))
    for key in (
        "name",
        "contract_name",
        "receiver_types",
        "receiver_type",
        "receiver_binding",
        "implementation_identity",
        "wrapper_implementation_identity",
        "assembly_identity",
        "assembly_revision",
        "evidence_kind",
        "source_backed",
        "verified",
        "reflection_only",
    ):
        if key not in candidate and key in context:
            candidate[key] = copy.deepcopy(context[key])
    snapshot = candidate.get("implementation_snapshot")
    if isinstance(snapshot, Mapping):
        binding = candidate.get("receiver_binding")
        receiver_types = candidate.get("receiver_types")
        if not receiver_types:
            receiver = _binding_value(
                binding if isinstance(binding, Mapping) else {},
                "implementation_identity",
                "concrete_implementation",
                "type_identity",
            )
            receiver = receiver or _binding_value(
                candidate,
                "implementation_identity",
                "wrapper_implementation_identity",
                "receiver_type",
                "wrapper_receiver_type",
            )
            if receiver:
                candidate["receiver_types"] = [receiver]
        name = str(
            candidate.get("name")
            or candidate.get("contract_name")
            or snapshot.get("contract_name")
            or snapshot.get("behavior_surface_unit")
            or snapshot.get("assembly_identity")
            or "contract"
        ).strip()
        candidate["name"] = _slug(name)
    return candidate


def _iter_scan_proposals(scans: Any) -> list[dict[str, Any]]:
    proposals: list[dict[str, Any]] = []
    for scan in scans or ():
        for attribute in (
            "contract_preflight_proposals",
            "contract_proposals",
            "wrapper_contract_proposals",
            "verified_implementation_snapshots",
            "implementation_snapshots",
        ):
            for item in _as_mappings(getattr(scan, attribute, None)):
                if attribute.endswith("snapshots"):
                    item = {"implementation_snapshot": dict(item)}
                proposals.append(_proposal_with_context(item))
        raw_by_file = getattr(scan, "db_invocations", {}) or {}
        if not isinstance(raw_by_file, Mapping):
            continue
        for records in raw_by_file.values():
            for raw in records or ():
                if not isinstance(raw, Mapping):
                    continue
                for key in _PROPOSAL_KEYS:
                    for item in _as_mappings(raw.get(key)):
                        proposals.append(_proposal_with_context(item, raw))
                for key in _SNAPSHOT_KEYS:
                    snapshot = raw.get(key)
                    if isinstance(snapshot, Mapping):
                        proposals.append(
                            _proposal_with_context(
                                {"implementation_snapshot": snapshot},
                                raw,
                            )
                        )
    return proposals


def _proposal_binding_key(proposal: Mapping[str, Any]) -> str:
    snapshot = proposal.get("implementation_snapshot")
    if isinstance(snapshot, Mapping):
        values = (
            snapshot.get("assembly_identity"),
            snapshot.get("assembly_revision"),
            snapshot.get("behavior_surface_unit"),
        )
        identity = "|".join(str(value or "").strip().casefold() for value in values)
        if identity.strip("|"):
            return identity
    return _binding_value(
        proposal,
        "implementation_identity",
        "wrapper_implementation_identity",
        "receiver_type",
        "wrapper_receiver_type",
    ).casefold()


def _has_external_wrapper(scans: Any) -> bool:
    for scan in scans or ():
        raw_by_file = getattr(scan, "db_invocations", {}) or {}
        if not isinstance(raw_by_file, Mapping):
            continue
        for records in raw_by_file.values():
            for raw in records or ():
                if not isinstance(raw, Mapping):
                    continue
                if str(raw.get("invocation_kind") or "").casefold() != "source_wrapper":
                    continue
                if raw.get("wrapper_source_available") is not True:
                    return True
    return False


def _review_candidate(
    proposal: Mapping[str, Any],
    reasons: list[str],
) -> dict[str, Any]:
    snapshot = proposal.get("implementation_snapshot")
    snapshot_identity = ""
    if isinstance(snapshot, Mapping):
        snapshot_identity = str(
            snapshot.get("snapshot_identity")
            or snapshot.get("artifact_identity")
            or ""
        ).strip()
    return {
        "status": "review",
        "contract_name": str(proposal.get("name") or ""),
        "receiver_types": list(proposal.get("receiver_types") or ()),
        "implementation_identity": _binding_value(
            proposal,
            "implementation_identity",
            "wrapper_implementation_identity",
            "receiver_type",
            "wrapper_receiver_type",
        ),
        "snapshot_identity": snapshot_identity,
        "unresolved_reasons": list(dict.fromkeys(reasons)),
    }


def _stage_complete_proposals(
    registry: Mapping[str, Any],
    proposals: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    staged = _registry_payload(registry)
    entries = _registry_entries(staged)
    complete: list[dict[str, Any]] = []
    review: list[dict[str, Any]] = []
    for proposal in proposals:
        if proposal.get("reflection_only") is True or proposal.get("verified") is False:
            review.append(_review_candidate(proposal, ["implementation_evidence_unverified"]))
            continue
        try:
            entry, report = versioned_contract_from_proposal(proposal)
        except ContractSnapshotError as exc:
            review.append(_review_candidate(proposal, list(exc.reasons)))
            continue
        complete.append(
            {
                "proposal": proposal,
                "entry": entry,
                "report": report,
                "contract_fingerprint": report["contract_fingerprint"],
                "binding_key": _proposal_binding_key(proposal),
            }
        )

    binding_fingerprints: dict[str, set[str]] = {}
    for item in complete:
        if item["binding_key"]:
            binding_fingerprints.setdefault(item["binding_key"], set()).add(
                item["contract_fingerprint"]
            )
    conflicting = {
        fingerprint
        for fingerprints in binding_fingerprints.values()
        if len(fingerprints) > 1
        for fingerprint in fingerprints
    }
    if conflicting:
        retained: list[dict[str, Any]] = []
        for item in complete:
            if item["contract_fingerprint"] in conflicting:
                review.append(
                    _review_candidate(
                        item["proposal"],
                        ["conflicting_behavior_surface"],
                    )
                )
            else:
                retained.append(item)
        complete = retained

    existing_by_fingerprint = {
        str(contract.get("contract_fingerprint")): name
        for name, contract in entries.items()
        if isinstance(contract, Mapping)
        and contract.get("contract_fingerprint")
        and isinstance(contract.get("behavior_signature"), Mapping)
    }
    staged_names: dict[str, dict[str, Any]] = {}
    for item in sorted(
        complete,
        key=lambda value: (
            str(value["contract_fingerprint"]),
            str(value["proposal"].get("name") or "").casefold(),
        ),
    ):
        fingerprint = str(item["contract_fingerprint"])
        existing_name = existing_by_fingerprint.get(fingerprint)
        if existing_name:
            name = existing_name
            lifecycle = "reused"
        else:
            base_name = str(item["proposal"].get("name") or "contract").strip() or "contract"
            taken_name = taken_contract_name(entries, staged_names, base_name)
            if taken_name is None:
                name = base_name
            else:
                name = unused_revision_name(
                    entries,
                    staged_names,
                    taken_name,
                    fingerprint,
                )
            staged_names[name] = copy.deepcopy(item["entry"])
            lifecycle = "created"
        item["contract_name"] = name
        item["lifecycle_status"] = lifecycle
        item["comparison_report_reference"] = item["report"].get(
            "comparison_report_reference", ""
        )
    entries.update(staged_names)
    staged["contracts"] = entries
    unique_complete: dict[str, dict[str, Any]] = {}
    for item in complete:
        unique_complete.setdefault(str(item["contract_name"]), item)
    return staged, list(unique_complete.values()), review


def run_contract_preflight(
    scans: Any,
    *,
    selector: Any = None,
    registry: Mapping[str, Any] | None = None,
    allow_onboarding: bool = True,
) -> ContractPreflightResult:
    """Build the staged contract view from one already-completed raw scan."""
    active_registry = _registry_payload(
        load_contract_registry() if registry is None else registry
    )
    normalized = normalize_contract_selector(selector, active_registry)
    if normalized.status == "valid":
        formal_selector: SelectorValue = (
            normalized.candidates[0]
            if len(normalized.candidates) == 1
            else normalized.candidates
        )
        return ContractPreflightResult(
            selector=normalized,
            onboarding_status="selected",
            formal_selector=formal_selector,
            staged_selector=formal_selector,
            formal_registry=active_registry,
            staged_registry=active_registry,
        )

    if not allow_onboarding:
        reason = "program_scope_requires_valid_selector"
        return ContractPreflightResult(
            selector=normalized,
            onboarding_status="preflight_failed",
            staged_selector=normalized.original,
            formal_registry={"contracts": {}},
            staged_registry=active_registry,
            reason=reason,
            review_candidates=({"status": "review", "unresolved_reasons": [reason]},),
        )

    proposals = _iter_scan_proposals(scans)
    staged_registry, complete, review = _stage_complete_proposals(
        active_registry,
        proposals,
    )
    if not complete:
        if normalized.reason or _has_external_wrapper(scans):
            review.append(
                {
                    "status": "review",
                    "unresolved_reasons": ["implementation_evidence_missing"],
                }
            )
            reason = "contract_preflight_failed"
            onboarding_status = "preflight_failed"
        else:
            reason = ""
            onboarding_status = "not_required"
        return ContractPreflightResult(
            selector=normalized,
            onboarding_status=onboarding_status,
            staged_selector=(
                normalized.original if normalized.reason else None
            ),
            formal_registry={"contracts": {}},
            staged_registry=active_registry,
            reason=reason,
            proposals=tuple(),
            review_candidates=tuple(review),
        )

    names = sorted(
        {str(item["contract_name"]) for item in complete if item.get("contract_name")},
        key=str.casefold,
    )
    formal_selector = names[0] if len(names) == 1 else tuple(names)
    lifecycle_statuses = {str(item.get("lifecycle_status") or "") for item in complete}
    onboarding_status = "created" if "created" in lifecycle_statuses else "reused"
    if review:
        onboarding_status = "conflicted"
    proposal_reports = []
    for item in complete:
        proposal = dict(item["proposal"])
        proposal.update(
            {
                "contract_name": item["contract_name"],
                "contract_fingerprint": item["contract_fingerprint"],
                "comparison_report_reference": item["comparison_report_reference"],
                "lifecycle_status": item["lifecycle_status"],
            }
        )
        proposal_reports.append(proposal)
    return ContractPreflightResult(
        selector=normalized,
        onboarding_status=onboarding_status,
        formal_selector=formal_selector,
        staged_selector=formal_selector,
        formal_registry=staged_registry,
        staged_registry=staged_registry,
        reason="contract_preflight_review" if review else "",
        proposals=tuple(proposal_reports),
        review_candidates=tuple(review),
    )


contract_preflight = run_contract_preflight


__all__ = [
    "ContractPreflightResult",
    "ContractSelector",
    "DEFAULT_CATALOG_PATH",
    "DEFAULT_REGISTRY_PATH",
    "contract_preflight",
    "load_contract_registry",
    "load_system_contract_selector",
    "normalize_contract_selector",
    "run_contract_preflight",
]
