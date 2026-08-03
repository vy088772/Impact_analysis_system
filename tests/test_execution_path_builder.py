"""Ticket 04 behavior checks for C# to SQL execution paths."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from code_analyzer.csharp_analysis_gateway import (
    DbInvocation,
    InvocationEvidence,
    InvocationSourceSpan,
    SpCatalog,
)
from service.execution_path_builder import (
    build_compact_execution_path_payload,
    build_compact_execution_path_summary,
    build_execution_paths,
    build_execution_paths_from_raw_invocations,
)


def _graph() -> dict:
    return {
        "graph_version": 1,
        "nodes": [
            {
                "id": "stored_procedure:dbo.usp_SaveOrder",
                "type": "stored_procedure",
                "schema": "dbo",
                "name": "usp_SaveOrder",
            },
            {
                "id": "dml_operation:stored_procedure:dbo.usp_SaveOrder:1",
                "type": "dml_operation",
                "module_id": "stored_procedure:dbo.usp_SaveOrder",
                "module": {"type": "stored_procedure", "schema": "dbo", "name": "usp_SaveOrder"},
                "sequence": 1,
                "operation_type": "UPDATE",
                "branch_path": ["IF @Mode = 1"],
                "conditions": ["IF @Mode = 1", "Id = @Id"],
                "read_tables": ["dbo.SourceOrder"],
                "write_tables": ["dbo.SOrder"],
                "written_columns": ["OrderNo"],
            },
            {
                "id": "dml_operation:stored_procedure:dbo.usp_SaveOrder:2",
                "type": "dml_operation",
                "module_id": "stored_procedure:dbo.usp_SaveOrder",
                "module": {"type": "stored_procedure", "schema": "dbo", "name": "usp_SaveOrder"},
                "sequence": 2,
                "operation_type": "DELETE",
                "branch_path": ["ELSE (NOT (@Mode = 1))"],
                "conditions": ["ELSE (NOT (@Mode = 1))", "Id = @Id"],
                "read_tables": [],
                "write_tables": ["dbo.SOrder"],
                "written_columns": [],
            },
            {"id": "table:dbo.SourceOrder", "type": "table", "schema": "dbo", "name": "SourceOrder"},
            {"id": "table:dbo.SOrder", "type": "table", "schema": "dbo", "name": "SOrder"},
        ],
        "relationships": [
            {"type": "contains", "source": "stored_procedure:dbo.usp_SaveOrder", "target": "dml_operation:stored_procedure:dbo.usp_SaveOrder:1"},
            {"type": "contains", "source": "stored_procedure:dbo.usp_SaveOrder", "target": "dml_operation:stored_procedure:dbo.usp_SaveOrder:2"},
            {"type": "reads", "source": "dml_operation:stored_procedure:dbo.usp_SaveOrder:1", "target": "table:dbo.SourceOrder"},
            {"type": "writes", "source": "dml_operation:stored_procedure:dbo.usp_SaveOrder:1", "target": "table:dbo.SOrder", "columns": ["OrderNo"]},
            {"type": "writes", "source": "dml_operation:stored_procedure:dbo.usp_SaveOrder:2", "target": "table:dbo.SOrder"},
        ],
        "parse_errors": [],
    }


def _nested_graph() -> dict:
    return {
        "graph_version": 1,
        "nodes": [
            {
                "id": "stored_procedure:dbo.usp_SaveOrder",
                "type": "stored_procedure",
                "schema": "dbo",
                "name": "usp_SaveOrder",
            },
            {
                "id": "stored_procedure:dbo.usp_WriteAudit",
                "type": "stored_procedure",
                "schema": "dbo",
                "name": "usp_WriteAudit",
            },
            {
                "id": "dml_operation:stored_procedure:dbo.usp_WriteAudit:1",
                "type": "dml_operation",
                "module_id": "stored_procedure:dbo.usp_WriteAudit",
                "module": {"type": "stored_procedure", "schema": "dbo", "name": "usp_WriteAudit"},
                "sequence": 1,
                "operation_type": "INSERT",
                "branch_path": [],
                "conditions": ["AuditEnabled = 1"],
                "read_tables": [],
                "write_tables": ["dbo.OrderAudit"],
                "written_columns": ["OrderId"],
            },
            {"id": "table:dbo.OrderAudit", "type": "table", "schema": "dbo", "name": "OrderAudit"},
        ],
        "relationships": [
            {
                "type": "calls",
                "source": "stored_procedure:dbo.usp_SaveOrder",
                "target": "stored_procedure:dbo.usp_WriteAudit",
                "branch_path": ["IF @Audit = 1"],
            },
            {
                "type": "contains",
                "source": "stored_procedure:dbo.usp_WriteAudit",
                "target": "dml_operation:stored_procedure:dbo.usp_WriteAudit:1",
            },
            {
                "type": "writes",
                "source": "dml_operation:stored_procedure:dbo.usp_WriteAudit:1",
                "target": "table:dbo.OrderAudit",
            },
        ],
        "parse_errors": [],
    }


def test_direct_invocation_builds_one_path_per_terminal_branch() -> None:
    invocation = DbInvocation(
        class_name="OrderPage",
        method_name="SaveData",
        database="OrdersDb",
        procedure_name="usp_saveorder",
        evidence=InvocationEvidence.PROVEN,
        source=InvocationSourceSpan("Ship/OrderPage.aspx.cs", 120, 220),
    )

    paths = build_execution_paths([invocation], _graph())

    assert len(paths) == 2
    assert {path["entry_method"] for path in paths} == {"OrderPage.SaveData"}
    assert {tuple(path["method_chain"]) for path in paths} == {("SaveData",)}
    assert {tuple(path["sp_chain"]) for path in paths} == {("dbo.usp_SaveOrder",)}
    assert {path["terminal_operation"] for path in paths} == {"UPDATE", "DELETE"}
    update_path = next(path for path in paths if path["terminal_operation"] == "UPDATE")
    assert update_path["conditions"] == ["IF @Mode = 1", "Id = @Id"]
    assert update_path["reads"] == ["dbo.SourceOrder"]
    assert update_path["writes"] == ["dbo.SOrder"]
    assert update_path["written_columns"] == ["OrderNo"]
    assert update_path["evidence"] == "proven"
    assert update_path["risk_flags"] == []
    assert "source" not in update_path
    assert "definition" not in update_path


def test_invocation_branch_context_is_preserved_and_part_of_path_identity() -> None:
    source = InvocationSourceSpan("Ship/OrderPage.aspx.cs", 120, 220)
    invocations = [
        DbInvocation(
            class_name="OrderPage",
            method_name="SaveData",
            database="OrdersDb",
            procedure_name="usp_saveorder",
            evidence=InvocationEvidence.PROVEN,
            source=source,
            branch_context=("if (useAlternate)",),
        ),
        DbInvocation(
            class_name="OrderPage",
            method_name="SaveData",
            database="OrdersDb",
            procedure_name="usp_saveorder",
            evidence=InvocationEvidence.PROVEN,
            source=source,
            branch_context=("else (useAlternate)",),
        ),
    ]

    paths = build_execution_paths(invocations, _graph())

    assert len(paths) == 4
    assert len({path["path_id"] for path in paths}) == 4
    assert {path["conditions"][0] for path in paths} == {
        "if (useAlternate)",
        "else (useAlternate)",
    }


def test_missing_stored_procedure_graph_target_is_explicitly_unresolved() -> None:
    invocation = DbInvocation(
        class_name="OrderPage",
        method_name="SaveData",
        database="OrdersDb",
        procedure_name="usp_missing",
        evidence=InvocationEvidence.PROVEN,
        source=InvocationSourceSpan("Ship/OrderPage.aspx.cs", 120, 220),
    )

    paths = build_execution_paths([invocation], _graph())

    assert len(paths) == 1
    path = paths[0]
    assert path["evidence"] == "unresolved"
    assert path["unresolved_reason"] == "stored_procedure_not_in_graph"
    assert path["risk_flags"] == ["stored_procedure_not_in_graph"]
    assert path["terminal_operation"] is None
    assert path["target"] == ""
    assert path["unresolved_targets"] == ["usp_missing"]


def test_graph_database_mismatch_is_explicitly_unresolved() -> None:
    graph = _graph()
    graph["database"] = "OtherDb"
    invocation = DbInvocation(
        class_name="OrderPage",
        method_name="SaveData",
        database="OrdersDb",
        procedure_name="usp_saveorder",
        evidence=InvocationEvidence.PROVEN,
        source=InvocationSourceSpan("Ship/OrderPage.aspx.cs", 120, 220),
    )

    paths = build_execution_paths([invocation], graph)

    assert len(paths) == 1
    assert paths[0]["unresolved_reason"] == "graph_database_mismatch"
    assert paths[0]["unresolved_targets"] == ["database:OtherDb"]


def test_compact_summary_is_bounded_and_excludes_source_material() -> None:
    invocation = DbInvocation(
        class_name="OrderPage",
        method_name="SaveData",
        database="OrdersDb",
        procedure_name="usp_saveorder",
        evidence=InvocationEvidence.PROVEN,
        source=InvocationSourceSpan("Ship/OrderPage.aspx.cs", 120, 220),
    )
    paths = build_execution_paths([invocation], _graph())

    summary = build_compact_execution_path_summary(paths, max_paths=1)

    assert len(summary) == 1
    assert set(summary[0]) == {
        "path_id",
        "entry_method",
        "method_chain",
        "sp_chain",
        "terminal_operation",
        "target",
        "written_columns",
        "conditions",
        "reads",
        "writes",
        "risk_flags",
        "evidence",
        "unresolved_targets",
    }
    assert "definition" not in summary[0]
    assert "source" not in summary[0]


def test_compact_summary_hard_caps_at_twenty_paths() -> None:
    paths = [
        {
            "path_id": f"P-{index:02d}",
            "entry_method": "OrderPage.SaveData",
            "method_chain": ["SaveData"],
            "sp_chain": ["dbo.usp_SaveOrder"],
        }
        for index in range(25)
    ]

    summary = build_compact_execution_path_summary(paths, max_paths=100)

    assert len(summary) == 20


def test_compact_summary_prioritizes_writes_and_question_matches() -> None:
    paths = [
        {
            "path_id": "P-a",
            "entry_method": "BrowsePage.LoadData",
            "method_chain": ["LoadData"],
            "sp_chain": ["dbo.usp_Browse"],
            "writes": [],
        },
        {
            "path_id": "P-z",
            "entry_method": "OrderPage.SaveData",
            "method_chain": ["SaveData"],
            "sp_chain": ["dbo.usp_SaveOrder"],
            "writes": ["dbo.SOrder"],
        },
        {
            "path_id": "P-y",
            "entry_method": "OrderPage.CancelData",
            "method_chain": ["CancelData"],
            "sp_chain": ["dbo.usp_CancelOrder"],
            "writes": [],
        },
    ]

    summary = build_compact_execution_path_summary(
        paths,
        max_paths=2,
        question="cancel order",
    )

    assert [item["path_id"] for item in summary] == ["P-z", "P-y"]


def test_raw_direct_invocation_is_catalog_validated_before_graph_join() -> None:
    raw_invocation = {
        "class_name": "OrderPage",
        "method_name": "SaveData",
        "command_text_kind": "literal",
        "command_text": "dbo.usp_SaveOrder",
        "command_type_stored_procedure": True,
        "connection_expression": "conn",
        "start_offset": 120,
        "end_offset": 220,
    }

    paths = build_execution_paths_from_raw_invocations(
        "Ship/OrderPage.aspx.cs",
        [raw_invocation],
        SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]}),
        _graph(),
        connection_sources={"conn": "OrdersDb"},
    )

    assert len(paths) == 2
    assert {path["evidence"] for path in paths} == {"proven"}
    assert {path["database"] for path in paths} == {"OrdersDb"}


def test_source_wrapper_invocation_joins_to_execution_path() -> None:
    raw_invocation = {
        "invocation_kind": "source_wrapper",
        "class_name": "OrderPage",
        "method_name": "SaveData",
        "wrapper_class_name": "DbWrapper",
        "wrapper_method_name": "Execute",
        "wrapper_source_available": True,
        "wrapper_reaches_stored_procedure_sink": True,
        "wrapper_mode": "stored_procedure",
        "command_text_kind": "literal",
        "command_text": "dbo.usp_SaveOrder",
        "command_type_stored_procedure": True,
        "connection_expression": "_connection",
        "method_chain": ["HandleSave", "SaveData", "Execute"],
        "start_offset": 120,
        "end_offset": 220,
    }

    paths = build_execution_paths_from_raw_invocations(
        "Ship/OrderPage.aspx.cs",
        [raw_invocation],
        SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]}),
        _graph(),
        connection_sources={"_connection": "OrdersDb"},
    )

    assert len(paths) == 2
    assert {path["entry_method"] for path in paths} == {"OrderPage.HandleSave"}
    assert {tuple(path["method_chain"]) for path in paths} == {
        ("HandleSave", "SaveData", "Execute"),
    }
    assert {path["evidence"] for path in paths} == {"proven"}
    assert {path["target"] for path in paths} == {"dbo.SOrder"}


def test_schema_qualified_invocation_joins_matching_graph_module() -> None:
    graph = _graph()
    graph["nodes"].extend([
        {
            "id": "stored_procedure:sales.usp_SaveOrder",
            "type": "stored_procedure",
            "schema": "sales",
            "name": "usp_SaveOrder",
        },
        {
            "id": "dml_operation:stored_procedure:sales.usp_SaveOrder:1",
            "type": "dml_operation",
            "module_id": "stored_procedure:sales.usp_SaveOrder",
            "sequence": 1,
            "operation_type": "UPDATE",
            "written_columns": ["OrderNo"],
        },
        {"id": "table:sales.SOrder", "type": "table", "schema": "sales", "name": "SOrder"},
    ])
    graph["relationships"].extend([
        {
            "type": "contains",
            "source": "stored_procedure:sales.usp_SaveOrder",
            "target": "dml_operation:stored_procedure:sales.usp_SaveOrder:1",
        },
        {
            "type": "writes",
            "source": "dml_operation:stored_procedure:sales.usp_SaveOrder:1",
            "target": "table:sales.SOrder",
        },
    ])
    raw_invocation = {
        "class_name": "OrderPage",
        "method_name": "SaveData",
        "command_text_kind": "literal",
        "command_text": "sales.usp_SaveOrder",
        "command_type_stored_procedure": True,
        "connection_expression": "conn",
        "start_offset": 120,
        "end_offset": 220,
    }

    paths = build_execution_paths_from_raw_invocations(
        "Ship/OrderPage.aspx.cs",
        [raw_invocation],
        SpCatalog.from_databases({"OrdersDb": ["sales.usp_SaveOrder"]}),
        graph,
        connection_sources={"conn": "OrdersDb"},
    )

    assert len(paths) == 1
    assert paths[0]["sp_chain"] == ["sales.usp_SaveOrder"]
    assert paths[0]["target"] == "sales.SOrder"


def test_ambiguous_graph_target_lists_candidate_node_ids() -> None:
    graph = _graph()
    graph["nodes"].append({
        "id": "stored_procedure:sales.usp_SaveOrder",
        "type": "stored_procedure",
        "schema": "sales",
        "name": "usp_SaveOrder",
    })
    invocation = DbInvocation(
        class_name="OrderPage",
        method_name="SaveData",
        database="OrdersDb",
        procedure_name="usp_saveorder",
        evidence=InvocationEvidence.PROVEN,
        source=InvocationSourceSpan("Ship/OrderPage.aspx.cs", 120, 220),
    )

    paths = build_execution_paths([invocation], graph)

    assert len(paths) == 1
    assert paths[0]["unresolved_reason"] == "ambiguous_stored_procedure_graph_target"
    assert paths[0]["unresolved_targets"] == [
        "stored_procedure:dbo.usp_SaveOrder",
        "stored_procedure:sales.usp_SaveOrder",
    ]


def test_path_ids_are_stable_when_invocation_input_order_changes() -> None:
    first = DbInvocation(
        class_name="OrderPage",
        method_name="SaveData",
        database="OrdersDb",
        procedure_name="usp_saveorder",
        evidence=InvocationEvidence.PROVEN,
        source=InvocationSourceSpan("Ship/OrderPage.aspx.cs", 120, 220),
    )
    second = DbInvocation(
        class_name="OrderPage",
        method_name="SaveData",
        database="OrdersDb",
        procedure_name="usp_saveorder",
        evidence=InvocationEvidence.PROVEN,
        source=InvocationSourceSpan("Ship/OrderPage.aspx.cs", 320, 420),
    )

    forward = build_execution_paths([first, second], _graph())
    reverse = build_execution_paths([second, first], _graph())

    assert [(path["terminal_operation"], path["path_id"]) for path in forward] == [
        (path["terminal_operation"], path["path_id"]) for path in reverse
    ]
    assert len({path["path_id"] for path in forward}) == len(forward)


def test_dynamic_invocation_keeps_gateway_unresolved_reason() -> None:
    raw_invocation = {
        "class_name": "OrderPage",
        "method_name": "SaveData",
        "command_text_kind": "dynamic",
        "command_text": None,
        "command_type_stored_procedure": True,
        "connection_expression": "conn",
        "start_offset": 120,
        "end_offset": 220,
    }

    paths = build_execution_paths_from_raw_invocations(
        "Ship/OrderPage.aspx.cs",
        [raw_invocation],
        SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]}),
        _graph(),
        connection_sources={"conn": "OrdersDb"},
    )

    assert len(paths) == 1
    assert paths[0]["evidence"] == "unresolved"
    assert paths[0]["unresolved_reason"] == "dynamic_command_text"
    assert paths[0]["risk_flags"] == ["dynamic_command_text"]


def test_unresolved_path_preserves_invocation_branch_context() -> None:
    invocation = DbInvocation(
        class_name="OrderPage",
        method_name="SaveData",
        database="OrdersDb",
        procedure_name=None,
        evidence=InvocationEvidence.UNRESOLVED,
        source=InvocationSourceSpan("Ship/OrderPage.aspx.cs", 120, 220),
        reason="dynamic_command_text",
        branch_context=("if (useAlternate)",),
    )

    paths = build_execution_paths([invocation], _graph())

    assert paths[0]["conditions"] == ["if (useAlternate)"]


def test_dangling_contains_relationship_returns_unresolved_path_evidence() -> None:
    graph = _graph()
    graph["relationships"].append({
        "type": "contains",
        "source": "stored_procedure:dbo.usp_SaveOrder",
    })
    invocation = DbInvocation(
        class_name="OrderPage",
        method_name="SaveData",
        database="OrdersDb",
        procedure_name="usp_saveorder",
        evidence=InvocationEvidence.PROVEN,
        source=InvocationSourceSpan("Ship/OrderPage.aspx.cs", 120, 220),
    )

    paths = build_execution_paths([invocation], graph)

    unresolved = [path for path in paths if path["unresolved_reason"] == "operation_not_in_graph"]
    assert len(unresolved) == 1
    assert unresolved[0]["evidence"] == "unresolved"
    assert unresolved[0]["risk_flags"] == ["operation_not_in_graph"]


def test_dangling_dml_target_returns_unresolved_path_evidence() -> None:
    graph = _graph()
    graph["relationships"].append({
        "type": "writes",
        "source": "dml_operation:stored_procedure:dbo.usp_SaveOrder:1",
        "target": "table:dbo.MissingTarget",
    })
    invocation = DbInvocation(
        class_name="OrderPage",
        method_name="SaveData",
        database="OrdersDb",
        procedure_name="usp_saveorder",
        evidence=InvocationEvidence.PROVEN,
        source=InvocationSourceSpan("Ship/OrderPage.aspx.cs", 120, 220),
    )

    paths = build_execution_paths([invocation], graph)

    update_path = next(path for path in paths if path["terminal_operation"] == "UPDATE")
    assert update_path["evidence"] == "unresolved"
    assert update_path["unresolved_reason"] == "missing_graph_target"
    assert update_path["risk_flags"] == ["missing_graph_target"]
    assert update_path["unresolved_targets"] == ["table:dbo.MissingTarget"]


def test_unresolved_dynamic_sql_node_stays_explicit() -> None:
    graph = _graph()
    graph["nodes"].append({
        "id": "unresolved_dynamic_sql:stored_procedure:dbo.usp_SaveOrder:3",
        "type": "unresolved_dynamic_sql",
        "module_id": "stored_procedure:dbo.usp_SaveOrder",
        "sequence": 3,
        "operation_type": "DYNAMIC_SQL",
        "branch_path": ["IF @UseDynamic = 1"],
    })
    graph["relationships"].append({
        "type": "contains",
        "source": "stored_procedure:dbo.usp_SaveOrder",
        "target": "unresolved_dynamic_sql:stored_procedure:dbo.usp_SaveOrder:3",
    })
    invocation = DbInvocation(
        class_name="OrderPage",
        method_name="SaveData",
        database="OrdersDb",
        procedure_name="usp_saveorder",
        evidence=InvocationEvidence.PROVEN,
        source=InvocationSourceSpan("Ship/OrderPage.aspx.cs", 120, 220),
    )

    paths = build_execution_paths([invocation], graph)

    dynamic_path = next(path for path in paths if path["terminal_operation"] == "DYNAMIC_SQL")
    assert dynamic_path["evidence"] == "unresolved"
    assert dynamic_path["unresolved_reason"] == "unresolved_dynamic_sql"
    assert dynamic_path["risk_flags"] == ["dynamic_sql"]
    assert dynamic_path["target"] == ""


def test_calls_relationship_extends_sp_chain_to_terminal_dml() -> None:
    invocation = DbInvocation(
        class_name="OrderPage",
        method_name="SaveData",
        database="OrdersDb",
        procedure_name="usp_saveorder",
        evidence=InvocationEvidence.PROVEN,
        source=InvocationSourceSpan("Ship/OrderPage.aspx.cs", 120, 220),
    )

    paths = build_execution_paths([invocation], _nested_graph())

    assert len(paths) == 1
    assert paths[0]["sp_chain"] == ["dbo.usp_SaveOrder", "dbo.usp_WriteAudit"]
    assert paths[0]["terminal_operation"] == "INSERT"
    assert paths[0]["conditions"] == ["IF @Audit = 1", "AuditEnabled = 1"]
    assert paths[0]["target"] == "dbo.OrderAudit"


def test_distinct_call_branch_conditions_produce_distinct_path_ids() -> None:
    graph = _nested_graph()
    graph["relationships"].append({
        "type": "calls",
        "source": "stored_procedure:dbo.usp_SaveOrder",
        "target": "stored_procedure:dbo.usp_WriteAudit",
        "branch_path": ["IF @Audit = 2"],
    })
    invocation = DbInvocation(
        class_name="OrderPage",
        method_name="SaveData",
        database="OrdersDb",
        procedure_name="usp_saveorder",
        evidence=InvocationEvidence.PROVEN,
        source=InvocationSourceSpan("Ship/OrderPage.aspx.cs", 120, 220),
    )

    paths = build_execution_paths([invocation], graph)

    assert len(paths) == 2
    assert len({path["path_id"] for path in paths}) == 2
    assert {tuple(path["conditions"]) for path in paths} == {
        ("IF @Audit = 1", "AuditEnabled = 1"),
        ("IF @Audit = 2", "AuditEnabled = 1"),
    }


def test_call_expansion_depth_limit_is_explicitly_unresolved() -> None:
    invocation = DbInvocation(
        class_name="OrderPage",
        method_name="SaveData",
        database="OrdersDb",
        procedure_name="usp_saveorder",
        evidence=InvocationEvidence.PROVEN,
        source=InvocationSourceSpan("Ship/OrderPage.aspx.cs", 120, 220),
    )

    paths = build_execution_paths([invocation], _nested_graph(), max_call_depth=0)

    assert len(paths) == 1
    assert paths[0]["unresolved_reason"] == "call_expansion_truncated"
    assert paths[0]["risk_flags"] == ["call_expansion_truncated"]


def test_call_cycle_is_explicitly_unresolved_and_deterministic() -> None:
    graph = _nested_graph()
    graph["relationships"].append(
        {
            "type": "calls",
            "source": "stored_procedure:dbo.usp_WriteAudit",
            "target": "stored_procedure:dbo.usp_SaveOrder",
            "branch_path": ["IF @Reenter = 1"],
        }
    )
    invocation = DbInvocation(
        class_name="OrderPage",
        method_name="SaveData",
        database="OrdersDb",
        procedure_name="usp_saveorder",
        evidence=InvocationEvidence.PROVEN,
        source=InvocationSourceSpan("Ship/OrderPage.aspx", 120, 220),
    )

    paths = build_execution_paths([invocation], graph)
    repeated = build_execution_paths([invocation], graph)

    cycle_paths = [path for path in paths if path["unresolved_reason"] == "stored_procedure_call_cycle"]
    assert len(cycle_paths) == 1
    assert cycle_paths[0]["evidence"] == "unresolved"
    assert cycle_paths[0]["sp_chain"] == [
        "dbo.usp_SaveOrder",
        "dbo.usp_WriteAudit",
        "dbo.usp_SaveOrder",
    ]
    assert cycle_paths[0]["conditions"] == ["IF @Audit = 1", "IF @Reenter = 1"]
    assert cycle_paths[0]["module_chain_ids"] == [
        "stored_procedure:dbo.usp_SaveOrder",
        "stored_procedure:dbo.usp_WriteAudit",
        "stored_procedure:dbo.usp_SaveOrder",
    ]
    assert cycle_paths[0]["terminal_operation_id"] == ""
    assert [(path["path_id"], path["unresolved_reason"]) for path in paths] == [
        (path["path_id"], path["unresolved_reason"]) for path in repeated
    ]


def test_compact_payload_reports_omitted_paths() -> None:
    invocation = DbInvocation(
        class_name="OrderPage",
        method_name="SaveData",
        database="OrdersDb",
        procedure_name="usp_saveorder",
        evidence=InvocationEvidence.PROVEN,
        source=InvocationSourceSpan("Ship/OrderPage.aspx.cs", 120, 220),
    )

    payload = build_compact_execution_path_payload(
        build_execution_paths([invocation], _graph()),
        max_paths=1,
    )

    assert payload["total_paths"] == 2
    assert payload["returned_paths"] == 1
    assert payload["omitted_paths"] == 1
    assert len(payload["paths"]) == 1