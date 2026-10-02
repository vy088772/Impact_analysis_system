"""find_by_sp() answers from the Derived Execution Evidence of its scope.

The freshness and reuse tests that drove find_by_sp() here moved to the module
seam: tests/test_derived_execution_evidence.py (derived-execution-evidence-one-
module, ticket 01). This file keeps the answers of the lookup, plus one
endpoint-seam test that gives fixed evidence through `evidence_source`.

Prior art for the seam: tests/test_graph_reverse_lookup.py drives find_by_sp()
directly with fixture scans/graphs.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from code_analyzer.csharp_analysis_gateway import DbInvocation, InvocationEvidence, InvocationSourceSpan
from code_analyzer.models import ClassInfo, FileAnalysisResult, FileType, FrameworkType, MethodInfo
from code_analyzer.project_scanner import ProjectScanResult
from service import analyze_service, derived_execution_evidence
from service.derived_execution_evidence import DerivedExecutionEvidence
from service.schemas import FindBySPRequest
from tests.derived_execution_evidence_fixtures import RatedInvocationsRetention
from tests.sql_cache_fixtures import (
    cache_payload,
    execution_graph,
    one_server_holds_every_database,
)


def _graph(*procedure_names: str) -> dict:
    return execution_graph(
        "OrdersDb",
        nodes=[
            {"id": f"stored_procedure:dbo.{name}", "type": "stored_procedure", "schema": "dbo", "name": name}
            for name in procedure_names
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


def _scan(root: Path, *, alpha_calls: str = "usp_Alpha", beta_calls: str = "usp_Beta") -> ProjectScanResult:
    """One repository scan with two programs, each calling one stored procedure."""
    alpha = _file(root, "AlphaPage.cs", "AlphaPage", "SaveAlpha")
    beta = _file(root, "BetaPage.cs", "BetaPage", "SaveBeta")
    raw = {
        str((root / name).resolve()): [
            {
                "class_name": class_name,
                "method_name": method_name,
                "command_text_kind": "literal",
                "command_text": procedure,
                "command_type_stored_procedure": True,
                "terminal_sink": "ExecuteNonQuery",
                "connection_expression": "conn",
                "start_offset": 10,
                "end_offset": 90,
            }
        ]
        for name, class_name, method_name, procedure in (
            ("AlphaPage.cs", "AlphaPage", "SaveAlpha", f"dbo.{alpha_calls}"),
            ("BetaPage.cs", "BetaPage", "SaveBeta", f"dbo.{beta_calls}"),
        )
    }
    return ProjectScanResult(
        project_root=str(root),
        project_name="orders",
        scan_time=datetime.now(),
        csharp_results=[alpha, beta],
        db_invocations=raw,
        connection_sources={
            str((root / name).resolve()): {"conn": "OrdersDb"} for name in ("AlphaPage.cs", "BetaPage.cs")
        },
    )


def _wire(
    monkeypatch,
    scan: ProjectScanResult,
    tmp_path: Path,
    graph: dict,
    *,
    scan_saved_at: str = "scan-v1",
    scan_commit: Optional[str] = "commit-v1",
    sql_cache_saved_at: str = "sql-cache-v1",
) -> None:
    """Wire scan/cache lookups so repeated calls see the same *recorded state*.

    Production reads the scan's and the SQL cache's recorded save time (ticket
    05) straight off disk, independently of whichever in-memory object a stub
    hands back for `_get_scan`/`load_cached` -- so a test double must stub
    those recorded-state reads explicitly, with a value that stays fixed
    across calls unless a test is deliberately proving invalidation. A stub
    that left them reading the real (nonexistent) disk state would return
    "not recorded" on every call, which ticket 05 treats as never matching
    itself -- that would force a fresh derivation on every request, defeating
    reuse for a reason unrelated to whatever a test is isolating.
    """
    sql_payload = cache_payload("OrdersDb", graph=graph)
    monkeypatch.setattr(analyze_service, "resolve_scan_roots", lambda source, refresh=False: [tmp_path])
    monkeypatch.setattr(analyze_service, "_get_scan", lambda root, refresh=False: scan)
    monkeypatch.setattr(derived_execution_evidence, "cached_saved_at", lambda root: scan_saved_at)
    monkeypatch.setattr(derived_execution_evidence, "cached_commit", lambda root: scan_commit)
    monkeypatch.setattr(
        analyze_service.sql_cache_store,
        "find_cache_identity",
        one_server_holds_every_database,
    )
    monkeypatch.setattr(
        analyze_service.sql_cache_store,
        "load_cached",
        lambda identity: sql_payload,
    )
    monkeypatch.setattr(
        analyze_service.sql_cache_store,
        "cached_saved_at",
        lambda identity: sql_cache_saved_at,
    )


def _request(sp_name: str, *, refresh: bool = False) -> FindBySPRequest:
    return FindBySPRequest(
        source={"project": "orders", "repo": "orders"},
        sp_name=sp_name,
        database="OrdersDb",
        cache_only=False,
        refresh=refresh,
    )


def _proven(class_name: str, method_name: str, procedure_name: str) -> DbInvocation:
    return DbInvocation(
        class_name=class_name,
        method_name=method_name,
        database="OrdersDb",
        procedure_name=procedure_name,
        evidence=InvocationEvidence.PROVEN,
        source=InvocationSourceSpan(relative_path=f"{class_name}.cs", start_offset=10, end_offset=90),
        command_text_literal="",
    )


# --------------------------------------------------------------- endpoint seam


def test_find_by_sp_filters_the_evidence_it_is_given(monkeypatch, tmp_path: Path) -> None:
    """The lookup keeps the invocations of the asked procedure and nothing else."""
    with RatedInvocationsRetention():
        _wire(monkeypatch, _scan(tmp_path), tmp_path, _graph("usp_Alpha", "usp_Beta"))
        # The scan has AlphaPage call usp_Alpha; this evidence says BetaPage does,
        # so the answer shows which of the two the lookup read.
        given = DerivedExecutionEvidence(
            [_proven("AlphaPage", "SaveAlpha", "usp_Gamma"), _proven("BetaPage", "SaveBeta", "usp_Alpha")],
            {},
        )
        asked_scopes: list = []

        def in_memory(scope, per_root_scans, merged_scan, root, *, refresh=False):
            asked_scopes.append(scope)
            return given

        response = analyze_service.find_by_sp(_request("dbo.usp_Alpha"), evidence_source=in_memory)

        assert [(m.program, m.file, m.caller) for m in response.matches] == [
            ("betapage", "BetaPage.cs", "BetaPage.SaveBeta")
        ]
        assert [scope.database for scope in asked_scopes] == ["OrdersDb"]


# ------------------------------------------------------------------- equivalence


def test_answer_identical_with_reuse_active_and_defeated_for_a_match(monkeypatch, tmp_path: Path) -> None:
    with RatedInvocationsRetention():
        scan = _scan(tmp_path)
        _wire(monkeypatch, scan, tmp_path, _graph("usp_Alpha", "usp_Beta"))

        analyze_service.find_by_sp(_request("dbo.usp_Alpha"))
        reused = analyze_service.find_by_sp(_request("dbo.usp_Alpha"))
        fresh = analyze_service.find_by_sp(_request("dbo.usp_Alpha", refresh=True))  # defeat reuse

        assert [(m.program, m.file) for m in reused.matches] == [(m.program, m.file) for m in fresh.matches]
        assert [m.program for m in reused.matches] == ["alphapage"]


def test_answer_identical_with_reuse_active_and_defeated_for_no_match(monkeypatch, tmp_path: Path) -> None:
    with RatedInvocationsRetention():
        scan = _scan(tmp_path)
        _wire(monkeypatch, scan, tmp_path, _graph("usp_Alpha", "usp_Beta"))

        analyze_service.find_by_sp(_request("dbo.usp_Missing"))
        reused = analyze_service.find_by_sp(_request("dbo.usp_Missing"))
        fresh = analyze_service.find_by_sp(_request("dbo.usp_Missing", refresh=True))  # defeat reuse

        assert reused.matches == [] == fresh.matches


def test_two_different_sp_names_in_one_scope_get_their_own_programs(monkeypatch, tmp_path: Path) -> None:
    """The evidence does not depend on which SP was asked about (ADR-0013)."""
    with RatedInvocationsRetention():
        _wire(monkeypatch, _scan(tmp_path), tmp_path, _graph("usp_Alpha", "usp_Beta"))

        alpha_response = analyze_service.find_by_sp(_request("dbo.usp_Alpha"))
        beta_response = analyze_service.find_by_sp(_request("dbo.usp_Beta"))

        assert [m.program for m in alpha_response.matches] == ["alphapage"]
        assert [m.program for m in beta_response.matches] == ["betapage"]


def _inline_scan(root: Path, command_text: str) -> ProjectScanResult:
    """One program whose only database call is inline SQL text, mode explicitly text."""
    alpha = _file(root, "AlphaPage.cs", "AlphaPage", "SaveAlpha")
    return ProjectScanResult(
        project_root=str(root),
        project_name="orders",
        scan_time=datetime.now(),
        csharp_results=[alpha],
        db_invocations={
            str((root / "AlphaPage.cs").resolve()): [
                {
                    "class_name": "AlphaPage",
                    "method_name": "SaveAlpha",
                    "command_text_kind": "literal",
                    "command_text": command_text,
                    "command_type_stored_procedure": False,
                    "command_type_mode": "text",
                    "terminal_sink": "ExecuteNonQuery",
                    "connection_expression": "conn",
                    "start_offset": 10,
                    "end_offset": 90,
                }
            ]
        },
        connection_sources={
            str((root / "AlphaPage.cs").resolve()): {"conn": "OrdersDb"}
        },
    )


def test_find_by_sp_finds_a_procedure_run_by_a_bare_name_in_inline_sql(
    monkeypatch, tmp_path: Path
) -> None:
    """T-SQL runs a batch whose first statement is a bare procedure name.

    The call reaches the database through an inline-SQL wrapper overload, so the
    invocation declares no procedure of its own -- but it runs one, and the
    reverse lookup exists to find exactly that.
    """
    with RatedInvocationsRetention():
        scan = _inline_scan(tmp_path, "[dbo].[usp_Alpha]")
        _wire(monkeypatch, scan, tmp_path, _graph("usp_Alpha"))

        response = analyze_service.find_by_sp(_request("dbo.usp_Alpha"))

        assert [match.program for match in response.matches] == ["alphapage"]
        # The row has to say which procedure it matched, and how it was named.
        assert response.matches[0].procedure_name == "usp_alpha"
        assert response.matches[0].procedure_name_source == "implicit_exec"


def test_find_by_sp_finds_a_procedure_run_by_inline_exec_text(
    monkeypatch, tmp_path: Path
) -> None:
    """The same call, written with the EXECUTE keyword the batch may omit."""
    with RatedInvocationsRetention():
        scan = _inline_scan(tmp_path, "EXEC dbo.usp_Alpha @OrderId")
        _wire(monkeypatch, scan, tmp_path, _graph("usp_Alpha"))

        response = analyze_service.find_by_sp(_request("dbo.usp_Alpha"))

        assert [match.program for match in response.matches] == ["alphapage"]
        assert response.matches[0].procedure_name_source == "exec_keyword"


def test_find_by_sp_ignores_a_procedure_merely_named_inside_inline_sql(
    monkeypatch, tmp_path: Path
) -> None:
    """A name inside a larger statement is not a call, and never becomes a match."""
    with RatedInvocationsRetention():
        scan = _inline_scan(tmp_path, "SELECT * FROM usp_Alpha")
        _wire(monkeypatch, scan, tmp_path, _graph("usp_Alpha"))

        response = analyze_service.find_by_sp(_request("dbo.usp_Alpha"))

        assert response.matches == []
        assert response.diagnostics == []


def test_find_by_sp_marks_a_declared_procedure_row_as_declared(monkeypatch, tmp_path: Path) -> None:
    """A call that selected stored-procedure mode names its own procedure."""
    with RatedInvocationsRetention():
        scan = _scan(tmp_path)
        _wire(monkeypatch, scan, tmp_path, _graph("usp_Alpha", "usp_Beta"))

        response = analyze_service.find_by_sp(_request("dbo.usp_Alpha"))

        assert response.matches[0].procedure_name_source == "declared"
        assert response.matches[0].procedure_name == "usp_alpha"
