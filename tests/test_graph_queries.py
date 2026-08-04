"""Acceptance checks for graph-backed table access queries."""

from __future__ import annotations

from code_analyzer.csharp_analysis_gateway import (
    DbInvocation,
    InvocationEvidence,
    InvocationSourceSpan,
)
from service.execution_path_builder import build_execution_paths
from service.graph_queries import query_table_accesses


def _invocation(method_name: str, procedure_name: str) -> DbInvocation:
    return DbInvocation(
        class_name="OrderPage",
        method_name=method_name,
        database="OrdersDb",
        procedure_name=procedure_name,
        evidence=InvocationEvidence.PROVEN,
        source=InvocationSourceSpan("OrderPage.cs", 0, 10),
        procedure_schema="dbo",
        method_chain=(method_name,),
    )


def _graph() -> dict:
    return {
        "graph_version": 2,
        "database": "OrdersDb",
        "nodes": [
            {
                "id": "stored_procedure:dbo.usp_Direct",
                "type": "stored_procedure",
                "schema": "dbo",
                "name": "usp_Direct",
            },
            {
                "id": "dml_operation:stored_procedure:dbo.usp_Direct:1",
                "type": "dml_operation",
                "module_id": "stored_procedure:dbo.usp_Direct",
                "sequence": 1,
                "operation_type": "UPDATE",
                "write_tables": ["dbo.SOrder"],
                "written_columns": ["Status"],
            },
            {
                "id": "stored_procedure:dbo.usp_Entry",
                "type": "stored_procedure",
                "schema": "dbo",
                "name": "usp_Entry",
            },
            {
                "id": "stored_procedure:dbo.usp_Nested",
                "type": "stored_procedure",
                "schema": "dbo",
                "name": "usp_Nested",
            },
            {
                "id": "dml_operation:stored_procedure:dbo.usp_Nested:1",
                "type": "dml_operation",
                "module_id": "stored_procedure:dbo.usp_Nested",
                "sequence": 1,
                "operation_type": "INSERT",
                "write_tables": ["dbo.SOrder"],
                "written_columns": ["OrderNo"],
            },
            {
                "id": "view:dbo.vSOrder",
                "type": "view",
                "schema": "dbo",
                "name": "vSOrder",
            },
            {
                "id": "dml_operation:view:dbo.vSOrder:1",
                "type": "dml_operation",
                "module_id": "view:dbo.vSOrder",
                "sequence": 1,
                "operation_type": "SELECT",
                "read_tables": ["dbo.SOrder"],
            },
            {
                "id": "function:dbo.fnSOrderStatus",
                "type": "function",
                "schema": "dbo",
                "name": "fnSOrderStatus",
            },
            {
                "id": "dml_operation:function:dbo.fnSOrderStatus:1",
                "type": "dml_operation",
                "module_id": "function:dbo.fnSOrderStatus",
                "sequence": 1,
                "operation_type": "SELECT",
                "read_tables": ["dbo.SOrder"],
            },
            {
                "id": "stored_procedure:dbo.usp_Dynamic",
                "type": "stored_procedure",
                "schema": "dbo",
                "name": "usp_Dynamic",
            },
            {
                "id": "unresolved_dynamic_sql:stored_procedure:dbo.usp_Dynamic:1",
                "type": "unresolved_dynamic_sql",
                "module_id": "stored_procedure:dbo.usp_Dynamic",
                "sequence": 1,
                "operation_type": "EXECUTE",
            },
            {"id": "table:dbo.SOrder", "type": "table", "schema": "dbo", "name": "SOrder"},
        ],
        "relationships": [
            {
                "type": "contains",
                "source": "stored_procedure:dbo.usp_Direct",
                "target": "dml_operation:stored_procedure:dbo.usp_Direct:1",
            },
            {
                "type": "writes",
                "source": "dml_operation:stored_procedure:dbo.usp_Direct:1",
                "target": "table:dbo.SOrder",
                "columns": ["Status"],
            },
            {
                "type": "calls",
                "source": "stored_procedure:dbo.usp_Entry",
                "target": "stored_procedure:dbo.usp_Nested",
            },
            {
                "type": "contains",
                "source": "stored_procedure:dbo.usp_Nested",
                "target": "dml_operation:stored_procedure:dbo.usp_Nested:1",
            },
            {
                "type": "writes",
                "source": "dml_operation:stored_procedure:dbo.usp_Nested:1",
                "target": "table:dbo.SOrder",
                "columns": ["OrderNo"],
            },
            {
                "type": "contains",
                "source": "view:dbo.vSOrder",
                "target": "dml_operation:view:dbo.vSOrder:1",
            },
            {
                "type": "reads",
                "source": "dml_operation:view:dbo.vSOrder:1",
                "target": "table:dbo.SOrder",
            },
            {
                "type": "contains",
                "source": "function:dbo.fnSOrderStatus",
                "target": "dml_operation:function:dbo.fnSOrderStatus:1",
            },
            {
                "type": "reads",
                "source": "dml_operation:function:dbo.fnSOrderStatus:1",
                "target": "table:dbo.SOrder",
            },
            {
                "type": "contains",
                "source": "stored_procedure:dbo.usp_Dynamic",
                "target": "unresolved_dynamic_sql:stored_procedure:dbo.usp_Dynamic:1",
            },
        ],
        "parse_errors": [],
    }


def test_query_table_accesses_returns_only_confirmed_direct_and_nested_writers() -> None:
    accesses = query_table_accesses(
        _graph(),
        [
            _invocation("SaveDirect", "usp_Direct"),
            _invocation("SaveNested", "usp_Entry"),
            _invocation("ReadView", "vSOrder"),
            _invocation("ReadFunction", "fnSOrderStatus"),
            _invocation("Dynamic", "usp_Dynamic"),
        ],
        "dbo.SOrder",
        access="write",
    )

    assert [(item["access_type"], item["sp_chain"]) for item in accesses] == [
        ("UPDATE", ["dbo.usp_Direct"]),
        ("INSERT", ["dbo.usp_Entry", "dbo.usp_Nested"]),
    ]
    assert all(item["evidence"] == "proven" for item in accesses)
    assert all(item["is_write"] is True for item in accesses)
    assert {item["entry_method"] for item in accesses} == {
        "OrderPage.SaveDirect",
        "OrderPage.SaveNested",
    }


def test_query_table_accesses_resolves_view_read_lineage_without_writer() -> None:
    graph = _graph()
    graph["nodes"].extend(
        [
            {
                "id": "stored_procedure:dbo.usp_ReadView",
                "type": "stored_procedure",
                "schema": "dbo",
                "name": "usp_ReadView",
            },
            {
                "id": "dml_operation:stored_procedure:dbo.usp_ReadView:1",
                "type": "dml_operation",
                "module_id": "stored_procedure:dbo.usp_ReadView",
                "sequence": 1,
                "operation_type": "SELECT",
                "read_tables": ["dbo.vSOrder"],
            },
        ]
    )
    graph["relationships"].extend(
        [
            {
                "type": "contains",
                "source": "stored_procedure:dbo.usp_ReadView",
                "target": "dml_operation:stored_procedure:dbo.usp_ReadView:1",
            },
            {
                "type": "reads",
                "source": "dml_operation:stored_procedure:dbo.usp_ReadView:1",
                "target": "view:dbo.vSOrder",
            },
        ]
    )

    invocations = [_invocation("ReadView", "usp_ReadView")]
    reads = query_table_accesses(graph, invocations, "dbo.SOrder", access="read")
    writes = query_table_accesses(graph, invocations, "dbo.SOrder", access="write")

    assert [(item["table"], item["access_type"], item["is_indirect"]) for item in reads] == [
        ("SOrder", "READ", True),
    ]
    assert reads[0]["evidence"] == "proven"
    assert writes == []


def test_query_table_accesses_excludes_likely_invocations_from_formal_results() -> None:
    invocation = _invocation("SaveDirect", "usp_Direct")
    invocation = DbInvocation(
        class_name=invocation.class_name,
        method_name=invocation.method_name,
        database=None,
        database_candidates=("OrdersDb",),
        procedure_name=invocation.procedure_name,
        evidence=InvocationEvidence.LIKELY,
        source=invocation.source,
        reason="unique_across_catalogs",
        procedure_schema=invocation.procedure_schema,
        method_chain=invocation.method_chain,
    )

    assert query_table_accesses(_graph(), [invocation], "dbo.SOrder") == []


def test_query_table_accesses_excludes_likely_reads_from_formal_results() -> None:
    graph = _graph()
    graph["nodes"].extend(
        [
            {
                "id": "stored_procedure:dbo.usp_Read",
                "type": "stored_procedure",
                "schema": "dbo",
                "name": "usp_Read",
            },
            {
                "id": "dml_operation:stored_procedure:dbo.usp_Read:1",
                "type": "dml_operation",
                "module_id": "stored_procedure:dbo.usp_Read",
                "sequence": 1,
                "operation_type": "SELECT",
                "read_tables": ["dbo.SOrder"],
            },
        ]
    )
    graph["relationships"].extend(
        [
            {
                "type": "contains",
                "source": "stored_procedure:dbo.usp_Read",
                "target": "dml_operation:stored_procedure:dbo.usp_Read:1",
            },
            {
                "type": "reads",
                "source": "dml_operation:stored_procedure:dbo.usp_Read:1",
                "target": "table:dbo.SOrder",
            },
        ]
    )
    proven = _invocation("Read", "usp_Read")
    likely = DbInvocation(
        class_name=proven.class_name,
        method_name=proven.method_name,
        database=None,
        database_candidates=("OrdersDb",),
        procedure_name=proven.procedure_name,
        evidence=InvocationEvidence.LIKELY,
        source=proven.source,
        reason="unique_across_catalogs",
        procedure_schema=proven.procedure_schema,
        method_chain=proven.method_chain,
    )

    assert query_table_accesses(graph, [likely], "dbo.SOrder", access="read") == []


def test_query_table_accesses_excludes_partial_unresolved_reads() -> None:
    graph = _graph()
    graph["nodes"].append(
        {
            "id": "stored_procedure:dbo.usp_PartialRead",
            "type": "stored_procedure",
            "schema": "dbo",
            "name": "usp_PartialRead",
        }
    )
    graph["nodes"].append(
        {
            "id": "dml_operation:stored_procedure:dbo.usp_PartialRead:1",
            "type": "dml_operation",
            "module_id": "stored_procedure:dbo.usp_PartialRead",
            "sequence": 1,
            "operation_type": "SELECT",
        }
    )
    graph["relationships"].extend(
        [
            {
                "type": "contains",
                "source": "stored_procedure:dbo.usp_PartialRead",
                "target": "dml_operation:stored_procedure:dbo.usp_PartialRead:1",
            },
            {
                "type": "reads",
                "source": "dml_operation:stored_procedure:dbo.usp_PartialRead:1",
                "target": "table:dbo.SOrder",
            },
            {
                "type": "reads",
                "source": "dml_operation:stored_procedure:dbo.usp_PartialRead:1",
                "target": "table:dbo.Missing",
            },
        ]
    )

    paths = build_execution_paths(
        [_invocation("PartialRead", "usp_PartialRead")],
        graph,
    )

    assert paths[0]["evidence"] == "unresolved"
    assert paths[0]["reads"] == ["dbo.SOrder"]
    assert query_table_accesses(
        graph,
        [_invocation("PartialRead", "usp_PartialRead")],
        "dbo.SOrder",
        access="read",
    ) == []