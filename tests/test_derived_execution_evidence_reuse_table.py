"""Ticket 05: find_by_table() builds Execution Paths once per scope, not once
per request and not once per table asked within that scope.

Prior art for the seam and the counting style: tests/test_derived_execution_evidence_reuse.py
(ticket 04) proves the same thing for the rating step alone, using find_by_sp();
this file drives the larger of the two reverse lookups, find_by_table(), and
additionally counts calls to `build_execution_paths` (via
`analyze_service.build_execution_paths`, the module-level name
`_execution_paths_for_scope` calls), since that -- not the rating step -- is
where ticket 05 says the measured wait actually goes away.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from code_analyzer.project_scanner import CSharpTableRelation, ProjectScanResult
from code_analyzer.models import ClassInfo, FileAnalysisResult, FileType, FrameworkType, MethodInfo
from service import analyze_service
from service.schemas import FindByTableRequest
from tests.derived_execution_evidence_fixtures import RatedInvocationsRetention


def _graph() -> dict:
    """Two stored procedures, each writing a different table."""
    return {
        "graph_version": 2,
        "database": "OrdersDb",
        "nodes": [
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
        "relationships": [
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
        "parse_errors": [],
    }


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


def _wire(monkeypatch, scan: ProjectScanResult, tmp_path: Path, graph: dict) -> None:
    """Same wiring as ticket 04's tests: fixed objects across calls, see that
    file's `_wire` docstring for why the SQL cache payload is built once."""
    cache_payload = {"database": "OrdersDb", "schema": "dbo", "sql_execution_graph": graph}
    monkeypatch.setattr(analyze_service, "resolve_scan_roots", lambda source, refresh=False: [tmp_path])
    monkeypatch.setattr(analyze_service, "_get_scan", lambda root, refresh=False: scan)
    monkeypatch.setattr(
        analyze_service.sql_cache_store,
        "load_cached",
        lambda database, schema, server="": cache_payload,
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


def _count_real_rating_derivations(monkeypatch) -> list:
    """Wrap the real rating step with a counter, still calling through to it."""
    calls: list = []
    real = analyze_service._rated_execution_invocations

    def counting(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(analyze_service, "_rated_execution_invocations", counting)
    return calls


def _count_real_path_builds(monkeypatch) -> list:
    """Wrap the real path builder with a counter, still calling through to it."""
    calls: list = []
    real = analyze_service.build_execution_paths

    def counting(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(analyze_service, "build_execution_paths", counting)
    return calls


# --------------------------------------------------------------- reuse itself


def test_two_consecutive_table_lookups_in_one_scope_build_execution_paths_once(monkeypatch, tmp_path: Path) -> None:
    with RatedInvocationsRetention():
        scan = _scan(tmp_path)
        _wire(monkeypatch, scan, tmp_path, _graph())
        rating_calls = _count_real_rating_derivations(monkeypatch)
        path_calls = _count_real_path_builds(monkeypatch)

        first = analyze_service.find_by_table(_request("TableA"))
        second = analyze_service.find_by_table(_request("TableA"))

        assert len(rating_calls) == 1
        assert len(path_calls) == 1
        assert [(m.program, m.file) for m in first.matches] == [(m.program, m.file) for m in second.matches]


def test_two_different_table_names_in_one_scope_derive_once_between_them(monkeypatch, tmp_path: Path) -> None:
    """The decisive test: two DIFFERENT tables asked in one scope must still
    build Execution Paths only once between them, proving reuse does not
    depend on which question was asked (ADR-0013)."""
    with RatedInvocationsRetention():
        scan = _scan(tmp_path)
        _wire(monkeypatch, scan, tmp_path, _graph())
        rating_calls = _count_real_rating_derivations(monkeypatch)
        path_calls = _count_real_path_builds(monkeypatch)

        table_a = analyze_service.find_by_table(_request("TableA"))
        table_b = analyze_service.find_by_table(_request("TableB"))

        assert len(rating_calls) == 1
        assert len(path_calls) == 1
        assert [m.program for m in table_a.matches] == ["alphapage"]
        assert [m.program for m in table_b.matches] == ["betapage"]


# ------------------------------------------------------------------- equivalence


def test_answer_identical_with_reuse_active_and_defeated_for_a_match(monkeypatch, tmp_path: Path) -> None:
    with RatedInvocationsRetention():
        scan = _scan(tmp_path)
        _wire(monkeypatch, scan, tmp_path, _graph())

        analyze_service.find_by_table(_request("TableA"))
        reused = analyze_service.find_by_table(_request("TableA"))

        analyze_service._rated_invocations_retention.clear()  # defeat reuse
        analyze_service.find_by_table(_request("TableA"))
        fresh = analyze_service.find_by_table(_request("TableA"))

        assert [(m.program, m.file, m.access_type) for m in reused.matches] == [
            (m.program, m.file, m.access_type) for m in fresh.matches
        ]


def test_answer_identical_with_reuse_active_and_defeated_for_no_match(monkeypatch, tmp_path: Path) -> None:
    with RatedInvocationsRetention():
        scan = _scan(tmp_path)
        _wire(monkeypatch, scan, tmp_path, _graph())

        analyze_service.find_by_table(_request("TableMissing"))
        reused = analyze_service.find_by_table(_request("TableMissing"))

        analyze_service._rated_invocations_retention.clear()  # defeat reuse
        analyze_service.find_by_table(_request("TableMissing"))
        fresh = analyze_service.find_by_table(_request("TableMissing"))

        assert reused.matches == [] == fresh.matches


def test_answer_identical_with_reuse_active_and_defeated_for_write_only(monkeypatch, tmp_path: Path) -> None:
    with RatedInvocationsRetention():
        scan = _scan(tmp_path)
        _wire(monkeypatch, scan, tmp_path, _graph())

        analyze_service.find_by_table(_request("TableA", write_only=True))
        reused = analyze_service.find_by_table(_request("TableA", write_only=True))

        analyze_service._rated_invocations_retention.clear()  # defeat reuse
        analyze_service.find_by_table(_request("TableA", write_only=True))
        fresh = analyze_service.find_by_table(_request("TableA", write_only=True))

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
                table_name="TableA",
                database="OrdersDb",
                access_type="READ",
            )
        )
        _wire(monkeypatch, scan, tmp_path, _graph())

        result = analyze_service.find_by_table(_request("TableA"))

        alpha_matches = [m for m in result.matches if m.program == "alphapage"]
        assert len(alpha_matches) == 1
        assert alpha_matches[0].access_type == "UPDATE"  # the graph-derived write wins over the inline read


# --------------------------------------------------------------- invalidation


def test_a_changed_repository_scan_causes_a_fresh_path_build(monkeypatch, tmp_path: Path) -> None:
    with RatedInvocationsRetention():
        first_scan = _scan(tmp_path)
        second_scan = _scan(tmp_path, alpha_calls="usp_Beta")
        scans = [first_scan, second_scan]
        cache_payload = {"database": "OrdersDb", "schema": "dbo", "sql_execution_graph": _graph()}
        monkeypatch.setattr(analyze_service, "resolve_scan_roots", lambda source, refresh=False: [tmp_path])
        monkeypatch.setattr(analyze_service, "_get_scan", lambda root, refresh=False: scans.pop(0))
        monkeypatch.setattr(
            analyze_service.sql_cache_store, "load_cached", lambda database, schema, server="": cache_payload
        )
        rating_calls = _count_real_rating_derivations(monkeypatch)
        path_calls = _count_real_path_builds(monkeypatch)

        before = analyze_service.find_by_table(_request("TableA"))
        after = analyze_service.find_by_table(_request("TableA"))

        assert len(rating_calls) == 2
        assert len(path_calls) == 2
        assert [m.program for m in before.matches] == ["alphapage"]
        assert after.matches == []  # AlphaPage now calls usp_Beta, which writes TableB, not TableA


def test_an_explicit_refresh_always_rebuilds_execution_paths(monkeypatch, tmp_path: Path) -> None:
    with RatedInvocationsRetention():
        scan = _scan(tmp_path)
        _wire(monkeypatch, scan, tmp_path, _graph())
        rating_calls = _count_real_rating_derivations(monkeypatch)
        path_calls = _count_real_path_builds(monkeypatch)

        analyze_service.find_by_table(_request("TableA"))
        analyze_service.find_by_table(_request("TableA", refresh=True))
        analyze_service.find_by_table(_request("TableA", refresh=True))

        assert len(rating_calls) == 3
        assert len(path_calls) == 3


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
