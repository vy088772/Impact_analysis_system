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

from service import sql_cache_store
from service.api import app
from tests.derived_execution_evidence_fixtures import RatedInvocationsRetention
from tests.sql_cache_fixtures import CacheRoot
from tests.test_find_by_sp_likely_matches import _graph as _graph_with_shared_sp
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
        _wire_scan(monkeypatch, tmp_path)
        yield cache_root


@pytest.fixture
def one_host(monkeypatch, tmp_path):
    with RatedInvocationsRetention(), CacheRoot() as cache_root:
        _write_host(cache_root, HOST_WITH_THE_SP, _graph_with_shared_sp())
        _wire_scan(monkeypatch, tmp_path)
        yield cache_root


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


def test_path_evidence_with_no_host_for_a_database_on_two_hosts_answers_not_scanned(two_hosts) -> None:
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
    two_hosts, direction_fields: dict
) -> None:
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
    monkeypatch.setattr("service.analyze_service.resolve_source", lambda req: [tmp_path])

    response = client.post("/analyze", json=_analyze_request())

    assert response.status_code == 200
    assert len(listings) == 1


def test_analyze_with_definitions_treats_a_blank_host_as_no_host(one_host, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("service.analyze_service.resolve_source", lambda req: [tmp_path])

    response = client.post("/analyze", json=_analyze_request(db_server="   "))

    assert response.status_code == 200
