"""The cached object lookup: a graph node finds the cache object that holds its definition.

Both sides state a schema, or nothing matches. An empty schema is not `dbo`
(`.scratch/canonical-object-identity/` ticket 08).
"""

from __future__ import annotations

from service.analyze_service import _cached_sql_object
from tests.sql_cache_fixtures import cache_payload


def _node(schema: str | None, name: str) -> dict:
    node = {"type": "stored_procedure", "name": name}
    if schema is not None:
        node["schema"] = schema
    return node


def test_a_node_finds_the_object_that_states_its_schema_and_name() -> None:
    cached = cache_payload(
        "OrdersDb",
        procedures={
            "COMMON.usp_Load": {"definition": "common"},
            "dbo.usp_Load": {"definition": "dbo"},
        },
    )

    found = _cached_sql_object(cached, _node("COMMON", "USP_LOAD"))

    assert found is not None and found["definition"] == "common"


def test_a_node_with_no_schema_matches_nothing() -> None:
    cached = cache_payload("OrdersDb", procedures={"dbo.usp_Load": {"definition": "dbo"}})

    assert _cached_sql_object(cached, _node(None, "usp_Load")) is None
    assert _cached_sql_object(cached, _node("", "usp_Load")) is None


def test_an_object_with_no_schema_matches_nothing() -> None:
    cached = cache_payload("OrdersDb", procedures={"usp_Load": {"definition": "unknown schema"}})
    del cached["procedures"][0]["schema"]

    assert _cached_sql_object(cached, _node("dbo", "usp_Load")) is None


def test_an_object_that_writes_its_schema_in_its_name_states_that_schema() -> None:
    cached = cache_payload("OrdersDb", procedures={"sales.usp_Load": {"definition": "sales"}})
    del cached["procedures"][0]["schema"]

    found = _cached_sql_object(cached, _node("sales", "usp_Load"))

    assert found is not None and found["definition"] == "sales"
