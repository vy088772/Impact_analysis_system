"""Ticket 02 behavior checks: /locate_object answers from the indexes alone."""

from __future__ import annotations

import os
import time

import pytest
from fastapi import HTTPException

from service import analyze_service, api, sql_cache_store
from service.schemas import LocateObjectRequest, LocateObjectResponse
from service.sql_cache_store import CacheIdentity
from service.sql_execution_graph import GRAPH_VERSION
from tests.sql_cache_fixtures import CacheRoot, write_cache


def _payload(
    database: str, procedures=None, tables=None, graph_nodes=None, schema: str = "dbo"
) -> dict:
    return {
        "database": database,
        "schema": schema,
        "procedures": procedures or [],
        "views": [],
        "functions": [],
        "tables": tables or [],
        "sql_execution_graph": {
            "graph_version": GRAPH_VERSION,
            "database": database,
            "nodes": graph_nodes or [],
            "relationships": [],
            "parse_errors": [],
        },
    }


# ------------------------------------------------------------- analyze_service seam


def test_a_matching_fresh_index_reports_the_database_as_matched() -> None:
    with CacheRoot():
        identity = CacheIdentity.of("vmsystest07", "PUR", "dbo")
        sql_cache_store._save(
            identity,
            _payload("PUR", procedures=[{"name": "dbo.spAddRecordError", "definition": ""}]),
        )

        response = analyze_service.locate_object(
            LocateObjectRequest(object_name="spAddRecordError", kind="sp")
        )

        assert [(d.server, d.database) for d in response.matched] == [
            ("vmsystest07.topmost.com.tw", "PUR")
        ]
        assert response.unindexed == []
        assert response.indexes_consulted == 1


def test_a_fresh_index_that_does_not_hold_the_name_prunes_the_database_from_both_lists() -> None:
    with CacheRoot():
        identity = CacheIdentity.of("vmsystest07", "PUR", "dbo")
        sql_cache_store._save(
            identity,
            _payload("PUR", procedures=[{"name": "dbo.spSomethingElse", "definition": ""}]),
        )

        response = analyze_service.locate_object(
            LocateObjectRequest(object_name="spAddRecordError", kind="sp")
        )

        assert response.matched == []
        assert response.unindexed == []
        assert response.indexes_consulted == 1


def test_a_missing_index_file_puts_the_database_in_unindexed() -> None:
    with CacheRoot() as cache_root:
        identity = CacheIdentity.of("vmsystest07", "PUR", "dbo")
        write_cache(cache_root, identity.key, _payload("PUR"))  # no .index.json written

        response = analyze_service.locate_object(
            LocateObjectRequest(object_name="spAddRecordError", kind="sp")
        )

        assert response.matched == []
        assert [(d.server, d.database) for d in response.unindexed] == [
            ("vmsystest07.topmost.com.tw", "PUR")
        ]
        assert response.indexes_consulted == 1


def test_a_stale_index_puts_the_database_in_unindexed() -> None:
    with CacheRoot() as cache_root:
        identity = CacheIdentity.of("vmsystest07", "PUR", "dbo")
        sql_cache_store._save(
            identity,
            _payload("PUR", procedures=[{"name": "dbo.spAddRecordError", "definition": ""}]),
        )
        old = time.time() - 1000
        os.utime(cache_root / identity.index_filename, (old, old))

        response = analyze_service.locate_object(
            LocateObjectRequest(object_name="spAddRecordError", kind="sp")
        )

        assert response.matched == []
        assert [(d.server, d.database) for d in response.unindexed] == [
            ("vmsystest07.topmost.com.tw", "PUR")
        ]


def test_the_reply_answers_for_every_cache_on_disk_in_one_call() -> None:
    with CacheRoot() as cache_root:
        matching = CacheIdentity.of("vmsystest07", "PUR", "dbo")
        pruned = CacheIdentity.of("vmsystest08", "STC", "dbo")
        missing_index = CacheIdentity.of("vmsystest09", "ETON", "dbo")
        sql_cache_store._save(
            matching,
            _payload("PUR", procedures=[{"name": "dbo.spAddRecordError", "definition": ""}]),
        )
        sql_cache_store._save(
            pruned,
            _payload("STC", procedures=[{"name": "dbo.spSomethingElse", "definition": ""}]),
        )
        write_cache(cache_root, missing_index.key, _payload("ETON"))

        response = analyze_service.locate_object(
            LocateObjectRequest(object_name="spAddRecordError", kind="sp")
        )

        assert response.indexes_consulted == 3
        assert [(d.server, d.database) for d in response.matched] == [
            ("vmsystest07.topmost.com.tw", "PUR")
        ]
        assert [(d.server, d.database) for d in response.unindexed] == [
            ("vmsystest09.topmost.com.tw", "ETON")
        ]


def test_table_kind_normalizes_and_matches_the_table_bucket() -> None:
    with CacheRoot():
        identity = CacheIdentity.of("vmsystest07", "PUR", "dbo")
        sql_cache_store._save(
            identity, _payload("PUR", tables=[{"name": "sales.Orders", "columns": [], "primary_keys": []}])
        )

        response = analyze_service.locate_object(
            LocateObjectRequest(object_name="[dbo].[Orders]", kind="table")
        )

        assert [(d.server, d.database) for d in response.matched] == [
            ("vmsystest07.topmost.com.tw", "PUR")
        ]


def test_table_kind_finds_a_table_reached_only_inside_a_stored_procedure_body() -> None:
    """The union bucket built by ticket 01 must survive through this endpoint too."""
    with CacheRoot():
        identity = CacheIdentity.of("vmsystest07", "PUR", "dbo")
        sql_cache_store._save(
            identity,
            _payload(
                "PUR",
                procedures=[{"name": "spTouchesOrders", "definition": ""}],
                tables=[{"name": "Customers", "columns": [], "primary_keys": []}],
                graph_nodes=[
                    {"id": "table:dbo.Orders", "type": "table", "schema": "dbo", "name": "Orders"},
                ],
            ),
        )

        response = analyze_service.locate_object(
            LocateObjectRequest(object_name="Orders", kind="table")
        )

        assert [(d.server, d.database) for d in response.matched] == [
            ("vmsystest07.topmost.com.tw", "PUR")
        ]


def test_two_schemas_of_one_database_never_land_in_both_lists() -> None:
    with CacheRoot() as cache_root:
        matching = CacheIdentity.of("vmsystest07", "PUR", "dbo")
        sql_cache_store._save(
            matching,
            _payload("PUR", procedures=[{"name": "dbo.spAddRecordError", "definition": ""}]),
        )
        unindexed = CacheIdentity.of("vmsystest07", "PUR", "sales")
        write_cache(cache_root, unindexed.key, _payload("PUR", schema="sales"))

        response = analyze_service.locate_object(
            LocateObjectRequest(object_name="spAddRecordError", kind="sp")
        )

        assert [(d.server, d.database) for d in response.matched] == [
            ("vmsystest07.topmost.com.tw", "PUR")
        ]
        assert response.unindexed == []
        assert response.indexes_consulted == 2


def test_two_schemas_that_both_hold_the_name_report_the_database_once() -> None:
    with CacheRoot():
        for schema in ("dbo", "sales"):
            identity = CacheIdentity.of("vmsystest07", "PUR", schema)
            sql_cache_store._save(
                identity,
                _payload(
                    "PUR",
                    procedures=[{"name": f"{schema}.spAddRecordError", "definition": ""}],
                    schema=schema,
                ),
            )

        response = analyze_service.locate_object(
            LocateObjectRequest(object_name="spAddRecordError", kind="sp")
        )

        assert [(d.server, d.database) for d in response.matched] == [
            ("vmsystest07.topmost.com.tw", "PUR")
        ]
        assert response.unindexed == []
        assert response.indexes_consulted == 2


def test_two_schemas_that_are_both_unindexed_report_the_database_once() -> None:
    with CacheRoot() as cache_root:
        for schema in ("dbo", "sales"):
            identity = CacheIdentity.of("vmsystest07", "PUR", schema)
            write_cache(cache_root, identity.key, _payload("PUR", schema=schema))

        response = analyze_service.locate_object(
            LocateObjectRequest(object_name="spAddRecordError", kind="sp")
        )

        assert response.matched == []
        assert [(d.server, d.database) for d in response.unindexed] == [
            ("vmsystest07.topmost.com.tw", "PUR")
        ]
        assert response.indexes_consulted == 2


def test_an_unknown_kind_is_rejected_rather_than_guessed() -> None:
    with pytest.raises(ValueError):
        analyze_service.locate_object(LocateObjectRequest(object_name="x", kind="view"))


def test_kind_matching_is_case_insensitive() -> None:
    with CacheRoot():
        identity = CacheIdentity.of("vmsystest07", "PUR", "dbo")
        sql_cache_store._save(
            identity,
            _payload("PUR", procedures=[{"name": "dbo.spAddRecordError", "definition": ""}]),
        )

        response = analyze_service.locate_object(
            LocateObjectRequest(object_name="spAddRecordError", kind="SP")
        )

        assert response.kind == "sp"
        assert [(d.server, d.database) for d in response.matched] == [
            ("vmsystest07.topmost.com.tw", "PUR")
        ]


def test_a_file_with_an_incomplete_cache_identity_is_tolerated_not_a_crash() -> None:
    """list_caches() lists even a stray file that doesn't fit the naming shape;
    locate_object must not let that turn the whole request into an error."""
    with CacheRoot() as cache_root:
        matching = CacheIdentity.of("vmsystest07", "PUR", "dbo")
        sql_cache_store._save(
            matching,
            _payload("PUR", procedures=[{"name": "dbo.spAddRecordError", "definition": ""}]),
        )
        (cache_root / "stray.json").write_text("{}", encoding="utf-8")  # no server/database in the name

        response = analyze_service.locate_object(
            LocateObjectRequest(object_name="spAddRecordError", kind="sp")
        )

        assert response.indexes_consulted == 1
        assert [(d.server, d.database) for d in response.matched] == [
            ("vmsystest07.topmost.com.tw", "PUR")
        ]


def test_the_endpoint_never_opens_a_sql_cache(monkeypatch) -> None:
    """A request that would require opening a cache is a bug here, not a fallback."""
    with CacheRoot():
        identity = CacheIdentity.of("vmsystest07", "PUR", "dbo")
        sql_cache_store._save(
            identity,
            _payload("PUR", procedures=[{"name": "dbo.spAddRecordError", "definition": ""}]),
        )

        def _fail(*args, **kwargs):
            raise AssertionError("locate_object must never open the SQL cache body")

        monkeypatch.setattr(sql_cache_store, "_load", _fail)

        response = analyze_service.locate_object(
            LocateObjectRequest(object_name="spAddRecordError", kind="sp")
        )

        assert response.matched


# ------------------------------------------------------------------------- route


def test_locate_object_route_rejects_an_unknown_kind() -> None:
    with pytest.raises(HTTPException) as error:
        api.locate_object(LocateObjectRequest(object_name="x", kind="view"))

    assert error.value.status_code == 400


def test_locate_object_route_returns_the_service_response(monkeypatch) -> None:
    expected = LocateObjectResponse(object_name="x", kind="sp", indexes_consulted=0)
    monkeypatch.setattr(analyze_service, "locate_object", lambda request: expected)

    assert api.locate_object(LocateObjectRequest(object_name="x", kind="sp")) == expected
