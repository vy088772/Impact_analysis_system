"""Ticket 02 behavior checks: /locate_object answers from the indexes alone."""

from __future__ import annotations

import os
import time

import pytest
from fastapi import HTTPException

from service import analyze_service, api, sql_cache_store
from service.schemas import LocateObjectRequest, LocateObjectResponse
from service.sql_cache_store import CacheIdentity
from tests.sql_cache_fixtures import CacheRoot, cache_payload, execution_graph, write_cache


def _payload(database: str, procedures=(), tables=(), graph_nodes=None) -> dict:
    return cache_payload(
        database,
        procedures=procedures,
        tables=tables,
        graph=execution_graph(database, nodes=graph_nodes or []),
    )


# ------------------------------------------------------------- analyze_service seam


def test_a_matching_fresh_index_reports_the_database_as_matched() -> None:
    with CacheRoot():
        identity = CacheIdentity.of("vmsystest07", "PUR")
        sql_cache_store._save(
            identity,
            _payload("PUR", procedures={"dbo.spAddRecordError": {"definition": ""}}),
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
        identity = CacheIdentity.of("vmsystest07", "PUR")
        sql_cache_store._save(
            identity,
            _payload("PUR", procedures={"dbo.spSomethingElse": {"definition": ""}}),
        )

        response = analyze_service.locate_object(
            LocateObjectRequest(object_name="spAddRecordError", kind="sp")
        )

        assert response.matched == []
        assert response.unindexed == []
        assert response.indexes_consulted == 1


def test_a_missing_index_file_puts_the_database_in_unindexed() -> None:
    with CacheRoot() as cache_root:
        identity = CacheIdentity.of("vmsystest07", "PUR")
        write_cache(cache_root, identity, _payload("PUR"))  # no .index.json written

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
        identity = CacheIdentity.of("vmsystest07", "PUR")
        sql_cache_store._save(
            identity,
            _payload("PUR", procedures={"dbo.spAddRecordError": {"definition": ""}}),
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
        matching = CacheIdentity.of("vmsystest07", "PUR")
        pruned = CacheIdentity.of("vmsystest08", "STC")
        missing_index = CacheIdentity.of("vmsystest09", "ETON")
        sql_cache_store._save(
            matching,
            _payload("PUR", procedures={"dbo.spAddRecordError": {"definition": ""}}),
        )
        sql_cache_store._save(
            pruned,
            _payload("STC", procedures={"dbo.spSomethingElse": {"definition": ""}}),
        )
        write_cache(cache_root, missing_index, _payload("ETON"))

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
        identity = CacheIdentity.of("vmsystest07", "PUR")
        sql_cache_store._save(
            identity, _payload("PUR", tables={"sales.Orders": {"columns": [], "primary_keys": []}})
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
        identity = CacheIdentity.of("vmsystest07", "PUR")
        sql_cache_store._save(
            identity,
            _payload(
                "PUR",
                procedures={"spTouchesOrders": {"definition": ""}},
                tables={"Customers": {"columns": [], "primary_keys": []}},
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


def test_an_unknown_kind_is_rejected_rather_than_guessed() -> None:
    with pytest.raises(ValueError):
        analyze_service.locate_object(LocateObjectRequest(object_name="x", kind="view"))


def test_kind_matching_is_case_insensitive() -> None:
    with CacheRoot():
        identity = CacheIdentity.of("vmsystest07", "PUR")
        sql_cache_store._save(
            identity,
            _payload("PUR", procedures={"dbo.spAddRecordError": {"definition": ""}}),
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
        matching = CacheIdentity.of("vmsystest07", "PUR")
        sql_cache_store._save(
            matching,
            _payload("PUR", procedures={"dbo.spAddRecordError": {"definition": ""}}),
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
        identity = CacheIdentity.of("vmsystest07", "PUR")
        sql_cache_store._save(
            identity,
            _payload("PUR", procedures={"dbo.spAddRecordError": {"definition": ""}}),
        )

        def _fail(*args, **kwargs):
            raise AssertionError("locate_object must never open the SQL cache body")

        monkeypatch.setattr(sql_cache_store, "_load", _fail)

        response = analyze_service.locate_object(
            LocateObjectRequest(object_name="spAddRecordError", kind="sp")
        )

        assert response.matched


def _locate(name: str, kind: str = "table") -> LocateObjectResponse:
    return analyze_service.locate_object(LocateObjectRequest(object_name=name, kind=kind))


def _schemas(response: LocateObjectResponse) -> list[tuple[str, str, str, str | None]]:
    return sorted(
        (d.server, d.database, d.schema_name, d.stated_database) for d in response.matched
    )


def test_a_database_with_three_schemas_gives_three_rows_for_a_bare_name() -> None:
    with CacheRoot():
        identity = CacheIdentity.of("vmsystest07", "Response")
        sql_cache_store._save(
            identity,
            _payload(
                "Response",
                tables={
                    "dbo.AVM": {"columns": []},
                    "COMMON.AVM": {"columns": []},
                    "HR.AVM": {"columns": []},
                },
            ),
        )

        response = _locate("AVM")

        assert _schemas(response) == [
            ("vmsystest07.topmost.com.tw", "Response", "common", None),
            ("vmsystest07.topmost.com.tw", "Response", "dbo", None),
            ("vmsystest07.topmost.com.tw", "Response", "hr", None),
        ]


def test_a_name_that_states_a_schema_asks_the_full_bucket() -> None:
    with CacheRoot():
        identity = CacheIdentity.of("vmsystest07", "Response")
        sql_cache_store._save(
            identity,
            _payload("Response", tables={"dbo.AVM": {"columns": []}, "COMMON.AVM": {"columns": []}}),
        )

        response = _locate("COMMON.AVM")

        assert [d.schema_name for d in response.matched] == ["common"]


def test_a_stated_schema_that_no_full_key_holds_still_matches_through_the_bare_bucket() -> None:
    with CacheRoot():
        identity = CacheIdentity.of("vmsystest07", "Response")
        sql_cache_store._save(
            identity, _payload("Response", tables={"COMMON.AVM": {"columns": []}})
        )

        response = _locate("dbo.AVM")

        assert [(d.database, d.schema_name, d.risk_flags) for d in response.matched] == [
            ("Response", "common", ["unproven_schema"])
        ]


def test_a_stated_schema_that_the_full_bucket_holds_carries_no_mark() -> None:
    with CacheRoot():
        identity = CacheIdentity.of("vmsystest07", "Response")
        sql_cache_store._save(
            identity, _payload("Response", tables={"COMMON.AVM": {"columns": []}})
        )

        assert [d.risk_flags for d in _locate("COMMON.AVM").matched] == [[]]
        assert [d.risk_flags for d in _locate("AVM").matched] == [[]]


def test_a_key_with_no_proven_schema_carries_the_mark() -> None:
    with CacheRoot():
        identity = CacheIdentity.of("vmsystest07", "Response")
        graph = execution_graph(
            "Response",
            nodes=[{"id": "table:.Users", "type": "table", "schema": "", "name": "Users"}],
        )
        sql_cache_store._save(identity, cache_payload("Response", graph=graph))

        response = _locate("Users")

        assert [(d.schema_name, d.risk_flags) for d in response.matched] == [("", ["unproven_schema"])]


def test_a_cross_database_reference_reports_stated_database_but_names_the_cache_it_came_from() -> None:
    with CacheRoot():
        identity = CacheIdentity.of("vmsystest07", "Response")
        graph = execution_graph(
            "Response",
            nodes=[{"id": "table:dbo.Users", "type": "table", "schema": "dbo", "name": "Users"}],
            relationships=[
                {"id": "r", "type": "reads", "source": "op", "target": "table:dbo.Users", "database": "PUR"}
            ],
        )
        sql_cache_store._save(identity, cache_payload("Response", graph=graph))

        response = _locate("PUR.dbo.Users")
        local = _locate("Response.dbo.Users")

        assert _schemas(response) == [("vmsystest07.topmost.com.tw", "Response", "dbo", "PUR")]
        # The cache holds a reference to PUR's table only, so the local table is not there.
        assert local.matched == []


def test_a_stated_database_is_never_relaxed_by_the_schema_fallback() -> None:
    with CacheRoot():
        identity = CacheIdentity.of("vmsystest07", "Response")
        sql_cache_store._save(
            identity, _payload("Response", tables={"dbo.Users": {"columns": []}})
        )

        assert _locate("PUR.dbo.Users").matched == []
        assert [d.database for d in _locate("Response.COMMON.Users").matched] == ["Response"]


def test_a_located_row_without_a_stated_database_omits_the_field_on_the_wire() -> None:
    with CacheRoot():
        identity = CacheIdentity.of("vmsystest07", "PUR")
        sql_cache_store._save(identity, _payload("PUR", procedures={"dbo.spX": {"definition": ""}}))

        wire = _locate("spX", "sp").model_dump(exclude_none=True, by_alias=True)

        assert wire["matched"] == [
            {"server": "vmsystest07.topmost.com.tw", "database": "PUR", "schema": "dbo", "risk_flags": []}
        ]


# ------------------------------------------------------------------------- route


def test_locate_object_route_rejects_an_unknown_kind() -> None:
    with pytest.raises(HTTPException) as error:
        api.locate_object(LocateObjectRequest(object_name="x", kind="view"))

    assert error.value.status_code == 400


def test_locate_object_route_returns_the_service_response(monkeypatch) -> None:
    expected = LocateObjectResponse(object_name="x", kind="sp", indexes_consulted=0)
    monkeypatch.setattr(analyze_service, "locate_object", lambda request: expected)

    assert api.locate_object(LocateObjectRequest(object_name="x", kind="sp")) == expected
