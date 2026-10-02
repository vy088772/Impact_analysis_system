"""Seam: the Impact responses carry the values the client used to copy.

`/find_by_table` sends `is_write` on each match. `/analyze` sends `relevance_key`
on each compact path. Both come from the same decision as the service filter and
the service sort, so the client keeps no copy of either rule.
"""

from __future__ import annotations

import pytest

from service.execution_path_builder import build_compact_execution_path_summary
from tests.test_table_match import _ask, _graph

WRITE_TYPES = ["WRITE", "WRITE_INDIRECT", "INSERT", "UPDATE", "DELETE", "MERGE", "SELECT_INTO"]


def _graph_with_operation(operation: str) -> dict:
    graph = _graph({"usp_Save": [("writes", "dbo", "Orders", None)]})
    for node in graph["nodes"]:
        if node.get("type") == "dml_operation":
            node["operation_type"] = operation
    return graph


@pytest.mark.parametrize("operation", WRITE_TYPES)
@pytest.mark.parametrize("change_case", [str.upper, str.lower, str.title])
def test_each_write_access_type_is_a_write_in_any_letter_case(monkeypatch, tmp_path, operation, change_case) -> None:
    matches = _ask(monkeypatch, tmp_path, _graph_with_operation(change_case(operation)), ["usp_Save"], "dbo.Orders")

    assert matches and all(match.is_write is True for match in matches)


def test_a_read_is_not_a_write(monkeypatch, tmp_path) -> None:
    graph = _graph({"usp_Read": [("reads", "dbo", "Orders", None)]})

    matches = _ask(monkeypatch, tmp_path, graph, ["usp_Read"], "dbo.Orders")

    assert matches and all(match.is_write is False for match in matches)


def test_write_only_keeps_exactly_the_matches_that_carry_is_write(monkeypatch, tmp_path) -> None:
    graph = _graph(
        {
            "usp_Save": [("writes", "dbo", "Orders", None)],
            "usp_Read": [("reads", "dbo", "Orders", None)],
        }
    )

    every = _ask(monkeypatch, tmp_path, graph, ["usp_Save", "usp_Read"], "dbo.Orders")
    only = _ask(monkeypatch, tmp_path, graph, ["usp_Save", "usp_Read"], "dbo.Orders", write_only=True)

    assert {False, True} <= {match.is_write for match in every}
    assert only == [match for match in every if match.is_write]


def _path(path_id: str, entry: str, *, writes=(), reads=(), sp="dbo.usp_X") -> dict:
    return {
        "path_id": path_id,
        "entry_method": entry,
        "method_chain": [entry],
        "sp_chain": [sp],
        "writes": list(writes),
        "reads": list(reads),
    }


def test_each_compact_path_carries_a_relevance_key_of_four_parts() -> None:
    summary = build_compact_execution_path_summary(
        [_path("P-a", "Order.Cancel", writes=["dbo.Orders"])], question="cancel order"
    )

    # Write Impact first, then keyword matches, then entry-method matches, then the path id.
    assert summary[0]["relevance_key"] == [0, -2, -2, "P-a"]


def test_the_key_ranks_write_impact_then_keywords_then_entry_method_then_path_id() -> None:
    paths = [
        _path("P-d", "Other.Run"),
        _path("P-c", "Other.Run", writes=["dbo.Orders"]),
        _path("P-b", "Order.Run", reads=["dbo.Orders"]),
        _path("P-a", "Order.Run", reads=["dbo.Orders"]),
    ]

    summary = build_compact_execution_path_summary(paths, question="order")
    by_key = sorted(summary, key=lambda item: item["relevance_key"])

    assert [item["path_id"] for item in by_key] == ["P-c", "P-a", "P-b", "P-d"]


def test_the_order_of_one_cache_is_the_order_of_its_keys() -> None:
    paths = [
        _path("P-3", "Plain.Run"),
        _path("P-2", "Order.Run", reads=["dbo.Orders"]),
        _path("P-1", "Order.Save", writes=["dbo.Orders"]),
    ]

    summary = build_compact_execution_path_summary(paths, question="order save")

    assert [item["path_id"] for item in summary] == ["P-1", "P-2", "P-3"]
    assert [item["relevance_key"] for item in summary] == sorted(item["relevance_key"] for item in summary)


def test_two_caches_that_give_one_question_produce_keys_that_compare() -> None:
    first = build_compact_execution_path_summary([_path("P-1", "Order.Run")], question="order")[0]
    second = build_compact_execution_path_summary(
        [_path("P-1", "Order.Run", writes=["dbo.Orders"])], question="order"
    )[0]

    assert first["relevance_key"] == [1, -1, -1, "P-1"]
    assert second["relevance_key"] < first["relevance_key"]


def test_an_empty_question_still_gives_a_key() -> None:
    summary = build_compact_execution_path_summary([_path("P-1", "Order.Run", writes=["dbo.Orders"])], question="")

    assert summary[0]["relevance_key"] == [0, 0, 0, "P-1"]


def test_the_analysis_question_reaches_the_key_through_the_payload() -> None:
    from service.execution_path_builder import build_compact_execution_path_payload

    paths = [_path("P-1", "Order.Run", reads=["dbo.Orders"])]

    with_question = build_compact_execution_path_payload(paths, question="order")["paths"][0]
    without_question = build_compact_execution_path_payload(paths)["paths"][0]

    assert with_question["relevance_key"] == [1, -1, -1, "P-1"]
    assert without_question["relevance_key"] == [1, 0, 0, "P-1"]
