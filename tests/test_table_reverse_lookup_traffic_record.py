"""Ticket 01 of `.scratch/table-reverse-lookup-cost/`: every table reverse
lookup records the table it was asked about and the Derived Execution
Evidence Scope it ran in.

Drives `find_by_table()` directly -- the seam this ticket names, and the same
seam tests/test_derived_execution_evidence_retention_bound.py already drives
for retention behaviour -- and asserts on the printed record via `capsys`,
matching that file's style for observability output.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from code_analyzer.project_scanner import ProjectScanResult
from code_analyzer.models import ClassInfo, FileAnalysisResult, FileType, FrameworkType, MethodInfo
from service import analyze_service
from service.schemas import FindByTableRequest
from tests.derived_execution_evidence_fixtures import RatedInvocationsRetention


def _file(root: Path) -> FileAnalysisResult:
    path = root / "AlphaPage.cs"
    return FileAnalysisResult(
        file_path=str(path),
        file_type=FileType.CSHARP,
        framework=FrameworkType.WEBFORMS,
        classes=[
            ClassInfo(
                name="AlphaPage",
                namespace="",
                file_path=str(path),
                methods=[MethodInfo(name="SaveAlpha", access_modifier="private", return_type="void")],
            )
        ],
    )


def _scan(root: Path) -> ProjectScanResult:
    """One program with an inline SQL fact -- no `database`, so no SQL
    Execution Graph is required. This is the "before an Agent exists" shape:
    a table reverse lookup that runs on inline C# facts alone."""
    return ProjectScanResult(
        project_root=str(root),
        project_name="orders",
        scan_time=datetime.now(),
        csharp_results=[_file(root)],
    )


def _wire(monkeypatch, scan: ProjectScanResult, tmp_path: Path) -> None:
    monkeypatch.setattr(analyze_service, "resolve_scan_roots", lambda source, refresh=False: [tmp_path])
    monkeypatch.setattr(analyze_service, "_get_scan", lambda root, refresh=False: scan)


def _request(table_name: str, *, database: str = "") -> FindByTableRequest:
    return FindByTableRequest(
        source={"project": "orders", "repo": "orders"},
        table_name=table_name,
        database=database,
        cache_only=False,
    )


def test_lookup_records_the_table_name_and_the_scope(monkeypatch, tmp_path: Path, capsys) -> None:
    with RatedInvocationsRetention():
        scan = _scan(tmp_path)
        _wire(monkeypatch, scan, tmp_path)

        analyze_service.find_by_table(_request("TableA"))

        printed = capsys.readouterr().out
        assert "TableA" in printed
        assert str(tmp_path) in printed


def test_lookup_before_an_agent_exists_is_recorded_the_same_way(monkeypatch, tmp_path: Path, capsys) -> None:
    """No `database` set is the shape of a lookup run before an Agent exists
    (Object Kind Ambiguity, per the ticket) -- it must still be recorded."""
    with RatedInvocationsRetention():
        scan = _scan(tmp_path)
        _wire(monkeypatch, scan, tmp_path)

        analyze_service.find_by_table(_request("TableA", database=""))

        printed = capsys.readouterr().out
        assert "TableA" in printed


def test_two_systems_asking_about_one_table_stay_distinguishable(monkeypatch, tmp_path: Path, capsys) -> None:
    """`database` is enough on its own to tell two systems apart in the
    record, so the graph lookup it would otherwise require is stubbed out --
    what is under test here is the record, not graph resolution."""
    other_root = tmp_path / "other"
    other_root.mkdir()
    empty_graph = {"graph_version": 2, "database": "", "nodes": [], "relationships": [], "parse_errors": []}
    monkeypatch.setattr(
        analyze_service.sql_cache_store,
        "load_cached",
        lambda database, schema, server="": {"database": database, "schema": "dbo", "sql_execution_graph": empty_graph},
    )

    with RatedInvocationsRetention():
        scan = _scan(tmp_path)
        _wire(monkeypatch, scan, tmp_path)
        analyze_service.find_by_table(_request("TableA", database="OrdersDb"))
        first_record = capsys.readouterr().out

        monkeypatch.setattr(analyze_service, "resolve_scan_roots", lambda source, refresh=False: [other_root])
        analyze_service.find_by_table(_request("TableA", database="BillingDb"))
        second_record = capsys.readouterr().out

        assert first_record != second_record
        assert "OrdersDb" in first_record
        assert "BillingDb" in second_record


def test_records_returned_are_unchanged_by_the_added_record(monkeypatch, tmp_path: Path, capsys) -> None:
    """The record is observability only -- it must not alter what a lookup
    returns."""
    with RatedInvocationsRetention():
        scan = _scan(tmp_path)
        _wire(monkeypatch, scan, tmp_path)

        response = analyze_service.find_by_table(_request("TableA"))

        assert response.table_name == "TableA"
        assert response.skipped is False


def test_a_skipped_cache_only_lookup_never_reaches_the_scan_it_would_need_to_record(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    """A `cache_only` miss returns before any repo scan is resolved; recording
    it would require doing exactly the scan work `cache_only` exists to
    avoid, so it stays unrecorded and unscanned."""
    monkeypatch.setattr(analyze_service, "peek_scan_roots", lambda source: [tmp_path])
    monkeypatch.setattr(analyze_service, "has_cache", lambda root: False)

    def _fail_resolve(source, refresh=False):
        raise AssertionError("cache_only miss must not resolve scan roots")

    monkeypatch.setattr(analyze_service, "resolve_scan_roots", _fail_resolve)

    response = analyze_service.find_by_table(
        FindByTableRequest(
            source={"project": "orders", "repo": "orders"},
            table_name="TableA",
            cache_only=True,
        )
    )

    assert response.skipped is True
    assert capsys.readouterr().out == ""
