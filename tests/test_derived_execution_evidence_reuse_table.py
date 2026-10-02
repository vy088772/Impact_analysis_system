"""find_by_table() answers from the Derived Execution Evidence of its scope.

The tests that counted rating and path building here moved to the module seam:
tests/test_derived_execution_evidence.py (derived-execution-evidence-one-module,
ticket 01). This file keeps the answers of the lookup, plus one endpoint-seam
test that gives fixed evidence through `evidence_source`.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from canonical_object_identity import parse
from code_analyzer.project_scanner import CSharpTableRelation, ProjectScanResult
from code_analyzer.models import ClassInfo, FileAnalysisResult, FileType, FrameworkType, MethodInfo
from code_analyzer.csharp_analysis_gateway import DbInvocation, InvocationEvidence, InvocationSourceSpan
from service import analyze_service, derived_execution_evidence
from service.derived_execution_evidence import DerivedExecutionEvidence
from service.schemas import FindByTableRequest
from tests.derived_execution_evidence_fixtures import RatedInvocationsRetention
from tests.sql_cache_fixtures import (
    cache_payload,
    execution_graph,
    one_server_holds_every_database,
)


def _graph() -> dict:
    """Two stored procedures, each writing a different table."""
    return execution_graph(
        "OrdersDb",
        nodes=[
            {"id": "stored_procedure:dbo.usp_Alpha", "type": "stored_procedure", "schema": "dbo", "name": "usp_Alpha"},
            {
                "id": "dml_operation:stored_procedure:dbo.usp_Alpha:1",
                "type": "dml_operation",
                "module_id": "stored_procedure:dbo.usp_Alpha",
                "sequence": 1,
                "operation_type": "UPDATE",
            },
            {"id": "stored_procedure:dbo.usp_Beta", "type": "stored_procedure", "schema": "dbo", "name": "usp_Beta"},
            {
                "id": "dml_operation:stored_procedure:dbo.usp_Beta:1",
                "type": "dml_operation",
                "module_id": "stored_procedure:dbo.usp_Beta",
                "sequence": 1,
                "operation_type": "INSERT",
            },
            {"id": "table:dbo.TableA", "type": "table", "schema": "dbo", "name": "TableA"},
            {"id": "table:dbo.TableB", "type": "table", "schema": "dbo", "name": "TableB"},
        ],
        relationships=[
            {
                "type": "contains",
                "source": "stored_procedure:dbo.usp_Alpha",
                "target": "dml_operation:stored_procedure:dbo.usp_Alpha:1",
            },
            {
                "type": "writes",
                "source": "dml_operation:stored_procedure:dbo.usp_Alpha:1",
                "target": "table:dbo.TableA",
                "columns": ["X"],
            },
            {
                "type": "contains",
                "source": "stored_procedure:dbo.usp_Beta",
                "target": "dml_operation:stored_procedure:dbo.usp_Beta:1",
            },
            {
                "type": "writes",
                "source": "dml_operation:stored_procedure:dbo.usp_Beta:1",
                "target": "table:dbo.TableB",
                "columns": ["Y"],
            },
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


def _scan(root: Path, *, alpha_calls: str = "usp_Alpha") -> ProjectScanResult:
    """One repository scan with two programs: AlphaPage calls a stored procedure
    that writes TableA (name configurable to simulate a changed scan); BetaPage
    calls one that writes TableB. No inline SQL facts, so every match below is
    graph-derived -- the seam this ticket touches."""
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
            ("BetaPage.cs", "BetaPage", "SaveBeta", "dbo.usp_Beta"),
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
    """Same wiring as ticket 04's tests: fixed recorded state across calls, see
    that file's `_wire` docstring for why the freshness reads are stubbed
    explicitly (ticket 05 keys reuse off recorded save time, not identity)."""
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


def _request(table_name: str, *, write_only: bool = False, refresh: bool = False) -> FindByTableRequest:
    return FindByTableRequest(
        source={"project": "orders", "repo": "orders"},
        table_name=table_name,
        database="OrdersDb",
        cache_only=False,
        write_only=write_only,
        refresh=refresh,
    )


# --------------------------------------------------------------- endpoint seam


def test_find_by_table_filters_the_evidence_it_is_given(monkeypatch, tmp_path: Path) -> None:
    """The lookup keeps the paths that reach the asked table and nothing else."""
    with RatedInvocationsRetention():
        scan = _scan(tmp_path)
        _wire(monkeypatch, scan, tmp_path, _graph())
        rated = [
            DbInvocation(
                class_name=class_name,
                method_name=method_name,
                database="OrdersDb",
                procedure_name=procedure_name,
                evidence=InvocationEvidence.PROVEN,
                source=InvocationSourceSpan(relative_path=f"{class_name}.cs", start_offset=10, end_offset=90),
                command_text_literal="",
            )
            # The scan has AlphaPage call usp_Alpha; this evidence says usp_Beta,
            # so the answer shows which of the two the lookup read.
            for class_name, method_name, procedure_name in (("AlphaPage", "SaveAlpha", "usp_Beta"),)
        ]
        given = DerivedExecutionEvidence(rated, _graph())

        response = analyze_service.find_by_table(
            _request("TableB"),
            evidence_source=lambda scope, per_root_scans, merged_scan, root, *, refresh=False: given,
        )

        assert [(m.program, m.file, m.access_type) for m in response.matches] == [
            ("alphapage", "AlphaPage.cs", "INSERT")
        ]


def test_two_different_table_names_in_one_scope_get_their_own_programs(monkeypatch, tmp_path: Path) -> None:
    """The evidence does not depend on which table was asked about (ADR-0013)."""
    with RatedInvocationsRetention():
        _wire(monkeypatch, _scan(tmp_path), tmp_path, _graph())

        table_a = analyze_service.find_by_table(_request("TableA"))
        table_b = analyze_service.find_by_table(_request("TableB"))

        assert [m.program for m in table_a.matches] == ["alphapage"]
        assert [m.program for m in table_b.matches] == ["betapage"]


# ------------------------------------------------------------------- equivalence


def test_answer_identical_with_reuse_active_and_defeated_for_a_match(monkeypatch, tmp_path: Path) -> None:
    with RatedInvocationsRetention():
        scan = _scan(tmp_path)
        _wire(monkeypatch, scan, tmp_path, _graph())

        analyze_service.find_by_table(_request("TableA"))
        reused = analyze_service.find_by_table(_request("TableA"))

        fresh = analyze_service.find_by_table(_request("TableA", refresh=True))  # defeat reuse

        assert [(m.program, m.file, m.access_type) for m in reused.matches] == [
            (m.program, m.file, m.access_type) for m in fresh.matches
        ]


def test_answer_identical_with_reuse_active_and_defeated_for_no_match(monkeypatch, tmp_path: Path) -> None:
    with RatedInvocationsRetention():
        scan = _scan(tmp_path)
        _wire(monkeypatch, scan, tmp_path, _graph())

        analyze_service.find_by_table(_request("TableMissing"))
        reused = analyze_service.find_by_table(_request("TableMissing"))

        fresh = analyze_service.find_by_table(_request("TableMissing", refresh=True))  # defeat reuse

        assert reused.matches == [] == fresh.matches


def test_answer_identical_with_reuse_active_and_defeated_for_write_only(monkeypatch, tmp_path: Path) -> None:
    with RatedInvocationsRetention():
        scan = _scan(tmp_path)
        _wire(monkeypatch, scan, tmp_path, _graph())

        analyze_service.find_by_table(_request("TableA", write_only=True))
        reused = analyze_service.find_by_table(_request("TableA", write_only=True))

        fresh = analyze_service.find_by_table(_request("TableA", write_only=True, refresh=True))  # defeat reuse

        assert [(m.program, m.access_type) for m in reused.matches] == [
            (m.program, m.access_type) for m in fresh.matches
        ]
        assert [m.access_type for m in reused.matches] == ["UPDATE"]


def test_write_only_still_excludes_reads(monkeypatch, tmp_path: Path) -> None:
    """`write_only` filtering is untouched by this ticket -- proven against a
    table reached only by a READ, not a WRITE."""
    with RatedInvocationsRetention():
        graph = _graph()
        graph["nodes"].append(
            {
                "id": "dml_operation:stored_procedure:dbo.usp_Alpha:2",
                "type": "dml_operation",
                "module_id": "stored_procedure:dbo.usp_Alpha",
                "sequence": 2,
                "operation_type": "SELECT",
            }
        )
        graph["nodes"].append({"id": "table:dbo.TableC", "type": "table", "schema": "dbo", "name": "TableC"})
        graph["relationships"].append(
            {
                "type": "contains",
                "source": "stored_procedure:dbo.usp_Alpha",
                "target": "dml_operation:stored_procedure:dbo.usp_Alpha:2",
            }
        )
        graph["relationships"].append(
            {
                "type": "reads",
                "source": "dml_operation:stored_procedure:dbo.usp_Alpha:2",
                "target": "table:dbo.TableC",
            }
        )
        scan = _scan(tmp_path)
        _wire(monkeypatch, scan, tmp_path, graph)

        all_access = analyze_service.find_by_table(_request("TableC", write_only=False))
        write_only = analyze_service.find_by_table(_request("TableC", write_only=True))

        assert [m.program for m in all_access.matches] == ["alphapage"]
        assert write_only.matches == []


def test_embedded_sql_and_graph_derived_preference_rule_is_unchanged(monkeypatch, tmp_path: Path) -> None:
    """The blending/preference rule between inline C# SQL matches and
    graph-derived matches (`_prefer_table_match`) is not touched by this
    ticket -- a write from either source must still beat a read for the same
    file."""
    with RatedInvocationsRetention():
        scan = _scan(tmp_path)
        scan.table_relations.append(
            CSharpTableRelation(
                csharp_file=str(tmp_path / "AlphaPage.cs"),
                class_name="AlphaPage",
                method_name="SaveAlpha",
                line_number=1,
                table=parse("TableA"),
                database="OrdersDb",
                access_type="READ",
            )
        )
        _wire(monkeypatch, scan, tmp_path, _graph())

        result = analyze_service.find_by_table(_request("TableA"))

        alpha_matches = [m for m in result.matches if m.program == "alphapage"]
        assert len(alpha_matches) == 1
        assert alpha_matches[0].access_type == "UPDATE"  # the graph-derived write wins over the inline read


# ------------------------------------------------------------------- response shape


def test_response_field_shape_matches_a_fresh_scope(monkeypatch, tmp_path: Path) -> None:
    """A reused response and a response derived in a brand-new, never-cached
    scope carry exactly the same fields with exactly the same values -- proof
    that routing path-building through retention did not add, drop, or rename
    anything on `TableMatchProgram`."""
    with RatedInvocationsRetention():
        scan = _scan(tmp_path)
        _wire(monkeypatch, scan, tmp_path, _graph())

        analyze_service.find_by_table(_request("TableA"))
        reused = analyze_service.find_by_table(_request("TableA"))

    with RatedInvocationsRetention():
        # A second, isolated retention scope: nothing here has ever been cached.
        fresh = analyze_service.find_by_table(_request("TableA"))

    assert [m.model_dump() for m in reused.matches] == [m.model_dump() for m in fresh.matches]
