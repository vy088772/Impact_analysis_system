"""Refresh-time onboarding for referenced external wrapper assemblies."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from code_analyzer.project_scanner import ProjectScanResult
from code_analyzer.static_analyzer_host import StaticAnalyzerHostError
from service import analyze_service

STC_CSPROJ = PROJECT_ROOT / "data" / "repos" / "System_Dept_1" / "STC" / "STC" / "STC.csproj"
SQLFUNC_DLL = STC_CSPROJ.parent / "bin" / "SQLFunc.dll"
requires_stc_fixture = pytest.mark.skipif(
    not (STC_CSPROJ.exists() and SQLFUNC_DLL.exists()),
    reason="local data/repos/System_Dept_1/STC fixture checkout is not present",
)


def _proposal() -> dict:
    return {
        "name": "SQLFunc",
        "receiver_types": ["SQLFunc"],
        "implementation_snapshot": {
            "artifact_identity": "SQLFunc.dll@sha256:fixture",
            "assembly_identity": "fixture",
            "assembly_revision": "fixture",
            "behavior_surface_unit": "SQLFunc",
            "complete": True,
            "methods": [
                {
                    "method_identity": "SQLFunc.ExeProcRead(string)",
                    "method_name": "ExeProcRead",
                    "method_arity": 1,
                    "parameter_types": ["string"],
                    "argument_roles": {"command_text": 0},
                    "effective_command_semantics": "stored_procedure",
                    "terminal_sink": "ExecuteReader",
                    "connection_behavior_boundary": "constructor_connection",
                    "branch_rules": [
                        {"mode": "stored_procedure", "sink": "ExecuteReader"}
                    ],
                    "assembly_revision": "fixture",
                    "body_complete": True,
                }
            ],
            "helper_operations_complete": True,
            "inherited_operations_complete": True,
        },
    }


def _scan(root: Path, *, source_available: bool = False) -> ProjectScanResult:
    source_file = root / "OrderPage.cs"
    return ProjectScanResult(
        project_root=str(root),
        project_name=root.name,
        scan_time=datetime.now(),
        db_invocations={
            str(source_file): [
                {
                    "invocation_kind": "source_wrapper",
                    "class_name": "OrderPage",
                    "method_name": "Save",
                    "wrapper_method_name": "ExeProcRead",
                    "wrapper_receiver_type": "SQLFunc",
                    "wrapper_source_available": source_available,
                    "wrapper_method_arity": 1,
                    "wrapper_parameter_types": ["string"],
                    "wrapper_mode": "stored_procedure",
                    "command_text_kind": "literal",
                    "command_text": "usp_Save",
                    "connection_expression": "conn",
                    "start_offset": 1,
                    "end_offset": 20,
                }
            ]
        },
    )


def _write_referencing_project(root: Path) -> Path:
    (root / "bin").mkdir(parents=True, exist_ok=True)
    (root / "bin" / "SQLFunc.dll").write_bytes(b"fixture")
    csproj = root / "Orders.csproj"
    csproj.write_text(
        "<Project xmlns=\"http://schemas.microsoft.com/developer/msbuild/2003\">"
        "<ItemGroup>"
        "<Reference Include=\"SQLFunc, Version=1.0.0.0\">"
        "<HintPath>bin\\SQLFunc.dll</HintPath>"
        "</Reference>"
        "</ItemGroup>"
        "</Project>",
        encoding="utf-8",
    )
    return csproj


def _patch_refresh(monkeypatch, root: Path, scan: ProjectScanResult) -> None:
    monkeypatch.setattr(
        analyze_service,
        "resolve_scan_roots",
        lambda source, refresh=False: [root],
    )
    monkeypatch.setattr(
        analyze_service,
        "get_or_scan",
        lambda scan_root, refresh=False: scan,
    )
    monkeypatch.setattr(
        analyze_service,
        "load_contract_registry",
        lambda: {"contracts": {}},
    )


def _patch_host(
    monkeypatch,
    responses: list[dict],
    calls: list[tuple[Path, str]],
    rerun_calls: list[bool] | None = None,
) -> None:
    class FakeHost:
        @classmethod
        def for_project(cls, project_root: Path) -> "FakeHost":
            return cls()

        def ensure_ready(self) -> dict:
            return {"contract_version": 2}

        def decompile_wrapper(
            self, csproj_path: Path, receiver_type: str, *, rerun: bool = False
        ) -> dict:
            calls.append((Path(csproj_path), receiver_type))
            if rerun_calls is not None:
                rerun_calls.append(rerun)
            return responses[len(calls) - 1]

    monkeypatch.setattr(analyze_service, "StaticAnalyzerHost", FakeHost, raising=False)


def _response(*, outcome: str = "complete", cached: bool = False, proposal: bool = True) -> dict:
    return {
        "status": "resolved" if outcome == "complete" else "decompile_failed",
        "attempt_outcome": outcome,
        "cache_status": "hit" if cached else "miss",
        "detail": "invalid IL" if outcome == "incomplete" else None,
        "decompilation_attempt": {
            "attempted": not cached,
            "outcome": outcome,
            "cache_status": "hit" if cached else "miss",
        },
        "contract_proposals": [_proposal()] if proposal else [],
        "translation_problem_methods": ["Broken"] if outcome == "incomplete" else [],
        "wrapper_definitions": [] if outcome == "incomplete" else [{"unresolved_reason": None}],
    }


def test_full_refresh_decompiles_and_commits_complete_proposal(monkeypatch, tmp_path) -> None:
    root = tmp_path / "Orders"
    root.mkdir()
    csproj = _write_referencing_project(root)
    scan = _scan(root)
    calls: list[tuple[Path, str]] = []
    _patch_refresh(monkeypatch, root, scan)
    _patch_host(monkeypatch, [_response()], calls)

    registry_path = tmp_path / "external_wrapper_contracts.json"
    catalog_path = tmp_path / "system_catalog.json"
    registry_path.write_text(json.dumps({"contracts": {}}), encoding="utf-8")
    catalog_path.write_text(
        json.dumps({"systems": [{"system_id": "Orders", "wrapper_contract": ""}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(analyze_service, "cached_commit", lambda scan_root: "deadbeef")
    monkeypatch.setattr(analyze_service, "CONTRACT_TRANSACTION_REGISTRY_PATH", registry_path)
    monkeypatch.setattr(analyze_service, "CONTRACT_TRANSACTION_CATALOG_PATH", catalog_path)

    result = analyze_service.refresh_source(
        {"project": "p", "repo": "r"},
        database="Orders",
    )

    assert calls == [(csproj, "SQLFunc")]
    assert result["contract_transaction"]["status"] == "committed"
    assert json.loads(catalog_path.read_text(encoding="utf-8"))["systems"][0][
        "wrapper_contract"
    ] == "sqlfunc"
    decompilation = result["wrapper_summary"]["decompilation"]
    assert decompilation["attempted"] is True
    assert decompilation["outcome"] == "complete"
    assert decompilation["attempts"][0]["receiver_type"] == "SQLFunc"
    assert decompilation["attempts"][0]["reasons"] == []
    assert result["wrapper_summary"]["observations"][0]["status"] == "explicit_selected"
    entry = result["wrapper_summary"]["contract_preflight"]["staged_registry"][
        "contracts"
    ]["sqlfunc"]
    assert entry["evidence_kind"] == "decompiled_auto"
    assert result["wrapper_summary"]["observations"][0]["evidence_kind"] == (
        "decompiled_auto"
    )


def test_cached_decompilation_is_reported_as_cached_skip(monkeypatch, tmp_path) -> None:
    root = tmp_path / "Orders"
    root.mkdir()
    _write_referencing_project(root)
    scan = _scan(root)
    calls: list[tuple[Path, str]] = []
    _patch_refresh(monkeypatch, root, scan)
    _patch_host(monkeypatch, [_response(cached=True)], calls)

    result = analyze_service.refresh_source({"project": "p", "repo": "r"})

    assert calls == [(root / "Orders.csproj", "SQLFunc")]
    decompilation = result["wrapper_summary"]["decompilation"]
    assert decompilation["attempted"] is False
    assert decompilation["outcome"] == "cached-skip"
    assert decompilation["attempts"][0]["attempt_outcome"] == "complete"
    assert result["wrapper_summary"]["contract_onboarding_status"] == "created"


@requires_stc_fixture
def test_real_sqlfunc_fixture_flows_through_full_refresh_orchestration(monkeypatch) -> None:
    scan = _scan(STC_CSPROJ.parent)
    _patch_refresh(monkeypatch, STC_CSPROJ.parent, scan)

    result = analyze_service.refresh_source({"project": "p", "repo": "r"})

    attempt = result["wrapper_summary"]["decompilation"]["attempts"][0]
    assert attempt["receiver_type"] == "SQLFunc"
    assert attempt["attempt_outcome"] == "complete"
    assert attempt["outcome"] in {"complete", "cached-skip"}
    assert result["wrapper_summary"]["contract_onboarding_status"] == "created"
    assert result["wrapper_summary"]["observations"][0]["status"] == "explicit_selected"


def test_incomplete_decompilation_uses_existing_preflight_failure(monkeypatch, tmp_path) -> None:
    root = tmp_path / "Orders"
    root.mkdir()
    _write_referencing_project(root)
    scan = _scan(root)
    calls: list[tuple[Path, str]] = []
    _patch_refresh(monkeypatch, root, scan)
    _patch_host(monkeypatch, [_response(outcome="incomplete", proposal=False)], calls)

    result = analyze_service.refresh_source({"project": "p", "repo": "r"})

    assert len(calls) == 1
    assert result["wrapper_summary"]["contract_onboarding_status"] == "preflight_failed"
    observation = result["wrapper_summary"]["observations"][0]
    assert observation["status"] == "unresolved_contract"
    assert observation["contract_preflight_reason"] == "contract_preflight_failed"
    decompilation = result["wrapper_summary"]["decompilation"]
    assert decompilation["outcome"] == "incomplete"
    assert "decompiler_translation_problem" in decompilation["attempts"][0]["reasons"]


def test_program_refresh_never_triggers_decompilation(monkeypatch, tmp_path) -> None:
    root = tmp_path / "Orders"
    root.mkdir()
    _write_referencing_project(root)
    scan = _scan(root)
    calls: list[tuple[Path, str]] = []
    _patch_refresh(monkeypatch, root, scan)
    _patch_host(monkeypatch, [_response()], calls)
    monkeypatch.setattr(analyze_service, "cache_status", lambda scan_root: "current")
    monkeypatch.setattr(
        analyze_service,
        "refresh_programs",
        lambda scan_root, names: analyze_service.ProgramRefreshResult(
            scan=scan,
            matched_programs=list(names),
        ),
    )

    result = analyze_service.refresh_source(
        {"project": "p", "repo": "r"},
        program_names=["OrderPage"],
    )

    assert calls == []
    assert result["wrapper_summary"]["decompilation"]["attempted"] is False


def test_valid_selector_never_triggers_decompilation(monkeypatch, tmp_path) -> None:
    root = tmp_path / "Orders"
    root.mkdir()
    _write_referencing_project(root)
    scan = _scan(root)
    calls: list[tuple[Path, str]] = []
    _patch_refresh(monkeypatch, root, scan)
    _patch_host(monkeypatch, [_response()], calls)
    monkeypatch.setattr(
        analyze_service,
        "load_contract_registry",
        lambda: {"contracts": {"sqlfunc": {}}},
    )

    result = analyze_service.refresh_source(
        {"project": "p", "repo": "r"},
        wrapper_contract="sqlfunc",
    )

    assert calls == []
    assert result["wrapper_summary"]["decompilation"]["attempted"] is False
    assert result["wrapper_summary"]["observations"][0]["selection_source"] == "explicit"


def test_registry_receiver_name_collision_with_different_fingerprint_still_decompiles(
    monkeypatch, tmp_path
) -> None:
    """A registry contract already exists for receiver type ``SQLFunc``, but its
    Contract Fingerprint differs from what the mocked decompiler will return for
    this system. Receiver-type name is never grounds to skip decompile-based
    Contract Onboarding -- only Contract Fingerprint comparison decides reuse
    vs. creation -- so the attempt must still be made, and since the
    fingerprints disagree, a new fingerprint-suffixed contract is created
    rather than reusing the name-colliding one."""

    root = tmp_path / "Orders"
    root.mkdir()
    csproj = _write_referencing_project(root)
    scan = _scan(root)
    calls: list[tuple[Path, str]] = []
    _patch_refresh(monkeypatch, root, scan)
    _patch_host(monkeypatch, [_response()], calls)

    registry_path = tmp_path / "external_wrapper_contracts.json"
    catalog_path = tmp_path / "system_catalog.json"
    registry_path.write_text(
        json.dumps(
            {
                "contracts": {
                    "sqlfunc": {
                        "receiver_types": ["SQLFunc"],
                        "contract_fingerprint": "0" * 64,
                        "behavior_signature": {
                            "signature_version": "v1",
                            "operations": [],
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    catalog_path.write_text(
        json.dumps({"systems": [{"system_id": "Orders", "wrapper_contract": ""}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(analyze_service, "cached_commit", lambda scan_root: "deadbeef")
    monkeypatch.setattr(analyze_service, "CONTRACT_TRANSACTION_REGISTRY_PATH", registry_path)
    monkeypatch.setattr(analyze_service, "CONTRACT_TRANSACTION_CATALOG_PATH", catalog_path)
    monkeypatch.setattr(
        analyze_service,
        "load_contract_registry",
        lambda: json.loads(registry_path.read_text(encoding="utf-8")),
    )

    result = analyze_service.refresh_source(
        {"project": "p", "repo": "r"},
        database="Orders",
    )

    assert calls == [(csproj, "SQLFunc")]
    decompilation = result["wrapper_summary"]["decompilation"]
    assert decompilation["attempted"] is True
    assert decompilation["outcome"] == "complete"
    assert "active_contract_evidence" not in decompilation["reasons"]

    assert result["wrapper_summary"]["contract_onboarding_status"] == "created"
    assert result["contract_transaction"]["status"] == "committed"

    committed_name = json.loads(catalog_path.read_text(encoding="utf-8"))["systems"][0][
        "wrapper_contract"
    ]
    assert committed_name != "sqlfunc"
    assert committed_name.startswith("sqlfunc-")

    staged_contracts = result["wrapper_summary"]["contract_preflight"]["staged_registry"][
        "contracts"
    ]
    assert "sqlfunc" in staged_contracts
    assert committed_name in staged_contracts


def test_source_backed_receiver_in_one_root_blocks_other_root_decompilation(
    monkeypatch,
    tmp_path,
) -> None:
    source_root = tmp_path / "Source"
    external_root = tmp_path / "External"
    source_root.mkdir()
    external_root.mkdir()
    _write_referencing_project(external_root)
    source_scan = _scan(source_root, source_available=True)
    external_scan = _scan(external_root)
    calls: list[tuple[Path, str]] = []
    monkeypatch.setattr(
        analyze_service,
        "resolve_scan_roots",
        lambda source, refresh=False: [source_root, external_root],
    )
    scans = {source_root: source_scan, external_root: external_scan}
    monkeypatch.setattr(
        analyze_service,
        "get_or_scan",
        lambda scan_root, refresh=False: scans[scan_root],
    )
    monkeypatch.setattr(
        analyze_service,
        "load_contract_registry",
        lambda: {"contracts": {}},
    )
    _patch_host(monkeypatch, [_response()], calls)

    result = analyze_service.refresh_source({"project": "p", "repo": "r"})

    assert calls == []
    assert result["wrapper_summary"]["decompilation"]["attempted"] is False
    assert "source_backed_evidence" in result["wrapper_summary"]["decompilation"]["reasons"]


def test_rerun_trigger_forwards_through_refresh_source_and_bypasses_cached_failure(
    monkeypatch, tmp_path
) -> None:
    """A stale cached failure survives an ordinary refresh, but is bypassed
    (and a fresh attempt made) once the maintainer names that receiver type
    in ``rerun_receiver_types`` on a later refresh — mirroring how the real
    StaticAnalyzerHost's ``--rerun`` flag behaves against its on-disk cache
    (see ``StaticAnalyzerHost.decompile_wrapper``)."""

    root = tmp_path / "Orders"
    root.mkdir()
    _write_referencing_project(root)
    scan = _scan(root)
    calls: list[tuple[Path, str, bool]] = []
    cached_failure = _response(outcome="incomplete", cached=True, proposal=False)
    fresh_success = _response(outcome="complete", cached=False)

    class StatefulFakeHost:
        @classmethod
        def for_project(cls, project_root: Path) -> "StatefulFakeHost":
            return cls()

        def ensure_ready(self) -> dict:
            return {"contract_version": 2}

        def decompile_wrapper(
            self, csproj_path: Path, receiver_type: str, *, rerun: bool = False
        ) -> dict:
            calls.append((Path(csproj_path), receiver_type, rerun))
            return fresh_success if rerun else cached_failure

    _patch_refresh(monkeypatch, root, scan)
    monkeypatch.setattr(analyze_service, "StaticAnalyzerHost", StatefulFakeHost, raising=False)

    stale_result = analyze_service.refresh_source({"project": "p", "repo": "r"})
    fresh_result = analyze_service.refresh_source(
        {"project": "p", "repo": "r"},
        rerun_receiver_types=["SQLFunc"],
    )

    assert calls == [
        (root / "Orders.csproj", "SQLFunc", False),
        (root / "Orders.csproj", "SQLFunc", True),
    ]
    stale_attempt = stale_result["wrapper_summary"]["decompilation"]["attempts"][0]
    fresh_attempt = fresh_result["wrapper_summary"]["decompilation"]["attempts"][0]
    # Without a rerun request, the cached incomplete attempt is reported as a
    # cache hit ("cached-skip"), preserving the underlying "incomplete" verdict
    # in attempt_outcome; the rerun request instead forces a fresh "complete"
    # attempt that misses the cache entirely.
    assert stale_attempt["attempt_outcome"] == "incomplete"
    assert stale_attempt["outcome"] == "cached-skip"
    assert stale_attempt["cache_status"] == "hit"
    assert fresh_attempt["attempt_outcome"] == "complete"
    assert fresh_attempt["outcome"] == "complete"
    assert fresh_attempt["cache_status"] == "miss"


def test_unnamed_receiver_type_does_not_trigger_rerun(monkeypatch, tmp_path) -> None:
    root = tmp_path / "Orders"
    root.mkdir()
    _write_referencing_project(root)
    scan = _scan(root)
    calls: list[tuple[Path, str]] = []
    rerun_calls: list[bool] = []
    _patch_refresh(monkeypatch, root, scan)
    _patch_host(monkeypatch, [_response(cached=True)], calls, rerun_calls)

    analyze_service.refresh_source(
        {"project": "p", "repo": "r"},
        rerun_receiver_types=["SomeOtherReceiver"],
    )

    assert rerun_calls == [False]


def test_csproj_lookup_failure_reason_differs_from_receiver_not_referenced(
    monkeypatch, tmp_path
) -> None:
    # No .csproj exists anywhere under root: _find_source_csproj cannot locate
    # one, so the host is never reached.
    no_csproj_root = tmp_path / "NoCsproj"
    no_csproj_root.mkdir()
    calls_without_csproj: list[tuple[Path, str]] = []
    _patch_refresh(monkeypatch, no_csproj_root, _scan(no_csproj_root))
    _patch_host(monkeypatch, [], calls_without_csproj)

    result_without_csproj = analyze_service.refresh_source({"project": "p", "repo": "r"})

    assert calls_without_csproj == []
    lookup_failure_reasons = result_without_csproj["wrapper_summary"]["decompilation"][
        "attempts"
    ][0]["reasons"]
    assert lookup_failure_reasons == ["csproj_not_found"]

    # A .csproj IS found this time, but the host itself reports the distinct
    # "receiver_not_referenced" status (a .csproj exists with no matching
    # <Reference> entry for the receiver).
    referenced_root = tmp_path / "Referenced"
    referenced_root.mkdir()
    _write_referencing_project(referenced_root)
    calls_with_csproj: list[tuple[Path, str]] = []
    _patch_refresh(monkeypatch, referenced_root, _scan(referenced_root))
    _patch_host(
        monkeypatch,
        [
            {
                "status": "receiver_not_referenced",
                "attempt_outcome": "not_attempted",
                "cache_status": "not_applicable",
                "decompilation_attempt": {
                    "attempted": False,
                    "outcome": "not_attempted",
                    "cache_status": "not_applicable",
                },
                "contract_proposals": [],
                "translation_problem_methods": [],
                "wrapper_definitions": [],
            }
        ],
        calls_with_csproj,
    )

    result_with_csproj = analyze_service.refresh_source({"project": "p", "repo": "r"})

    assert len(calls_with_csproj) == 1
    referenced_reasons = result_with_csproj["wrapper_summary"]["decompilation"]["attempts"][
        0
    ]["reasons"]
    assert referenced_reasons == ["receiver_not_referenced"]
    assert referenced_reasons != lookup_failure_reasons


def test_source_backed_wrapper_is_stronger_than_decompile_candidate(monkeypatch, tmp_path) -> None:
    root = tmp_path / "Orders"
    root.mkdir()
    _write_referencing_project(root)
    scan = _scan(root, source_available=True)
    calls: list[tuple[Path, str]] = []
    _patch_refresh(monkeypatch, root, scan)
    _patch_host(monkeypatch, [_response()], calls)

    result = analyze_service.refresh_source({"project": "p", "repo": "r"})

    assert calls == []
    assert result["wrapper_summary"]["decompilation"]["attempted"] is False
    assert result["wrapper_summary"]["contract_onboarding_status"] == "not_required"


def test_decompiler_host_unavailable_skips_with_reason(monkeypatch, tmp_path) -> None:
    root = tmp_path / "Orders"
    root.mkdir()
    _write_referencing_project(root)
    scan = _scan(root)
    _patch_refresh(monkeypatch, root, scan)

    class UnavailableHost:
        @classmethod
        def for_project(cls, project_root: Path) -> "UnavailableHost":
            return cls()

        def ensure_ready(self) -> dict:
            raise StaticAnalyzerHostError("decompiler binary not found")

    monkeypatch.setattr(analyze_service, "StaticAnalyzerHost", UnavailableHost, raising=False)

    result = analyze_service.refresh_source({"project": "p", "repo": "r"})

    decompilation = result["wrapper_summary"]["decompilation"]
    assert decompilation["attempts"][0]["attempted"] is False
    assert decompilation["attempts"][0]["outcome"] == "incomplete"
    assert "decompiler_host_unavailable" in decompilation["attempts"][0]["reasons"]


def test_decompiler_failed_skips_with_reason(monkeypatch, tmp_path) -> None:
    root = tmp_path / "Orders"
    root.mkdir()
    _write_referencing_project(root)
    scan = _scan(root)
    _patch_refresh(monkeypatch, root, scan)

    class FailingHost:
        @classmethod
        def for_project(cls, project_root: Path) -> "FailingHost":
            return cls()

        def ensure_ready(self) -> dict:
            return {"contract_version": 2}

        def decompile_wrapper(
            self, csproj_path: Path, receiver_type: str, *, rerun: bool = False
        ) -> dict:
            raise StaticAnalyzerHostError("decompilation crashed")

    monkeypatch.setattr(analyze_service, "StaticAnalyzerHost", FailingHost, raising=False)

    result = analyze_service.refresh_source({"project": "p", "repo": "r"})

    decompilation = result["wrapper_summary"]["decompilation"]
    assert decompilation["attempts"][0]["attempted"] is True
    assert decompilation["attempts"][0]["outcome"] == "incomplete"
    assert "decompiler_failed" in decompilation["attempts"][0]["reasons"]