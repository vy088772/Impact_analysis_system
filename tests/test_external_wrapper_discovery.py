from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
import subprocess
import sys

import tools.discover_external_wrappers as discovery
from service import analyze_service


def _record(**overrides: object) -> dict:
    record = {
        "invocation_kind": "source_wrapper",
        "class_name": "PUR_SOMaintain",
        "method_name": "DeleteData",
        "wrapper_method_name": "ExeProcNon",
        "wrapper_receiver_type": "SQLObject",
        "wrapper_source_available": False,
        "wrapper_mode": "stored_procedure",
        "command_text_kind": "literal",
        "command_text": "usp_SO_Delete",
        "line_number": 42,
        "start_offset": 100,
        "end_offset": 180,
    }
    record.update(overrides)
    return record


def test_sqlobject_receiver_auto_selects_reusable_contract() -> None:
    result = discovery._classify_wrapper(_record())

    assert result["status"] == "auto_selected"
    assert result["selection_source"] == "auto_receiver_type"
    assert result["contract"] == "sqlobject"
    assert result["contract_mode"] == "stored_procedure"


def test_unknown_receiver_stays_unresolved() -> None:
    result = discovery._classify_wrapper(
        _record(wrapper_receiver_type="UnknownDbHelper", wrapper_method_name="RunProc")
    )

    assert result["status"] == "unresolved_contract"
    assert result["reason"] == "no_contract_matches_receiver_type"


def test_classifier_delegates_to_gateway_reconciliation_boundary(monkeypatch, tmp_path: Path) -> None:
    seen = {}

    class FakeResult:
        def to_dict(self) -> dict:
            return {"status": "from_gateway", "review_candidate": True}

    def fake_reconcile(self, relative_path, raw, **kwargs):
        seen["relative_path"] = relative_path
        seen["raw"] = raw
        seen.update(kwargs)
        return FakeResult()

    monkeypatch.setattr(discovery.CSharpAnalysisGateway, "reconcile_wrapper", fake_reconcile)
    source_file = tmp_path / "OrderPage.cs"
    result = discovery._classify_wrapper(
        _record(),
        "sqlobject",
        source_file=str(source_file),
        project_root=str(tmp_path),
    )

    assert result == {"status": "from_gateway", "review_candidate": True}
    assert seen["relative_path"] == "OrderPage.cs"
    assert seen["raw"]["wrapper_method_name"] == "ExeProcNon"
    assert seen["scan_root"] == str(tmp_path)
    assert seen["explicit_contract"] == "sqlobject"


def test_report_classification_matches_gateway_boundary(tmp_path: Path) -> None:
    source_file = tmp_path / "OrderPage.cs"
    record = _record()
    gateway = discovery.CSharpAnalysisGateway(
        discovery.SpCatalog.from_databases({}),
    )
    expected = gateway.reconcile_wrapper(
        "OrderPage.cs",
        record,
        scan_root=str(tmp_path),
    ).to_dict()

    actual = discovery._classify_wrapper(
        record,
        source_file=str(source_file),
        project_root=str(tmp_path),
    )

    assert actual == expected


def test_report_groups_calls_and_preserves_source_locations(tmp_path: Path, monkeypatch) -> None:
    source_file = tmp_path / "PUR_SOMaintain.aspx.cs"
    scan = SimpleNamespace(
        project_root=str(tmp_path),
        db_invocations={
            str(source_file): [
                _record(line_number=42),
                _record(line_number=58, start_offset=200, end_offset=280),
            ]
        },
    )
    monkeypatch.setattr(discovery.scan_store, "has_cache", lambda root: True)
    monkeypatch.setattr(discovery.scan_store, "get_or_scan", lambda root, refresh=False: scan)

    report = discovery.build_report(
        [{"system_id": "Y-Docs_TTPUR", "root": tmp_path, "configured_contract": ""}]
    )

    assert report["totals"]["wrapper_calls"] == 2
    assert report["totals"]["auto_selected"] == 1
    observation = report["observations"][0]
    assert observation["calls"] == 2
    assert [location["line"] for location in observation["locations"]] == [42, 58]
    assert observation["locations"][0]["file"] == "PUR_SOMaintain.aspx.cs"


def test_report_keeps_distinct_wrapper_implementation_facts_separate(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_file = tmp_path / "OrderPage.cs"
    scan = SimpleNamespace(
        project_root=str(tmp_path),
        db_invocations={
            str(source_file): [
                _record(
                    wrapper_source_available=True,
                    wrapper_implementation_identity="Vendor.One.SQLObject",
                    wrapper_method_identity="Vendor.One.SQLObject.Execute(string)",
                    wrapper_method_arity=1,
                    wrapper_parameter_types=["string"],
                    wrapper_method_semantics="fixed_inline_sql",
                    wrapper_mode="inline_sql",
                    terminal_sink="ExecuteReader",
                ),
                _record(
                    wrapper_source_available=True,
                    wrapper_implementation_identity="Vendor.Two.SQLObject",
                    wrapper_method_identity="Vendor.Two.SQLObject.Execute(string)",
                    wrapper_method_arity=1,
                    wrapper_parameter_types=["string"],
                    wrapper_method_semantics="fixed_stored_procedure",
                    wrapper_mode="stored_procedure",
                    terminal_sink="ExecuteReader",
                ),
            ]
        },
    )
    monkeypatch.setattr(discovery.scan_store, "has_cache", lambda root: True)
    monkeypatch.setattr(discovery.scan_store, "get_or_scan", lambda root, refresh=False: scan)

    report = discovery.build_report(
        [{"system_id": "OrdersDb", "root": tmp_path, "configured_contract": ""}]
    )

    assert report["totals"]["wrapper_calls"] == 2
    assert report["totals"]["observation_groups"] == 2
    assert {
        observation["implementation_identity"]
        for observation in report["observations"]
    } == {"Vendor.One.SQLObject", "Vendor.Two.SQLObject"}


def test_report_evidence_and_provenance_match_refresh_reconciliation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_file = tmp_path / "OrderPage.cs"
    record = _record(connection_expression="conn")
    scan = SimpleNamespace(
        project_root=str(tmp_path),
        db_invocations={str(source_file): [record]},
        connection_sources={str(source_file.resolve()): {"conn": "OrdersDb"}},
    )
    monkeypatch.setattr(discovery.scan_store, "has_cache", lambda root: True)
    monkeypatch.setattr(discovery.scan_store, "get_or_scan", lambda root, refresh=False: scan)
    monkeypatch.setattr(
        analyze_service.sql_cache_store,
        "load_cached",
        lambda database, schema: {
            "database": "OrdersDb",
            "schema": "dbo",
            "procedures": [{"name": "dbo.usp_SO_Delete"}],
        },
    )

    refresh = analyze_service.reconcile_refresh_wrappers(
        [scan],
        database="OrdersDb",
        explicit_contract="sqlobject",
    )
    report = discovery.build_report(
        [{"system_id": "OrdersDb", "root": tmp_path, "configured_contract": "sqlobject"}]
    )

    refresh_observation = refresh["observations"][0]
    report_observation = report["observations"][0]
    assert report_observation["status"] == refresh_observation["status"]
    assert report_observation["contract"] == refresh_observation["contract"]
    assert report_observation["selection_source"] == refresh_observation["selection_source"]
    assert report_observation["evidence_status"] == refresh_observation["evidence_status"]
    assert report_observation["evidence_reason"] == refresh_observation["evidence_reason"]
    assert report_observation["source_provenance"] == refresh_observation["source_provenance"]
    assert report_observation["locations"][0]["evidence_status"] == "proven"


def test_json_cli_output_is_machine_readable(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parent.parent
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.discover_external_wrappers",
            "--root",
            str(tmp_path),
            "--format",
            "json",
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["totals"]["systems"] == 1