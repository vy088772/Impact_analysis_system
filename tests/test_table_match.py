"""Seam 1: `/find_by_table` separates schemas and Databases (canonical-object-identity, Step 2b).

Each case writes one cache for the `Response` Database with a hand-built graph,
asks `find_by_table` for one name, and reads the records back. No case calls the
table match function directly: its keys are the internal detail.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from canonical_object_identity import ObjectName
from code_analyzer.project_scanner import UNRESOLVED_CONNECTION_DATABASE, CSharpTableRelation, ProjectScanResult
from service import analyze_service
from service.sql_cache_store import CacheIdentity, build_object_location_index
from service.schemas import FindByTableRequest
from tests.sql_cache_fixtures import (
    analyzer_operation,
    cache_payload,
    execution_graph,
    one_server_holds_every_database,
)
from tests.test_graph_reverse_lookup import _file, _scan_with_calls

DATABASE = "Response"

Target = tuple[str, str, str, str | None]  # (verb, node schema, node name, Database the relationship states)


def _procedure_id(name: str) -> str:
    return f"stored_procedure:dbo.{name}"


def _graph(
    procedures: dict[str, list[Target]],
    views: dict[str, list[Target]] | None = None,
    schema_source: str = "",
) -> dict:
    """One operation per target. A procedure or a View holds the operations listed for it.

    ``schema_source`` states how the graph found the schema of every target, as the graph builder records it.
    """
    nodes: list[dict] = []
    relationships: list[dict] = []
    seen_tables: set[str] = set()

    def add_module(kind: str, name: str, targets: list[Target]) -> str:
        module_id = f"{kind}:dbo.{name}"
        nodes.append({"id": module_id, "type": kind, "schema": "dbo", "name": name})
        for sequence, (verb, schema, table, database) in enumerate(targets, start=1):
            operation_id = f"dml_operation:{module_id}:{sequence}"
            nodes.append(
                analyzer_operation(
                    "UPDATE" if verb == "writes" else "SELECT",
                    sequence=sequence,
                    id=operation_id,
                    type="dml_operation",
                    module_id=module_id,
                )
            )
            relationships.append({"type": "contains", "source": module_id, "target": operation_id})
            table_id = f"table:{schema}.{table}"
            if table_id not in seen_tables:
                seen_tables.add(table_id)
                nodes.append({"id": table_id, "type": "table", "schema": schema, "name": table})
            relationship = {"type": verb, "source": operation_id, "target": table_id}
            if database:
                relationship["database"] = database
            if schema_source:
                relationship["schema_source"] = schema_source
            relationships.append(relationship)
        return module_id

    for name, targets in procedures.items():
        add_module("stored_procedure", name, targets)
    for name, targets in (views or {}).items():
        view_id = add_module("view", name, targets)
        # A procedure reads the View through one more operation.
        procedure_name = f"usp_Read_{name}"
        procedure_id = f"stored_procedure:dbo.{procedure_name}"
        operation_id = f"dml_operation:{procedure_id}:1"
        nodes.append({"id": procedure_id, "type": "stored_procedure", "schema": "dbo", "name": procedure_name})
        nodes.append(
            analyzer_operation(
                "SELECT", id=operation_id, type="dml_operation", module_id=procedure_id
            )
        )
        relationships.append({"type": "contains", "source": procedure_id, "target": operation_id})
        relationships.append({"type": "reads", "source": operation_id, "target": view_id})
    return execution_graph(DATABASE, nodes=nodes, relationships=relationships)


def _ask(
    monkeypatch,
    tmp_path: Path,
    graph: dict,
    procedures: list[str],
    table_name: str,
    *,
    write_only: bool = False,
    scan: ProjectScanResult | None = None,
    database: str = DATABASE,
):
    if scan is None:
        scan = _scan_with_calls(
            tmp_path,
            [(f"Page{index}.cs", f"Page{index}", "Save", f"dbo.{name}") for index, name in enumerate(procedures)],
        )
        for sources in scan.connection_sources.values():
            sources["conn"] = DATABASE
    monkeypatch.setattr(analyze_service, "resolve_scan_roots", lambda source, refresh=False: [tmp_path])
    monkeypatch.setattr(analyze_service, "_get_scan", lambda root, refresh=False: scan)
    monkeypatch.setattr(analyze_service.sql_cache_store, "find_cache_identity", one_server_holds_every_database)
    monkeypatch.setattr(
        analyze_service.sql_cache_store,
        "load_cached",
        lambda identity: cache_payload(DATABASE, graph=graph),
    )
    return analyze_service.find_by_table(
        FindByTableRequest(
            source={"project": "orders", "repo": "orders"},
            table_name=table_name,
            database=database,
            cache_only=False,
            write_only=write_only,
        )
    ).matches


def _tables(matches) -> list[str]:
    return sorted(match.table for match in matches)


def test_case_1_a_schema_that_the_graph_states_never_matches_another_schema(monkeypatch, tmp_path) -> None:
    graph = _graph({"usp_Save": [("writes", "COMMON", "AVM", None)]})

    assert _ask(monkeypatch, tmp_path, graph, ["usp_Save"], "dbo.AVM") == []


def test_case_2_the_same_schema_matches_with_no_mark(monkeypatch, tmp_path) -> None:
    graph = _graph({"usp_Save": [("writes", "COMMON", "AVM", None)]})

    matches = _ask(monkeypatch, tmp_path, graph, ["usp_Save"], "COMMON.AVM")

    assert _tables(matches) == ["COMMON.AVM"]
    assert "unproven_schema" not in matches[0].risk_flags


def test_case_3_a_target_with_no_schema_matches_with_the_unproven_schema_mark(monkeypatch, tmp_path) -> None:
    graph = _graph({"usp_Save": [("writes", "", "AVM", None)]})

    matches = _ask(monkeypatch, tmp_path, graph, ["usp_Save"], "COMMON.AVM", write_only=True)

    assert _tables(matches) == ["AVM"]
    assert "unproven_schema" in matches[0].risk_flags
    assert matches[0].evidence_status == "proven"
    assert matches[0].stated_database is None


def test_case_4_a_bare_name_matches_every_schema_with_no_mark(monkeypatch, tmp_path) -> None:
    graph = _graph({"usp_A": [("writes", "COMMON", "AVM", None)], "usp_B": [("writes", "dbo", "AVM", None)]})

    matches = _ask(monkeypatch, tmp_path, graph, ["usp_A", "usp_B"], "AVM")

    assert _tables(matches) == ["COMMON.AVM", "dbo.AVM"]
    assert all("unproven_schema" not in match.risk_flags for match in matches)


def test_case_5_a_relationship_that_states_another_database_never_matches_the_local_table(
    monkeypatch, tmp_path
) -> None:
    graph = _graph({"usp_Save": [("reads", "dbo", "Users", "PUR")]})

    assert _ask(monkeypatch, tmp_path, graph, ["usp_Save"], "Response.dbo.Users") == []


def test_case_6_a_relationship_that_states_a_database_matches_that_database(monkeypatch, tmp_path) -> None:
    graph = _graph({"usp_Save": [("reads", "dbo", "Users", "PUR")]})

    matches = _ask(monkeypatch, tmp_path, graph, ["usp_Save"], "PUR.dbo.Users")

    assert _tables(matches) == ["dbo.Users"]
    assert matches[0].stated_database == "PUR"


def test_case_7_a_relationship_that_states_no_database_takes_the_graphs_own(monkeypatch, tmp_path) -> None:
    graph = _graph({"usp_Save": [("reads", "dbo", "Users", None)]})

    matches = _ask(monkeypatch, tmp_path, graph, ["usp_Save"], "Response.dbo.Users")

    assert _tables(matches) == ["dbo.Users"]
    assert matches[0].stated_database is None


def test_case_8_a_view_read_obeys_the_same_rule(monkeypatch, tmp_path) -> None:
    graph = _graph(
        {},
        views={"vw_Unproven": [("reads", "", "AVM", None)], "vw_Proven": [("reads", "dbo", "AVM", None)]},
    )

    matches = _ask(
        monkeypatch, tmp_path, graph, ["usp_Read_vw_Unproven", "usp_Read_vw_Proven"], "COMMON.AVM"
    )

    assert [match.program for match in matches] == ["page0"]
    assert "unproven_schema" in matches[0].risk_flags


def test_a_bare_name_question_takes_the_database_of_the_request(monkeypatch, tmp_path) -> None:
    graph = _graph({"usp_Save": [("reads", "dbo", "Users", "PUR")]})

    assert _ask(monkeypatch, tmp_path, graph, ["usp_Save"], "Users") == []


def test_an_execution_path_states_a_full_key_for_each_target() -> None:
    from code_analyzer.csharp_analysis_gateway import (
        DbInvocation,
        InvocationEvidence,
        InvocationSourceSpan,
    )
    from service.execution_path_builder import build_execution_paths

    graph = _graph(
        {"usp_Save": [("writes", "", "AVM", None), ("reads", "dbo", "Users", "PUR")]}
    )
    invocation = DbInvocation(
        class_name="Page",
        method_name="Save",
        database=DATABASE,
        procedure_name="usp_Save",
        evidence=InvocationEvidence.PROVEN,
        source=InvocationSourceSpan("Page.cs", 1, 2),
        procedure_schema="dbo",
        source_snapshot_hash="sha256:x",
    )

    paths = build_execution_paths([invocation], graph)

    assert [path["write_full_keys"] for path in paths] == [
        [{"database": DATABASE, "schema": "", "name": "AVM", "schema_source": "unresolved"}],
        [],
    ]
    assert [path["read_full_keys"] for path in paths] == [
        [],
        [{"database": "PUR", "schema": "dbo", "name": "Users", "schema_source": "written"}],
    ]


# ---------------------------------------------------------------- inline C# SQL


def _inline_scan(
    root: Path, table: ObjectName, connection_database: str
) -> ProjectScanResult:
    csharp = _file(root, "InlinePage.cs", [])
    return ProjectScanResult(
        project_root=str(root),
        project_name="orders",
        scan_time=datetime.now(),
        csharp_results=[csharp],
        aspx_results=[],
        table_relations=[
            CSharpTableRelation(
                csharp_file=str(root / "InlinePage.cs"),
                class_name="InlinePage",
                method_name="Load",
                line_number=1,
                table=table,
                database=connection_database,
                access_type="READ",
            )
        ],
    )


def _ask_inline(
    monkeypatch,
    tmp_path,
    table: ObjectName,
    connection_database: str,
    asked: str,
    *,
    listed_tables: list[str] | None = None,
):
    """Ask one inline C# SQL question.

    ``listed_tables`` are the objects that the Object Location Index of the
    connection's Database holds. None means that no index exists. No case may open a cache.
    """
    scan = _inline_scan(tmp_path, table, connection_database)
    monkeypatch.setattr(analyze_service, "resolve_scan_roots", lambda source, refresh=False: [tmp_path])
    monkeypatch.setattr(analyze_service, "_get_scan", lambda root, refresh=False: scan)

    def fail_to_open_a_cache(identity):
        raise AssertionError("an inline C# SQL question must not open a cache")

    monkeypatch.setattr(analyze_service.sql_cache_store, "load_cached", fail_to_open_a_cache)
    if listed_tables is None:
        monkeypatch.setattr(analyze_service.sql_cache_store, "find_cache_identity", lambda database: None)
    else:
        identity = CacheIdentity.of("vmsystest07", connection_database)
        index = build_object_location_index(identity, cache_payload(connection_database, tables=listed_tables))
        monkeypatch.setattr(analyze_service.sql_cache_store, "find_cache_identity", lambda database: identity)
        monkeypatch.setattr(analyze_service.sql_cache_store, "load_object_location_index", lambda given: index)
    return analyze_service.find_by_table(
        FindByTableRequest(
            source={"project": "orders", "repo": "orders"},
            table_name=asked,
            cache_only=False,
        )
    ).matches


def test_inline_case_1_a_schema_that_the_relation_states_never_matches_another_schema(
    monkeypatch, tmp_path
) -> None:
    table = ObjectName("", "", "COMMON", "AVM")

    assert _ask_inline(monkeypatch, tmp_path, table, "Response", "dbo.AVM") == []


def test_inline_case_2_a_relation_with_no_schema_matches_with_the_mark(monkeypatch, tmp_path) -> None:
    matches = _ask_inline(monkeypatch, tmp_path, ObjectName("", "", "", "AVM"), "Response", "COMMON.AVM")

    assert [(match.table, match.risk_flags) for match in matches] == [("AVM", ["unproven_schema"])]


def test_inline_case_3_a_relation_that_states_another_database_never_matches(monkeypatch, tmp_path) -> None:
    table = ObjectName("", "PUR", "dbo", "Users")

    assert _ask_inline(monkeypatch, tmp_path, table, "Response", "Response.dbo.Users") == []


def test_inline_case_4_an_unresolved_connection_leaves_the_database_out_of_the_match(
    monkeypatch, tmp_path
) -> None:
    # The scanner writes this marker when it cannot resolve the connection.
    matches = _ask_inline(
        monkeypatch, tmp_path, ObjectName("", "", "dbo", "Users"), UNRESOLVED_CONNECTION_DATABASE, "Response.dbo.Users"
    )

    assert [match.table for match in matches] == ["dbo.Users"]
    assert matches[0].stated_database is None


def test_an_inline_relation_that_states_another_database_than_its_connection_reports_it(
    monkeypatch, tmp_path
) -> None:
    table = ObjectName("", "PUR", "dbo", "Users")

    matches = _ask_inline(monkeypatch, tmp_path, table, "Response", "PUR.dbo.Users")

    assert [(match.table, match.stated_database) for match in matches] == [("PUR.dbo.Users", "PUR")]


def test_the_backward_chain_keeps_an_inline_relation_whose_connection_is_unresolved(tmp_path) -> None:
    from service import flow_chain_builder

    scan = _inline_scan(tmp_path, ObjectName("", "", "dbo", "Users"), UNRESOLVED_CONNECTION_DATABASE)

    chains = flow_chain_builder.build_backward_chains(scan, tmp_path, "dbo.Users", database="Response")

    assert [(chain["via"], chain["method"]) for chain in chains] == [("direct_sql", "Load")]


# ---------------------------------------------------------------- schema source (unstated-schema, ticket 06)


def test_a_record_shows_the_schema_source_that_the_graph_resolved_to_the_module_schema(
    monkeypatch, tmp_path
) -> None:
    graph = _graph({"usp_Save": [("writes", "COMMON", "AVM", None)]}, schema_source="module_schema")

    matches = _ask(monkeypatch, tmp_path, graph, ["usp_Save"], "COMMON.AVM")

    assert [(match.table, match.schema_source) for match in matches] == [("COMMON.AVM", "module_schema")]
    assert "unproven_schema" not in matches[0].risk_flags


def test_a_record_shows_a_written_schema_source(monkeypatch, tmp_path) -> None:
    graph = _graph({"usp_Save": [("writes", "COMMON", "AVM", None)]}, schema_source="written")

    matches = _ask(monkeypatch, tmp_path, graph, ["usp_Save"], "COMMON.AVM")

    assert [match.schema_source for match in matches] == ["written"]


def test_a_record_for_a_target_with_no_schema_shows_the_unresolved_source(monkeypatch, tmp_path) -> None:
    graph = _graph({"usp_Save": [("writes", "", "AVM", None)]}, schema_source="unresolved")

    matches = _ask(monkeypatch, tmp_path, graph, ["usp_Save"], "AVM")

    assert [(match.schema_source, match.risk_flags) for match in matches] == [("unresolved", ["unproven_schema"])]


def test_a_view_read_record_shows_the_schema_source_of_the_read_inside_the_view(monkeypatch, tmp_path) -> None:
    graph = _graph({}, views={"vw_Avm": [("reads", "dbo", "AVM", None)]}, schema_source="default_schema")

    matches = _ask(monkeypatch, tmp_path, graph, ["usp_Read_vw_Avm"], "dbo.AVM")

    assert [match.schema_source for match in matches] == ["default_schema"]


def test_a_graph_with_no_recorded_source_shows_written_for_a_stated_schema(monkeypatch, tmp_path) -> None:
    graph = _graph({"usp_Save": [("writes", "COMMON", "AVM", None)]})

    matches = _ask(monkeypatch, tmp_path, graph, ["usp_Save"], "COMMON.AVM")

    assert [match.schema_source for match in matches] == ["written"]


def test_an_inline_table_with_no_schema_takes_dbo_when_the_index_holds_it(monkeypatch, tmp_path) -> None:
    matches = _ask_inline(
        monkeypatch, tmp_path, ObjectName("", "", "", "AVM"), "Response", "dbo.AVM", listed_tables=["dbo.AVM"]
    )

    assert [(match.table, match.schema_source, match.risk_flags) for match in matches] == [
        ("dbo.AVM", "default_schema", [])
    ]


def test_an_inline_table_that_dbo_holds_never_answers_another_schema(monkeypatch, tmp_path) -> None:
    matches = _ask_inline(
        monkeypatch, tmp_path, ObjectName("", "", "", "AVM"), "Response", "COMMON.AVM", listed_tables=["dbo.AVM"]
    )

    assert matches == []


def test_an_inline_table_with_no_schema_keeps_the_mark_when_the_index_lacks_dbo(monkeypatch, tmp_path) -> None:
    matches = _ask_inline(
        monkeypatch, tmp_path, ObjectName("", "", "", "AVM"), "Response", "COMMON.AVM", listed_tables=["COMMON.AVM"]
    )

    assert [(match.table, match.schema_source, match.risk_flags) for match in matches] == [
        ("AVM", "unresolved", ["unproven_schema"])
    ]


def test_an_inline_table_with_no_index_keeps_the_mark(monkeypatch, tmp_path) -> None:
    matches = _ask_inline(monkeypatch, tmp_path, ObjectName("", "", "", "AVM"), "Response", "AVM")

    assert [(match.schema_source, match.risk_flags) for match in matches] == [("unresolved", ["unproven_schema"])]


def test_an_inline_table_with_a_written_schema_shows_written(monkeypatch, tmp_path) -> None:
    matches = _ask_inline(monkeypatch, tmp_path, ObjectName("", "", "COMMON", "AVM"), "Response", "COMMON.AVM")

    assert [(match.schema_source, match.risk_flags) for match in matches] == [("written", [])]


def test_a_located_database_row_carries_no_schema_source() -> None:
    from service.schemas import LocatedDatabase

    assert "schema_source" not in LocatedDatabase.model_fields
    assert "schema_source" not in LocatedDatabase().model_dump(by_alias=True)
