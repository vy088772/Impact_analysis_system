"""Ticket 06: retention has a bound, and reaching it is observable.

ADR-0013 spends memory to buy latency and requires the retention bound to be
justified against the number of systems one Cross-system Lookup visits, and
requires reaching it to leave a trace rather than quietly discard work. This
module drives `find_by_sp()` across several distinct scopes (one per
`database`, everything else held fixed) with the bound turned down to a small
number via `settings.DERIVED_EXECUTION_EVIDENCE_RETENTION_LIMIT`, so eviction
is exercised without needing anything near the real catalog size.

Prior art for the fixtures below: tests/test_derived_execution_evidence_reuse.py
builds the same kind of two-program scan and wires the same stubs; this module
does not import from it (each reuse test module is self-contained, matching
tests/test_derived_execution_evidence_reuse_table.py's own separate fixtures).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from code_analyzer.project_scanner import ProjectScanResult
from code_analyzer.models import ClassInfo, FileAnalysisResult, FileType, FrameworkType, MethodInfo
from service import analyze_service
from service.schemas import FindBySPRequest
from tests.derived_execution_evidence_fixtures import RatedInvocationsRetention


def _graph() -> dict:
    return {
        "graph_version": 2,
        "database": "OrdersDb",
        "nodes": [
            {"id": "stored_procedure:dbo.usp_Alpha", "type": "stored_procedure", "schema": "dbo", "name": "usp_Alpha"},
        ],
        "relationships": [],
        "parse_errors": [],
    }


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
    """One repository scan, shared by every scope -- only `database` varies."""
    alpha = _file(root)
    raw = {
        str((root / "AlphaPage.cs").resolve()): [
            {
                "class_name": "AlphaPage",
                "method_name": "SaveAlpha",
                "command_text_kind": "literal",
                "command_text": "dbo.usp_Alpha",
                "command_type_stored_procedure": True,
                "terminal_sink": "ExecuteNonQuery",
                "connection_expression": "conn",
                "start_offset": 10,
                "end_offset": 90,
            }
        ]
    }
    return ProjectScanResult(
        project_root=str(root),
        project_name="orders",
        scan_time=datetime.now(),
        csharp_results=[alpha],
        db_invocations=raw,
        connection_sources={str((root / "AlphaPage.cs").resolve()): {"conn": "OrdersDb"}},
    )


def _wire(monkeypatch, scan: ProjectScanResult, tmp_path: Path) -> None:
    """Fixed recorded state across calls: ticket 05 keys reuse off each
    input's recorded save time, not object identity, so a stub must supply
    those reads explicitly (see tests/test_derived_execution_evidence_reuse.py's
    `_wire` docstring for why leaving them unset would defeat reuse)."""
    cache_payload = {"database": "OrdersDb", "schema": "dbo", "sql_execution_graph": _graph()}
    monkeypatch.setattr(analyze_service, "resolve_scan_roots", lambda source, refresh=False: [tmp_path])
    monkeypatch.setattr(analyze_service, "_get_scan", lambda root, refresh=False: scan)
    monkeypatch.setattr(analyze_service, "cached_saved_at", lambda root: "scan-v1")
    monkeypatch.setattr(analyze_service, "cached_commit", lambda root: "commit-v1")
    monkeypatch.setattr(
        analyze_service.sql_cache_store,
        "load_cached",
        lambda database, schema, server="": cache_payload,
    )
    monkeypatch.setattr(
        analyze_service.sql_cache_store,
        "cached_saved_at",
        lambda database, schema="dbo", server="": "sql-cache-v1",
    )


def _request(database: str) -> FindBySPRequest:
    return FindBySPRequest(
        source={"project": "orders", "repo": "orders"},
        sp_name="dbo.usp_Alpha",
        database=database,
        cache_only=False,
        refresh=False,
    )


def _scope_for(database: str, tmp_path: Path) -> analyze_service.DerivedExecutionEvidenceScope:
    return analyze_service.DerivedExecutionEvidenceScope.of(_request(database), [tmp_path])


def _count_real_derivations(monkeypatch) -> list:
    calls: list = []
    real = analyze_service._rated_execution_invocations

    def counting(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(analyze_service, "_rated_execution_invocations", counting)
    return calls


def test_exceeding_the_limit_evicts_the_oldest_scope_and_records_it(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.setattr(analyze_service.settings, "DERIVED_EXECUTION_EVIDENCE_RETENTION_LIMIT", 2)
    with RatedInvocationsRetention():
        scan = _scan(tmp_path)
        _wire(monkeypatch, scan, tmp_path)

        analyze_service.find_by_sp(_request("Db1"))
        analyze_service.find_by_sp(_request("Db2"))
        assert len(analyze_service._rated_invocations_retention) == 2

        capsys.readouterr()  # discard output from the first two, unbounded, insertions
        analyze_service.find_by_sp(_request("Db3"))

        retained = analyze_service._rated_invocations_retention
        assert len(retained) == 2
        assert _scope_for("Db1", tmp_path) not in retained
        assert _scope_for("Db2", tmp_path) in retained
        assert _scope_for("Db3", tmp_path) in retained

        printed = capsys.readouterr().out
        assert "已達上限" in printed
        assert "Db1" in printed


def test_eviction_never_changes_the_answer(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(analyze_service.settings, "DERIVED_EXECUTION_EVIDENCE_RETENTION_LIMIT", 1)
    with RatedInvocationsRetention():
        scan = _scan(tmp_path)
        _wire(monkeypatch, scan, tmp_path)
        calls = _count_real_derivations(monkeypatch)

        first = analyze_service.find_by_sp(_request("Db1"))
        assert len(calls) == 1

        # A second scope with the bound at 1 evicts Db1's retained entry.
        analyze_service.find_by_sp(_request("Db2"))
        assert _scope_for("Db1", tmp_path) not in analyze_service._rated_invocations_retention

        # Db1's next request finds nothing retained in memory, but ticket 06's
        # disk-backed store still holds Db1's evidence from the first call --
        # an eviction re-derives from scratch only when the disk store is also
        # absent, which test_derived_execution_evidence_disk_retention.py covers directly.
        again = analyze_service.find_by_sp(_request("Db1"))
        assert len(calls) == 2  # Db1 (1st), Db2 -- Db1's second answer came from disk

        assert [(m.program, m.file) for m in first.matches] == [(m.program, m.file) for m in again.matches]
