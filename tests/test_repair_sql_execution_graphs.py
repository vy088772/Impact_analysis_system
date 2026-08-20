"""Ticket 03 behavior checks: repairing SQL execution graphs already on disk."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from code_analyzer.static_analyzer_host import StaticAnalyzerHost
from service import sql_cache_store
from service.sql_execution_graph import GRAPH_VERSION
from tests.sql_cache_fixtures import CacheRoot, write_cache
from tools.repair_sql_execution_graphs import repair_all_caches, repair_cache_file


TEST_SERVER = "vmsystest07"


def _stale_payload(database: str = "TestDb") -> dict:
    definition = (
        "CREATE PROCEDURE dbo.usp_RepairMe AS\n"
        "BEGIN\n"
        "    DELETE FROM dbo.RepairTarget WHERE Id = 1;\n"
        "    DECLARE @sql NVARCHAR(200) = 'SELECT 1';\n"
        "    EXEC(@sql);\n"
        "END;\n"
    )
    return {
        "database": database,
        "schema": "dbo",
        "procedures": [
            {"name": "usp_RepairMe", "definition": definition, "parameters": []}
        ],
        "views": [],
        "functions": [],
        "tables": [{"name": "RepairTarget", "columns": []}],
        # A graph built under the old (pre-repair) version, with an offset
        # that would be wrong under the old corrupting write path — the
        # repair rebuilds it from the (already-correct) definition text
        # above rather than trusting anything already stored here.
        "sql_execution_graph": {
            "graph_version": GRAPH_VERSION - 1,
            "database": database,
            "nodes": [],
            "relationships": [],
            "parse_errors": [],
        },
    }


def _write_stale_fixture(cache_root: Path, database: str = "TestDb") -> Path:
    key = sql_cache_store.CacheIdentity.of(TEST_SERVER, database, "dbo").key
    write_cache(cache_root, key, _stale_payload(database))
    return cache_root / f"{key}.json"


def test_repair_rebuilds_a_stale_cache_to_the_current_graph_version() -> None:
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with CacheRoot() as cache_root:
        data_path = _write_stale_fixture(cache_root)

        results = repair_all_caches(cache_root, host=host, project_root=PROJECT_ROOT)

        assert [entry["action"] for entry in results] == ["repaired"]
        assert results[0]["old_graph_version"] == GRAPH_VERSION - 1
        assert results[0]["new_graph_version"] == GRAPH_VERSION

        repaired = json.loads(data_path.read_text(encoding="utf-8"))
        graph = repaired["sql_execution_graph"]
        assert graph["graph_version"] == GRAPH_VERSION

        definition_length = len(repaired["procedures"][0]["definition"])
        offset_bearing_nodes = [
            node
            for node in graph["nodes"]
            if node["type"] in ("dml_operation", "unresolved_dynamic_sql")
        ]
        node_types = {node["type"] for node in offset_bearing_nodes}
        assert node_types == {"dml_operation", "unresolved_dynamic_sql"}, (
            "expected both the DELETE and the EXEC(@sql) to survive the repair"
        )
        for node in offset_bearing_nodes:
            source = node["source"]
            assert source["start_offset"] + source["length"] <= definition_length
            # Ticket 02's staleness field must come along for the ride, on
            # every offset-bearing node type — not just dml_operation.
            assert source["module_definition_length"] == definition_length


def test_repaired_cache_is_accepted_by_the_normal_load_path() -> None:
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with CacheRoot() as cache_root:
        _write_stale_fixture(cache_root)
        assert sql_cache_store.load_cached("TestDb", "dbo", server=TEST_SERVER) is None

        repair_all_caches(cache_root, host=host, project_root=PROJECT_ROOT)

        assert sql_cache_store.load_cached("TestDb", "dbo", server=TEST_SERVER) is not None


def test_repair_only_touches_the_graph_field() -> None:
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with CacheRoot() as cache_root:
        data_path = _write_stale_fixture(cache_root)
        before = json.loads(data_path.read_text(encoding="utf-8"))

        repair_all_caches(cache_root, host=host, project_root=PROJECT_ROOT)

        after_bytes = data_path.read_bytes()
        after = json.loads(after_bytes.decode("utf-8"))
        assert after["database"] == before["database"]
        assert after["schema"] == before["schema"]
        assert after["procedures"] == before["procedures"]
        assert after["views"] == before["views"]
        assert after["functions"] == before["functions"]
        assert after["tables"] == before["tables"]
        assert after["sql_execution_graph"] != before["sql_execution_graph"]

        # Byte-level, not just value-level: swapping only sql_execution_graph
        # into `before` and re-serializing the same way sql_cache_store._save()
        # always writes must reproduce exactly what is now on disk — proving
        # the repair did not perturb any other field's formatting either.
        expected = dict(before, sql_execution_graph=after["sql_execution_graph"])
        expected_bytes = json.dumps(
            expected, ensure_ascii=False, indent=2
        ).encode("utf-8")
        assert after_bytes == expected_bytes


def test_repair_dry_run_changes_nothing_on_disk() -> None:
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with CacheRoot() as cache_root:
        data_path = _write_stale_fixture(cache_root)
        raw_before = data_path.read_bytes()

        results = repair_all_caches(
            cache_root, host=host, project_root=PROJECT_ROOT, dry_run=True
        )

        assert [entry["action"] for entry in results] == ["would_repair"]
        assert data_path.read_bytes() == raw_before


def test_repair_is_idempotent_once_a_cache_is_current() -> None:
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with CacheRoot() as cache_root:
        _write_stale_fixture(cache_root)

        first = repair_all_caches(cache_root, host=host, project_root=PROJECT_ROOT)
        second = repair_all_caches(cache_root, host=host, project_root=PROJECT_ROOT)

        assert [entry["action"] for entry in first] == ["repaired"]
        assert [entry["action"] for entry in second] == ["already_current"]


def test_repair_cache_file_skips_an_already_current_cache() -> None:
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with CacheRoot() as cache_root:
        payload = _stale_payload()
        payload["sql_execution_graph"]["graph_version"] = GRAPH_VERSION
        key = sql_cache_store.CacheIdentity.of(TEST_SERVER, "TestDb", "dbo").key
        write_cache(cache_root, key, payload)
        data_path = cache_root / f"{key}.json"
        raw_before = data_path.read_bytes()

        entry = repair_cache_file(data_path, host, PROJECT_ROOT)

        assert entry["action"] == "already_current"
        assert data_path.read_bytes() == raw_before
