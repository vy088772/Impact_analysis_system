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


def test_query_table_accesses_resolves_two_levels_of_view_read_lineage() -> None:
    graph = _graph()
    graph["nodes"].extend(
        [
            {
                "id": "stored_procedure:dbo.usp_ReadTwoLevelView",
                "type": "stored_procedure",
                "schema": "dbo",
                "name": "usp_ReadTwoLevelView",
            },
            {
                "id": "dml_operation:stored_procedure:dbo.usp_ReadTwoLevelView:1",
                "type": "dml_operation",
                "module_id": "stored_procedure:dbo.usp_ReadTwoLevelView",
                "sequence": 1,
                "operation_type": "SELECT",
                "read_tables": ["dbo.vLevel1"],
            },
            {
                "id": "view:dbo.vLevel1",
                "type": "view",
                "schema": "dbo",
                "name": "vLevel1",
            },
            {
                "id": "dml_operation:view:dbo.vLevel1:1",
                "type": "dml_operation",
                "module_id": "view:dbo.vLevel1",
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
                "source": "stored_procedure:dbo.usp_ReadTwoLevelView",
                "target": "dml_operation:stored_procedure:dbo.usp_ReadTwoLevelView:1",
            },
            {
                "type": "reads",
                "source": "dml_operation:stored_procedure:dbo.usp_ReadTwoLevelView:1",
                "target": "view:dbo.vLevel1",
            },
            {
                "type": "contains",
                "source": "view:dbo.vLevel1",
                "target": "dml_operation:view:dbo.vLevel1:1",
            },
            {
                "type": "reads",
                "source": "dml_operation:view:dbo.vLevel1:1",
                "target": "view:dbo.vSOrder",
            },
        ]
    )

    reads = query_table_accesses(
        graph,
        [_invocation("ReadTwoLevelView", "usp_ReadTwoLevelView")],
        "dbo.SOrder",
        access="read",
    )

    assert [(item["table"], item["access_type"], item["is_indirect"]) for item in reads] == [
        ("SOrder", "READ", True),
    ]


def test_query_table_accesses_resolves_function_only_read_lineage() -> None:
    graph = _graph()
    graph["nodes"].extend(
        [
            {
                "id": "stored_procedure:dbo.usp_ReadFunction",
                "type": "stored_procedure",
                "schema": "dbo",
                "name": "usp_ReadFunction",
            },
            {
                "id": "dml_operation:stored_procedure:dbo.usp_ReadFunction:1",
                "type": "dml_operation",
                "module_id": "stored_procedure:dbo.usp_ReadFunction",
                "sequence": 1,
                "operation_type": "SELECT",
                "read_tables": ["dbo.fnSOrderStatus"],
            },
        ]
    )
    graph["relationships"].extend(
        [
            {
                "type": "contains",
                "source": "stored_procedure:dbo.usp_ReadFunction",
                "target": "dml_operation:stored_procedure:dbo.usp_ReadFunction:1",
            },
            {
                "type": "reads",
                "source": "dml_operation:stored_procedure:dbo.usp_ReadFunction:1",
                "target": "function:dbo.fnSOrderStatus",
            },
        ]
    )

    reads = query_table_accesses(
        graph,
        [_invocation("ReadFunction", "usp_ReadFunction")],
        "dbo.SOrder",
        access="read",
    )

    assert [(item["table"], item["access_type"], item["is_indirect"]) for item in reads] == [
        ("SOrder", "READ", True),
    ]


def test_query_table_accesses_read_lineage_terminates_on_view_cycle() -> None:
    graph = _graph()
    graph["nodes"].extend(
        [
            {
                "id": "stored_procedure:dbo.usp_ReadCycle",
                "type": "stored_procedure",
                "schema": "dbo",
                "name": "usp_ReadCycle",
            },
            {
                "id": "dml_operation:stored_procedure:dbo.usp_ReadCycle:1",
                "type": "dml_operation",
                "module_id": "stored_procedure:dbo.usp_ReadCycle",
                "sequence": 1,
                "operation_type": "SELECT",
                "read_tables": ["dbo.vCycleA"],
            },
            {"id": "view:dbo.vCycleA", "type": "view", "schema": "dbo", "name": "vCycleA"},
            {
                "id": "dml_operation:view:dbo.vCycleA:1",
                "type": "dml_operation",
                "module_id": "view:dbo.vCycleA",
                "sequence": 1,
                "operation_type": "SELECT",
                "read_tables": ["dbo.vCycleB"],
            },
            {"id": "view:dbo.vCycleB", "type": "view", "schema": "dbo", "name": "vCycleB"},
            {
                "id": "dml_operation:view:dbo.vCycleB:1",
                "type": "dml_operation",
                "module_id": "view:dbo.vCycleB",
                "sequence": 1,
                "operation_type": "SELECT",
                # Cycles back to vCycleA *and* reaches a real table, so the
                # cycle must not block the match that exists alongside it.
                "read_tables": ["dbo.vCycleA", "dbo.SOrder"],
            },
        ]
    )
    graph["relationships"].extend(
        [
            {
                "type": "contains",
                "source": "stored_procedure:dbo.usp_ReadCycle",
                "target": "dml_operation:stored_procedure:dbo.usp_ReadCycle:1",
            },
            {
                "type": "reads",
                "source": "dml_operation:stored_procedure:dbo.usp_ReadCycle:1",
                "target": "view:dbo.vCycleA",
            },
            {
                "type": "contains",
                "source": "view:dbo.vCycleA",
                "target": "dml_operation:view:dbo.vCycleA:1",
            },
            {
                "type": "reads",
                "source": "dml_operation:view:dbo.vCycleA:1",
                "target": "view:dbo.vCycleB",
            },
            {
                "type": "contains",
                "source": "view:dbo.vCycleB",
                "target": "dml_operation:view:dbo.vCycleB:1",
            },
            {
                "type": "reads",
                "source": "dml_operation:view:dbo.vCycleB:1",
                "target": "view:dbo.vCycleA",
            },
            {
                "type": "reads",
                "source": "dml_operation:view:dbo.vCycleB:1",
                "target": "table:dbo.SOrder",
            },
        ]
    )

    reads = query_table_accesses(
        graph,
        [_invocation("ReadCycle", "usp_ReadCycle")],
        "dbo.SOrder",
        access="read",
    )

    assert [(item["table"], item["access_type"], item["is_indirect"]) for item in reads] == [
        ("SOrder", "READ", True),
    ]


def test_query_table_accesses_two_tables_in_one_request_return_their_own_records() -> None:
    graph = _graph()
    graph["nodes"].extend(
        [
            {"id": "table:dbo.SCustomer", "type": "table", "schema": "dbo", "name": "SCustomer"},
            {
                "id": "stored_procedure:dbo.usp_ReadCustomer",
                "type": "stored_procedure",
                "schema": "dbo",
                "name": "usp_ReadCustomer",
            },
            {
                "id": "dml_operation:stored_procedure:dbo.usp_ReadCustomer:1",
                "type": "dml_operation",
                "module_id": "stored_procedure:dbo.usp_ReadCustomer",
                "sequence": 1,
                "operation_type": "SELECT",
                "read_tables": ["dbo.vSCustomer"],
            },
            {
                "id": "view:dbo.vSCustomer",
                "type": "view",
                "schema": "dbo",
                "name": "vSCustomer",
            },
            {
                "id": "dml_operation:view:dbo.vSCustomer:1",
                "type": "dml_operation",
                "module_id": "view:dbo.vSCustomer",
                "sequence": 1,
                "operation_type": "SELECT",
                "read_tables": ["dbo.SCustomer"],
            },
        ]
    )
    graph["relationships"].extend(
        [
            {
                "type": "contains",
                "source": "stored_procedure:dbo.usp_ReadCustomer",
                "target": "dml_operation:stored_procedure:dbo.usp_ReadCustomer:1",
            },
            {
                "type": "reads",
                "source": "dml_operation:stored_procedure:dbo.usp_ReadCustomer:1",
                "target": "view:dbo.vSCustomer",
            },
            {
                "type": "contains",
                "source": "view:dbo.vSCustomer",
                "target": "dml_operation:view:dbo.vSCustomer:1",
            },
            {
                "type": "reads",
                "source": "dml_operation:view:dbo.vSCustomer:1",
                "target": "table:dbo.SCustomer",
            },
        ]
    )

    invocations = [
        _invocation("ReadOrder", "usp_ReadView"),
        _invocation("ReadCustomer", "usp_ReadCustomer"),
    ]
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

    order_reads = query_table_accesses(graph, invocations, "dbo.SOrder", access="read")
    customer_reads = query_table_accesses(graph, invocations, "dbo.SCustomer", access="read")

    assert [(item["table"], item["is_indirect"]) for item in order_reads] == [("SOrder", True)]
    assert [(item["table"], item["is_indirect"]) for item in customer_reads] == [
        ("SCustomer", True)
    ]
    assert {item["entry_method"] for item in order_reads} == {"OrderPage.ReadOrder"}
    assert {item["entry_method"] for item in customer_reads} == {"OrderPage.ReadCustomer"}


def test_query_table_accesses_read_lineage_survives_a_shared_cyclic_view() -> None:
    """A container revisited mid-cycle must not cache a stunted answer.

    `vDiamondA` has two children: one cycles to `vDiamondB`, the other reads
    the table directly. `vDiamondB`'s only child cycles back to `vDiamondA`.
    A caller reaching the table only through the cycle (`usp_ReadDiamondB`,
    via `vDiamondB`) must still see it -- the same as a caller reaching it
    directly (`usp_ReadDiamondA`). A build that resolves `vDiamondB` while
    `vDiamondA` is still mid-computation, and caches that incomplete result,
    would wrongly drop the table for `usp_ReadDiamondB` alone.
    """
    graph = _graph()
    graph["nodes"].extend(
        [
            {
                "id": "stored_procedure:dbo.usp_ReadDiamondA",
                "type": "stored_procedure",
                "schema": "dbo",
                "name": "usp_ReadDiamondA",
            },
            {
                "id": "dml_operation:stored_procedure:dbo.usp_ReadDiamondA:1",
                "type": "dml_operation",
                "module_id": "stored_procedure:dbo.usp_ReadDiamondA",
                "sequence": 1,
                "operation_type": "SELECT",
                "read_tables": ["dbo.vDiamondA"],
            },
            {
                "id": "stored_procedure:dbo.usp_ReadDiamondB",
                "type": "stored_procedure",
                "schema": "dbo",
                "name": "usp_ReadDiamondB",
            },
            {
                "id": "dml_operation:stored_procedure:dbo.usp_ReadDiamondB:1",
                "type": "dml_operation",
                "module_id": "stored_procedure:dbo.usp_ReadDiamondB",
                "sequence": 1,
                "operation_type": "SELECT",
                "read_tables": ["dbo.vDiamondB"],
            },
            {"id": "view:dbo.vDiamondA", "type": "view", "schema": "dbo", "name": "vDiamondA"},
            {
                "id": "dml_operation:view:dbo.vDiamondA:1",
                "type": "dml_operation",
                "module_id": "view:dbo.vDiamondA",
                "sequence": 1,
                "operation_type": "SELECT",
                "read_tables": ["dbo.vDiamondB"],
            },
            {
                "id": "dml_operation:view:dbo.vDiamondA:2",
                "type": "dml_operation",
                "module_id": "view:dbo.vDiamondA",
                "sequence": 2,
                "operation_type": "SELECT",
                "read_tables": ["dbo.SOrder"],
            },
            {"id": "view:dbo.vDiamondB", "type": "view", "schema": "dbo", "name": "vDiamondB"},
            {
                "id": "dml_operation:view:dbo.vDiamondB:1",
                "type": "dml_operation",
                "module_id": "view:dbo.vDiamondB",
                "sequence": 1,
                "operation_type": "SELECT",
                "read_tables": ["dbo.vDiamondA"],
            },
        ]
    )
    graph["relationships"].extend(
        [
            {
                "type": "contains",
                "source": "stored_procedure:dbo.usp_ReadDiamondA",
                "target": "dml_operation:stored_procedure:dbo.usp_ReadDiamondA:1",
            },
            {
                "type": "reads",
                "source": "dml_operation:stored_procedure:dbo.usp_ReadDiamondA:1",
                "target": "view:dbo.vDiamondA",
            },
            {
                "type": "contains",
                "source": "stored_procedure:dbo.usp_ReadDiamondB",
                "target": "dml_operation:stored_procedure:dbo.usp_ReadDiamondB:1",
            },
            {
                "type": "reads",
                "source": "dml_operation:stored_procedure:dbo.usp_ReadDiamondB:1",
                "target": "view:dbo.vDiamondB",
            },
            {
                "type": "contains",
                "source": "view:dbo.vDiamondA",
                "target": "dml_operation:view:dbo.vDiamondA:1",
            },
            {
                "type": "reads",
                "source": "dml_operation:view:dbo.vDiamondA:1",
                "target": "view:dbo.vDiamondB",
            },
            {
                "type": "contains",
                "source": "view:dbo.vDiamondA",
                "target": "dml_operation:view:dbo.vDiamondA:2",
            },
            {
                "type": "reads",
                "source": "dml_operation:view:dbo.vDiamondA:2",
                "target": "table:dbo.SOrder",
            },
            {
                "type": "contains",
                "source": "view:dbo.vDiamondB",
                "target": "dml_operation:view:dbo.vDiamondB:1",
            },
            {
                "type": "reads",
                "source": "dml_operation:view:dbo.vDiamondB:1",
                "target": "view:dbo.vDiamondA",
            },
        ]
    )

    invocations = [
        _invocation("ReadDiamondA", "usp_ReadDiamondA"),
        _invocation("ReadDiamondB", "usp_ReadDiamondB"),
    ]
    reads = query_table_accesses(graph, invocations, "dbo.SOrder", access="read")

    assert {item["entry_method"] for item in reads} == {
        "OrderPage.ReadDiamondA",
        "OrderPage.ReadDiamondB",
    }
    assert all(item["table"] == "SOrder" and item["is_indirect"] for item in reads)
