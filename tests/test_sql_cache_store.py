"""Ticket 02 behavior checks: SQL cache identity is (server, database, schema)."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from service import analyze_service, sql_cache_store
from service.sql_cache_store import CacheIdentity
from tests.sql_cache_fixtures import (
    CacheRoot,
    analyzer_operation,
    cache_payload,
    execution_graph,
    write_cache,
)

AGREEMENT = json.loads(
    (Path(__file__).resolve().parent / "cross_repository_agreement.json").read_text(encoding="utf-8")
)


def _payload(database: str, graph_nodes: tuple = (), **objects: object) -> dict:
    objects.setdefault(
        "procedures", {"spAddRecordError": {"definition": "CREATE PROCEDURE x AS SELECT 1"}}
    )
    return cache_payload(
        database,
        graph=execution_graph(database, nodes=list(graph_nodes)),
        **objects,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------- cross-repository agreement


@pytest.mark.parametrize(
    "case",
    AGREEMENT["sql_cache_identity"],
    ids=[case["filename"] for case in AGREEMENT["sql_cache_identity"]],
)
def test_each_agreed_identity_names_its_cache_file(case: dict) -> None:
    identity = CacheIdentity.of(case["server"], case["database"], case["schema"])

    assert identity.filename == case["filename"]


def _sample_cache_files() -> dict:
    """Write the one fixed sample cache and read back its data file and its meta file.

    The payload builder, the graph helper, and the meta writer produce both
    files. When the cache shape changes, copy this function's output into the
    `sample_cache` entry of tests/cross_repository_agreement.json.
    """
    identity = CacheIdentity.of("sqlsrv01", "SampleDb", "dbo")
    procedure_id = "stored_procedure:dbo.usp_Load"
    operation_id = f"dml_operation:{procedure_id}:1"
    definition = (
        "CREATE PROCEDURE dbo.usp_Load AS UPDATE o SET Status = 1 "
        "FROM dbo.Orders o JOIN LNK.PUR.dbo.Customers c ON c.Id = o.CustomerId"
    )
    source = {
        "source_path": procedure_id,
        "module_id": procedure_id,
        "module_definition_length": len(definition),
    }
    graph = execution_graph(
        "SampleDb",
        nodes=[
            {"id": procedure_id, "type": "stored_procedure", "schema": "dbo", "name": "usp_Load"},
            {"id": "view:dbo.vw_Orders", "type": "view", "schema": "dbo", "name": "vw_Orders"},
            {"id": "function:dbo.fn_Rate", "type": "function", "schema": "dbo", "name": "fn_Rate"},
            {"id": "table:dbo.Orders", "type": "table", "schema": "dbo", "name": "Orders"},
            {"id": "table:dbo.Customers", "type": "table", "schema": "dbo", "name": "Customers"},
            analyzer_operation(
                "UPDATE",
                reads=["LNK.PUR.dbo.Customers"],
                writes=["dbo.Orders"],
                read_columns=["Id", "CustomerId"],
                written_columns=["Status"],
                id=operation_id,
                type="dml_operation",
                module={"type": "stored_procedure", "schema": "dbo", "name": "usp_Load"},
                module_id=procedure_id,
                source=source,
            ),
        ],
        relationships=[
            {
                "id": f"contains:{procedure_id}:{operation_id}",
                "type": "contains",
                "source": procedure_id,
                "target": operation_id,
                "confidence": "proven",
                "branch_path": [],
                "source_location": source,
            },
            {
                "id": f"writes:{operation_id}:table:dbo.Orders",
                "type": "writes",
                "source": operation_id,
                "target": "table:dbo.Orders",
                "confidence": "proven",
                "branch_path": [],
                "source_location": source,
                "columns": ["Status"],
            },
            {
                # A relationship records the database and server its reference
                # stated; the node it targets records neither.
                "id": f"reads:{operation_id}:table:dbo.Customers@LNK.PUR",
                "type": "reads",
                "source": operation_id,
                "target": "table:dbo.Customers",
                "confidence": "proven",
                "branch_path": [],
                "source_location": source,
                "columns": ["Id", "CustomerId"],
                "database": "PUR",
                "server": "LNK",
            },
        ],
    )
    payload = cache_payload(
        "SampleDb",
        procedures={
            "dbo.usp_Load": {
                "definition": definition,
                "parameters": [],
            }
        },
        views={"dbo.vw_Orders": {"definition": "CREATE VIEW dbo.vw_Orders AS SELECT Id FROM dbo.Orders"}},
        functions={
            "dbo.fn_Rate": {
                "definition": "CREATE FUNCTION dbo.fn_Rate() RETURNS int AS BEGIN RETURN 1 END",
                "parameters": [],
                "return_type": "int",
            }
        },
        tables={
            "dbo.Orders": {
                "columns": [{"name": "Id", "type": "int", "nullable": False, "default": None}],
                "primary_keys": ["Id"],
            }
        },
        graph=graph,
    )
    with CacheRoot() as root:
        write_cache(root, identity, payload)
        return {
            "data_file": json.loads((root / identity.filename).read_text(encoding="utf-8")),
            "meta_file": json.loads((root / identity.meta_filename).read_text(encoding="utf-8")),
        }


def test_the_committed_sample_cache_is_what_the_builders_produce() -> None:
    assert _sample_cache_files() == AGREEMENT["sample_cache"]


# ---------------------------------------------------------------- normalization


def test_bare_hostname_gets_the_internal_domain_suffix() -> None:
    assert sql_cache_store.normalize_server("vmsystest07") == "vmsystest07.topmost.com.tw"


def test_already_dotted_hostname_is_unchanged() -> None:
    assert (
        sql_cache_store.normalize_server("vmsystest07.topmost.com.tw")
        == "vmsystest07.topmost.com.tw"
    )


def test_named_instance_suffix_is_discarded() -> None:
    assert (
        sql_cache_store.normalize_server("vmsystest08.topmost.com.tw\\vmsystest08_pdcs")
        == "vmsystest08.topmost.com.tw"
    )


def test_named_instance_suffix_is_discarded_before_the_domain_suffix_is_added() -> None:
    assert sql_cache_store.normalize_server("vmsystest08\\vmsystest08_pdcs") == "vmsystest08.topmost.com.tw"


def test_hostname_case_does_not_change_the_normalized_server() -> None:
    assert sql_cache_store.normalize_server("VMSYSTEST07") == "vmsystest07.topmost.com.tw"


def test_empty_server_normalizes_to_empty() -> None:
    assert sql_cache_store.normalize_server("") == ""
    assert sql_cache_store.normalize_server("   ") == ""


def test_tcp_protocol_prefix_is_discarded() -> None:
    assert (
        sql_cache_store.normalize_server("tcp:vmsystest07.topmost.com.tw")
        == "vmsystest07.topmost.com.tw"
    )


def test_port_suffix_is_discarded() -> None:
    assert (
        sql_cache_store.normalize_server("vmsystest07.topmost.com.tw,1433")
        == "vmsystest07.topmost.com.tw"
    )


def test_protocol_prefix_and_port_suffix_together_normalize_like_neither() -> None:
    assert (
        sql_cache_store.normalize_server("tcp:vmsystest07.topmost.com.tw,1433")
        == sql_cache_store.normalize_server("vmsystest07.topmost.com.tw")
    )


def test_port_suffix_is_discarded_before_the_domain_suffix_is_added() -> None:
    assert sql_cache_store.normalize_server("vmsystest07,1433") == "vmsystest07.topmost.com.tw"


def test_port_suffix_with_named_instance_suffix_is_discarded() -> None:
    assert (
        sql_cache_store.normalize_server("vmsystest08.topmost.com.tw\\vmsystest08_pdcs,1433")
        == "vmsystest08.topmost.com.tw"
    )


# ------------------------------------------------------------------ cache key


def test_a_cache_identity_names_its_own_files() -> None:
    identity = CacheIdentity.of("vmsystest07", "STC", "dbo")

    assert identity.filename == "vmsystest07.topmost.com.tw__STC__dbo.json"
    assert identity.meta_filename == "vmsystest07.topmost.com.tw__STC__dbo.meta.json"


def test_one_shared_database_has_one_key_regardless_of_which_system_asks() -> None:
    """SysErrorRecord is referenced by many systems; its cache key must not vary."""
    assert (
        CacheIdentity.of("vmsystest07", "SysErrorRecord", "dbo").key
        == CacheIdentity.of("VMSYSTEST07.topmost.com.tw\\pdcs", "SysErrorRecord", "dbo").key
    )


def test_same_database_name_on_two_servers_gets_two_keys() -> None:
    assert (
        CacheIdentity.of("vmsystest07", "PUR", "dbo").key
        != CacheIdentity.of("vmsystest08", "PUR", "dbo").key
    )


def test_a_cache_identity_rejects_an_unknown_server() -> None:
    with pytest.raises(ValueError):
        CacheIdentity.of("", "PUR", "dbo")


def test_a_cache_identity_rejects_an_unknown_database() -> None:
    with pytest.raises(ValueError):
        CacheIdentity.of("vmsystest07", "", "dbo")


def test_the_reverse_parse_reads_a_three_part_stem_back_into_its_identity() -> None:
    assert CacheIdentity.from_key("vmsystest07.topmost.com.tw__PUR__dbo") == CacheIdentity(
        "vmsystest07.topmost.com.tw", "PUR", "dbo"
    )


def test_the_reverse_parse_returns_nothing_for_a_stem_that_names_no_identity() -> None:
    assert CacheIdentity.from_key("stray") is None
    assert CacheIdentity.from_key("STC__dbo") is None
    assert CacheIdentity.from_key("__PUR__dbo") is None


# ------------------------------------------------------- the directory listing


def test_the_directory_listing_returns_the_data_file_alone_beside_its_siblings() -> None:
    with CacheRoot() as cache_root:
        identity = CacheIdentity.of("vmsystest07", "PUR", "dbo")
        sql_cache_store._save(identity, _payload("PUR"))
        assert (cache_root / identity.meta_filename).exists()  # sanity: all three files
        assert (cache_root / identity.index_filename).exists()

        rows = sql_cache_store.list_cache_files()

        assert [(row.data_path.name, row.identity) for row in rows] == [
            ("vmsystest07.topmost.com.tw__PUR__dbo.json", identity)
        ]


def test_the_directory_listing_returns_an_empty_identity_for_a_file_that_names_none() -> None:
    with CacheRoot() as cache_root:
        (cache_root / "stray.json").write_text("{}", encoding="utf-8")
        (cache_root / "vmsystest07__PUR__dbo.json").write_text("{}", encoding="utf-8")

        rows = sql_cache_store.list_cache_files()

        assert [(row.data_path.name, row.identity) for row in rows] == [
            ("stray.json", None),
            ("vmsystest07__PUR__dbo.json", None),
        ]


def test_the_server_is_found_for_a_database_name_that_holds_the_separator() -> None:
    with CacheRoot() as cache_root:
        write_cache(
            cache_root,
            CacheIdentity.of("vmsystest07", "Y__Docs", "dbo"),
            _payload("Y__Docs"),
        )

        identity = sql_cache_store.find_cache_identity("Y__Docs", "dbo")

        assert identity == CacheIdentity.of("vmsystest07", "Y__Docs", "dbo")
        assert sql_cache_store.load_cached(identity)["database"] == "Y__Docs"


# ------------------------------------------------------- catalog membership


def test_a_database_is_cataloged_exactly_when_its_cache_file_exists() -> None:
    with CacheRoot() as cache_root:
        assert sql_cache_store.has_cache(CacheIdentity.of("vmsystest07", "SysErrorRecord", "dbo")) is False

        write_cache(
            cache_root,
            CacheIdentity.of("vmsystest07", "SysErrorRecord", "dbo"),
            _payload("SysErrorRecord"),
        )

        assert sql_cache_store.has_cache(CacheIdentity.of("vmsystest07", "SysErrorRecord", "dbo")) is True


def test_a_cache_written_for_one_server_is_not_found_under_another() -> None:
    with CacheRoot() as cache_root:
        write_cache(
            cache_root, CacheIdentity.of("vmsystest07", "PUR", "dbo"), _payload("PUR")
        )

        assert sql_cache_store.load_cached(CacheIdentity.of("vmsystest08", "PUR", "dbo")) is None


def test_a_caller_without_a_server_resolves_the_only_cache_for_that_database() -> None:
    with CacheRoot() as cache_root:
        write_cache(
            cache_root, CacheIdentity.of("vmsystest07", "PUR", "dbo"), _payload("PUR")
        )

        identity = sql_cache_store.find_cache_identity("PUR", "dbo")

        assert identity == CacheIdentity.of("vmsystest07", "PUR", "dbo")
        cached = sql_cache_store.load_cached(identity)

        assert cached is not None
        assert cached["database"] == "PUR"


def test_a_caller_without_a_server_refuses_an_ambiguous_database_name() -> None:
    with CacheRoot() as cache_root:
        write_cache(
            cache_root, CacheIdentity.of("vmsystest07", "PUR", "dbo"), _payload("PUR")
        )
        write_cache(
            cache_root, CacheIdentity.of("vmsystest08", "PUR", "dbo"), _payload("PUR")
        )

        assert sql_cache_store.find_cache_identity("PUR", "dbo") == sql_cache_store.AmbiguousServer(
            database="PUR",
            schema="dbo",
            servers=("vmsystest07.topmost.com.tw", "vmsystest08.topmost.com.tw"),
        )


def test_a_caller_without_a_server_reads_a_database_whose_name_the_filename_rewrites() -> None:
    """The filename holds a safe-named Database; the read still names the real one."""
    with CacheRoot() as cache_root:
        write_cache(
            cache_root, CacheIdentity.of("vmsystest07", "Y Docs", "dbo"), _payload("Y Docs")
        )

        identity = sql_cache_store.find_cache_identity("Y Docs", "dbo")

        assert identity == CacheIdentity.of("vmsystest07", "Y Docs", "dbo")
        assert sql_cache_store.load_cached(identity)["database"] == "Y Docs"


def test_a_caller_without_a_server_finds_nothing_when_no_cache_names_the_database() -> None:
    with CacheRoot() as cache_root:
        write_cache(
            cache_root, CacheIdentity.of("vmsystest07", "PUR", "dbo"), _payload("PUR")
        )

        assert sql_cache_store.find_cache_identity("STC", "dbo") is None


def test_a_system_id_is_not_a_cache_key() -> None:
    """Y-Docs_TTPUR is a system_id; the cached database is named PUR."""
    with CacheRoot() as cache_root:
        write_cache(
            cache_root, CacheIdentity.of("vmsystest07", "PUR", "dbo"), _payload("PUR")
        )

        assert sql_cache_store.load_cached(CacheIdentity.of("vmsystest07", "Y-Docs_TTPUR", "dbo")) is None


# --------------------------------------------------------- freshness (ticket 05)


def test_cached_saved_at_reads_the_recorded_save_time() -> None:
    with CacheRoot() as cache_root:
        write_cache(
            cache_root, CacheIdentity.of("vmsystest07", "PUR", "dbo"), _payload("PUR")
        )

        assert sql_cache_store.cached_saved_at(CacheIdentity.of("vmsystest07", "PUR", "dbo")) == "2026-08-04 13:29:13"


def test_cached_saved_at_resolves_the_server_the_same_way_load_cached_does() -> None:
    """No server given, exactly one cache on disk -- resolved the same as load_cached()."""
    with CacheRoot() as cache_root:
        write_cache(
            cache_root, CacheIdentity.of("vmsystest07", "PUR", "dbo"), _payload("PUR")
        )

        identity = sql_cache_store.find_cache_identity("PUR", "dbo")

        assert isinstance(identity, CacheIdentity)
        assert sql_cache_store.cached_saved_at(identity) == "2026-08-04 13:29:13"


def test_cached_saved_at_is_none_when_nothing_is_cached() -> None:
    with CacheRoot():
        assert sql_cache_store.cached_saved_at(CacheIdentity.of("vmsystest07", "NoSuchDb", "dbo")) is None


# ---------------------------------------------------------------- get_or_dump


def test_get_or_dump_refuses_to_key_a_cache_by_the_display_alias() -> None:
    """database is a display label; without db_name there is no cache identity."""
    with pytest.raises(ValueError):
        sql_cache_store.get_or_dump(
            CacheIdentity.of("vmsystest07", "", "dbo"), connection_server="vmsystest07"
        )


# -------------------------------------------------------------- list_caches


def test_list_caches_returns_every_cache_with_its_four_fields() -> None:
    with CacheRoot() as cache_root:
        write_cache(
            cache_root, CacheIdentity.of("vmsystest07", "PUR", "dbo"), _payload("PUR")
        )

        rows = sql_cache_store.list_caches()

        assert len(rows) == 1
        row = rows[0]
        assert row.server == "vmsystest07.topmost.com.tw"
        assert row.database == "PUR"
        assert row.schema == "dbo"
        assert row.scanned_at == "2026-08-04 13:29:13"


def test_list_caches_reports_an_absent_scan_time_when_the_meta_file_is_missing() -> None:
    with CacheRoot() as cache_root:
        (cache_root / CacheIdentity.of("vmsystest07", "PUR", "dbo").filename).write_text(
            json.dumps(_payload("PUR"), ensure_ascii=False), encoding="utf-8"
        )

        rows = sql_cache_store.list_caches()

        assert len(rows) == 1
        assert rows[0].server == "vmsystest07.topmost.com.tw"
        assert rows[0].database == "PUR"
        assert rows[0].schema == "dbo"
        assert rows[0].scanned_at is None


def test_list_caches_reports_an_absent_scan_time_when_the_meta_file_is_unreadable() -> None:
    with CacheRoot() as cache_root:
        write_cache(
            cache_root, CacheIdentity.of("vmsystest07", "PUR", "dbo"), _payload("PUR")
        )
        (cache_root / CacheIdentity.of("vmsystest07", "PUR", "dbo").meta_filename).write_text(
            "{not valid json", encoding="utf-8"
        )

        rows = sql_cache_store.list_caches()

        assert len(rows) == 1
        row = rows[0]
        assert row.scanned_at is None
        # Identity still comes from the filename when meta cannot be read.
        assert row.server == "vmsystest07.topmost.com.tw"
        assert row.database == "PUR"
        assert row.schema == "dbo"


def test_list_caches_never_lists_a_scan_record_file_as_a_cache() -> None:
    with CacheRoot() as cache_root:
        # A meta file with no sibling data file must never surface as a row.
        (cache_root / CacheIdentity.of("vmsystest07", "PUR", "dbo").meta_filename).write_text(
            json.dumps(
                {
                    "server": "vmsystest07.topmost.com.tw",
                    "database": "PUR",
                    "schema": "dbo",
                    "saved_at": "2026-08-04 13:29:13",
                }
            ),
            encoding="utf-8",
        )

        assert sql_cache_store.list_caches() == []


def test_list_caches_never_lists_an_object_location_index_file_as_a_cache() -> None:
    """The index file also ends in ``.json``; it must not surface as a second row."""
    with CacheRoot() as cache_root:
        identity = CacheIdentity.of("vmsystest07", "PUR", "dbo")

        sql_cache_store._save(identity, _payload("PUR"))

        assert (cache_root / identity.index_filename).exists()  # sanity: the index exists
        rows = sql_cache_store.list_caches()
        assert len(rows) == 1
        assert rows[0].server == "vmsystest07.topmost.com.tw"
        assert rows[0].database == "PUR"
        assert rows[0].schema == "dbo"


def test_list_caches_orders_rows_by_server_then_database_then_schema() -> None:
    with CacheRoot() as cache_root:
        write_cache(
            cache_root, CacheIdentity.of("vmsystest08", "PUR", "dbo"), _payload("PUR")
        )
        write_cache(
            cache_root, CacheIdentity.of("vmsystest07", "STC", "dbo"), _payload("STC")
        )
        write_cache(
            cache_root, CacheIdentity.of("vmsystest07", "PUR", "dbo"), _payload("PUR")
        )

        rows = sql_cache_store.list_caches()

        assert [(row.server, row.database, row.schema) for row in rows] == [
            ("vmsystest07.topmost.com.tw", "PUR", "dbo"),
            ("vmsystest07.topmost.com.tw", "STC", "dbo"),
            ("vmsystest08.topmost.com.tw", "PUR", "dbo"),
        ]


# ----------------------------------------------------- analyze-side read path


def _payload_with_procedure(database: str, procedure: str) -> dict:
    return _payload(
        database,
        procedures={procedure: {"definition": "CREATE PROCEDURE x AS SELECT 1"}},
        graph_nodes=(
            {"id": f"stored_procedure:dbo.{procedure}", "type": "stored_procedure",
             "name": procedure, "schema": "dbo"},
        ),
    )


def test_the_analyze_read_path_reads_the_server_the_request_named() -> None:
    """Two servers hold a PUR cache; db_server decides which one /analyze reads."""
    with CacheRoot() as cache_root:
        write_cache(
            cache_root,
            CacheIdentity.of("vmsystest07", "PUR", "dbo"),
            _payload_with_procedure("PUR", "spOnSeven"),
        )
        write_cache(
            cache_root,
            CacheIdentity.of("vmsystest08", "PUR", "dbo"),
            _payload_with_procedure("PUR", "spOnEight"),
        )

        catalog, _graph, _database = analyze_service._execution_sql_context("PUR", "vmsystest08")

        assert catalog.contains("PUR", "sponeight") is True
        assert catalog.contains("PUR", "sponseven") is False


def test_the_analyze_read_path_without_a_server_cannot_pick_between_two() -> None:
    """The ambiguity is reported as "no cache", not silently resolved to one server."""
    with CacheRoot() as cache_root:
        write_cache(
            cache_root,
            CacheIdentity.of("vmsystest07", "PUR", "dbo"),
            _payload_with_procedure("PUR", "spOnSeven"),
        )
        write_cache(
            cache_root,
            CacheIdentity.of("vmsystest08", "PUR", "dbo"),
            _payload_with_procedure("PUR", "spOnEight"),
        )

        with pytest.raises(analyze_service.SqlExecutionGraphRequiredError):
            analyze_service._require_sql_execution_graph("PUR")

        cached, _graph = analyze_service._require_sql_execution_graph("PUR", "vmsystest07")
        assert cached["database"] == "PUR"


# --------------------------------------------------- Object Location Index


def _payload_with_graph_only_table(database: str) -> dict:
    """A table reached only inside a stored-procedure body: absent from ``tables``.

    ``Orders`` never appears in the declared ``tables`` list — only as a table
    node the SQL Execution Graph produced from a procedure body. This is the
    fixture the union bucket exists for (ticket 01's proof requirement).
    """
    return _payload(
        database,
        procedures={
            "spTouchesOrders": {"definition": "CREATE PROCEDURE spTouchesOrders AS SELECT 1"}
        },
        tables={"Customers": {"columns": [], "primary_keys": []}},
        graph_nodes=(
            {
                "id": "stored_procedure:dbo.spTouchesOrders",
                "type": "stored_procedure",
                "schema": "dbo",
                "name": "spTouchesOrders",
            },
            {"id": "table:dbo.Orders", "type": "table", "schema": "dbo", "name": "Orders"},
        ),
    )


def test_the_stored_procedure_bucket_holds_procedures_views_and_functions_normalized() -> None:
    identity = CacheIdentity.of("vmsystest07", "PUR", "dbo")
    data = _payload(
        "PUR",
        procedures={"[dbo].[spDoThing]": {"definition": ""}},
        views={"vwSomething": {"definition": ""}},
        functions={"ufnCalc": {"definition": ""}},
    )

    index = sql_cache_store.build_object_location_index(identity, data)

    assert index.stored_procedures == {"spdothing", "vwsomething", "ufncalc"}


def test_the_table_bucket_holds_the_declared_tables_normalized() -> None:
    identity = CacheIdentity.of("vmsystest07", "PUR", "dbo")
    data = _payload("PUR", tables={"Customers": {"columns": [], "primary_keys": []}})

    index = sql_cache_store.build_object_location_index(identity, data)

    assert index.tables == {"customers"}


def test_table_name_normalization_drops_the_schema() -> None:
    """dbo.Orders and sales.Orders must collapse to the same key."""
    identity = CacheIdentity.of("vmsystest07", "PUR", "dbo")
    data = _payload("PUR", tables={"sales.Orders": {"columns": [], "primary_keys": []}})

    index = sql_cache_store.build_object_location_index(identity, data)

    assert index.tables == {"orders"}


def test_the_table_bucket_includes_a_table_reached_only_inside_a_stored_procedure_body() -> None:
    """The union with graph node names is the point of the table bucket."""
    identity = CacheIdentity.of("vmsystest07", "PUR", "dbo")
    data = _payload_with_graph_only_table("PUR")

    index = sql_cache_store.build_object_location_index(identity, data)

    assert "orders" in index.tables  # only a graph node, never in data["tables"]
    assert "customers" in index.tables  # a declared table is still included too


def test_the_index_carries_its_identity_and_the_cache_format_version() -> None:
    identity = CacheIdentity.of("vmsystest07", "PUR", "dbo")

    index = sql_cache_store.build_object_location_index(identity, _payload("PUR"))

    assert index.server == "vmsystest07.topmost.com.tw"
    assert index.database == "PUR"
    assert index.schema == "dbo"
    assert index.cache_version == sql_cache_store._SQL_CACHE_VERSION


def test_the_index_is_written_beside_the_cache_not_merged_into_the_scan_record() -> None:
    with CacheRoot() as cache_root:
        identity = CacheIdentity.of("vmsystest07", "PUR", "dbo")

        sql_cache_store._save(identity, _payload("PUR"))

        assert (cache_root / identity.index_filename).exists()
        meta = json.loads((cache_root / identity.meta_filename).read_text(encoding="utf-8"))
        assert "stored_procedures" not in meta
        assert "tables" not in meta


def test_a_refresh_writes_the_cache_before_the_index() -> None:
    """An interrupted refresh must leave the index detectably older, never missing this order."""
    with CacheRoot() as cache_root:
        identity = CacheIdentity.of("vmsystest07", "PUR", "dbo")

        sql_cache_store._save(identity, _payload("PUR"))

        data_mtime = (cache_root / identity.filename).stat().st_mtime
        index_mtime = (cache_root / identity.index_filename).stat().st_mtime
        assert index_mtime >= data_mtime


def test_a_fresh_index_round_trips_through_load_object_location_index() -> None:
    with CacheRoot() as cache_root:
        identity = CacheIdentity.of("vmsystest07", "PUR", "dbo")
        data = _payload("PUR", procedures={"spAddRecordError": {"definition": ""}})

        sql_cache_store._save(identity, data)

        loaded = sql_cache_store.load_object_location_index(identity)

        assert loaded is not None
        assert "spaddrecorderror" in loaded.stored_procedures


def test_a_missing_index_file_counts_as_absent() -> None:
    with CacheRoot() as cache_root:
        identity = CacheIdentity.of("vmsystest07", "PUR", "dbo")
        write_cache(cache_root, identity, _payload("PUR"))

        assert sql_cache_store.load_object_location_index(identity) is None


def test_an_unreadable_index_file_counts_as_absent() -> None:
    with CacheRoot() as cache_root:
        identity = CacheIdentity.of("vmsystest07", "PUR", "dbo")
        write_cache(cache_root, identity, _payload("PUR"))
        (cache_root / identity.index_filename).write_text("{not valid json", encoding="utf-8")

        assert sql_cache_store.load_object_location_index(identity) is None


def test_an_index_older_than_its_cache_counts_as_absent() -> None:
    """Simulates a refresh that stopped halfway: the cache moved on, the index did not."""
    with CacheRoot() as cache_root:
        identity = CacheIdentity.of("vmsystest07", "PUR", "dbo")
        sql_cache_store._save(identity, _payload("PUR"))

        old = time.time() - 1000
        os.utime(cache_root / identity.index_filename, (old, old))

        assert sql_cache_store.load_object_location_index(identity) is None


def test_an_index_built_against_a_different_cache_format_version_counts_as_absent() -> None:
    with CacheRoot() as cache_root:
        identity = CacheIdentity.of("vmsystest07", "PUR", "dbo")
        sql_cache_store._save(identity, _payload("PUR"))

        index_path = cache_root / identity.index_filename
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        payload["cache_version"] = sql_cache_store._SQL_CACHE_VERSION - 1
        index_path.write_text(json.dumps(payload), encoding="utf-8")
        future = time.time() + 10
        os.utime(index_path, (future, future))  # rule out the mtime check alone

        assert sql_cache_store.load_object_location_index(identity) is None


def test_an_index_moved_by_hand_to_a_different_identity_counts_as_absent() -> None:
    """A reviewer must be able to detect a file moved/renamed by hand, not trust it."""
    with CacheRoot() as cache_root:
        identity = CacheIdentity.of("vmsystest07", "PUR", "dbo")
        other = CacheIdentity.of("vmsystest08", "PUR", "dbo")
        sql_cache_store._save(identity, _payload("PUR"))

        (cache_root / other.filename).write_bytes((cache_root / identity.filename).read_bytes())
        (cache_root / other.meta_filename).write_bytes(
            (cache_root / identity.meta_filename).read_bytes()
        )
        (cache_root / other.index_filename).write_bytes(
            (cache_root / identity.index_filename).read_bytes()
        )

        assert sql_cache_store.load_object_location_index(other) is None


def test_the_staleness_check_never_reads_the_cache_body() -> None:
    """A 105 MB cache must never be parsed just to decide whether its index is fresh."""
    with CacheRoot() as cache_root:
        identity = CacheIdentity.of("vmsystest07", "PUR", "dbo")
        sql_cache_store._save(identity, _payload("PUR"))

        data_path = cache_root / identity.filename
        index_path = cache_root / identity.index_filename
        # Corrupt the content only; keep the index's mtime at least as new as the
        # cache's so the (valid) mtime rule alone cannot explain a fresh result.
        data_path.write_text("{not valid json at all", encoding="utf-8")
        fresh = data_path.stat().st_mtime + 10
        os.utime(index_path, (fresh, fresh))

        loaded = sql_cache_store.load_object_location_index(identity)

        assert loaded is not None


# ------------------------------------------- bounded memory retention (ticket 08)


def test_the_memory_cache_retains_no_more_databases_than_its_bound(monkeypatch) -> None:
    with CacheRoot() as cache_root:
        monkeypatch.setattr(sql_cache_store.settings, "SQL_CACHE_MEMORY_RETENTION_LIMIT", 2)
        for name in ("Db1", "Db2", "Db3"):
            write_cache(cache_root, CacheIdentity.of("vmsystest07", name, "dbo"), _payload(name))

        for name in ("Db1", "Db2", "Db3"):
            assert sql_cache_store.load_cached(CacheIdentity.of("vmsystest07", name, "dbo")) is not None

        assert len(sql_cache_store._mem_cache) == 2


def test_exceeding_the_bound_evicts_the_least_recently_used_database_and_records_it(
    monkeypatch, capsys
) -> None:
    with CacheRoot() as cache_root:
        monkeypatch.setattr(sql_cache_store.settings, "SQL_CACHE_MEMORY_RETENTION_LIMIT", 2)
        for name in ("Db1", "Db2"):
            write_cache(cache_root, CacheIdentity.of("vmsystest07", name, "dbo"), _payload(name))

        sql_cache_store.load_cached(CacheIdentity.of("vmsystest07", "Db1", "dbo"))
        sql_cache_store.load_cached(CacheIdentity.of("vmsystest07", "Db2", "dbo"))
        capsys.readouterr()  # discard output from the first two, unbounded, insertions

        write_cache(cache_root, CacheIdentity.of("vmsystest07", "Db3", "dbo"), _payload("Db3"))
        sql_cache_store.load_cached(CacheIdentity.of("vmsystest07", "Db3", "dbo"))

        db1 = CacheIdentity.of("vmsystest07", "Db1", "dbo")
        db2 = CacheIdentity.of("vmsystest07", "Db2", "dbo")
        db3 = CacheIdentity.of("vmsystest07", "Db3", "dbo")
        assert db1 not in sql_cache_store._mem_cache
        assert db2 in sql_cache_store._mem_cache
        assert db3 in sql_cache_store._mem_cache

        printed = capsys.readouterr().out
        assert "已達上限" in printed
        assert "Db1" in printed


def test_a_served_database_survives_more_new_arrivals_than_the_bound(monkeypatch) -> None:
    """A database re-served before each new arrival stays retained across two
    new arrivals -- more than a plain first-in-first-out bound of 2 would
    allow a database that only arrived first, because eviction falls instead
    on the database least recently served."""
    with CacheRoot() as cache_root:
        monkeypatch.setattr(sql_cache_store.settings, "SQL_CACHE_MEMORY_RETENTION_LIMIT", 2)
        for name in ("Db1", "Db2", "Db3", "Db4"):
            write_cache(cache_root, CacheIdentity.of("vmsystest07", name, "dbo"), _payload(name))

        sql_cache_store.load_cached(CacheIdentity.of("vmsystest07", "Db1", "dbo"))
        sql_cache_store.load_cached(CacheIdentity.of("vmsystest07", "Db2", "dbo"))

        sql_cache_store.load_cached(CacheIdentity.of("vmsystest07", "Db1", "dbo"))
        sql_cache_store.load_cached(CacheIdentity.of("vmsystest07", "Db3", "dbo"))

        sql_cache_store.load_cached(CacheIdentity.of("vmsystest07", "Db1", "dbo"))
        sql_cache_store.load_cached(CacheIdentity.of("vmsystest07", "Db4", "dbo"))

        retained = sql_cache_store._mem_cache
        assert CacheIdentity.of("vmsystest07", "Db1", "dbo") in retained
        assert CacheIdentity.of("vmsystest07", "Db2", "dbo") not in retained
        assert CacheIdentity.of("vmsystest07", "Db3", "dbo") not in retained
        assert CacheIdentity.of("vmsystest07", "Db4", "dbo") in retained


def test_a_database_evicted_from_memory_is_read_from_disk_again_with_the_same_content(
    monkeypatch,
) -> None:
    with CacheRoot() as cache_root:
        monkeypatch.setattr(sql_cache_store.settings, "SQL_CACHE_MEMORY_RETENTION_LIMIT", 1)
        write_cache(cache_root, CacheIdentity.of("vmsystest07", "Db1", "dbo"), _payload("Db1"))
        write_cache(cache_root, CacheIdentity.of("vmsystest07", "Db2", "dbo"), _payload("Db2"))

        first = sql_cache_store.load_cached(CacheIdentity.of("vmsystest07", "Db1", "dbo"))
        sql_cache_store.load_cached(CacheIdentity.of("vmsystest07", "Db2", "dbo"))  # evicts Db1 from memory
        db1 = CacheIdentity.of("vmsystest07", "Db1", "dbo")
        assert db1 not in sql_cache_store._mem_cache  # sanity: really evicted

        reloaded = sql_cache_store.load_cached(CacheIdentity.of("vmsystest07", "Db1", "dbo"))

        assert reloaded is not None
        assert reloaded == first


def test_eviction_never_changes_which_databases_answer_a_read(monkeypatch) -> None:
    """A tighter bound must not make a still-cataloged database unreadable."""
    with CacheRoot() as cache_root:
        monkeypatch.setattr(sql_cache_store.settings, "SQL_CACHE_MEMORY_RETENTION_LIMIT", 1)
        for name in ("Db1", "Db2", "Db3"):
            write_cache(cache_root, CacheIdentity.of("vmsystest07", name, "dbo"), _payload(name))

        for name in ("Db1", "Db2", "Db3"):
            assert sql_cache_store.load_cached(CacheIdentity.of("vmsystest07", name, "dbo"))["database"] == name
