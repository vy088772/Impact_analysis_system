"""Ticket 02 behavior checks: SQL cache identity is (server, database, schema)."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import settings
from service import sql_cache_store
from service.sql_execution_graph import GRAPH_VERSION
from tools.migrate_sql_cache_keys import LEGACY_CACHE_SCOPES, migrate_cache_keys


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


def _write_legacy_cache(cache_root: Path, legacy_key: str, payload: dict) -> None:
    (cache_root / f"{legacy_key}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (cache_root / f"{legacy_key}.meta.json").write_text(
        json.dumps(
            {
                "cache_version": sql_cache_store._SQL_CACHE_VERSION,
                "database": payload["database"],
                "schema": payload["schema"],
                "saved_at": "2026-08-04 13:29:13",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


class _CacheRoot:
    """Point settings.SQL_CACHE_ROOT at a temp dir and clear the in-process cache."""

    def __enter__(self) -> Path:
        self._previous_root = settings.SQL_CACHE_ROOT
        self._previous_mem = dict(sql_cache_store._mem_cache)
        self._tmp = tempfile.TemporaryDirectory()
        settings.SQL_CACHE_ROOT = self._tmp.name
        sql_cache_store._mem_cache.clear()
        return Path(self._tmp.name)

    def __exit__(self, *exc: object) -> None:
        settings.SQL_CACHE_ROOT = self._previous_root
        sql_cache_store._mem_cache.clear()
        sql_cache_store._mem_cache.update(self._previous_mem)
        self._tmp.cleanup()


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


def test_cache_filename_is_built_from_server_database_and_schema() -> None:
    assert (
        sql_cache_store.cache_filename("vmsystest07", "STC", "dbo")
        == "vmsystest07.topmost.com.tw__STC__dbo.json"
    )


def test_cache_filename_defaults_to_the_dbo_schema() -> None:
    assert (
        sql_cache_store.cache_filename("vmsystest07.topmost.com.tw", "PUR")
        == "vmsystest07.topmost.com.tw__PUR__dbo.json"
    )


def test_one_shared_database_has_one_key_regardless_of_which_system_asks() -> None:
    """SysErrorRecord is referenced by many systems; its cache key must not vary."""
    assert sql_cache_store.cache_key("vmsystest07", "SysErrorRecord") == sql_cache_store.cache_key(
        "VMSYSTEST07.topmost.com.tw\\pdcs", "SysErrorRecord"
    )


def test_same_database_name_on_two_servers_gets_two_keys() -> None:
    assert sql_cache_store.cache_key("vmsystest07", "PUR") != sql_cache_store.cache_key(
        "vmsystest08", "PUR"
    )


def test_cache_key_rejects_an_unknown_server() -> None:
    try:
        sql_cache_store.cache_key("", "PUR")
    except ValueError:
        return
    raise AssertionError("cache_key() must refuse to build a key without a server")


def test_cache_key_rejects_an_unknown_database() -> None:
    try:
        sql_cache_store.cache_key("vmsystest07", "")
    except ValueError:
        return
    raise AssertionError("cache_key() must refuse to build a key without a database")


# ------------------------------------------------------- catalog membership


def test_a_database_is_cataloged_exactly_when_its_cache_file_exists() -> None:
    with _CacheRoot() as cache_root:
        assert sql_cache_store.has_cache("SysErrorRecord", "dbo", server="vmsystest07") is False

        _write_legacy_cache(
            cache_root,
            "vmsystest07.topmost.com.tw__SysErrorRecord__dbo",
            _payload("SysErrorRecord"),
        )

        assert sql_cache_store.has_cache("SysErrorRecord", "dbo", server="vmsystest07") is True


def test_a_cache_written_for_one_server_is_not_found_under_another() -> None:
    with _CacheRoot() as cache_root:
        _write_legacy_cache(
            cache_root, "vmsystest07.topmost.com.tw__PUR__dbo", _payload("PUR")
        )

        assert sql_cache_store.load_cached("PUR", "dbo", server="vmsystest08") is None


def test_a_caller_without_a_server_resolves_the_only_cache_for_that_database() -> None:
    with _CacheRoot() as cache_root:
        _write_legacy_cache(
            cache_root, "vmsystest07.topmost.com.tw__PUR__dbo", _payload("PUR")
        )

        cached = sql_cache_store.load_cached("PUR", "dbo")

        assert cached is not None
        assert cached["database"] == "PUR"


def test_a_caller_without_a_server_refuses_an_ambiguous_database_name() -> None:
    with _CacheRoot() as cache_root:
        _write_legacy_cache(
            cache_root, "vmsystest07.topmost.com.tw__PUR__dbo", _payload("PUR")
        )
        _write_legacy_cache(
            cache_root, "vmsystest08.topmost.com.tw__PUR__dbo", _payload("PUR")
        )

        assert sql_cache_store.load_cached("PUR", "dbo") is None


def test_a_system_id_is_not_a_cache_key() -> None:
    """Y-Docs_TTPUR is a system_id; the cached database is named PUR."""
    with _CacheRoot() as cache_root:
        _write_legacy_cache(
            cache_root, "vmsystest07.topmost.com.tw__PUR__dbo", _payload("PUR")
        )

        assert sql_cache_store.load_cached("Y-Docs_TTPUR", "dbo", server="vmsystest07") is None


# ---------------------------------------------------------------- migration


def test_migration_renames_a_legacy_cache_file_to_the_new_key() -> None:
    with _CacheRoot() as cache_root:
        _write_legacy_cache(cache_root, "STC__dbo", _payload("STC"))

        migrate_cache_keys(cache_root, [("STC__dbo", "vmsystest07", "STC", "dbo")])

        assert (cache_root / "vmsystest07.topmost.com.tw__STC__dbo.json").exists()
        assert (cache_root / "vmsystest07.topmost.com.tw__STC__dbo.meta.json").exists()
        assert not (cache_root / "STC__dbo.json").exists()
        assert not (cache_root / "STC__dbo.meta.json").exists()


def test_a_migrated_cache_reads_back_identically_under_its_new_name() -> None:
    """Smoke test: rename only — the parsed payload must not change."""
    with _CacheRoot() as cache_root:
        before = _payload("STC")
        _write_legacy_cache(cache_root, "STC__dbo", before)

        migrate_cache_keys(cache_root, [("STC__dbo", "vmsystest07", "STC", "dbo")])

        after = sql_cache_store.load_cached("STC", "dbo", server="vmsystest07")
        assert after == before


def test_migration_corrects_a_payload_whose_identity_was_a_system_id() -> None:
    """Y-Docs_TTPUR__dbo holds database PUR; only the identity fields may change."""
    with _CacheRoot() as cache_root:
        before = _payload("Y-Docs_TTPUR")
        _write_legacy_cache(cache_root, "Y-Docs_TTPUR__dbo", before)

        migrate_cache_keys(cache_root, [("Y-Docs_TTPUR__dbo", "vmsystest07", "PUR", "dbo")])

        after = sql_cache_store.load_cached("PUR", "dbo", server="vmsystest07")
        assert after is not None
        assert after["database"] == "PUR"
        assert after["sql_execution_graph"]["database"] == "PUR"
        expected = dict(before)
        expected["database"] = "PUR"
        expected["sql_execution_graph"] = dict(before["sql_execution_graph"], database="PUR")
        assert after == expected


def test_migration_does_not_rescan_the_procedure_definitions() -> None:
    with _CacheRoot() as cache_root:
        before = _payload("Y-Docs_TTPUR")
        _write_legacy_cache(cache_root, "Y-Docs_TTPUR__dbo", before)

        migrate_cache_keys(cache_root, [("Y-Docs_TTPUR__dbo", "vmsystest07", "PUR", "dbo")])

        after = json.loads(
            (cache_root / "vmsystest07.topmost.com.tw__PUR__dbo.json").read_text(encoding="utf-8")
        )
        assert after["procedures"] == before["procedures"]


def test_migration_touches_only_the_identity_bytes() -> None:
    """No re-scan means no rewrite: even the line endings must survive."""
    with _CacheRoot() as cache_root:
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

        migrate_cache_keys(cache_root, [("Y-Docs_TTPUR__dbo", "vmsystest07", "PUR", "dbo")])

        after = (cache_root / "vmsystest07.topmost.com.tw__PUR__dbo.json").read_bytes()
        assert after == raw.replace(b'"database": "Y-Docs_TTPUR"', b'"database": "PUR"')


def test_migration_is_idempotent() -> None:
    with _CacheRoot() as cache_root:
        _write_legacy_cache(cache_root, "STC__dbo", _payload("STC"))
        scopes = [("STC__dbo", "vmsystest07", "STC", "dbo")]

        first = migrate_cache_keys(cache_root, scopes)
        second = migrate_cache_keys(cache_root, scopes)

        assert [entry["action"] for entry in first] == ["migrated"]
        assert [entry["action"] for entry in second] == ["missing"]
        assert sql_cache_store.load_cached("STC", "dbo", server="vmsystest07") is not None


def test_migration_dry_run_changes_nothing() -> None:
    with _CacheRoot() as cache_root:
        _write_legacy_cache(cache_root, "STC__dbo", _payload("STC"))

        migrate_cache_keys(cache_root, [("STC__dbo", "vmsystest07", "STC", "dbo")], dry_run=True)

        assert (cache_root / "STC__dbo.json").exists()
        assert not (cache_root / "vmsystest07.topmost.com.tw__STC__dbo.json").exists()


def test_the_shipped_migration_scopes_cover_both_existing_cache_files() -> None:
    assert LEGACY_CACHE_SCOPES == [
        ("STC__dbo", "vmsystest07", "STC", "dbo"),
        ("Y-Docs_TTPUR__dbo", "vmsystest07", "PUR", "dbo"),
    ]
