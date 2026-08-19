"""Ticket 02 behavior checks: SQL cache identity is (server, database, schema)."""

from __future__ import annotations

import json
import sys
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
