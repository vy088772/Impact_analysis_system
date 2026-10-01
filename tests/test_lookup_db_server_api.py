"""Ticket 05 of `.scratch/lookup-review-defects/`: the two lookup endpoints take `db_server`.

The seam is the HTTP API. Two SQL caches of one Database name sit on disk under two
hosts, and a request reaches `/find_by_sp` and `/find_by_table` through the app.
Prior art for the scan wiring: tests/test_find_by_sp_likely_matches.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from service import analyze_service
from service.api import app
from service.sql_cache_store import CacheIdentity
from tests.derived_execution_evidence_fixtures import RatedInvocationsRetention
from tests.sql_cache_fixtures import CacheRoot, cache_payload, execution_graph, write_cache
from tests.test_find_by_sp_likely_matches import _graph as _graph_with_shared_sp
from tests.test_find_by_sp_likely_matches import _scan

HOST_WITH_THE_SP = "vmsystest07"
HOST_WITHOUT_THE_SP = "vmsystest08"

client = TestClient(app)


def _graph_without_the_sp() -> dict:
    return execution_graph(
        "OrdersDb",
        nodes=[
            {
                "id": "stored_procedure:dbo.usp_Other",
                "type": "stored_procedure",
                "schema": "dbo",
                "name": "usp_Other",
            }
        ],
    )


def _write_host(cache_root: Path, host: str, graph: dict) -> None:
    write_cache(cache_root, CacheIdentity.of(host, "OrdersDb"), cache_payload("OrdersDb", graph=graph))


def _wire_scan(monkeypatch, tmp_path: Path) -> None:
    scan = _scan(tmp_path)
    monkeypatch.setattr(analyze_service, "resolve_scan_roots", lambda source, refresh=False: [tmp_path])
    monkeypatch.setattr(analyze_service, "_get_scan", lambda root, refresh=False: scan)
    monkeypatch.setattr(analyze_service, "cached_saved_at", lambda root: "scan-v1")
    monkeypatch.setattr(analyze_service, "cached_commit", lambda root: "commit-v1")


def _sp_request(**extra) -> dict:
    return {
        "source": {"project": "orders", "repo": "orders"},
        "sp_name": "dbo.usp_Shared",
        "database": "OrdersDb",
        "cache_only": False,
        **extra,
    }


def _table_request(**extra) -> dict:
    return {
        "source": {"project": "orders", "repo": "orders"},
        "table_name": "dbo.SOrder",
        "database": "OrdersDb",
        "cache_only": False,
        **extra,
    }


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
def no_host(monkeypatch, tmp_path):
    with RatedInvocationsRetention(), CacheRoot() as cache_root:
        _wire_scan(monkeypatch, tmp_path)
        yield cache_root


@pytest.mark.parametrize(
    ("endpoint", "payload"),
    [("/find_by_sp", _sp_request()), ("/find_by_table", _table_request())],
)
def test_a_database_on_two_hosts_with_no_host_named_gets_the_ambiguous_code(
    two_hosts, endpoint: str, payload: dict
) -> None:
    response = client.post(endpoint, json=payload)

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "ambiguous_database"
    assert detail["database"] == "OrdersDb"
    assert [server.split(".")[0] for server in detail["servers"]] == [HOST_WITH_THE_SP, HOST_WITHOUT_THE_SP]


def test_find_by_sp_answers_from_the_host_that_the_request_names(two_hosts) -> None:
    on_host_with_sp = client.post("/find_by_sp", json=_sp_request(db_server=HOST_WITH_THE_SP))
    on_other_host = client.post("/find_by_sp", json=_sp_request(db_server=HOST_WITHOUT_THE_SP))

    assert on_host_with_sp.status_code == 200
    assert [match["program"] for match in on_host_with_sp.json()["matches"]] == ["provenpage"]
    # The other host's cache does not hold the procedure, so the same call is not proven there.
    assert on_other_host.status_code == 200
    assert on_other_host.json()["matches"] == []


def test_find_by_table_answers_when_the_request_names_a_host(two_hosts) -> None:
    response = client.post("/find_by_table", json=_table_request(db_server=HOST_WITH_THE_SP))

    assert response.status_code == 200


def test_the_host_name_is_normalized_like_the_other_endpoints(two_hosts) -> None:
    response = client.post(
        "/find_by_sp", json=_sp_request(db_server=f"{HOST_WITH_THE_SP.upper()}\\SQLEXPRESS")
    )

    assert response.status_code == 200
    assert [match["program"] for match in response.json()["matches"]] == ["provenpage"]


@pytest.mark.parametrize(
    ("endpoint", "payload"),
    [("/find_by_sp", _sp_request()), ("/find_by_table", _table_request())],
)
def test_a_database_that_is_not_scanned_keeps_the_not_scanned_code(
    no_host, endpoint: str, payload: dict
) -> None:
    response = client.post(endpoint, json=payload)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "sql_execution_graph_required"


def test_a_named_host_with_no_cache_keeps_the_not_scanned_code(two_hosts) -> None:
    response = client.post("/find_by_sp", json=_sp_request(db_server="vmsystest99"))

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "sql_execution_graph_required"


@pytest.mark.parametrize(
    ("endpoint", "payload"),
    [("/find_by_sp", _sp_request()), ("/find_by_table", _table_request())],
)
def test_a_call_without_a_host_for_a_database_on_one_host_keeps_today_behavior(
    one_host, endpoint: str, payload: dict
) -> None:
    response = client.post(endpoint, json=payload)

    assert response.status_code == 200
    if endpoint == "/find_by_sp":
        assert [match["program"] for match in response.json()["matches"]] == ["provenpage"]
