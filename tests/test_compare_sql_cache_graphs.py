import importlib.util
from pathlib import Path

from tests.sql_cache_fixtures import cache_payload, execution_graph

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "compare_sql_cache_graphs", PROJECT_ROOT / "tools" / "compare_sql_cache_graphs.py"
)
compare_sql_cache_graphs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(compare_sql_cache_graphs)


def _cache(definition_b: str, nodes: list[dict]) -> dict:
    return cache_payload(
        "PUR",
        procedures={"usp_A": {"definition": "SELECT 1"}, "usp_B": {"definition": definition_b}},
        graph=execution_graph("PUR", nodes=nodes),
    )


def test_equal_definitions_and_equal_graphs_have_no_difference() -> None:
    nodes = [{"id": "stored_procedure:dbo.usp_A"}]

    changed, differing = compare_sql_cache_graphs.compare(_cache("SELECT 2", nodes), _cache("SELECT 2", nodes))

    assert (changed, differing) == ([], [])


def test_a_module_with_a_changed_definition_is_listed_and_left_out_of_the_comparison() -> None:
    kept = {"id": "stored_procedure:dbo.usp_A"}
    old = _cache("SELECT 2", [kept, {"id": "stored_procedure:dbo.usp_B", "name": "usp_B"}])
    new = _cache("SELECT 3", [kept, {"id": "stored_procedure:dbo.usp_B", "name": "usp_B", "extra": 1}])

    changed, differing = compare_sql_cache_graphs.compare(old, new)

    assert changed == [("procedures", "dbo", "usp_B")]
    assert differing == []


def test_a_difference_in_an_unchanged_module_is_reported() -> None:
    old = _cache("SELECT 2", [{"id": "stored_procedure:dbo.usp_A"}])
    new = _cache("SELECT 2", [{"id": "stored_procedure:dbo.usp_A", "extra": 1}])

    changed, differing = compare_sql_cache_graphs.compare(old, new)

    assert changed == []
    assert differing == ["nodes"]
