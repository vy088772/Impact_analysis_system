"""Checks that formal output consumers no longer depend on legacy relations."""

from __future__ import annotations

import json
from types import SimpleNamespace

from service.dependency_fetcher import fetch_dependencies
from service import sp_fetcher


def test_dependency_fetcher_requires_execution_graph() -> None:
    graph = {
        "nodes": [
            {"id": "sp:entry", "type": "stored_procedure", "name": "usp_Entry"},
            {"id": "sp:nested", "type": "stored_procedure", "name": "usp_Nested"},
        ],
        "relationships": [
            {"type": "calls", "source": "sp:entry", "target": "sp:nested"},
        ],
    }

    assert fetch_dependencies(["dbo.usp_Entry"], "OrdersDb", graph=graph) == {
        "dbo.usp_Entry": {
            "depends_on": ["usp_Nested"],
            "depended_by": [],
        }
    }
    assert fetch_dependencies(["dbo.usp_Entry"], "OrdersDb") == {}


def test_dependency_graph_renderer_ignores_legacy_sp_relations(tmp_path) -> None:
    import pytest

    pytest.importorskip("networkx")
    pytest.importorskip("matplotlib")
    from code_analyzer.dependency_graph import DependencyGraphGenerator

    scan_result = SimpleNamespace(
        project_name="demo",
        csharp_results=[],
        sp_relations=[SimpleNamespace(sp_name="legacy_only")],
    )
    scan_result.iter_formal_sp_invocations = lambda: [
        {
            "source_file": "OrderPage.cs",
            "class_name": "OrderPage",
            "method_name": "Save",
            "line_number": 12,
            "procedure_name": "usp_Save",
            "database": "OrdersDb",
        }
    ]

    renderer = DependencyGraphGenerator(scan_result)
    output_path = tmp_path / "graph.json"

    assert renderer.export_to_json(str(output_path)) == str(output_path)
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert {node["label"] for node in payload["nodes"]} == {"OrderPage", "usp_Save"}
    assert payload["edges"] == [{"from": "OrderPage", "to": "usp_Save", "weight": 1}]
    assert renderer.visualize_sp_to_table(str(tmp_path / "sp_to_table.png")) is None


def test_sp_fetcher_uses_graph_lineage_and_keeps_dynamic_sql_unresolved(monkeypatch) -> None:
    procedures = [
        {"name": name, "definition": f"CREATE PROCEDURE dbo.{name} AS SELECT 1;"}
        for name in ("usp_Direct", "usp_Entry", "usp_ReadModules", "usp_Dynamic")
    ]
    graph = {
        "nodes": [
            {"id": "sp:direct", "type": "stored_procedure", "schema": "dbo", "name": "usp_Direct"},
            {"id": "op:direct", "type": "dml_operation", "name": "usp_Direct:1"},
            {"id": "sp:entry", "type": "stored_procedure", "schema": "dbo", "name": "usp_Entry"},
            {"id": "sp:nested", "type": "stored_procedure", "schema": "dbo", "name": "usp_Nested"},
            {"id": "op:nested", "type": "dml_operation", "name": "usp_Nested:1"},
            {"id": "sp:modules", "type": "stored_procedure", "schema": "dbo", "name": "usp_ReadModules"},
            {"id": "op:modules", "type": "dml_operation", "name": "usp_ReadModules:1"},
            {"id": "view:orders", "type": "view", "schema": "dbo", "name": "vOrders"},
            {"id": "op:view", "type": "dml_operation", "name": "vOrders:1"},
            {"id": "function:status", "type": "function", "schema": "dbo", "name": "fnOrderStatus"},
            {"id": "op:function", "type": "dml_operation", "name": "fnOrderStatus:1"},
            {"id": "sp:dynamic", "type": "stored_procedure", "schema": "dbo", "name": "usp_Dynamic"},
            {"id": "op:dynamic", "type": "unresolved_dynamic_sql", "name": "usp_Dynamic:1"},
            {"id": "table:direct", "type": "table", "schema": "dbo", "name": "DirectTable"},
            {"id": "table:nested", "type": "table", "schema": "dbo", "name": "NestedTable"},
            {"id": "table:base", "type": "table", "schema": "dbo", "name": "OrderTable"},
        ],
        "relationships": [
            {"type": "contains", "source": "sp:direct", "target": "op:direct"},
            {"type": "writes", "source": "op:direct", "target": "table:direct"},
            {"type": "calls", "source": "sp:entry", "target": "sp:nested"},
            {"type": "contains", "source": "sp:nested", "target": "op:nested"},
            {"type": "writes", "source": "op:nested", "target": "table:nested"},
            {"type": "contains", "source": "sp:modules", "target": "op:modules"},
            {"type": "reads", "source": "op:modules", "target": "view:orders"},
            {"type": "reads", "source": "op:modules", "target": "function:status"},
            {"type": "contains", "source": "view:orders", "target": "op:view"},
            {"type": "reads", "source": "op:view", "target": "table:base"},
            {"type": "contains", "source": "function:status", "target": "op:function"},
            {"type": "reads", "source": "op:function", "target": "table:base"},
            {"type": "contains", "source": "sp:dynamic", "target": "op:dynamic"},
        ],
    }
    monkeypatch.setattr(
        sp_fetcher,
        "load_cached",
        lambda database, schema="dbo", server="": {
            "database": database,
            "schema": schema,
            "procedures": procedures,
            "sql_execution_graph": graph,
        },
    )

    results = sp_fetcher.fetch_sp_definitions(
        ["usp_Direct", "usp_Entry", "usp_ReadModules", "usp_Dynamic"],
        database_alias="OrdersDb",
    )
    by_name = {item["name"]: item for item in results}

    assert by_name["usp_Direct"]["tables"] == ["dbo.DirectTable"]
    assert by_name["usp_Entry"]["tables"] == ["dbo.NestedTable"]
    assert by_name["usp_ReadModules"]["tables"] == ["dbo.OrderTable"]
    assert by_name["usp_Dynamic"]["tables"] == []
    assert all(item["dependency_source"] == "execution_graph" for item in results)
