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
from service.sql_execution_graph import GRAPH_VERSION
from tests.sql_cache_fixtures import CacheRoot, write_cache
from tools.migrate_sql_cache_keys import LEGACY_CACHE_SCOPES, Scope, migrate_cache_keys


def _payload(database: str) -> dict:
    return {
        "database": database,
        "schema": "dbo",
        "procedures": [{"name": "spAddRecordError", "definition": "CREATE PROCEDURE x AS SELECT 1"}],
        "views": [],
        "functions": [],
        "tables": [],
        "sql_execution_graph": {
            "graph_version": GRAPH_VERSION,
            "database": database,
            "nodes": [],
            "relationships": [],
            "parse_errors": [],
        },
    }


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


# ------------------------------------------------------------------ cache key


def test_a_cache_identity_names_its_own_files() -> None:
    identity = CacheIdentity.of("vmsystest07", "STC", "dbo")

    assert identity.filename == "vmsystest07.topmost.com.tw__STC__dbo.json"
    assert identity.meta_filename == "vmsystest07.topmost.com.tw__STC__dbo.meta.json"


def test_a_cache_identity_defaults_to_the_dbo_schema() -> None:
    assert (
        CacheIdentity.of("vmsystest07.topmost.com.tw", "PUR").filename
        == "vmsystest07.topmost.com.tw__PUR__dbo.json"
    )


def test_one_shared_database_has_one_key_regardless_of_which_system_asks() -> None:
    """SysErrorRecord is referenced by many systems; its cache key must not vary."""
    assert (
        CacheIdentity.of("vmsystest07", "SysErrorRecord").key
        == CacheIdentity.of("VMSYSTEST07.topmost.com.tw\\pdcs", "SysErrorRecord").key
    )


def test_same_database_name_on_two_servers_gets_two_keys() -> None:
    assert (
        CacheIdentity.of("vmsystest07", "PUR").key
        != CacheIdentity.of("vmsystest08", "PUR").key
    )


def test_a_cache_identity_rejects_an_unknown_server() -> None:
    with pytest.raises(ValueError):
        CacheIdentity.of("", "PUR")


def test_a_cache_identity_rejects_an_unknown_database() -> None:
    with pytest.raises(ValueError):
        CacheIdentity.of("vmsystest07", "")


# ------------------------------------------------------- catalog membership


def test_a_database_is_cataloged_exactly_when_its_cache_file_exists() -> None:
    with CacheRoot() as cache_root:
        assert sql_cache_store.has_cache("SysErrorRecord", "dbo", server="vmsystest07") is False

        write_cache(
            cache_root,
            "vmsystest07.topmost.com.tw__SysErrorRecord__dbo",
            _payload("SysErrorRecord"),
        )

        assert sql_cache_store.has_cache("SysErrorRecord", "dbo", server="vmsystest07") is True


def test_a_cache_written_for_one_server_is_not_found_under_another() -> None:
    with CacheRoot() as cache_root:
        write_cache(
            cache_root, "vmsystest07.topmost.com.tw__PUR__dbo", _payload("PUR")
        )

        assert sql_cache_store.load_cached("PUR", "dbo", server="vmsystest08") is None


def test_a_caller_without_a_server_resolves_the_only_cache_for_that_database() -> None:
    with CacheRoot() as cache_root:
        write_cache(
            cache_root, "vmsystest07.topmost.com.tw__PUR__dbo", _payload("PUR")
        )

        cached = sql_cache_store.load_cached("PUR", "dbo")

        assert cached is not None
        assert cached["database"] == "PUR"


def test_a_caller_without_a_server_refuses_an_ambiguous_database_name() -> None:
    with CacheRoot() as cache_root:
        write_cache(
            cache_root, "vmsystest07.topmost.com.tw__PUR__dbo", _payload("PUR")
        )
        write_cache(
            cache_root, "vmsystest08.topmost.com.tw__PUR__dbo", _payload("PUR")
        )

        assert sql_cache_store.load_cached("PUR", "dbo") is None


def test_a_system_id_is_not_a_cache_key() -> None:
    """Y-Docs_TTPUR is a system_id; the cached database is named PUR."""
    with CacheRoot() as cache_root:
        write_cache(
            cache_root, "vmsystest07.topmost.com.tw__PUR__dbo", _payload("PUR")
        )

        assert sql_cache_store.load_cached("Y-Docs_TTPUR", "dbo", server="vmsystest07") is None


# --------------------------------------------------------- freshness (ticket 05)


def test_cached_saved_at_reads_the_recorded_save_time() -> None:
    with CacheRoot() as cache_root:
        write_cache(
            cache_root, "vmsystest07.topmost.com.tw__PUR__dbo", _payload("PUR")
        )

        assert sql_cache_store.cached_saved_at("PUR", "dbo", server="vmsystest07") == "2026-08-04 13:29:13"


def test_cached_saved_at_resolves_the_server_the_same_way_load_cached_does() -> None:
    """No server given, exactly one cache on disk -- resolved the same as load_cached()."""
    with CacheRoot() as cache_root:
        write_cache(
            cache_root, "vmsystest07.topmost.com.tw__PUR__dbo", _payload("PUR")
        )

        assert sql_cache_store.cached_saved_at("PUR", "dbo") == "2026-08-04 13:29:13"


def test_cached_saved_at_is_none_when_nothing_is_cached() -> None:
    with CacheRoot():
        assert sql_cache_store.cached_saved_at("NoSuchDb", "dbo", server="vmsystest07") is None


# ---------------------------------------------------------------- migration


def test_migration_renames_a_legacy_cache_file_to_the_new_key() -> None:
    with CacheRoot() as cache_root:
        write_cache(cache_root, "STC__dbo", _payload("STC"))

        migrate_cache_keys(cache_root, [Scope("STC__dbo", "vmsystest07", "STC", "dbo")])

        assert (cache_root / "vmsystest07.topmost.com.tw__STC__dbo.json").exists()
        assert (cache_root / "vmsystest07.topmost.com.tw__STC__dbo.meta.json").exists()
        assert not (cache_root / "STC__dbo.json").exists()
        assert not (cache_root / "STC__dbo.meta.json").exists()


def test_a_migrated_cache_reads_back_identically_under_its_new_name() -> None:
    """Smoke test: rename only — the parsed payload must not change."""
    with CacheRoot() as cache_root:
        before = _payload("STC")
        write_cache(cache_root, "STC__dbo", before)

        migrate_cache_keys(cache_root, [Scope("STC__dbo", "vmsystest07", "STC", "dbo")])

        after = sql_cache_store.load_cached("STC", "dbo", server="vmsystest07")
        assert after == before


def test_migration_corrects_a_payload_whose_identity_was_a_system_id() -> None:
    """Y-Docs_TTPUR__dbo holds database PUR; only the identity fields may change."""
    with CacheRoot() as cache_root:
        before = _payload("Y-Docs_TTPUR")
        write_cache(cache_root, "Y-Docs_TTPUR__dbo", before)

        migrate_cache_keys(cache_root, [Scope("Y-Docs_TTPUR__dbo", "vmsystest07", "PUR", "dbo")])

        after = sql_cache_store.load_cached("PUR", "dbo", server="vmsystest07")
        assert after is not None
        assert after["database"] == "PUR"
        assert after["sql_execution_graph"]["database"] == "PUR"
        expected = dict(before)
        expected["database"] = "PUR"
        expected["sql_execution_graph"] = dict(before["sql_execution_graph"], database="PUR")
        assert after == expected


def test_migration_does_not_rescan_the_procedure_definitions() -> None:
    with CacheRoot() as cache_root:
        before = _payload("Y-Docs_TTPUR")
        write_cache(cache_root, "Y-Docs_TTPUR__dbo", before)

        migrate_cache_keys(cache_root, [Scope("Y-Docs_TTPUR__dbo", "vmsystest07", "PUR", "dbo")])

        after = json.loads(
            (cache_root / "vmsystest07.topmost.com.tw__PUR__dbo.json").read_text(encoding="utf-8")
        )
        assert after["procedures"] == before["procedures"]


def test_migration_touches_only_the_identity_bytes() -> None:
    """No re-scan means no rewrite: even the line endings must survive."""
    with CacheRoot() as cache_root:
        before = _payload("Y-Docs_TTPUR")
        raw = (
            json.dumps(before, ensure_ascii=False, indent=2)
            .replace("\n", "\r\n")
            .encode("utf-8")
        )
        (cache_root / "Y-Docs_TTPUR__dbo.json").write_bytes(raw)
        (cache_root / "Y-Docs_TTPUR__dbo.meta.json").write_text(
            json.dumps(
                {
                    "cache_version": sql_cache_store._SQL_CACHE_VERSION,
                    "database": "Y-Docs_TTPUR",
                    "schema": "dbo",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        migrate_cache_keys(cache_root, [Scope("Y-Docs_TTPUR__dbo", "vmsystest07", "PUR", "dbo")])

        after = (cache_root / "vmsystest07.topmost.com.tw__PUR__dbo.json").read_bytes()
        assert after == raw.replace(b'"database": "Y-Docs_TTPUR"', b'"database": "PUR"')


def test_migration_is_idempotent() -> None:
    with CacheRoot() as cache_root:
        write_cache(cache_root, "STC__dbo", _payload("STC"))
        scopes = [Scope("STC__dbo", "vmsystest07", "STC", "dbo")]

        first = migrate_cache_keys(cache_root, scopes)
        second = migrate_cache_keys(cache_root, scopes)

        assert [entry["action"] for entry in first] == ["migrated"]
        assert [entry["action"] for entry in second] == ["missing"]
        assert sql_cache_store.load_cached("STC", "dbo", server="vmsystest07") is not None


def test_migration_dry_run_changes_nothing() -> None:
    with CacheRoot() as cache_root:
        write_cache(cache_root, "STC__dbo", _payload("STC"))

        migrate_cache_keys(
            cache_root,
            [Scope("STC__dbo", "vmsystest07", "STC", "dbo")],
            dry_run=True,
        )

        assert (cache_root / "STC__dbo.json").exists()
        assert not (cache_root / "vmsystest07.topmost.com.tw__STC__dbo.json").exists()


def test_the_shipped_migration_scopes_cover_both_existing_cache_files() -> None:
    assert LEGACY_CACHE_SCOPES == [
        ("STC__dbo", "vmsystest07", "STC", "dbo"),
        ("Y-Docs_TTPUR__dbo", "vmsystest07", "PUR", "dbo"),
    ]


def test_the_migration_writes_the_meta_the_store_itself_would_write() -> None:
    """The meta format lives in sql_cache_store; the migration must not fork it."""
    with CacheRoot() as cache_root:
        write_cache(cache_root, "STC__dbo", _payload("STC"))

        migrate_cache_keys(cache_root, [Scope("STC__dbo", "vmsystest07", "STC", "dbo")])

        identity = CacheIdentity.of("vmsystest07", "STC", "dbo")
        migrated = json.loads(
            (cache_root / identity.meta_filename).read_text(encoding="utf-8")
        )
        sql_cache_store._save(CacheIdentity.of("vmsystest08", "STC", "dbo"), _payload("STC"))
        saved = json.loads(
            (cache_root / CacheIdentity.of("vmsystest08", "STC", "dbo").meta_filename)
            .read_text(encoding="utf-8")
        )

        assert migrated.keys() == saved.keys()
        assert migrated["cache_version"] == saved["cache_version"]
        assert migrated["server"] == "vmsystest07.topmost.com.tw"
        # A rename is not a re-scan: the legacy scan time survives untouched.
        assert migrated["saved_at"] == "2026-08-04 13:29:13"


# ---------------------------------------------------------------- get_or_dump


def test_get_or_dump_refuses_to_key_a_cache_by_the_display_alias() -> None:
    """database is a display label; without db_name there is no cache identity."""
    with pytest.raises(ValueError):
        sql_cache_store.get_or_dump("Y-Docs_TTPUR", server="vmsystest07")


# -------------------------------------------------------------- list_caches


def test_list_caches_returns_every_cache_with_its_four_fields() -> None:
    with CacheRoot() as cache_root:
        write_cache(
            cache_root, "vmsystest07.topmost.com.tw__PUR__dbo", _payload("PUR")
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
        (cache_root / "vmsystest07.topmost.com.tw__PUR__dbo.json").write_text(
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
            cache_root, "vmsystest07.topmost.com.tw__PUR__dbo", _payload("PUR")
        )
        (cache_root / "vmsystest07.topmost.com.tw__PUR__dbo.meta.json").write_text(
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
        (cache_root / "vmsystest07.topmost.com.tw__PUR__dbo.meta.json").write_text(
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
            cache_root, "vmsystest08.topmost.com.tw__PUR__dbo", _payload("PUR")
        )
        write_cache(
            cache_root, "vmsystest07.topmost.com.tw__STC__dbo", _payload("STC")
        )
        write_cache(
            cache_root, "vmsystest07.topmost.com.tw__PUR__dbo", _payload("PUR")
        )

        rows = sql_cache_store.list_caches()

        assert [(row.server, row.database, row.schema) for row in rows] == [
            ("vmsystest07.topmost.com.tw", "PUR", "dbo"),
            ("vmsystest07.topmost.com.tw", "STC", "dbo"),
            ("vmsystest08.topmost.com.tw", "PUR", "dbo"),
        ]


# ----------------------------------------------------- analyze-side read path


def _payload_with_procedure(database: str, procedure: str) -> dict:
    payload = _payload(database)
    payload["procedures"] = [{"name": procedure, "definition": "CREATE PROCEDURE x AS SELECT 1"}]
    payload["sql_execution_graph"]["nodes"] = [
        {"id": f"stored_procedure:dbo.{procedure}", "type": "stored_procedure",
         "name": procedure, "schema": "dbo"}
    ]
    return payload


def test_the_analyze_read_path_reads_the_server_the_request_named() -> None:
    """Two servers hold a PUR cache; db_server decides which one /analyze reads."""
    with CacheRoot() as cache_root:
        write_cache(
            cache_root,
            "vmsystest07.topmost.com.tw__PUR__dbo",
            _payload_with_procedure("PUR", "spOnSeven"),
        )
        write_cache(
            cache_root,
            "vmsystest08.topmost.com.tw__PUR__dbo",
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
            "vmsystest07.topmost.com.tw__PUR__dbo",
            _payload_with_procedure("PUR", "spOnSeven"),
        )
        write_cache(
            cache_root,
            "vmsystest08.topmost.com.tw__PUR__dbo",
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
    payload = _payload(database)
    payload["procedures"] = [
        {"name": "spTouchesOrders", "definition": "CREATE PROCEDURE spTouchesOrders AS SELECT 1"}
    ]
    payload["tables"] = [{"name": "Customers", "columns": [], "primary_keys": []}]
    payload["sql_execution_graph"] = {
        "graph_version": GRAPH_VERSION,
        "database": database,
        "nodes": [
            {
                "id": "stored_procedure:dbo.spTouchesOrders",
                "type": "stored_procedure",
                "schema": "dbo",
                "name": "spTouchesOrders",
            },
            {"id": "table:dbo.Orders", "type": "table", "schema": "dbo", "name": "Orders"},
        ],
        "relationships": [],
        "parse_errors": [],
    }
    return payload


def test_the_stored_procedure_bucket_holds_procedures_views_and_functions_normalized() -> None:
    identity = CacheIdentity.of("vmsystest07", "PUR", "dbo")
    data = _payload("PUR")
    data["procedures"] = [{"name": "[dbo].[spDoThing]", "definition": ""}]
    data["views"] = [{"name": "vwSomething", "definition": ""}]
    data["functions"] = [{"name": "ufnCalc", "definition": ""}]

    index = sql_cache_store.build_object_location_index(identity, data)

    assert index.stored_procedures == {"spdothing", "vwsomething", "ufncalc"}


def test_the_table_bucket_holds_the_declared_tables_normalized() -> None:
    identity = CacheIdentity.of("vmsystest07", "PUR", "dbo")
    data = _payload("PUR")
    data["tables"] = [{"name": "Customers", "columns": [], "primary_keys": []}]

    index = sql_cache_store.build_object_location_index(identity, data)

    assert index.tables == {"customers"}


def test_table_name_normalization_drops_the_schema() -> None:
    """dbo.Orders and sales.Orders must collapse to the same key."""
    identity = CacheIdentity.of("vmsystest07", "PUR", "dbo")
    data = _payload("PUR")
    data["tables"] = [{"name": "sales.Orders", "columns": [], "primary_keys": []}]

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
        data = _payload("PUR")
        data["procedures"] = [{"name": "spAddRecordError", "definition": ""}]

        sql_cache_store._save(identity, data)

        loaded = sql_cache_store.load_object_location_index(identity)

        assert loaded is not None
        assert "spaddrecorderror" in loaded.stored_procedures


def test_a_missing_index_file_counts_as_absent() -> None:
    with CacheRoot() as cache_root:
        identity = CacheIdentity.of("vmsystest07", "PUR", "dbo")
        write_cache(cache_root, identity.key, _payload("PUR"))

        assert sql_cache_store.load_object_location_index(identity) is None


def test_an_unreadable_index_file_counts_as_absent() -> None:
    with CacheRoot() as cache_root:
        identity = CacheIdentity.of("vmsystest07", "PUR", "dbo")
        write_cache(cache_root, identity.key, _payload("PUR"))
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
