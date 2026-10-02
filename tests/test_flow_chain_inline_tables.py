"""Seam 2: `/flow_chain` reads the inline SQL table relations in both directions.

Each test builds a C# Scan Result with table relations and asks `/flow_chain`,
and the schema case also asks `/find_by_table`. Forward takes the relations of
the reachable methods, and backward takes the relations that match the table
question, so both directions name the same inline SQL tables for one method.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from canonical_object_identity import ObjectName
from code_analyzer.models import MethodInfo
from code_analyzer.project_scanner import CSharpTableRelation, INLINE_SQL_PARSED, ProjectScanResult
from service import analyze_service
from service.schemas import AzureSource, FindByTableRequest, FlowChainRequest
from service.sql_cache_store import AmbiguousServer, CacheIdentity, build_object_location_index
from tests.sql_cache_fixtures import cache_payload
from tests.scan_fixtures import csharp_file, scan_of
from service.request_context_adapters import InMemoryCacheStore
from tests.request_context_fixtures import RequestStores

_SOURCE = AzureSource(project="orders", repo="orders")


@pytest.mark.parametrize("direction", ["forward", "backward"])
def test_flow_skips_when_one_candidate_root_has_no_scan_cache(tmp_path: Path, direction: str) -> None:
    stores = RequestStores.of(tmp_path, scan_of(tmp_path, [], []))
    stores.scan_store.candidate_roots = [tmp_path, tmp_path / "unscanned"]

    response = analyze_service.flow_chain(
        FlowChainRequest(source=_SOURCE, direction=direction),
        scan_store=stores.scan_store,
        cache_store=stores.cache_store,
    )

    assert response.model_dump() == {
        "direction": direction,
        "forward_chain": None,
        "backward_chains": [],
        "diagnostics": [],
        "source_root": "",
        "skipped": True,
    }


@pytest.mark.parametrize("direction", ["forward", "backward"])
def test_flow_reads_an_ambiguous_database_as_not_scanned(tmp_path: Path, direction: str) -> None:
    load = MethodInfo(name="Load", access_modifier="private", return_type="void")
    stores = RequestStores.of(tmp_path, _scan(tmp_path, [load], []))
    stores.cache_store = InMemoryCacheStore({
        "OrdersDb": AmbiguousServer("OrdersDb", ("host-a", "host-b")),
    })

    with pytest.raises(analyze_service.SqlExecutionGraphRequiredError) as caught:
        analyze_service.flow_chain(
            FlowChainRequest(
                source=_SOURCE,
                direction=direction,
                program_name="OrderPage",
                anchor_method="Load",
                table_name="Orders",
                database="OrdersDb",
            ),
            scan_store=stores.scan_store,
            cache_store=stores.cache_store,
        )

    assert caught.value.code == "sql_execution_graph_required"
    assert caught.value.reason == "missing_or_invalid"
    assert caught.value.database == "OrdersDb"


@pytest.mark.parametrize("direction", ["forward", "backward"])
def test_flow_refresh_bypasses_a_missing_scan_cache(tmp_path: Path, direction: str) -> None:
    stores = RequestStores.of(tmp_path, scan_of(tmp_path, [], []))
    stores.scan_store.cached_roots.clear()

    response = analyze_service.flow_chain(
        FlowChainRequest(source=_SOURCE, direction=direction, refresh=True),
        scan_store=stores.scan_store,
        cache_store=stores.cache_store,
    )

    assert response.skipped is False
    assert response.source_root == str(tmp_path)
    assert response.forward_chain is None
    assert response.backward_chains == []


def _relation(root: Path, method: str, table: ObjectName, access_type: str = "SELECT") -> CSharpTableRelation:
    return CSharpTableRelation(
        csharp_file=str(root / "OrderPage.cs"),
        class_name="OrderPage",
        method_name=method,
        line_number=1,
        table=table,
        database="Response",
        access_type=access_type,
        reason=INLINE_SQL_PARSED,
    )


def _scan(root: Path, methods: list[MethodInfo], relations: list[CSharpTableRelation]) -> ProjectScanResult:
    return scan_of(root, [csharp_file(root, "OrderPage.cs", methods)], relations)


def _serve(monkeypatch, root: Path, scan: ProjectScanResult, listed_tables: list[str] | None = None) -> None:
    """Serve the scan to every question. ``listed_tables`` are the objects of the Object Location Index."""
    stores = RequestStores.of(root, scan)
    stores.cache_store = InMemoryCacheStore()
    if listed_tables is None:
        stores.install_flow(monkeypatch)
        stores.install_table(monkeypatch)
        return
    identity = CacheIdentity.of("vmsystest07", "Response")
    index = build_object_location_index(identity, cache_payload("Response", tables=listed_tables))
    stores.cache_store.identities.update({"": identity, "Response": identity})
    stores.install_flow(monkeypatch)
    stores.install_table(monkeypatch)
    monkeypatch.setattr(analyze_service.sql_cache_store, "load_object_location_index", lambda given: index)


def _forward(anchor: str) -> dict:
    response = analyze_service.flow_chain(
        FlowChainRequest(
            source=_SOURCE, direction="forward", program_name="OrderPage", anchor_method=anchor, cache_only=False
        )
    )
    assert response.forward_chain is not None
    return response.forward_chain


def _backward_methods(table_name: str) -> list[str]:
    response = analyze_service.flow_chain(
        FlowChainRequest(source=_SOURCE, direction="backward", table_name=table_name, cache_only=False)
    )
    return [chain["method"] for chain in response.backward_chains if chain["via"] == "direct_sql"]


def _find_by_table_methods(table_name: str) -> list[str]:
    response = analyze_service.find_by_table(
        FindByTableRequest(source=_SOURCE, table_name=table_name, cache_only=False)
    )
    return [match.caller_method for match in response.matches]


def test_a_function_in_the_sql_string_gives_no_table_in_either_direction(monkeypatch, tmp_path) -> None:
    # The parser gives a relation for the table and none for the function.
    load = MethodInfo(
        name="Load",
        access_modifier="private",
        return_type="void",
        sql_queries=["SELECT * FROM dbo.fnList(1) f JOIN dbo.Orders o ON o.Id = f.Id"],
    )
    scan = _scan(tmp_path, [load], [_relation(tmp_path, "Load", ObjectName("", "", "dbo", "Orders"))])
    _serve(monkeypatch, tmp_path, scan)

    forward = _forward("Load")

    assert forward["inline_sql_tables"] == ["Orders"]
    assert "fnList" not in forward["tables"]
    assert _backward_methods("dbo.fnList") == []
    assert _backward_methods("dbo.Orders") == ["Load"]


def test_a_relation_that_resolves_to_dbo_never_answers_another_schema_backward(monkeypatch, tmp_path) -> None:
    load = MethodInfo(name="Load", access_modifier="private", return_type="void")
    scan = _scan(tmp_path, [load], [_relation(tmp_path, "Load", ObjectName("", "", "", "AVM"))])
    _serve(monkeypatch, tmp_path, scan, listed_tables=["dbo.AVM"])

    assert _backward_methods("COMMON.AVM") == []
    assert _find_by_table_methods("COMMON.AVM") == []
    # The proof that the two asserts above are not empty: the resolved schema answers.
    assert _backward_methods("dbo.AVM") == ["Load"]
    assert _find_by_table_methods("dbo.AVM") == ["Load"]


def test_forward_and_backward_give_the_same_inline_tables_for_one_method(monkeypatch, tmp_path) -> None:
    save = MethodInfo(name="SaveData", access_modifier="private", return_type="void", calls=["WriteAudit"])
    audit = MethodInfo(name="WriteAudit", access_modifier="private", return_type="void")
    relations = [
        _relation(tmp_path, "SaveData", ObjectName("", "", "dbo", "Orders"), "UPDATE"),
        _relation(tmp_path, "SaveData", ObjectName("", "", "dbo", "Items")),
        _relation(tmp_path, "WriteAudit", ObjectName("", "", "dbo", "AuditLog"), "INSERT"),
    ]
    _serve(monkeypatch, tmp_path, _scan(tmp_path, [save, audit], relations))

    forward = _forward("SaveData")

    assert forward["inline_sql_tables"] == ["AuditLog", "Items", "Orders"]
    for table in forward["inline_sql_tables"]:
        reachable_writers = set(_backward_methods(table)) & set(forward["reachable_methods"])
        assert reachable_writers, table
    assert _backward_methods("dbo.Items") == ["SaveData"]
    assert _backward_methods("dbo.AuditLog") == ["WriteAudit"]


def test_a_relation_of_a_method_that_is_not_reachable_stays_out_of_forward(monkeypatch, tmp_path) -> None:
    save = MethodInfo(name="SaveData", access_modifier="private", return_type="void")
    other = MethodInfo(name="BindOther", access_modifier="private", return_type="void")
    relations = [
        _relation(tmp_path, "SaveData", ObjectName("", "", "dbo", "Orders")),
        _relation(tmp_path, "BindOther", ObjectName("", "", "dbo", "Customers")),
    ]
    _serve(monkeypatch, tmp_path, _scan(tmp_path, [save, other], relations))

    forward = _forward("SaveData")

    assert forward["inline_sql_tables"] == ["Orders"]
    assert forward["tables"] == ["Orders"]
