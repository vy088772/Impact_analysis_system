"""Ticket 08 of `.scratch/inherited-web-config-connections/`: find_by_sp() returns
each `likely` caller in `likely_matches`.

Seam B of the spec: the `find_by_sp` service function. Prior art for the
fixtures and the wiring: tests/test_derived_execution_evidence_reuse.py.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from code_analyzer.csharp_analysis_gateway import DbInvocation, InvocationEvidence, InvocationSourceSpan
from code_analyzer.models import ClassInfo, FileAnalysisResult, FileType, FrameworkType, MethodInfo
from code_analyzer.project_scanner import ProjectScanResult
from service import analyze_service
from service.api import app
from service.schemas import FindBySPRequest
from tests.derived_execution_evidence_fixtures import RatedInvocationsRetention
from tests.sql_cache_fixtures import (
    cache_payload,
    execution_graph,
    one_server_holds_every_database,
)

_PROGRAMS = (
    ("ProvenPage.cs", "ProvenPage", "SaveProven"),
    ("LikelyPage.cs", "LikelyPage", "SaveLikely"),
)


def _graph() -> dict:
    return execution_graph(
        "OrdersDb",
        nodes=[
            {
                "id": "stored_procedure:dbo.usp_Shared",
                "type": "stored_procedure",
                "schema": "dbo",
                "name": "usp_Shared",
            }
        ],
    )


def _file(root: Path, name: str, class_name: str, method_name: str) -> FileAnalysisResult:
    path = root / name
    return FileAnalysisResult(
        file_path=str(path),
        file_type=FileType.CSHARP,
        framework=FrameworkType.WEBFORMS,
        classes=[
            ClassInfo(
                name=class_name,
                namespace="",
                file_path=str(path),
                methods=[MethodInfo(name=method_name, access_modifier="private", return_type="void")],
            )
        ],
    )


def _scan(root: Path) -> ProjectScanResult:
    """Two programs call `dbo.usp_Shared`. Only ProvenPage has a connection source."""
    return ProjectScanResult(
        project_root=str(root),
        project_name="orders",
        scan_time=datetime.now(),
        csharp_results=[_file(root, *program) for program in _PROGRAMS],
        db_invocations={
            str((root / name).resolve()): [
                {
                    "class_name": class_name,
                    "method_name": method_name,
                    "command_text_kind": "literal",
                    "command_text": "dbo.usp_Shared",
                    "command_type_stored_procedure": True,
                    "terminal_sink": "ExecuteNonQuery",
                    "connection_expression": "conn",
                    "start_offset": 10,
                    "end_offset": 90,
                }
            ]
            for name, class_name, method_name in _PROGRAMS
        },
        connection_sources={str((root / "ProvenPage.cs").resolve()): {"conn": "OrdersDb"}},
    )


def _wire(monkeypatch, scan: ProjectScanResult, tmp_path: Path) -> None:
    sql_payload = cache_payload("OrdersDb", graph=_graph())
    monkeypatch.setattr(analyze_service, "resolve_scan_roots", lambda source, refresh=False: [tmp_path])
    monkeypatch.setattr(analyze_service, "_get_scan", lambda root, refresh=False: scan)
    monkeypatch.setattr(analyze_service, "cached_saved_at", lambda root: "scan-v1")
    monkeypatch.setattr(analyze_service, "cached_commit", lambda root: "commit-v1")
    monkeypatch.setattr(analyze_service.sql_cache_store, "find_cache_identity", one_server_holds_every_database)
    monkeypatch.setattr(analyze_service.sql_cache_store, "load_cached", lambda identity: sql_payload)
    monkeypatch.setattr(analyze_service.sql_cache_store, "cached_saved_at", lambda identity: "sql-cache-v1")


def _request() -> FindBySPRequest:
    return FindBySPRequest(
        source={"project": "orders", "repo": "orders"},
        sp_name="dbo.usp_Shared",
        database="OrdersDb",
        cache_only=False,
    )


def test_a_likely_caller_goes_into_likely_matches_beside_a_proven_caller(monkeypatch, tmp_path: Path) -> None:
    with RatedInvocationsRetention():
        _wire(monkeypatch, _scan(tmp_path), tmp_path)

        response = analyze_service.find_by_sp(_request())

    assert [(match.program, match.file, match.evidence_status) for match in response.matches] == [
        ("provenpage", "ProvenPage.cs", "proven")
    ]
    assert [
        (match.program, match.file, match.evidence_status, match.reason) for match in response.likely_matches
    ] == [("likelypage", "LikelyPage.cs", "likely", "unique_across_catalogs")]
    likely = response.likely_matches[0]
    # The gateway gives a `likely` call the procedure name as the SP Catalog keys it.
    assert likely.procedure_name.casefold() == "usp_shared"
    assert likely.caller == "LikelyPage.SaveLikely"
    assert set(type(likely).model_fields) == set(type(response.matches[0]).model_fields)

    # `diagnostics` stays as it was: the one call that is not proven, and no other.
    assert len(response.diagnostics) == 1
    diagnostic = response.diagnostics[0]
    assert diagnostic["diagnostic"] is True
    assert diagnostic["evidence"] == "likely"
    assert diagnostic["reason"] == "unique_across_catalogs"
    assert diagnostic["caller"] == "LikelyPage.SaveLikely"
    assert diagnostic["requested_sp"] == "dbo.usp_Shared"
    assert diagnostic["source_span"]["relative_path"] == "LikelyPage.cs"


def _rate_as(monkeypatch, *invocations: DbInvocation) -> None:
    """Replace the rating step, so a test can give a call the scan cannot produce."""
    monkeypatch.setattr(
        analyze_service,
        "_rated_execution_invocations",
        lambda scope, scan, matched_files, root: (list(invocations), {}),
    )


def _invocation(evidence: InvocationEvidence, relative_path: str, *, reason: str = "") -> DbInvocation:
    return DbInvocation(
        class_name=Path(relative_path).stem,
        method_name="Save",
        database=None,
        procedure_name="usp_Shared",
        evidence=evidence,
        source=InvocationSourceSpan(relative_path=relative_path, start_offset=10, end_offset=90),
        reason=reason,
    )


def test_a_likely_caller_with_no_source_file_shows_in_diagnostics_only(monkeypatch, tmp_path: Path) -> None:
    with RatedInvocationsRetention():
        _wire(monkeypatch, _scan(tmp_path), tmp_path)
        _rate_as(
            monkeypatch,
            _invocation(InvocationEvidence.LIKELY, "Removed/GonePage.cs", reason="unique_across_catalogs"),
        )

        response = analyze_service.find_by_sp(_request())

    assert response.matches == []
    assert response.likely_matches == []
    assert [(item["evidence"], item["source_span"]["relative_path"]) for item in response.diagnostics] == [
        ("likely", "Removed/GonePage.cs")
    ]


def test_an_unresolved_caller_does_not_go_into_likely_matches(monkeypatch, tmp_path: Path) -> None:
    with RatedInvocationsRetention():
        _wire(monkeypatch, _scan(tmp_path), tmp_path)
        _rate_as(
            monkeypatch,
            _invocation(InvocationEvidence.UNRESOLVED, "LikelyPage.cs", reason="not_in_resolved_catalog"),
        )

        response = analyze_service.find_by_sp(_request())

    assert response.matches == []
    assert response.likely_matches == []
    assert [item["evidence"] for item in response.diagnostics] == ["unresolved"]


def test_the_openapi_document_shows_likely_matches() -> None:
    properties = app.openapi()["components"]["schemas"]["FindBySPResponse"]["properties"]

    assert properties["likely_matches"]["items"] == properties["matches"]["items"]
