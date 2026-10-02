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

import pytest

from canonical_object_identity import parse
from code_analyzer.project_scanner import CSharpTableRelation, ProjectScanResult
from code_analyzer.models import ClassInfo, FileAnalysisResult, FileType, FrameworkType, MethodInfo
from code_analyzer.csharp_analysis_gateway import DbInvocation, InvocationEvidence, InvocationSourceSpan
from service import analyze_service, derived_execution_evidence
from service.derived_execution_evidence import DerivedExecutionEvidence
from service.schemas import FindByTableRequest, FlowChainRequest
from tests.derived_execution_evidence_fixtures import RatedInvocationsRetention
from tests.request_context_fixtures import RequestStores
from tests.sql_cache_fixtures import (
    cache_payload,
    execution_graph,
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
) -> RequestStores:
    """Same wiring as ticket 04's tests: fixed recorded state across calls, see
    that file's `_wire` docstring for why the freshness reads are stubbed
    explicitly (ticket 05 keys reuse off recorded save time, not identity)."""
    sql_payload = cache_payload("OrdersDb", graph=graph)
    monkeypatch.setattr(derived_execution_evidence, "cached_saved_at", lambda root: scan_saved_at)
    monkeypatch.setattr(derived_execution_evidence, "cached_commit", lambda root: scan_commit)
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
    return RequestStores.of(tmp_path, scan)


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


@pytest.mark.parametrize("database", ["OrdersDb", ""])
def test_backward_flow_uses_the_given_scope_paths_and_diagnostics(
    monkeypatch, tmp_path: Path, database: str
) -> None:
    scan = _scan(tmp_path)
    stores = _wire(monkeypatch, scan, tmp_path, _graph())
    proven = DbInvocation(
        class_name="AlphaPage",
        method_name="SaveAlpha",
        database="OrdersDb",
        procedure_name="usp_Alpha",
        evidence=InvocationEvidence.PROVEN,
        source=InvocationSourceSpan("AlphaPage.cs", 10, 90),
    )
    likely = DbInvocation(
        class_name="BetaPage",
        method_name="SaveBeta",
        database="OrdersDb",
        procedure_name="",
        evidence=InvocationEvidence.LIKELY,
        reason="fixed_unresolved_target",
        source=InvocationSourceSpan("BetaPage.cs", 10, 90),
    )
    given = DerivedExecutionEvidence(
        [proven, likely],
        _graph(),
        paths_by_invocation=[[
            {
                "path_id": "fixed-backward-path",
                "entry_method": "AlphaPage.SaveAlpha",
                "source_span": {"relative_path": "AlphaPage.cs"},
                "database": "OrdersDb",
                "evidence": "proven",
                "terminal_operation": "UPDATE",
                "sp_chain": ["dbo.usp_Alpha"],
                "writes": ["TableA"],
                "write_full_keys": [{"database": "OrdersDb", "schema": "dbo", "name": "TableA"}],
                "written_columns": ["X"],
            }
        ], []],
    )

    requested_scopes = []

    def source(scope, per_root_scans, merged_scan, root, *, needed_files=None, refresh=False):
        assert needed_files is None
        assert refresh is True
        requested_scopes.append(scope.database)
        return given

    response = analyze_service.flow_chain(
        FlowChainRequest(
            source={"project": "orders", "repo": "orders"},
            direction="backward",
            table_name="dbo.TableA",
            column_name="X",
            database=database,
            cache_only=False,
            refresh=True,
        ),
        evidence_source=source,
        scan_store=stores.scan_store,
        cache_store=stores.cache_store,
    )

    assert requested_scopes == [database]
    assert [(chain["file"], chain["method"], chain["path_id"], chain["access_type"])
            for chain in response.backward_chains] == (
        [("AlphaPage.cs", "SaveAlpha", "fixed-backward-path", "UPDATE")] if database else []
    )
    assert [diagnostic["reason"] for diagnostic in response.diagnostics] == (
        ["fixed_unresolved_target"] if database else []
    )


def test_find_by_table_filters_the_evidence_it_is_given(monkeypatch, tmp_path: Path) -> None:
    """The lookup keeps the paths that reach the asked table and nothing else."""
    with RatedInvocationsRetention():
        scan = _scan(tmp_path)
        stores = _wire(monkeypatch, scan, tmp_path, _graph())
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
            scan_store=stores.scan_store, cache_store=stores.cache_store,
        )

        assert [(m.program, m.file, m.access_type) for m in response.matches] == [
            ("alphapage", "AlphaPage.cs", "INSERT")
        ]


@pytest.mark.parametrize("first_endpoint", ["backward", "find_by_table"])
def test_backward_flow_reuses_the_whole_evidence_of_an_earlier_request(
    monkeypatch, tmp_path: Path, first_endpoint: str
) -> None:
    with RatedInvocationsRetention():
        stores = _wire(monkeypatch, _scan(tmp_path), tmp_path, _graph())

        def backward(table_name: str):
            return analyze_service.flow_chain(
                FlowChainRequest(
                    source={"project": "orders", "repo": "orders"},
                    direction="backward",
                    table_name=table_name,
                    database="OrdersDb",
                    cache_only=False,
                ),
                scan_store=stores.scan_store,
                cache_store=stores.cache_store,
            )

        if first_endpoint == "backward":
            first = backward("TableA")
            assert [chain["method"] for chain in first.backward_chains] == ["SaveAlpha"]
        else:
            lookup = analyze_service.find_by_table(
                _request("TableA"), scan_store=stores.scan_store, cache_store=stores.cache_store,
            )
            assert [match.caller_method for match in lookup.matches] == ["SaveAlpha"]

        _wire(monkeypatch, _scan(tmp_path, alpha_calls="usp_Beta"), tmp_path, _graph())
        stores.scan_store.scans[tmp_path] = _scan(tmp_path, alpha_calls="usp_Beta")
        retained = backward("TableA")
        second = backward("TableB")

        assert [(chain["method"], chain["access_type"]) for chain in retained.backward_chains] == [
            ("SaveAlpha", "UPDATE")
        ]
        assert [(chain["method"], chain["access_type"]) for chain in second.backward_chains] == [
            ("SaveBeta", "INSERT")
        ]
        assert second.diagnostics == []


def test_two_different_table_names_in_one_scope_get_their_own_programs(monkeypatch, tmp_path: Path) -> None:
    """The evidence does not depend on which table was asked about (ADR-0013)."""
    with RatedInvocationsRetention():
        stores = _wire(monkeypatch, _scan(tmp_path), tmp_path, _graph())

        table_a = analyze_service.find_by_table(
            _request("TableA"), scan_store=stores.scan_store, cache_store=stores.cache_store,
        )
        table_b = analyze_service.find_by_table(
            _request("TableB"), scan_store=stores.scan_store, cache_store=stores.cache_store,
        )

        assert [m.program for m in table_a.matches] == ["alphapage"]
        assert [m.program for m in table_b.matches] == ["betapage"]


# ------------------------------------------------------------------- equivalence


def test_answer_identical_with_reuse_active_and_defeated_for_a_match(monkeypatch, tmp_path: Path) -> None:
    with RatedInvocationsRetention():
        scan = _scan(tmp_path)
        stores = _wire(monkeypatch, scan, tmp_path, _graph())
        stores.install_table(monkeypatch)

        analyze_service.find_by_table(_request("TableA"))
        reused = analyze_service.find_by_table(_request("TableA"))

        fresh = analyze_service.find_by_table(_request("TableA", refresh=True))  # defeat reuse

        assert [(m.program, m.file, m.access_type) for m in reused.matches] == [
            (m.program, m.file, m.access_type) for m in fresh.matches
        ]


def test_answer_identical_with_reuse_active_and_defeated_for_no_match(monkeypatch, tmp_path: Path) -> None:
    with RatedInvocationsRetention():
        scan = _scan(tmp_path)
        stores = _wire(monkeypatch, scan, tmp_path, _graph())
        stores.install_table(monkeypatch)

        analyze_service.find_by_table(_request("TableMissing"))
        reused = analyze_service.find_by_table(_request("TableMissing"))

        fresh = analyze_service.find_by_table(_request("TableMissing", refresh=True))  # defeat reuse

        assert reused.matches == [] == fresh.matches


def test_answer_identical_with_reuse_active_and_defeated_for_write_only(monkeypatch, tmp_path: Path) -> None:
    with RatedInvocationsRetention():
        scan = _scan(tmp_path)
        stores = _wire(monkeypatch, scan, tmp_path, _graph())
        stores.install_table(monkeypatch)

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
        stores = _wire(monkeypatch, scan, tmp_path, graph)
        stores.install_table(monkeypatch)

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
        stores = _wire(monkeypatch, scan, tmp_path, _graph())
        stores.install_table(monkeypatch)

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
        stores = _wire(monkeypatch, scan, tmp_path, _graph())
        stores.install_table(monkeypatch)

        analyze_service.find_by_table(_request("TableA"))
        reused = analyze_service.find_by_table(_request("TableA"))

    with RatedInvocationsRetention():
        # A second, isolated retention scope: nothing here has ever been cached.
        fresh = analyze_service.find_by_table(_request("TableA"))

    assert [m.model_dump() for m in reused.matches] == [m.model_dump() for m in fresh.matches]
