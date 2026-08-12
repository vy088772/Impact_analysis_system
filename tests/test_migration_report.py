"""Acceptance checks for the legacy-versus-Gateway migration report."""

from __future__ import annotations

from datetime import datetime
import json
import pickle
from pathlib import Path

from code_analyzer.csharp_analysis_gateway import (
    DbInvocation,
    InvocationEvidence,
    InvocationSourceSpan,
)
from code_analyzer.models import CodeLocation, StoredProcedureCall
from code_analyzer.project_scanner import CSharpSPRelation, ProjectScanResult
from service.migration_report import (
    build_cutover_report,
    compare_legacy_gateway,
    render_migration_report_markdown,
    save_migration_report,
)


def _legacy(root: Path, method: str, procedure: str) -> CSharpSPRelation:
    return CSharpSPRelation(
        csharp_file=str(root / "OrderPage.cs"),
        class_name="OrderPage",
        method_name=method,
        line_number=20,
        sp_name=procedure,
        sp_database="OrdersDb",
    )


def _gateway(method: str, procedure: str, evidence: InvocationEvidence, offset: int) -> DbInvocation:
    return DbInvocation(
        class_name="OrderPage",
        method_name=method,
        database="OrdersDb",
        procedure_name=procedure,
        evidence=evidence,
        source=InvocationSourceSpan("OrderPage.cs", offset, offset + 20),
        procedure_schema="dbo",
    )


def test_compare_legacy_gateway_reports_matched_new_dropped_confidence_and_unresolved(
    tmp_path: Path,
) -> None:
    legacy = [
        _legacy(tmp_path, "SaveDirect", "dbo.usp_Save"),
        _legacy(tmp_path, "SaveWrapper", "dbo.usp_Wrapped"),
        _legacy(tmp_path, "SaveLikely", "dbo.usp_Likely"),
        _legacy(tmp_path, "SaveDropped", "dbo.usp_Dropped"),
    ]
    gateway = [
        _gateway("SaveDirect", "usp_Save", InvocationEvidence.PROVEN, 10),
        _gateway("SaveWrapper", "usp_Wrapped", InvocationEvidence.PROVEN, 30),
        _gateway("SaveLikely", "usp_Likely", InvocationEvidence.LIKELY, 50),
        _gateway("SaveNew", "usp_NewBranch", InvocationEvidence.PROVEN, 70),
        DbInvocation(
            class_name="OrderPage",
            method_name="SaveDynamic",
            database="OrdersDb",
            procedure_name=None,
            evidence=InvocationEvidence.UNRESOLVED,
            source=InvocationSourceSpan("OrderPage.cs", 90, 110),
            reason="dynamic_command_text",
        ),
    ]
    source_kinds = {
        ("orderpage.cs", 10, 30): "direct_sqlclient",
        ("orderpage.cs", 30, 50): "source_wrapper",
        ("orderpage.cs", 50, 70): "dapper",
        ("orderpage.cs", 70, 90): "branch_invocation",
        ("orderpage.cs", 90, 110): "dynamic_sql",
    }

    report = compare_legacy_gateway(
        legacy,
        gateway,
        source_root=tmp_path,
        source_kinds=source_kinds,
    )

    assert report["summary"] == {
        "legacy_count": 4,
        "gateway_count": 5,
        "matched_count": 2,
        "dropped_count": 1,
        "new_count": 1,
        "confidence_changed_count": 1,
        "unresolved_count": 1,
    }
    assert report["dropped"][0]["reason"] == "legacy_detection_missing_from_gateway"
    assert report["new"][0]["gateway"]["source_kind"] == "branch_invocation"
    assert report["confidence_changed"][0]["gateway"]["evidence"] == "likely"
    assert report["unresolved"][0]["reason"] == "dynamic_command_text"
    markdown = render_migration_report_markdown(report)
    assert "| Dropped | 1 |" in markdown
    assert "dynamic_command_text" in markdown


def test_compare_legacy_gateway_accepts_stored_procedure_call_records(tmp_path: Path) -> None:
    report = compare_legacy_gateway(
        [
            StoredProcedureCall(
                procedure_name="usp_Legacy",
                database_source="OrdersDb",
                location=CodeLocation(str(tmp_path / "Legacy.cs"), 12),
            )
        ],
        [],
        source_root=tmp_path,
    )

    assert report["summary"]["dropped_count"] == 1
    assert report["dropped"][0]["legacy"]["procedure"] == "dbo.usp_legacy"


def test_migration_report_preserves_gateway_context_for_review() -> None:
    legacy = [
        {
            "file": "OrderPage.cs",
            "class": "OrderPage",
            "method": "Save",
            "database": "unknown",
            "procedure": "dbo.usp_Save",
            "line": 20,
        }
    ]
    gateway = DbInvocation(
        class_name="OrderPage",
        method_name="Save",
        database=None,
        database_candidates=("OrdersDb",),
        procedure_name="usp_Save",
        evidence=InvocationEvidence.LIKELY,
        source=InvocationSourceSpan("OrderPage.cs", 100, 140),
        reason="unique_across_catalogs",
        method_chain=("Save", "Execute"),
        branch_context=("if (isDraft)",),
        source_snapshot_hash="snapshot-1",
    )

    report = compare_legacy_gateway(legacy, [gateway])
    record = report["confidence_changed"][0]["gateway"]

    assert record["caller"] == {
        "file": "orderpage.cs",
        "class": "OrderPage",
        "method": "Save",
    }
    assert record["evidence"] == "likely"
    assert record["reason"] == "unique_across_catalogs"
    assert record["source_kind"] == "gateway"
    assert record["database_candidates"] == ["OrdersDb"]
    assert record["database_attribution"] == "candidate"
    assert record["source"] == {
        "start_offset": 100,
        "end_offset": 140,
        "branch_context": ["if (isDraft)"],
        "method_chain": ["Save", "Execute"],
        "method_class_chain": [],
        "source_snapshot_hash": "snapshot-1",
    }


def test_migration_report_sorting_is_independent_of_input_order() -> None:
    legacy = [
        {
            "file": "OrderPage.cs",
            "class": "OrderPage",
            "method": "Save",
            "database": "OrdersDb",
            "procedure": "dbo.usp_Save",
            "line": 30,
        },
        {
            "file": "OrderPage.cs",
            "class": "OrderPage",
            "method": "Save",
            "database": "OrdersDb",
            "procedure": "dbo.usp_Save",
            "line": 10,
        },
    ]
    gateway = [
        _gateway("Save", "usp_Save", InvocationEvidence.PROVEN, 200),
        _gateway("Save", "usp_Save", InvocationEvidence.PROVEN, 100),
    ]

    forward = compare_legacy_gateway(legacy, gateway)
    reverse = compare_legacy_gateway(list(reversed(legacy)), list(reversed(gateway)))

    assert forward == reverse
    assert forward["summary"]["matched_count"] == 2


def test_project_scan_result_does_not_persist_legacy_comparison_records(tmp_path: Path) -> None:
    result = ProjectScanResult(
        project_root=str(tmp_path),
        project_name="demo",
        scan_time=datetime.now(),
    )
    result.legacy_sp_relations = [_legacy(tmp_path, "Save", "usp_Save")]

    assert "legacy_sp_relations" not in result.to_dict()

    restored = pickle.loads(pickle.dumps(result))
    assert restored.legacy_sp_relations == []


def test_migration_report_can_be_saved_as_review_artifact(tmp_path: Path) -> None:
    report = compare_legacy_gateway(
        [_legacy(tmp_path, "Save", "usp_Save")],
        [],
        source_root=tmp_path,
    )

    json_path = save_migration_report(report, tmp_path / "migration.json")
    markdown_path = save_migration_report(report, tmp_path / "migration.md")

    assert json.loads(json_path.read_text(encoding="utf-8"))["summary"] == report["summary"]
    assert "# Legacy vs Gateway Invocation Report" in markdown_path.read_text(encoding="utf-8")


def test_build_cutover_report_summarizes_evidence_review_and_lifecycle(tmp_path: Path) -> None:
    gateway = [
        _gateway("SaveDirect", "usp_Save", InvocationEvidence.PROVEN, 10),
        _gateway("SaveLikely", "usp_Likely", InvocationEvidence.LIKELY, 30),
        DbInvocation(
            class_name="OrderPage",
            method_name="SaveDynamic",
            database="OrdersDb",
            procedure_name=None,
            evidence=InvocationEvidence.UNRESOLVED,
            source=InvocationSourceSpan("OrderPage.cs", 50, 70),
            reason="dynamic_command_text",
        ),
        DbInvocation(
            class_name="OrderPage",
            method_name="SaveWrapper",
            database="OrdersDb",
            procedure_name="usp_Wrapped",
            evidence=InvocationEvidence.PROVEN,
            source=InvocationSourceSpan("OrderPage.cs", 80, 100),
            contract_lifecycle_status="reused",
        ),
        DbInvocation(
            class_name="OrderPage",
            method_name="SaveNewWrapper",
            database="OrdersDb",
            procedure_name=None,
            evidence=InvocationEvidence.UNRESOLVED,
            source=InvocationSourceSpan("OrderPage.cs", 110, 130),
            wrapper_review_candidate=True,
            contract_lifecycle_status="preflight_failed",
            reason="contract_preflight_failed",
        ),
    ]
    legacy = [
        _legacy(tmp_path, "SaveDirect", "dbo.usp_Save"),
        _legacy(tmp_path, "SaveDropped", "dbo.usp_Dropped"),
    ]

    report = build_cutover_report(
        gateway,
        legacy_records=legacy,
        source_root=tmp_path,
    )

    assert report["evidence_summary"] == {
        "proven": 2,
        "likely": 1,
        "unresolved": 2,
    }
    assert report["review_candidate_count"] == 1
    assert report["contract_lifecycle_summary"] == {
        "reused": 1,
        "preflight_failed": 1,
        "": 3,
    }
    assert report["legacy_migration"]["summary"]["dropped_count"] == 1
    assert report["cutover_signals"] == {
        "legacy_only_detections": 1,
        "unresolved_count": 2,
        "review_candidate_count": 1,
        "ready_for_legacy_retirement": False,
    }


def test_build_cutover_report_is_ready_when_no_legacy_only_detections_remain() -> None:
    gateway = [_gateway("SaveDirect", "usp_Save", InvocationEvidence.PROVEN, 10)]
    legacy = [
        {
            "file": "OrderPage.cs",
            "class": "OrderPage",
            "method": "SaveDirect",
            "database": "OrdersDb",
            "procedure": "dbo.usp_Save",
            "line": 20,
        }
    ]

    report = build_cutover_report(gateway, legacy_records=legacy)

    assert report["cutover_signals"]["ready_for_legacy_retirement"] is True