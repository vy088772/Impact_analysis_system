"""Seam 2: an inline read of a View or a Function reaches the tables behind it.

Each case builds a SQL Execution Graph from a cache payload, and a C# Scan
Result whose table relations read a View or a Function. The by-table query of
the inline table relations module takes that graph, as `/find_by_table` and
`/flow_chain` backward give it when the request names a Database.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Mapping, Optional, Sequence

import pytest

from canonical_object_identity import parse
from code_analyzer.csharp_analysis_gateway import DbInvocation, InvocationEvidence, InvocationSourceSpan
from code_analyzer.models import MethodInfo
from code_analyzer.project_scanner import INLINE_SQL_PARSED, INLINE_SQL_REGEX, ProjectScanResult
from service import analyze_service, inline_table_relations
from service.schemas import AnalyzeRequest, AzureSource, FindByTableRequest, FlowChainRequest
from service.sql_cache_store import CacheIdentity, build_object_location_index
from service.sql_execution_graph import build_sql_execution_graph
from service.table_match import TableQuestion
from tests.sql_cache_fixtures import (
    analyzer_operation,
    cache_payload,
    in_memory_sql_text_analysis,
    one_server_holds_every_database,
)
from tests.test_flow_chain_inline_tables import _relation, _scan as _flow_scan
from tests.test_table_match import _inline_scan

_SOURCE = AzureSource(project="orders", repo="orders")


@pytest.fixture(autouse=True)
def _no_object_location_index(monkeypatch) -> None:
    monkeypatch.setattr(inline_table_relations.sql_cache_store, "find_cache_identity", lambda database: None)


def _graph(
    views: Mapping[str, list[str]] = {},
    functions: Mapping[str, list[str]] = {},
    database: str = "PUR",
) -> dict:
    """A graph whose each View and Function reads the written names that it maps to."""
    modules = {**views, **functions}
    return build_sql_execution_graph(
        cache_payload(
            database,
            views={name: {"definition": name} for name in views},
            functions={name: {"definition": name} for name in functions},
            tables=["dbo.Orders", "dbo.Customers"],
        ),
        sql_text_analysis=in_memory_sql_text_analysis(
            {name: [analyzer_operation("SELECT", reads=reads)] for name, reads in modules.items()}
        ),
    )


def _scan(tmp_path: Path, read: str, reason: str = INLINE_SQL_PARSED, connection_database: str = "PUR"):
    scan = _inline_scan(tmp_path, parse(read), connection_database)
    access_type = "SELECT" if reason == INLINE_SQL_PARSED else "UNRESOLVED"
    scan.table_relations[:] = [replace(scan.table_relations[0], access_type=access_type, reason=reason)]
    return scan


def _answers(scan: ProjectScanResult, table_name: str, graph: Optional[dict], root: Path):
    question = TableQuestion.of(table_name, "PUR" if graph is not None else "")
    return [
        (
            answer.access_type,
            answer.table.name,
            answer.through.schema if answer.through else None,
            answer.through.name if answer.through else None,
        )
        for answer in inline_table_relations.by_table(scan, question, [], root, graph)
    ]


def test_a_parsed_read_of_a_view_reaches_the_table_behind_it(tmp_path) -> None:
    graph = _graph(views={"dbo.vOrder": ["dbo.Orders"]})

    assert _answers(_scan(tmp_path, "dbo.vOrder"), "Orders", graph, tmp_path) == [
        ("READ_INDIRECT", "Orders", "dbo", "vOrder")
    ]


def test_the_relation_still_gives_its_direct_answer_to_the_view(tmp_path) -> None:
    graph = _graph(views={"dbo.vOrder": ["dbo.Orders"]})

    assert _answers(_scan(tmp_path, "dbo.vOrder"), "vOrder", graph, tmp_path) == [
        ("SELECT", "vOrder", None, None)
    ]


def test_a_fallback_read_of_a_view_reaches_the_table_unresolved(tmp_path) -> None:
    graph = _graph(views={"dbo.vOrder": ["dbo.Orders"]})

    assert _answers(_scan(tmp_path, "dbo.vOrder", INLINE_SQL_REGEX), "Orders", graph, tmp_path) == [
        ("UNRESOLVED", "Orders", "dbo", "vOrder")
    ]


def test_a_view_that_reads_a_function_names_the_view_that_the_relation_reads(tmp_path) -> None:
    graph = _graph(views={"dbo.vOrder": ["dbo.fnOrders"]}, functions={"dbo.fnOrders": ["dbo.Orders"]})

    assert _answers(_scan(tmp_path, "dbo.vOrder"), "Orders", graph, tmp_path) == [
        ("READ_INDIRECT", "Orders", "dbo", "vOrder")
    ]


def test_a_read_of_a_table_valued_function_reaches_the_table_behind_it(tmp_path) -> None:
    graph = _graph(functions={"dbo.fun_GetRoleOrderTypeList": ["dbo.Orders"]})

    assert _answers(_scan(tmp_path, "dbo.fun_GetRoleOrderTypeList"), "Orders", graph, tmp_path) == [
        ("READ_INDIRECT", "Orders", "dbo", "fun_GetRoleOrderTypeList")
    ]


def test_a_view_and_a_function_that_read_each_other_give_a_finite_answer(tmp_path) -> None:
    graph = _graph(
        views={"dbo.vOrder": ["dbo.fnOrders", "dbo.Customers"]},
        functions={"dbo.fnOrders": ["dbo.vOrder", "dbo.Orders"]},
    )

    assert _answers(_scan(tmp_path, "dbo.vOrder"), "Orders", graph, tmp_path) == [
        ("READ_INDIRECT", "Orders", "dbo", "vOrder")
    ]
    assert _answers(_scan(tmp_path, "dbo.fnOrders"), "Customers", graph, tmp_path) == [
        ("READ_INDIRECT", "Customers", "dbo", "fnOrders")
    ]


def test_with_no_graph_a_read_of_a_view_gives_no_answer_to_the_table(tmp_path) -> None:
    assert _answers(_scan(tmp_path, "dbo.vOrder"), "Orders", None, tmp_path) == []


def test_a_relation_that_states_another_database_reaches_nothing(tmp_path) -> None:
    graph = _graph(views={"dbo.vOrder": ["dbo.Orders"]})

    assert _answers(_scan(tmp_path, "STC.dbo.vOrder"), "Orders", graph, tmp_path) == []


def test_a_relation_whose_connection_names_another_database_reaches_nothing(tmp_path) -> None:
    """The SQL text states no Database, and the connection names `STC`: the graph of `PUR` holds no `dbo.vOrder` of `STC`."""
    graph = _graph(views={"dbo.vOrder": ["dbo.Orders"]})

    assert _answers(_scan(tmp_path, "dbo.vOrder", connection_database="STC"), "Orders", graph, tmp_path) == []


def test_a_relation_with_an_unresolved_connection_database_uses_the_graph(tmp_path) -> None:
    graph = _graph(views={"dbo.vOrder": ["dbo.Orders"]})

    assert _answers(_scan(tmp_path, "dbo.vOrder", connection_database=""), "Orders", graph, tmp_path) == [
        ("READ_INDIRECT", "Orders", "dbo", "vOrder")
    ]


def test_a_relation_that_states_no_schema_reaches_through_the_listed_dbo_view(monkeypatch, tmp_path) -> None:
    """Schema Resolution against the graph's Database gives the relation `dbo` from the index."""
    identity = CacheIdentity.of("vmsystest07", "PUR")
    index = build_object_location_index(identity, cache_payload("PUR", views=["dbo.vOrder"]))
    monkeypatch.setattr(inline_table_relations.sql_cache_store, "find_cache_identity", lambda database: identity)
    monkeypatch.setattr(inline_table_relations.sql_cache_store, "load_object_location_index", lambda given: index)
    graph = _graph(views={"dbo.vOrder": ["dbo.Orders"]})

    assert _answers(_scan(tmp_path, "vOrder", connection_database=""), "Orders", graph, tmp_path) == [
        ("READ_INDIRECT", "Orders", "dbo", "vOrder")
    ]


def _serve(
    monkeypatch, root: Path, scan: ProjectScanResult, graph: dict, rated: Sequence[DbInvocation] = ()
) -> None:
    """Serve the scan, the graph, and the rated invocations to `/find_by_table` and `/flow_chain`.

    No Execution Path exists.
    """
    monkeypatch.setattr(analyze_service, "resolve_scan_roots", lambda source, refresh=False: [root])
    monkeypatch.setattr(analyze_service, "_get_scan", lambda given, refresh=False: scan)
    monkeypatch.setattr(analyze_service, "_require_sql_execution_graph", lambda name, server="", **_: (None, graph))
    monkeypatch.setattr(
        analyze_service, "_execution_paths_for_scope", lambda *args, **kwargs: (list(rated), graph, [])
    )
    monkeypatch.setattr(analyze_service, "_rated_execution_invocations", lambda *args, **kwargs: (list(rated), graph))


def _find_by_table(table_name: str, write_only: bool = False):
    return analyze_service.find_by_table(
        FindByTableRequest(
            source=_SOURCE, table_name=table_name, database="PUR", cache_only=False, write_only=write_only
        )
    )


def _view_reader_scan(root: Path, *relations: tuple[str, str]) -> ProjectScanResult:
    """One `OrderPage.cs` whose method `Load` reads each (written name, access type)."""
    load = MethodInfo(name="Load", access_modifier="private", return_type="void")
    return _flow_scan(
        root,
        [load],
        [replace(_relation(root, "Load", parse(read), access_type), database="PUR") for read, access_type in relations],
    )


def test_find_by_table_names_the_view_that_a_reached_record_passes_through(monkeypatch, tmp_path) -> None:
    _serve(monkeypatch, tmp_path, _view_reader_scan(tmp_path, ("dbo.vOrder", "SELECT")), _graph(
        views={"dbo.vOrder": ["dbo.Orders"]}
    ))

    response = _find_by_table("Orders")

    assert [
        (match.file, match.access_type, match.table, match.read_through, match.reason, match.evidence_status)
        for match in response.matches
    ] == [("OrderPage.cs", "READ_INDIRECT", "Orders", "dbo.vOrder", INLINE_SQL_PARSED, "not_applicable")]
    assert [(match.access_type, match.read_through) for match in _find_by_table("vOrder").matches] == [
        ("SELECT", "")
    ]


def test_a_reached_record_takes_the_database_fields_of_its_rated_invocation(monkeypatch, tmp_path) -> None:
    """A parsed relation whose invocation has candidates still reaches through the graph, and its record keeps them."""
    scan = _view_reader_scan(tmp_path, ("dbo.vOrder", "SELECT"))
    scan.table_relations[:] = [replace(scan.table_relations[0], invocation_span=(154, 310))]
    rated = DbInvocation(
        class_name="OrderPage",
        method_name="Load",
        database=None,
        procedure_name=None,
        evidence=InvocationEvidence.UNRESOLVED,
        source=InvocationSourceSpan("OrderPage.cs", 154, 310),
        database_candidates=("PUR", "STC"),
    )
    _serve(monkeypatch, tmp_path, scan, _graph(views={"dbo.vOrder": ["dbo.Orders"]}), [rated])

    (match,) = _find_by_table("Orders").matches

    assert (match.access_type, match.read_through) == ("READ_INDIRECT", "dbo.vOrder")
    assert (match.database, list(match.database_candidates), match.database_attribution) == (
        "",
        ["PUR", "STC"],
        "candidate",
    )


def test_find_by_table_keeps_the_direct_read_when_one_file_also_reads_through_a_view(
    monkeypatch, tmp_path
) -> None:
    scan = _view_reader_scan(tmp_path, ("dbo.vOrder", "SELECT"), ("dbo.Orders", "SELECT"))
    _serve(monkeypatch, tmp_path, scan, _graph(views={"dbo.vOrder": ["dbo.Orders"]}))

    response = _find_by_table("Orders")

    assert [(match.file, match.access_type, match.read_through) for match in response.matches] == [
        ("OrderPage.cs", "SELECT", "")
    ]


def test_write_only_does_not_count_a_reached_read_as_a_write(monkeypatch, tmp_path) -> None:
    _serve(monkeypatch, tmp_path, _view_reader_scan(tmp_path, ("dbo.vOrder", "SELECT")), _graph(
        views={"dbo.vOrder": ["dbo.Orders"]}
    ))

    response = _find_by_table("Orders", write_only=True)

    assert response.matches == []
    assert response.excluded_count == 1


def test_flow_chain_backward_lists_the_method_that_reads_through_a_view(monkeypatch, tmp_path) -> None:
    _serve(monkeypatch, tmp_path, _view_reader_scan(tmp_path, ("dbo.vOrder", "SELECT")), _graph(
        views={"dbo.vOrder": ["dbo.Orders"]}
    ))

    response = analyze_service.flow_chain(
        FlowChainRequest(source=_SOURCE, direction="backward", table_name="Orders", database="PUR", cache_only=False)
    )

    assert [(chain["method"], chain["via"]) for chain in response.backward_chains] == [("Load", "direct_sql")]


def test_flow_chain_forward_still_lists_the_view_and_not_the_table_behind_it(monkeypatch, tmp_path) -> None:
    _serve(monkeypatch, tmp_path, _view_reader_scan(tmp_path, ("dbo.vOrder", "SELECT")), _graph(
        views={"dbo.vOrder": ["dbo.Orders"]}
    ))

    response = analyze_service.flow_chain(
        FlowChainRequest(
            source=_SOURCE, direction="forward", program_name="OrderPage", anchor_method="Load", cache_only=False
        )
    )

    assert response.forward_chain is not None
    assert response.forward_chain["inline_sql_tables"] == ["vOrder"]


def test_the_analyze_screen_table_list_still_lists_the_view(monkeypatch, tmp_path) -> None:
    graph = _graph(views={"dbo.vOrder": ["dbo.Orders"]})
    scan = _view_reader_scan(tmp_path, ("dbo.vOrder", "SELECT"))
    monkeypatch.setattr(analyze_service, "resolve_source", lambda request: [tmp_path])
    monkeypatch.setattr(analyze_service, "_get_scan", lambda root, refresh=False: scan)
    monkeypatch.setattr(analyze_service.sql_cache_store, "find_cache_identity", one_server_holds_every_database)
    monkeypatch.setattr(
        analyze_service.sql_cache_store,
        "load_cached",
        lambda identity: cache_payload("PUR", views=["dbo.vOrder"], tables=["dbo.Orders"], graph=graph),
    )

    response = analyze_service.analyze(
        AnalyzeRequest(database="PUR", program_names=["OrderPage"], include_snippets=False)
    )

    assert response.programs[0].tables == ["vOrder"]
