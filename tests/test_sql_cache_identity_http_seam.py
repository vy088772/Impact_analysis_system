"""Ticket 01 of `.scratch/sql-cache-identity-crosses-http-seam/`: each request
handler builds the SQL Cache Identity once.

The seam is the HTTP API, as in tests/test_lookup_db_server_api.py. The spec
allows one count below the API: the directory listings of the cache store,
because "a reverse lookup lists the cache directory at most one time" is a
stated requirement.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from canonical_object_identity import ObjectName
from code_analyzer.csharp_analysis_gateway import DbInvocation, InvocationEvidence, InvocationSourceSpan
from code_analyzer.project_scanner import CSharpTableRelation
from service import analyze_service, derived_execution_evidence, sql_cache_store
from service.api import app
from service.request_context_adapters import RealCacheStore
from tests.request_context_fixtures import RequestStores
from service.execution_path_builder import build_execution_paths
from tests.derived_execution_evidence_fixtures import RatedInvocationsRetention
from tests.sql_cache_fixtures import CacheRoot, cache_payload, write_cache
from tests.test_exact_path_evidence import _cached_path_fixture
from tests.test_find_by_sp_likely_matches import _graph as _graph_with_shared_sp
from tests.test_find_by_sp_likely_matches import _scan
from tests.test_lookup_db_server_api import (
    HOST_WITH_THE_SP,
    HOST_WITHOUT_THE_SP,
    _graph_without_the_sp,
    _sp_request,
    _table_request,
    _wire_scan,
    _write_host,
)

client = TestClient(app)

_REVERSE_LOOKUPS = [("/find_by_sp", _sp_request), ("/find_by_table", _table_request)]


@pytest.fixture
def listings(monkeypatch) -> list[int]:
    """Count each directory listing of the cache store; one entry per listing."""
    counted: list[int] = []
    list_cache_files = sql_cache_store.list_cache_files

    def counting_list_cache_files():
        counted.append(1)
        return list_cache_files()

    monkeypatch.setattr(sql_cache_store, "list_cache_files", counting_list_cache_files)
    return counted


@pytest.fixture
def two_hosts(monkeypatch, tmp_path):
    with RatedInvocationsRetention(), CacheRoot() as cache_root:
        _write_host(cache_root, HOST_WITH_THE_SP, _graph_with_shared_sp())
        _write_host(cache_root, HOST_WITHOUT_THE_SP, _graph_without_the_sp())
        stores = _wire_scan(monkeypatch, tmp_path)
        yield stores


@pytest.fixture
def one_host(monkeypatch, tmp_path):
    with RatedInvocationsRetention(), CacheRoot() as cache_root:
        _write_host(cache_root, HOST_WITH_THE_SP, _graph_with_shared_sp())
        stores = _wire_scan(monkeypatch, tmp_path)
        yield stores


@pytest.fixture
def only_the_other_host(monkeypatch, tmp_path):
    with RatedInvocationsRetention(), CacheRoot() as cache_root:
        _write_host(cache_root, HOST_WITHOUT_THE_SP, _graph_with_shared_sp())
        _wire_scan(monkeypatch, tmp_path)
        yield cache_root


@pytest.mark.parametrize(("endpoint", "request_of"), _REVERSE_LOOKUPS)
def test_a_named_host_never_reads_the_cache_of_another_host(
    only_the_other_host, endpoint: str, request_of
) -> None:
    response = client.post(endpoint, json=request_of(db_server=HOST_WITH_THE_SP))

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "sql_execution_graph_required"


@pytest.mark.parametrize(("endpoint", "request_of"), _REVERSE_LOOKUPS)
def test_an_ambiguous_database_lists_the_cache_directory_one_time(
    two_hosts, listings, endpoint: str, request_of
) -> None:
    response = client.post(endpoint, json=request_of())

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "ambiguous_database"
    assert len(listings) == 1


@pytest.mark.parametrize(("endpoint", "request_of"), _REVERSE_LOOKUPS)
def test_a_reverse_lookup_with_no_host_lists_the_cache_directory_one_time(
    one_host, listings, endpoint: str, request_of
) -> None:
    response = client.post(endpoint, json=request_of())

    assert response.status_code == 200
    assert len(listings) == 1


@pytest.mark.parametrize(("endpoint", "request_of"), _REVERSE_LOOKUPS)
def test_a_reverse_lookup_that_names_a_host_lists_the_cache_directory_zero_times(
    two_hosts, listings, endpoint: str, request_of
) -> None:
    response = client.post(endpoint, json=request_of(db_server=HOST_WITH_THE_SP))

    assert response.status_code == 200
    assert listings == []


def test_path_evidence_with_no_host_for_a_database_on_two_hosts_answers_not_scanned(two_hosts, monkeypatch) -> None:
    two_hosts.install_legacy(monkeypatch)
    response = client.post(
        "/path_evidence",
        json={"path_id": "any-path", "source": {"project": "orders", "repo": "orders"}, "database": "OrdersDb"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "sql_execution_graph_required"


@pytest.mark.parametrize(
    "direction_fields",
    [
        {"direction": "backward", "table_name": "dbo.SOrder"},
        {"direction": "forward", "program_name": "ProvenPage", "anchor_method": "SaveProven"},
    ],
)
def test_flow_chain_with_no_host_for_a_database_on_two_hosts_answers_not_scanned(
    two_hosts, monkeypatch, direction_fields: dict
) -> None:
    two_hosts.install_flow(monkeypatch)
    response = client.post(
        "/flow_chain",
        json={
            "source": {"project": "orders", "repo": "orders"},
            "database": "OrdersDb",
            "cache_only": False,
            **direction_fields,
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "sql_execution_graph_required"


def _analyze_request(**extra) -> dict:
    return {
        "source": {"project": "orders", "repo": "orders"},
        "program_names": ["ProvenPage"],
        "database": "OrdersDb",
        "include_sp_defs": True,
        **extra,
    }


def test_analyze_with_definitions_and_no_host_lists_the_cache_directory_one_time(
    one_host, listings, monkeypatch, tmp_path
) -> None:
    one_host.install_analyze(monkeypatch)

    response = client.post("/analyze", json=_analyze_request())

    assert response.status_code == 200
    assert len(listings) == 1


def test_analyze_with_definitions_treats_a_blank_host_as_no_host(one_host, monkeypatch, tmp_path) -> None:
    one_host.install_analyze(monkeypatch)

    response = client.post("/analyze", json=_analyze_request(db_server="   "))

    assert response.status_code == 200


# ------------------------------------------------ follow-up: the inline schema resolver


def _write_host_with_the_table(cache_root, host: str) -> None:
    identity = sql_cache_store.CacheIdentity.of(host, "OrdersDb")
    payload = cache_payload("OrdersDb", tables=["SOrder"], graph=_graph_with_shared_sp())
    write_cache(cache_root, identity, payload)
    sql_cache_store.write_object_location_index(
        identity, sql_cache_store.build_object_location_index(identity, payload)
    )


@pytest.fixture
def two_hosts_and_an_inline_table(monkeypatch, tmp_path):
    """Both hosts hold `dbo.SOrder`. A program reads `SOrder` with no schema in inline SQL."""
    with RatedInvocationsRetention(), CacheRoot() as cache_root:
        _write_host_with_the_table(cache_root, HOST_WITH_THE_SP)
        _write_host_with_the_table(cache_root, HOST_WITHOUT_THE_SP)
        scan = _scan(tmp_path)
        scan.table_relations = [
            CSharpTableRelation(
                csharp_file=str(tmp_path / "ProvenPage.cs"),
                class_name="ProvenPage",
                method_name="SaveProven",
                line_number=1,
                table=ObjectName("", "", "", "SOrder"),
                database="OrdersDb",
                access_type="SELECT",
            )
        ]
        stores = RequestStores.of(tmp_path, scan)
        stores.cache_store = RealCacheStore()
        stores.install_http(monkeypatch)
        monkeypatch.setattr(derived_execution_evidence, "cached_saved_at", lambda root: "scan-v1")
        monkeypatch.setattr(derived_execution_evidence, "cached_commit", lambda root: "commit-v1")
        yield cache_root


def test_find_by_table_resolves_an_inline_schema_from_the_named_host_with_no_listing(
    two_hosts_and_an_inline_table, listings
) -> None:
    response = client.post("/find_by_table", json=_table_request(db_server=HOST_WITH_THE_SP))

    assert response.status_code == 200
    assert [(match["program"], match["schema_source"]) for match in response.json()["matches"]] == [
        ("provenpage", "default_schema")
    ]
    assert listings == []


# ------------------------------------------ follow-up: the literal procedure of path evidence


def test_path_evidence_reads_a_literal_procedure_from_the_requested_cache(tmp_path) -> None:
    """The path names another Database than the request. The definition still comes
    from the cache that the handler identity names, which holds the joined graph."""
    scan, cached, _ = _cached_path_fixture(tmp_path)
    graph = cached["sql_execution_graph"]
    invocation = DbInvocation(
        class_name="OrderPage",
        method_name="Save",
        database="OrdersConnectionDb",
        procedure_name="usp_saveorder",
        evidence=InvocationEvidence.UNRESOLVED,
        source=InvocationSourceSpan("OrderPage.cs", 0, 10),
        reason="wrapper_source_unavailable",
        procedure_schema="dbo",
        method_chain=("Save",),
        raw_command_text="[dbo].[usp_SaveOrder]",
    )
    path = build_execution_paths([invocation], graph)[0]
    with CacheRoot() as cache_root:
        identity = sql_cache_store.CacheIdentity.of(HOST_WITH_THE_SP, "OrdersDb")
        write_cache(cache_root, identity, cached)

        evidence = analyze_service._materialize_path_evidence(
            path, invocation, scan, cached, graph, sql_cache_identity=identity
        )

    candidate = evidence.literal_sp_candidates[0]
    assert candidate["sql_cache_matched"] is True
    assert candidate["sql_cache_database"] == "OrdersDb"
