"""Regression checks for program-scoped source refresh."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from code_analyzer.models import FileAnalysisResult, FileType, FrameworkType, SourceSnapshot
from code_analyzer.project_scanner import ProjectScanResult
from service import analyze_service
from service import scan_store


def test_refresh_source_delegates_program_scope_without_full_rescan(monkeypatch, tmp_path) -> None:
    """A program-scoped refresh must use the selected-file cache seam."""
    calls: list[tuple[Path, tuple[str, ...]]] = []
    root = tmp_path / "TTPUR"
    root.mkdir()

    def fake_resolve_scan_roots(source: dict, refresh: bool = False) -> list[Path]:
        assert refresh is True
        return [root]

    def fake_refresh_programs(scan_root: Path, program_names: list[str]) -> ProjectScanResult:
        calls.append((scan_root, tuple(program_names)))
        return ProjectScanResult(
            project_root=str(scan_root),
            project_name=scan_root.name,
            scan_time=datetime.now(),
            total_files=2,
            scanned_files=2,
        )

    monkeypatch.setattr(analyze_service, "resolve_scan_roots", fake_resolve_scan_roots)
    monkeypatch.setattr(analyze_service, "cache_status", lambda scan_root: "current")
    monkeypatch.setattr(analyze_service, "refresh_programs", fake_refresh_programs, raising=False)

    result = analyze_service.refresh_source(
        {"project": "System Dept 1", "repo": "Y-DOCs", "path": "TTPUR"},
        program_names=["Evaluate/PUR_MasterEdit.aspx"],
    )

    assert calls == [(root, ("Evaluate/PUR_MasterEdit.aspx",))]
    assert result["scope"] == "program"
    assert result["updated_programs"] == ["Evaluate/PUR_MasterEdit.aspx"]


def test_refresh_source_rejects_stale_root_before_partial_updates(monkeypatch, tmp_path) -> None:
    roots = [tmp_path / "TTPUR", tmp_path / "ATV"]
    refresh_calls: list[Path] = []

    monkeypatch.setattr(
        analyze_service,
        "resolve_scan_roots",
        lambda source, refresh=False: roots,
    )
    monkeypatch.setattr(
        analyze_service,
        "cache_status",
        lambda root: "current" if root == roots[0] else "stale",
    )
    monkeypatch.setattr(
        analyze_service,
        "refresh_programs",
        lambda root, program_names: refresh_calls.append(root),
    )

    try:
        analyze_service.refresh_source(
            {"project": "p", "repo": "r", "path": ["TTPUR", "ATV"]},
            program_names=["PUR_MasterEdit"],
        )
    except analyze_service.ProgramRefreshCacheError as exc:
        assert exc.root == roots[1]
        assert exc.status == "stale"
    else:
        raise AssertionError("stale roots must be rejected before partial updates")

    assert refresh_calls == []


def test_refresh_source_rejects_missing_root_before_partial_updates(monkeypatch, tmp_path) -> None:
    roots = [tmp_path / "TTPUR", tmp_path / "ATV"]
    refresh_calls: list[Path] = []

    monkeypatch.setattr(
        analyze_service,
        "resolve_scan_roots",
        lambda source, refresh=False: roots,
    )
    monkeypatch.setattr(
        analyze_service,
        "cache_status",
        lambda root: "current" if root == roots[0] else "missing",
    )
    monkeypatch.setattr(
        analyze_service,
        "refresh_programs",
        lambda root, program_names: refresh_calls.append(root),
    )

    try:
        analyze_service.refresh_source(
            {"project": "p", "repo": "r", "path": ["TTPUR", "ATV"]},
            program_names=["PUR_MasterEdit"],
        )
    except analyze_service.ProgramRefreshCacheError as exc:
        assert exc.root == roots[1]
        assert exc.status == "missing"
        assert exc.code == "program_refresh_requires_current_cache"
    else:
        raise AssertionError("missing roots must be rejected before partial updates")

    assert refresh_calls == []


def test_refresh_programs_replaces_selected_cache_records_only(monkeypatch, tmp_path) -> None:
    root = tmp_path / "TTPUR"
    selected_file = root / "Evaluate" / "PUR_MasterEdit.aspx.cs"
    untouched_file = root / "Evaluate" / "PUR_SOQry.aspx.cs"
    selected_file.parent.mkdir(parents=True)
    selected_file.write_text("class Selected {}", encoding="utf-8")
    untouched_file.write_text("class Untouched {}", encoding="utf-8")

    selected_result = FileAnalysisResult(
        file_path=str(selected_file),
        file_type=FileType.CSHARP,
        framework=FrameworkType.WEBFORMS,
    )
    untouched_result = FileAnalysisResult(
        file_path=str(untouched_file),
        file_type=FileType.CSHARP,
        framework=FrameworkType.WEBFORMS,
    )
    scan = ProjectScanResult(
        project_root=str(root),
        project_name="TTPUR",
        scan_time=datetime.now(),
        total_files=2,
        scanned_files=2,
        csharp_results=[selected_result, untouched_result],
    )
    replacement_calls: list[tuple[list[str], list[str]]] = []
    save_calls: list[ProjectScanResult] = []

    class FakeScanner:
        parsers = {}

        def __init__(self, project_root: str):
            assert Path(project_root) == root

        def find_csharp_files(self) -> list[str]:
            return [str(selected_file), str(untouched_file)]

        def refresh_csharp_files(
            self,
            scan_result: ProjectScanResult,
            csharp_files: list[str],
            removed_files: list[str],
        ) -> ProjectScanResult:
            replacement_calls.append((csharp_files, removed_files))
            return scan_result

        def _find_files_by_extensions(self, extensions: set[str]) -> list[str]:
            return []

    def fake_get_or_scan(scan_root: Path, refresh: bool = False) -> ProjectScanResult:
        assert refresh is False
        return scan

    monkeypatch.setattr(analyze_service, "cache_status", lambda scan_root: "current")
    monkeypatch.setattr(analyze_service, "get_or_scan", fake_get_or_scan)
    monkeypatch.setattr(analyze_service, "ProjectScanner", FakeScanner)
    monkeypatch.setattr(analyze_service, "save_scan", lambda scan_root, result: save_calls.append(result))

    result = analyze_service.refresh_programs(root, ["Evaluate/PUR_MasterEdit.aspx"])

    assert result.updated_files == ["Evaluate/PUR_MasterEdit.aspx.cs"]
    assert result.not_found == []
    assert replacement_calls == [([str(selected_file.resolve())], [])]
    assert scan.csharp_results == [selected_result, untouched_result]
    assert save_calls == [scan]


def test_refresh_programs_removes_deleted_orphaned_wrapper_facts(monkeypatch, tmp_path) -> None:
    root = tmp_path / "TTPUR"
    untouched_file = root / "Evaluate" / "PUR_SOQry.aspx.cs"
    deleted_file = root / "Evaluate" / "PUR_MasterEdit.aspx.cs"
    untouched_file.parent.mkdir(parents=True)
    untouched_file.write_text("class Untouched {}", encoding="utf-8")

    untouched_result = FileAnalysisResult(
        file_path=str(untouched_file),
        file_type=FileType.CSHARP,
        framework=FrameworkType.WEBFORMS,
    )
    scan = ProjectScanResult(
        project_root=str(root),
        project_name="TTPUR",
        scan_time=datetime.now(),
        total_files=2,
        scanned_files=2,
        csharp_results=[untouched_result],
        db_invocations={str(deleted_file.resolve()): [{"old": True}]},
        connection_sources={str(deleted_file.resolve()): {"conn": "OldDb"}},
    )
    class FakeScanner(analyze_service.ProjectScanner):
        def __init__(self, project_root: str):
            assert Path(project_root) == root
            self.project_root = str(root)
            self.parsers = {}

        def find_csharp_files(self) -> list[str]:
            return [str(untouched_file)]

        def _find_files_by_extensions(self, extensions: set[str]) -> list[str]:
            return []

    monkeypatch.setattr(analyze_service, "cache_status", lambda scan_root: "current")
    monkeypatch.setattr(analyze_service, "get_or_scan", lambda scan_root, refresh=False: scan)
    monkeypatch.setattr(analyze_service, "ProjectScanner", FakeScanner)
    monkeypatch.setattr(analyze_service, "save_scan", lambda scan_root, result: None)

    result = analyze_service.refresh_programs(root, ["Evaluate/PUR_MasterEdit.aspx"])

    assert result.removed_files == ["Evaluate/PUR_MasterEdit.aspx.cs"]
    assert str(deleted_file.resolve()) not in scan.db_invocations
    assert str(deleted_file.resolve()) not in scan.connection_sources


def test_program_refresh_does_not_full_scan_when_cache_version_is_stale(
    monkeypatch,
    tmp_path,
) -> None:
    """A stale existing cache must fail closed instead of triggering a full scan."""
    root = tmp_path / "TTPUR"
    selected_file = root / "Evaluate" / "PUR_MasterEdit.aspx.cs"
    untouched_file = root / "Evaluate" / "PUR_SOQry.aspx.cs"
    selected_file.parent.mkdir(parents=True)
    selected_file.write_text("class Selected {}", encoding="utf-8")
    untouched_file.write_text("class Untouched {}", encoding="utf-8")

    scan = ProjectScanResult(
        project_root=str(root),
        project_name="TTPUR",
        scan_time=datetime.now(),
        total_files=2,
        scanned_files=2,
        csharp_results=[
            FileAnalysisResult(
                file_path=str(selected_file),
                file_type=FileType.CSHARP,
                framework=FrameworkType.WEBFORMS,
            ),
            FileAnalysisResult(
                file_path=str(untouched_file),
                file_type=FileType.CSHARP,
                framework=FrameworkType.WEBFORMS,
            ),
        ],
    )

    monkeypatch.setattr(scan_store.settings, "SCAN_CACHE_ROOT", str(tmp_path / "cache"))
    scan_store.save_scan(root, scan)
    scan_store._mem_cache.pop(str(root.resolve()), None)
    _, meta_path = scan_store._paths(root)
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    metadata["cache_version"] = scan_store._CACHE_VERSION - 1
    meta_path.write_text(json.dumps(metadata), encoding="utf-8")

    class FullScanForbidden:
        def __init__(self, project_root: str):
            self.project_root = project_root

        def scan_project(self, analyze_sp: bool = False):
            raise AssertionError("program refresh triggered a full project scan")

    monkeypatch.setattr(scan_store, "ProjectScanner", FullScanForbidden)

    try:
        analyze_service.refresh_programs(root, ["Evaluate/PUR_MasterEdit.aspx"])
    except analyze_service.ProgramRefreshCacheError as exc:
        assert exc.status == "stale"
        assert exc.code == "program_refresh_requires_current_cache"
    else:
        raise AssertionError("stale cache must not be used for program refresh")


def test_project_scanner_refresh_replaces_file_evidence(tmp_path) -> None:
    from code_analyzer.project_scanner import ProjectScanner

    root = tmp_path / "TTPUR"
    root.mkdir()
    selected_file = root / "PUR_MasterEdit.aspx.cs"
    untouched_file = root / "PUR_SOQry.aspx.cs"
    selected_file.write_text("class Selected { }", encoding="utf-8")
    untouched_file.write_text("class Untouched { }", encoding="utf-8")

    old_selected = FileAnalysisResult(
        file_path=str(selected_file),
        file_type=FileType.CSHARP,
        framework=FrameworkType.WEBFORMS,
    )
    untouched = FileAnalysisResult(
        file_path=str(untouched_file),
        file_type=FileType.CSHARP,
        framework=FrameworkType.WEBFORMS,
    )
    scan = ProjectScanResult(
        project_root=str(root),
        project_name="TTPUR",
        scan_time=datetime.now(),
        csharp_results=[old_selected, untouched],
        db_invocations={
            str(selected_file.resolve()): [{"old": True}],
            str(untouched_file.resolve()): [{"untouched": True}],
        },
        connection_sources={
            str(selected_file.resolve()): {"conn": "OldDb"},
            str(untouched_file.resolve()): {"conn": "UntouchedDb"},
        },
    )

    class FakeHost:
        def ensure_ready(self) -> None:
            return None

        def analyze_csharp_files(self, input_paths, source_roots):
            assert input_paths == [selected_file]
            assert source_roots == [root]
            return [
                {
                    "source_id": hashlib.sha256(selected_file.read_bytes()).hexdigest(),
                    "methods": [],
                    "db_invocations": [{"new": True}],
                }
            ]

    class FakeParser:
        db_tracker = SimpleNamespace(
            connections={"conn": SimpleNamespace(database_name="NewDb")}
        )

        def parse_file(self, file_path: str) -> FileAnalysisResult:
            return FileAnalysisResult(
                file_path=file_path,
                file_type=FileType.CSHARP,
                framework=FrameworkType.WEBFORMS,
            )

    scanner = object.__new__(ProjectScanner)
    scanner.project_root = str(root)
    scanner.scan_result = None
    scanner.csharp_parser = FakeParser()
    scanner.static_analyzer_host = FakeHost()

    scanner.refresh_csharp_files(scan, [str(selected_file)])

    assert [Path(result.file_path).name for result in scan.csharp_results] == [
        "PUR_MasterEdit.aspx.cs",
        "PUR_SOQry.aspx.cs",
    ]
    assert scan.db_invocations[str(selected_file.resolve())] == [{"new": True}]
    assert scan.connection_sources[str(selected_file.resolve())] == {"conn": "NewDb"}
    assert scan.db_invocations[str(untouched_file.resolve())] == [{"untouched": True}]
    assert scan.connection_sources[str(untouched_file.resolve())] == {"conn": "UntouchedDb"}
    assert scan.source_snapshots["PUR_MasterEdit.aspx.cs"].content == "class Selected { }"
    assert scan.source_snapshots.get("PUR_SOQry.aspx.cs") is None


def test_refresh_api_forwards_program_names(monkeypatch) -> None:
    from service import api
    from service.schemas import RefreshRequest

    observed: dict[str, object] = {}

    def fake_refresh_source(
        source: dict,
        program_names: list[str],
        database: str,
    ) -> dict:
        observed["source"] = source
        observed["program_names"] = program_names
        observed["database"] = database
        return {
            "scope": "program",
            "partial": True,
            "requested_programs": program_names,
        }

    monkeypatch.setattr(api.analyze_service, "refresh_source", fake_refresh_source)

    response = api.refresh(
        RefreshRequest(
            system="SYS",
            source={"project": "p", "repo": "r", "path": "TTPUR"},
            program_names=["PUR_MasterEdit"],
        )
    )

    assert observed == {
        "source": {"project": "p", "repo": "r", "branch": "", "path": "TTPUR"},
        "program_names": ["PUR_MasterEdit"],
        "database": "SYS",
    }
    assert response.scope == "program"
    assert response.partial is True
    assert response.requested_programs == ["PUR_MasterEdit"]


def test_refresh_api_forwards_wrapper_contract_and_serializes_summary(monkeypatch) -> None:
    from service import api
    from service.schemas import RefreshRequest

    observed: dict[str, object] = {}
    summary = {
        "observed_receiver_types": ["UnknownDbHelper"],
        "observed_methods": ["RunProc"],
        "classification_statuses": ["unresolved_contract"],
        "evidence_statuses": ["unresolved"],
        "selected_contracts": [],
        "selection_sources": ["unresolved_receiver_type"],
        "candidate_contracts": [],
        "observations": [
            {
                "receiver_type": "UnknownDbHelper",
                "observed_methods": ["RunProc"],
                "status": "unresolved_contract",
                "evidence_status": "unresolved",
                "evidence_reason": "wrapper_source_unavailable",
                "selection_source": "unresolved_receiver_type",
                "candidate_contracts": [],
                "source_provenance": {"scan_root": "C:/scan/TTPUR"},
                "review_reasons": ["no_contract_matches_receiver_type"],
            }
        ],
    }

    def fake_refresh_source(
        source: dict,
        program_names: list[str],
        wrapper_contract: str,
        database: str,
    ) -> dict:
        observed["source"] = source
        observed["program_names"] = program_names
        observed["wrapper_contract"] = wrapper_contract
        observed["database"] = database
        return {"scope": "system", "wrapper_summary": summary}

    monkeypatch.setattr(api.analyze_service, "refresh_source", fake_refresh_source)

    response = api.refresh(
        RefreshRequest(
            system="SYS",
            wrapper_contract="sqlobject",
            source={"project": "p", "repo": "r", "path": "TTPUR"},
        )
    )

    assert observed["wrapper_contract"] == "sqlobject"
    assert observed["database"] == "SYS"
    assert response.wrapper_summary["observations"][0]["status"] == "unresolved_contract"
    assert response.wrapper_summary["observations"][0]["source_provenance"] == {
        "scan_root": "C:/scan/TTPUR"
    }


def test_refresh_source_without_programs_keeps_full_refresh(monkeypatch, tmp_path) -> None:
    root = tmp_path / "TTPUR"
    root.mkdir()
    refresh_flags: list[bool] = []
    scan = ProjectScanResult(
        project_root=str(root),
        project_name="TTPUR",
        scan_time=datetime.now(),
    )

    monkeypatch.setattr(
        analyze_service,
        "resolve_scan_roots",
        lambda source, refresh=False: [root],
    )

    def fake_get_or_scan(scan_root: Path, refresh: bool = False) -> ProjectScanResult:
        refresh_flags.append(refresh)
        return scan

    monkeypatch.setattr(analyze_service, "get_or_scan", fake_get_or_scan)

    result = analyze_service.refresh_source({"project": "p", "repo": "r"})

    assert refresh_flags == [True]
    assert result["scope"] == "system"
    assert result["partial"] is False
    assert result["requested_programs"] == []


def test_full_refresh_reconciles_raw_wrappers_once_without_sql(monkeypatch, tmp_path) -> None:
    """A full source refresh returns wrapper review data from its single scan."""
    root = tmp_path / "TTPUR"
    source_file = root / "OrderPage.aspx.cs"
    root.mkdir()
    scan = ProjectScanResult(
        project_root=str(root),
        project_name="TTPUR",
        scan_time=datetime.now(),
        total_files=1,
        scanned_files=1,
        db_invocations={
            str(source_file): [
                {
                    "invocation_kind": "source_wrapper",
                    "class_name": "OrderPage",
                    "method_name": "Save",
                    "wrapper_method_name": "RunProc",
                    "wrapper_receiver_type": "UnknownDbHelper",
                    "wrapper_source_available": False,
                    "wrapper_mode": "stored_procedure",
                    "command_text_kind": "literal",
                    "command_text": "usp_SaveOrder",
                    "connection_expression": "conn",
                    "line_number": 42,
                    "start_offset": 100,
                    "end_offset": 180,
                }
            ]
        },
        connection_sources={str(source_file): {"conn": "OrdersDb"}},
    )
    scan_calls: list[tuple[Path, bool]] = []

    monkeypatch.setattr(
        analyze_service,
        "resolve_scan_roots",
        lambda source, refresh=False: [root],
    )

    def fake_get_or_scan(scan_root: Path, refresh: bool = False) -> ProjectScanResult:
        scan_calls.append((scan_root, refresh))
        return scan

    monkeypatch.setattr(analyze_service, "get_or_scan", fake_get_or_scan)

    result = analyze_service.refresh_source({"project": "p", "repo": "r"})

    assert scan_calls == [(root, True)]
    assert result["database_invocations"] == 1
    assert result["wrapper_summary"]["observed_receiver_types"] == ["UnknownDbHelper"]
    observation = result["wrapper_summary"]["observations"][0]
    assert observation["receiver_type"] == "UnknownDbHelper"
    assert observation["observed_methods"] == ["RunProc"]
    assert observation["status"] == "unresolved_contract"
    assert observation["selection_source"] == "unresolved_receiver_type"
    assert observation["evidence_status"] == "unresolved"
    assert observation["evidence_reason"] == "wrapper_source_unavailable"
    assert observation["candidate_contracts"] == []
    assert observation["source_provenance"]["scan_root"] == str(root)
    assert observation["review_reasons"] == ["no_contract_matches_receiver_type"]
    assert result["wrapper_summary"]["totals"]["evidence_unresolved"] == 1
    assert observation["locations"][0]["evidence_status"] == "unresolved"
    assert observation["locations"][0]["evidence_reason"] == "wrapper_source_unavailable"
    assert observation["locations"][0]["procedure_name"] == "usp_saveorder"
    assert observation["locations"][0]["database"] == "OrdersDb"


def test_review_candidates_keep_each_source_snapshot_identity(monkeypatch, tmp_path) -> None:
    root = tmp_path / "TTPUR"
    first_file = root / "FirstPage.aspx.cs"
    second_file = root / "SecondPage.aspx.cs"
    root.mkdir()
    scan = ProjectScanResult(
        project_root=str(root),
        project_name="TTPUR",
        scan_time=datetime.now(),
        db_invocations={
            str(first_file): [
                {
                    "invocation_kind": "source_wrapper",
                    "class_name": "Page",
                    "method_name": "Save",
                    "wrapper_method_name": "Execute",
                    "wrapper_receiver_type": "UnknownDbHelper",
                    "wrapper_source_available": False,
                    "wrapper_mode": "stored_procedure",
                    "command_text_kind": "literal",
                    "command_text": "usp_SaveOrder",
                    "start_offset": 10,
                    "end_offset": 20,
                }
            ],
            str(second_file): [
                {
                    "invocation_kind": "source_wrapper",
                    "class_name": "Page",
                    "method_name": "Save",
                    "wrapper_method_name": "Execute",
                    "wrapper_receiver_type": "UnknownDbHelper",
                    "wrapper_source_available": False,
                    "wrapper_mode": "stored_procedure",
                    "command_text_kind": "literal",
                    "command_text": "usp_SaveOrder",
                    "start_offset": 30,
                    "end_offset": 40,
                }
            ],
        },
        source_snapshots={
            "FirstPage.aspx.cs": SourceSnapshot(
                relative_path="FirstPage.aspx.cs",
                content_hash="snapshot-first",
                content="class FirstPage {}",
            ),
            "SecondPage.aspx.cs": SourceSnapshot(
                relative_path="SecondPage.aspx.cs",
                content_hash="snapshot-second",
                content="class SecondPage {}",
            ),
        },
    )

    monkeypatch.setattr(
        analyze_service,
        "resolve_scan_roots",
        lambda source, refresh=False: [root],
    )
    monkeypatch.setattr(analyze_service, "get_or_scan", lambda scan_root, refresh=False: scan)

    result = analyze_service.refresh_source({"project": "p", "repo": "r"})

    review_items = result["wrapper_summary"]["review_items"]
    assert len(review_items) == 2
    by_path = {
        item["source_span"]["relative_path"]: item
        for item in review_items
    }
    assert by_path["FirstPage.aspx.cs"]["observed_method"] == "Execute"
    assert by_path["FirstPage.aspx.cs"]["source_snapshot_hash"] == "snapshot-first"
    assert by_path["FirstPage.aspx.cs"]["source_snapshot_identity"] == "snapshot-first"
    assert by_path["FirstPage.aspx.cs"]["active_contract"] is False
    assert by_path["FirstPage.aspx.cs"]["source_provenance"]["source_snapshot_hash"] == (
        "snapshot-first"
    )
    assert by_path["SecondPage.aspx.cs"]["source_provenance"]["source_snapshot_hash"] == (
        "snapshot-second"
    )
    assert all(item["unresolved_reason"] == "no_contract_matches_receiver_type" for item in review_items)


def test_refresh_selector_does_not_prove_database_evidence(monkeypatch, tmp_path) -> None:
    root = tmp_path / "TTPUR"
    source_file = root / "OrderPage.aspx.cs"
    root.mkdir()
    scan = ProjectScanResult(
        project_root=str(root),
        project_name="TTPUR",
        scan_time=datetime.now(),
        db_invocations={
            str(source_file): [
                {
                    "invocation_kind": "source_wrapper",
                    "class_name": "OrderPage",
                    "method_name": "Save",
                    "wrapper_method_name": "ExeProcNon",
                    "wrapper_receiver_type": "SQLObject",
                    "wrapper_source_available": False,
                    "wrapper_mode": "stored_procedure",
                    "command_text_kind": "literal",
                    "command_text": "usp_SaveOrder",
                    "connection_expression": "conn",
                }
            ]
        },
        connection_sources={str(source_file): {"conn": "OrdersDb"}},
    )

    monkeypatch.setattr(analyze_service, "resolve_scan_roots", lambda source, refresh=False: [root])
    monkeypatch.setattr(analyze_service, "get_or_scan", lambda scan_root, refresh=False: scan)

    result = analyze_service.refresh_source(
        {"project": "p", "repo": "r"},
        wrapper_contract="sqlobject",
    )

    summary = result["wrapper_summary"]
    observation = summary["observations"][0]
    assert observation["status"] == "explicit_selected"
    assert observation["selected_contract"] == "sqlobject"
    assert observation["evidence_status"] == "unresolved"
    assert observation["evidence_reason"] == "not_in_resolved_catalog"
    assert summary["selected_contracts"] == ["sqlobject"]
    assert summary["totals"]["evidence_unresolved"] == 1


def test_refresh_reconciles_multi_root_wrappers_with_root_provenance(monkeypatch, tmp_path) -> None:
    roots = [tmp_path / "TTPUR", tmp_path / "ATV"]
    scans = {}
    for root in roots:
        root.mkdir()
        source_file = root / "OrderPage.aspx.cs"
        scans[root] = ProjectScanResult(
            project_root=str(root),
            project_name=root.name,
            scan_time=datetime.now(),
            db_invocations={
                str(source_file): [
                    {
                        "invocation_kind": "source_wrapper",
                        "class_name": "OrderPage",
                        "method_name": "Save",
                        "wrapper_method_name": "RunProc",
                        "wrapper_receiver_type": "UnknownDbHelper",
                        "wrapper_source_available": False,
                        "wrapper_mode": "stored_procedure",
                        "command_text_kind": "literal",
                        "command_text": "usp_SaveOrder",
                    }
                ]
            },
        )
    scan_calls: list[tuple[Path, bool]] = []

    monkeypatch.setattr(analyze_service, "resolve_scan_roots", lambda source, refresh=False: roots)

    def fake_get_or_scan(root: Path, refresh: bool = False) -> ProjectScanResult:
        scan_calls.append((root, refresh))
        return scans[root]

    monkeypatch.setattr(analyze_service, "get_or_scan", fake_get_or_scan)

    result = analyze_service.refresh_source({"project": "p", "repo": "r"})

    summary = result["wrapper_summary"]
    assert scan_calls == [(roots[0], True), (roots[1], True)]
    assert summary["source_scan_count"] == 2
    assert summary["totals"]["wrapper_calls"] == 2
    assert {
        observation["source_provenance"]["scan_root"]
        for observation in summary["observations"]
    } == {str(root) for root in roots}


def test_partial_refresh_reconciles_selected_cache_without_full_scan(monkeypatch, tmp_path) -> None:
    root = tmp_path / "TTPUR"
    root.mkdir()
    source_file = root / "OrderPage.aspx.cs"
    scan = ProjectScanResult(
        project_root=str(root),
        project_name="TTPUR",
        scan_time=datetime.now(),
        db_invocations={
            str(source_file): [
                {
                    "invocation_kind": "source_wrapper",
                    "class_name": "OrderPage",
                    "method_name": "Save",
                    "wrapper_method_name": "RunProc",
                    "wrapper_receiver_type": "UnknownDbHelper",
                    "wrapper_source_available": False,
                    "wrapper_mode": "stored_procedure",
                    "command_text_kind": "literal",
                    "command_text": "usp_SaveOrder",
                }
            ]
        },
    )

    monkeypatch.setattr(analyze_service, "resolve_scan_roots", lambda source, refresh=False: [root])
    monkeypatch.setattr(analyze_service, "cache_status", lambda scan_root: "current")
    monkeypatch.setattr(
        analyze_service,
        "get_or_scan",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("partial wrapper reconciliation triggered a full scan")
        ),
    )
    monkeypatch.setattr(
        analyze_service,
        "refresh_programs",
        lambda scan_root, program_names: analyze_service.ProgramRefreshResult(
            scan=scan,
            updated_files=["OrderPage.aspx.cs"],
            matched_programs=list(program_names),
        ),
    )

    result = analyze_service.refresh_source(
        {"project": "p", "repo": "r"},
        program_names=["OrderPage.aspx"],
    )

    assert result["scope"] == "program"
    assert result["partial"] is True
    assert result["wrapper_summary"]["totals"]["wrapper_calls"] == 1
    assert result["wrapper_summary"]["observations"][0]["status"] == "unresolved_contract"


def test_partial_refresh_keeps_wrapper_source_lookup_inside_each_root(monkeypatch, tmp_path) -> None:
    roots = [tmp_path / "TTPUR", tmp_path / "ATV"]
    scans: dict[Path, ProjectScanResult] = {}
    scanners: dict[Path, object] = {}
    analyzer_calls: list[tuple[Path, list[Path]]] = []

    class FakeParser:
        db_tracker = SimpleNamespace(connections={})

        def parse_file(self, file_path: str) -> FileAnalysisResult:
            return FileAnalysisResult(
                file_path=file_path,
                file_type=FileType.CSHARP,
                framework=FrameworkType.WEBFORMS,
            )

    for index, root in enumerate(roots):
        root.mkdir()
        caller_file = root / "PUR_MasterEdit.aspx.cs"
        caller_file.write_text("class Caller {}", encoding="utf-8")
        if index == 0:
            (root / "DbWrapper.cs").write_text("class DbWrapper {}", encoding="utf-8")

        scan = ProjectScanResult(
            project_root=str(root),
            project_name=root.name,
            scan_time=datetime.now(),
            total_files=1,
            scanned_files=1,
            csharp_results=[
                FileAnalysisResult(
                    file_path=str(caller_file),
                    file_type=FileType.CSHARP,
                    framework=FrameworkType.WEBFORMS,
                )
            ],
        )
        scans[root] = scan

        class FakeHost:
            def ensure_ready(self) -> None:
                return None

            def analyze_csharp_files(
                self,
                input_paths,
                source_roots,
                selected_root=root,
                selected_caller=caller_file,
            ):
                analyzer_calls.append((selected_root, list(source_roots)))
                assert input_paths == [selected_caller]
                assert source_roots == [selected_root]
                has_local_wrapper = (selected_root / "DbWrapper.cs").exists()
                return [
                    {
                        "source_id": hashlib.sha256(selected_caller.read_bytes()).hexdigest(),
                        "methods": [],
                        "db_invocations": [
                            {
                                "invocation_kind": "source_wrapper",
                                "class_name": "Caller",
                                "method_name": "Save",
                                "wrapper_method_name": "Execute",
                                "wrapper_receiver_type": "DbWrapper",
                                "wrapper_source_available": has_local_wrapper,
                                "wrapper_mode": "stored_procedure",
                                "command_text_kind": "literal",
                                "command_text": "usp_SaveOrder",
                                "connection_expression": "conn",
                                "line_number": 1,
                                "start_offset": 0,
                                "end_offset": 10,
                            }
                        ],
                    }
                ]

        scanner = object.__new__(analyze_service.ProjectScanner)
        scanner.project_root = str(root)
        scanner.scan_result = None
        scanner.csharp_parser = FakeParser()
        scanner.static_analyzer_host = FakeHost()
        scanner.parsers = {}
        scanners[root] = scanner

    monkeypatch.setattr(analyze_service, "resolve_scan_roots", lambda source, refresh=False: roots)
    monkeypatch.setattr(analyze_service, "cache_status", lambda scan_root: "current")
    monkeypatch.setattr(analyze_service, "get_or_scan", lambda root, refresh=False: scans[root])
    monkeypatch.setattr(analyze_service, "ProjectScanner", lambda project_root: scanners[Path(project_root)])
    monkeypatch.setattr(analyze_service, "save_scan", lambda scan_root, result: None)

    result = analyze_service.refresh_source(
        {"project": "p", "repo": "r", "path": ["TTPUR", "ATV"]},
        program_names=["PUR_MasterEdit.aspx"],
    )

    assert analyzer_calls == [(roots[0], [roots[0]]), (roots[1], [roots[1]])]
    observations = {
        observation["scan_root"]: observation
        for observation in result["wrapper_summary"]["observations"]
    }
    assert observations[str(roots[0])]["status"] == "source_wrapper"
    assert observations[str(roots[1])]["status"] == "unresolved_contract"


def test_refresh_does_not_write_wrapper_registry_or_system_catalog(monkeypatch, tmp_path) -> None:
    root = tmp_path / "TTPUR"
    root.mkdir()
    scan = ProjectScanResult(
        project_root=str(root),
        project_name="TTPUR",
        scan_time=datetime.now(),
    )
    registry_path = PROJECT_ROOT / "config" / "external_wrapper_contracts.json"
    catalog_path = PROJECT_ROOT.parent / "llamaindex-spec-rag" / "catalog" / "system_catalog.json"
    before = {path: path.read_bytes() for path in (registry_path, catalog_path)}

    monkeypatch.setattr(analyze_service, "resolve_scan_roots", lambda source, refresh=False: [root])
    monkeypatch.setattr(analyze_service, "get_or_scan", lambda scan_root, refresh=False: scan)

    analyze_service.refresh_source({"project": "p", "repo": "r"})

    assert {path: path.read_bytes() for path in before} == before


def test_refresh_reconciliation_uses_database_scoped_sp_catalog(monkeypatch, tmp_path) -> None:
    root = tmp_path / "Orders"
    source_file = root / "OrderPage.aspx.cs"
    root.mkdir()
    scan = ProjectScanResult(
        project_root=str(root),
        project_name="Orders",
        scan_time=datetime.now(),
        total_files=1,
        scanned_files=1,
        db_invocations={
            str(source_file): [
                {
                    "invocation_kind": "source_wrapper",
                    "class_name": "OrderPage",
                    "method_name": "Save",
                    "wrapper_method_name": "ExeProcNon",
                    "wrapper_receiver_type": "SQLObject",
                    "wrapper_source_available": False,
                    "wrapper_mode": "stored_procedure",
                    "command_text_kind": "literal",
                    "command_text": "usp_SaveOrder",
                    "connection_expression": "conn",
                    "line_number": 42,
                    "start_offset": 100,
                    "end_offset": 180,
                }
            ]
        },
        connection_sources={str(source_file): {"conn": "OrdersDb"}},
    )
    monkeypatch.setattr(analyze_service, "resolve_scan_roots", lambda source, refresh=False: [root])
    monkeypatch.setattr(analyze_service, "get_or_scan", lambda scan_root, refresh=False: scan)
    monkeypatch.setattr(
        analyze_service.sql_cache_store,
        "load_cached",
        lambda database, schema: {
            "database": "OrdersDb",
            "schema": "dbo",
            "procedures": [{"name": "dbo.usp_SaveOrder"}],
        },
    )

    result = analyze_service.refresh_source(
        {"project": "p", "repo": "r"},
        wrapper_contract="sqlobject",
        database="OrdersDb",
    )

    observation = result["wrapper_summary"]["observations"][0]
    assert observation["evidence_status"] == "proven"
    assert observation["database"] == "OrdersDb"
    assert observation["procedure_name"] == "usp_saveorder"