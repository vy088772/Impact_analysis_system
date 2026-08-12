"""Acceptance checks for nested SQL execution facts."""

from __future__ import annotations

import tempfile
from pathlib import Path

from code_analyzer.static_analyzer_host import StaticAnalyzerHost
from code_analyzer.csharp_analysis_gateway import (
    DbInvocation,
    InvocationEvidence,
    InvocationSourceSpan,
)
from service.execution_path_builder import build_execution_paths
from service.sql_execution_graph import build_sql_execution_graph


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_sql_host_emits_nested_calls_and_dynamic_sql_facts() -> None:
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()
    sql = """CREATE PROCEDURE dbo.usp_Parent
AS
BEGIN
    IF @Mode = 1
        EXEC dbo.usp_Child @Id = @Id;
    ELSE
        EXECUTE dbo.usp_Other;
    EXEC(@sql);
END;
"""

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "usp_Parent.sql"
        source_path.write_text(sql, encoding="utf-8")

        result = host.analyze_sql(source_path)

    operations = result["operations"]
    assert [operation["operation_type"] for operation in operations] == [
        "CALL",
        "CALL",
        "DYNAMIC_SQL",
    ]
    assert operations[0]["call_targets"] == ["dbo.usp_Child"]
    assert operations[0]["branch_path"] == ["IF @Mode = 1"]
    assert operations[1]["call_targets"] == ["dbo.usp_Other"]
    assert operations[1]["branch_path"] == ["ELSE (NOT (@Mode = 1))"]
    assert operations[2]["dynamic_sql"] is True
    assert operations[2]["call_targets"] == []


def test_sql_host_preserves_try_catch_and_loop_branch_paths() -> None:
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()
    sql = """CREATE PROCEDURE dbo.usp_ControlFlow
AS
BEGIN
    BEGIN TRY
        UPDATE dbo.OrderItem SET Status = 1 WHERE Id = @Id;
    END TRY
    BEGIN CATCH
        DELETE FROM dbo.OrderItem WHERE Id = @Id;
    END CATCH;
    WHILE @Retry < 3
        UPDATE dbo.OrderItem SET Status = 2 WHERE Id = @Id;
END;
"""

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "usp_ControlFlow.sql"
        source_path.write_text(sql, encoding="utf-8")

        result = host.analyze_sql(source_path)

    operations = result["operations"]
    assert [operation["operation_type"] for operation in operations] == [
        "UPDATE",
        "DELETE",
        "UPDATE",
    ]
    assert operations[0]["branch_path"] == ["TRY"]
    assert operations[1]["branch_path"] == ["CATCH"]
    assert operations[2]["branch_path"] == ["WHILE @Retry < 3"]


def test_sql_host_emits_schema_qualified_scalar_udf_facts() -> None:
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()
    sql = """CREATE PROCEDURE dbo.usp_NormalizeOrder
AS
BEGIN
    SELECT dbo.fn_NormalizeOrder(Id) FROM dbo.OrderItem;
END;
"""

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "usp_NormalizeOrder.sql"
        source_path.write_text(sql, encoding="utf-8")

        result = host.analyze_sql(source_path)

    assert result["operations"][0]["function_references"] == ["dbo.fn_NormalizeOrder"]


def test_sql_graph_expands_nested_calls_and_keeps_dynamic_sql_unresolved() -> None:
    data = {
        "database": "OrdersDb",
        "schema": "dbo",
        "procedures": [
            {
                "name": "dbo.usp_Parent",
                "definition": """CREATE PROCEDURE dbo.usp_Parent
AS
BEGIN
    IF @Mode = 1
        EXEC dbo.usp_Child;
    ELSE
        EXEC dbo.usp_Child;
    EXEC(@sql);
END;
""",
            },
            {
                "name": "dbo.usp_Child",
                "definition": """CREATE PROCEDURE dbo.usp_Child
AS
BEGIN
    IF @Mode = 1
        UPDATE dbo.OrderItem SET Status = 1 WHERE Id = @Id;
    ELSE
        DELETE FROM dbo.OrderItem WHERE Id = @Id;
END;
""",
            },
        ],
        "views": [],
        "functions": [],
        "tables": [{"name": "dbo.OrderItem"}],
    }

    graph = build_sql_execution_graph(data)
    nodes_by_id = {node["id"]: node for node in graph["nodes"]}
    calls = [relationship for relationship in graph["relationships"] if relationship["type"] == "calls"]

    assert len(calls) == 2
    assert {relationship["target"] for relationship in calls} == {
        "stored_procedure:dbo.usp_Child"
    }
    assert {tuple(relationship["branch_path"]) for relationship in calls} == {
        ("IF @Mode = 1",),
        ("ELSE (NOT (@Mode = 1))",),
    }
    dynamic_nodes = [node for node in graph["nodes"] if node["type"] == "unresolved_dynamic_sql"]
    assert len(dynamic_nodes) == 1
    assert dynamic_nodes[0]["operation_type"] == "DYNAMIC_SQL"
    assert any(
        relationship["type"] == "unresolved"
        and relationship["target"] == dynamic_nodes[0]["id"]
        for relationship in graph["relationships"]
    )
    assert any(
        node["type"] == "dml_operation"
        and node["module_id"] == "stored_procedure:dbo.usp_Child"
        and node["operation_type"] == "UPDATE"
        for node in nodes_by_id.values()
    )


def test_execution_paths_expand_nested_sql_calls_into_branch_specific_terminals() -> None:
    graph = build_sql_execution_graph(
        {
            "database": "OrdersDb",
            "schema": "dbo",
            "procedures": [
                {
                    "name": "dbo.usp_Parent",
                    "definition": """CREATE PROCEDURE dbo.usp_Parent
AS
BEGIN
    IF @Mode = 1
        EXEC dbo.usp_Child;
    ELSE
        EXEC dbo.usp_Child;
    EXEC(@sql);
END;
""",
                },
                {
                    "name": "dbo.usp_Child",
                    "definition": """CREATE PROCEDURE dbo.usp_Child
AS
BEGIN
    IF @Mode = 1
        UPDATE dbo.OrderItem SET Status = 1 WHERE Id = @Id;
    ELSE
        DELETE FROM dbo.OrderItem WHERE Id = @Id;
END;
""",
                },
            ],
            "views": [],
            "functions": [],
            "tables": [{"name": "dbo.OrderItem"}],
        }
    )
    invocation = DbInvocation(
        class_name="OrderPage",
        method_name="Save",
        database="OrdersDb",
        procedure_name="usp_Parent",
        evidence=InvocationEvidence.PROVEN,
        source=InvocationSourceSpan("OrderPage.cs", 10, 20),
        procedure_schema="dbo",
        method_chain=("Save",),
    )

    paths = build_execution_paths([invocation], graph)

    assert len(paths) == 5
    terminal_paths = [path for path in paths if path["terminal_operation"]]
    assert len(terminal_paths) == 5
    assert {path["terminal_operation"] for path in terminal_paths} == {
        "UPDATE",
        "DELETE",
        "DYNAMIC_SQL",
    }
    nested_paths = [path for path in terminal_paths if path["sp_chain"] == ["dbo.usp_Parent", "dbo.usp_Child"]]
    assert len(nested_paths) == 4
    assert len({path["path_id"] for path in nested_paths}) == 4
    assert all("dbo.usp_Child" in path["sp_chain"] for path in nested_paths)
    assert any(
        path["terminal_operation"] == "DYNAMIC_SQL"
        and path["evidence"] == "unresolved"
        and "dynamic_sql" in path["risk_flags"]
        and path["target"] == ""
        for path in paths
    )


def test_sql_graph_preserves_cte_temp_lineage_and_typed_view_function_usage() -> None:
    graph = build_sql_execution_graph(
        {
            "database": "OrdersDb",
            "schema": "dbo",
            "procedures": [
                {
                    "name": "dbo.usp_Lineage",
                    "definition": """CREATE PROCEDURE dbo.usp_Lineage
AS
BEGIN
    WITH SourceRows AS (
        SELECT Id FROM dbo.OrderItem
    )
    SELECT Id INTO #TempOrder FROM SourceRows;
    SELECT Id FROM #TempOrder;
    SELECT Id FROM dbo.vOrder;
    SELECT Id FROM dbo.fn_OrderItems();
END;
""",
                }
            ],
            "views": [
                {
                    "name": "dbo.vOrder",
                    "definition": "CREATE VIEW dbo.vOrder AS SELECT Id FROM dbo.OrderItem;",
                }
            ],
            "functions": [
                {
                    "name": "dbo.fn_OrderItems",
                    "definition": "CREATE FUNCTION dbo.fn_OrderItems() RETURNS TABLE AS RETURN (SELECT Id FROM dbo.OrderItem);",
                }
            ],
            "tables": [{"name": "dbo.OrderItem"}],
        }
    )

    nodes_by_id = {node["id"]: node for node in graph["nodes"]}
    relationships = graph["relationships"]
    operation_nodes = sorted(
        (
            node
            for node in graph["nodes"]
            if node["type"] == "dml_operation"
            and node["module_id"] == "stored_procedure:dbo.usp_Lineage"
        ),
        key=lambda node: node["sequence"],
    )

    assert nodes_by_id["view:dbo.vOrder"]["type"] == "view"
    assert nodes_by_id["function:dbo.fn_OrderItems"]["type"] == "function"
    assert any(
        relationship["type"] == "reads"
        and relationship["source"] == operation_nodes[0]["id"]
        and relationship["target"] == "table:dbo.OrderItem"
        for relationship in relationships
    )
    assert any(
        relationship["type"] == "reads"
        and relationship["source"] == operation_nodes[1]["id"]
        and relationship["target"] == "table:dbo.OrderItem"
        and relationship.get("lineage")
        for relationship in relationships
    )
    assert any(
        relationship["type"] == "uses"
        and relationship["source"] == "stored_procedure:dbo.usp_Lineage"
        and relationship["target"] == "view:dbo.vOrder"
        for relationship in relationships
    )
    assert any(
        relationship["type"] == "uses"
        and relationship["source"] == "stored_procedure:dbo.usp_Lineage"
        and relationship["target"] == "function:dbo.fn_OrderItems"
        for relationship in relationships
    )
