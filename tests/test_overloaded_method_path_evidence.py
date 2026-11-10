"""Path Evidence of a path through an overloaded C# method (Impact #9).

A method of a path is one call graph node (ADR-0044). Two overloads are two
nodes, so the Path Evidence holds the source of the overload the path goes
through, and not the source of the other overload.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from code_analyzer.csharp_analysis_gateway import (
    DbInvocation,
    InvocationEvidence,
    InvocationSourceSpan,
)
from code_analyzer.models import (
    CallSite,
    ClassInfo,
    FileAnalysisResult,
    FileType,
    FrameworkType,
    MethodInfo,
    MethodSourceSpan,
    SourceSnapshot,
)
from code_analyzer.project_scanner import ProjectScanResult
from service import analyze_service
from service.execution_path_builder import build_execution_paths
from service.schemas import PathEvidenceRequest
from service.sql_execution_graph import build_sql_execution_graph
from tests.derived_execution_evidence_fixtures import RatedInvocationsRetention
from tests.request_context_fixtures import RequestStores
from tests.sql_cache_fixtures import (
    analyzer_operation,
    cache_payload,
    in_memory_sql_text_analysis,
)

_SAVE_DEFINITION = "CREATE PROCEDURE dbo.usp_SaveOrder AS UPDATE dbo.SOrder SET Status = 1 WHERE Id = @Id;"
_LOG_DEFINITION = "CREATE PROCEDURE dbo.usp_LogOrder AS INSERT INTO dbo.OrderLog (Id) VALUES (@Id);"

_CONTENT = """class OrderPage
{
    public void Run()
    {
        Save(table, "x");
    }

    public void Audit()
    {
        Save();
    }

    public void Save()
    {
        ExecuteLog();
    }

    public void Save(DataTable table, string mode)
    {
        ExecuteSave();
    }
}
"""

_RUN = "OrderPage.Run()"
_AUDIT = "OrderPage.Audit()"
_SAVE_EMPTY = "OrderPage.Save()"
_SAVE_TABLE = "OrderPage.Save(System.Data.DataTable, string)"


@pytest.fixture(autouse=True)
def _isolated_retention():
    with RatedInvocationsRetention():
        yield


def _span(content: str, header: str, method_name: str, node: str, calls=()) -> MethodSourceSpan:
    start = content.index(f"    {header}")
    end = content.index("\n    }", start) + len("\n    }")
    return MethodSourceSpan(
        class_name="OrderPage",
        method_name=method_name,
        start_offset=start,
        end_offset=end,
        calls=list(calls),
        node=node,
    )


def _call(content: str, text: str, target_node: str) -> CallSite:
    start = content.index(text)
    return CallSite(
        call_text=text,
        start_offset=start,
        end_offset=start + len(text),
        target_class="OrderPage",
        target_method="Save",
        target_node=target_node,
    )


def _raw_invocation(content: str, call_text: str, procedure: str) -> dict:
    start = content.index(call_text)
    return {
        "class_name": "OrderPage",
        "method_name": "Save",
        "command_text_kind": "literal",
        "command_text": procedure,
        "command_type_stored_procedure": True,
        "terminal_sink": "ExecuteNonQuery",
        "connection_expression": "conn",
        "start_offset": start,
        "end_offset": start + len(call_text),
    }


def _scan(
    tmp_path: Path,
    content: str,
    methods: list[MethodInfo],
    spans: list[MethodSourceSpan],
    raw_invocations: list[dict],
) -> tuple[ProjectScanResult, dict]:
    """One `OrderPage.cs` scan, and a cache with `usp_SaveOrder` and `usp_LogOrder`."""
    source_file = tmp_path / "OrderPage.cs"
    source_file.write_text(content, encoding="utf-8")
    scan = ProjectScanResult(
        project_root=str(tmp_path),
        project_name="orders",
        scan_time=datetime.now(),
        csharp_results=[
            FileAnalysisResult(
                file_path=str(source_file),
                file_type=FileType.CSHARP,
                framework=FrameworkType.WEBFORMS,
                classes=[
                    ClassInfo(name="OrderPage", namespace="", file_path=str(source_file), methods=methods)
                ],
            )
        ],
        source_snapshots={
            "OrderPage.cs": SourceSnapshot(
                relative_path="OrderPage.cs",
                content_hash="snapshot-hash",
                content=content,
                method_spans=spans,
            )
        },
        db_invocations={str(source_file.resolve()): raw_invocations},
        connection_sources={str(source_file.resolve()): {"conn": "OrdersDb"}},
    )
    analysis = in_memory_sql_text_analysis(
        {
            _SAVE_DEFINITION: [analyzer_operation("UPDATE", writes=["dbo.SOrder"], where="Id = @Id")],
            _LOG_DEFINITION: [analyzer_operation("INSERT", writes=["dbo.OrderLog"])],
        }
    )

    def payload(graph=None) -> dict:
        return cache_payload(
            "OrdersDb",
            procedures={
                "dbo.usp_SaveOrder": {"definition": _SAVE_DEFINITION},
                "dbo.usp_LogOrder": {"definition": _LOG_DEFINITION},
            },
            tables=["dbo.SOrder", "dbo.OrderLog"],
            graph=graph,
        )

    return scan, payload(build_sql_execution_graph(payload(), sql_text_analysis=analysis))


def _overload_scan(tmp_path: Path) -> tuple[ProjectScanResult, dict]:
    """A class with `Save()` and `Save(DataTable, string)`; each overload calls its own procedure."""
    methods = [
        MethodInfo(name="Run", access_modifier="public", return_type="void", calls=["Save"]),
        MethodInfo(name="Audit", access_modifier="public", return_type="void", calls=["Save"]),
        MethodInfo(name="Save", access_modifier="public", return_type="void"),
        MethodInfo(name="Save", access_modifier="public", return_type="void"),
    ]
    spans = [
        _span(_CONTENT, "public void Run()", "Run", _RUN,
              [_call(_CONTENT, 'Save(table, "x")', _SAVE_TABLE)]),
        _span(_CONTENT, "public void Audit()", "Audit", _AUDIT,
              [_call(_CONTENT, "Save();", _SAVE_EMPTY)]),
        _span(_CONTENT, "public void Save()", "Save", _SAVE_EMPTY),
        _span(_CONTENT, "public void Save(DataTable", "Save", _SAVE_TABLE),
    ]
    return _scan(tmp_path, _CONTENT, methods, spans, [
        _raw_invocation(_CONTENT, "ExecuteSave();", "dbo.usp_SaveOrder"),
        _raw_invocation(_CONTENT, "ExecuteLog();", "dbo.usp_LogOrder"),
    ])


def _invocation(
    content: str,
    call_text: str,
    procedure: str,
    method_chain: tuple[str, ...],
    method_node_chain: tuple[str, ...] = (),
) -> DbInvocation:
    start = content.index(call_text)
    return DbInvocation(
        class_name="OrderPage",
        method_name="Save",
        database="OrdersDb",
        procedure_name=procedure,
        evidence=InvocationEvidence.PROVEN,
        source=InvocationSourceSpan("OrderPage.cs", start, start + len(call_text)),
        procedure_schema="dbo",
        method_chain=method_chain,
        method_node_chain=method_node_chain,
        source_snapshot_hash="snapshot-hash",
    )


def _path_id(cached: dict, invocation: DbInvocation) -> str:
    return build_execution_paths([invocation], cached["sql_execution_graph"])[0]["path_id"]


def _path_evidence(monkeypatch, tmp_path: Path, scan: ProjectScanResult, cached: dict, path_id: str):
    RequestStores.of(tmp_path, scan).install_path(monkeypatch)
    monkeypatch.setattr(analyze_service.sql_cache_store, "load_cached", lambda identity: cached)
    return analyze_service.get_path_evidence(
        PathEvidenceRequest(path_id=path_id, database="OrdersDb", program_names=["OrderPage"])
    )


def _materialize(scan: ProjectScanResult, cached: dict, invocation: DbInvocation):
    graph = cached["sql_execution_graph"]
    path = build_execution_paths([invocation], graph)[0]
    return analyze_service._materialize_path_evidence(
        path, invocation, scan, cached, graph, sql_cache_identity=None
    )


def test_path_through_the_second_overload_holds_only_that_overload(monkeypatch, tmp_path: Path) -> None:
    scan, cached = _overload_scan(tmp_path)
    path_id = _path_id(cached, _invocation(_CONTENT, "ExecuteSave();", "usp_saveorder", ("Run", "Save")))

    evidence = _path_evidence(monkeypatch, tmp_path, scan, cached, path_id)

    sources = [method["source"] for method in evidence.csharp_methods]
    assert [method["method"] for method in evidence.csharp_methods] == ["Run", "Save"]
    assert "public void Save(DataTable table, string mode)" in sources[1]
    assert not any("public void Save()" in source for source in sources)
    assert [procedure["name"] for procedure in evidence.stored_procedures] == ["dbo.usp_SaveOrder"]
    assert "UPDATE dbo.SOrder" in evidence.stored_procedures[0]["definition"]
    assert [operation["operation_type"] for operation in evidence.operations] == ["UPDATE"]


def test_path_through_the_first_overload_holds_only_that_overload(monkeypatch, tmp_path: Path) -> None:
    scan, cached = _overload_scan(tmp_path)
    path_id = _path_id(cached, _invocation(_CONTENT, "ExecuteLog();", "usp_logorder", ("Audit", "Save")))

    evidence = _path_evidence(monkeypatch, tmp_path, scan, cached, path_id)

    sources = [method["source"] for method in evidence.csharp_methods]
    assert [method["method"] for method in evidence.csharp_methods] == ["Audit", "Save"]
    assert "public void Save()" in sources[1]
    assert not any("DataTable" in source for source in sources)
    assert [procedure["name"] for procedure in evidence.stored_procedures] == ["dbo.usp_LogOrder"]
    assert [operation["operation_type"] for operation in evidence.operations] == ["INSERT"]


_PLAIN_CONTENT = """class OrderPage
{
    public void Run()
    {
        Save(table, "x");
    }

    public void Save(DataTable table, string mode)
    {
        ExecuteSave();
    }
}
"""


def test_a_file_without_overloads_keeps_the_chain_by_name(monkeypatch, tmp_path: Path) -> None:
    """The call in `Run` has no Bound Call Target; the name rule still links it, as before."""
    unbound = CallSite(call_text='Save(table, "x")', start_offset=0, end_offset=0, unresolved_reason="no_symbol")
    methods = [
        MethodInfo(name="Run", access_modifier="public", return_type="void", calls=["Save"]),
        MethodInfo(name="Save", access_modifier="public", return_type="void"),
    ]
    spans = [
        _span(_PLAIN_CONTENT, "public void Run()", "Run", _RUN, [unbound]),
        _span(_PLAIN_CONTENT, "public void Save(DataTable", "Save", _SAVE_TABLE),
    ]
    scan, cached = _scan(tmp_path, _PLAIN_CONTENT, methods, spans, [
        _raw_invocation(_PLAIN_CONTENT, "ExecuteSave();", "dbo.usp_SaveOrder"),
    ])
    path_id = _path_id(cached, _invocation(_PLAIN_CONTENT, "ExecuteSave();", "usp_saveorder", ("Run", "Save")))

    evidence = _path_evidence(monkeypatch, tmp_path, scan, cached, path_id)

    assert [method["method"] for method in evidence.csharp_methods] == ["Run", "Save"]
    assert [method["node"] for method in evidence.csharp_methods] == [_RUN, _SAVE_TABLE]


def test_path_without_nodes_through_an_overload_is_ambiguous(tmp_path: Path) -> None:
    """A path from before the node chain names its methods by simple name only."""
    scan, cached = _overload_scan(tmp_path)

    with pytest.raises(analyze_service.PathEvidenceError) as error:
        _materialize(scan, cached, _invocation(_CONTENT, "ExecuteSave();", "usp_saveorder", ("Save",)))

    assert error.value.code == "ambiguous_method"
    assert "ambiguous" in str(error.value)
    assert "不存在" not in str(error.value)


def test_path_without_nodes_through_a_method_not_in_the_snapshot_is_stale(tmp_path: Path) -> None:
    scan, cached = _overload_scan(tmp_path)

    with pytest.raises(analyze_service.PathEvidenceError) as error:
        _materialize(scan, cached, _invocation(_CONTENT, "ExecuteSave();", "usp_saveorder", ("Gone", "Save")))

    assert error.value.code == "stale_path"
    assert "不存在" in str(error.value)


def test_path_with_a_node_not_in_the_snapshot_is_stale(tmp_path: Path) -> None:
    """The simple name `Save` still exists, but the node of the path does not: the method changed."""
    scan, cached = _overload_scan(tmp_path)
    invocation = _invocation(
        _CONTENT, "ExecuteSave();", "usp_saveorder", ("Save",), method_node_chain=("OrderPage.Save(int)",)
    )

    with pytest.raises(analyze_service.PathEvidenceError) as error:
        _materialize(scan, cached, invocation)

    assert error.value.code == "stale_path"
    assert "OrderPage.Save(int)" in str(error.value)
