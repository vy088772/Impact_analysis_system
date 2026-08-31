"""Ticket 03 behavior checks: backfilling an Object Location Index for caches
already on disk, without reconnecting to SQL Server."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from service import sql_cache_store
from service.sql_cache_store import CacheIdentity
from service.sql_execution_graph import GRAPH_VERSION
from tests.sql_cache_fixtures import CacheRoot, write_cache
from tools.backfill_object_location_indexes import backfill_all_caches, backfill_cache_row


def _payload(database: str) -> dict:
    return {
        "database": database,
        "schema": "dbo",
        "procedures": [{"name": "spAddRecordError", "definition": "CREATE PROCEDURE x AS SELECT 1"}],
        "views": [],
        "functions": [],
        "tables": [{"name": "RecordError", "columns": []}],
        "sql_execution_graph": {
            "graph_version": GRAPH_VERSION,
            "database": database,
            "nodes": [],
            "relationships": [],
            "parse_errors": [],
        },
    }


def test_backfill_writes_an_index_for_a_cache_that_never_had_one() -> None:
    with CacheRoot() as cache_root:
        identity = CacheIdentity.of("vmsystest07", "PUR", "dbo")
        write_cache(cache_root, identity.key, _payload("PUR"))
        assert not (cache_root / identity.index_filename).exists()

        results = backfill_all_caches()

        assert [entry["action"] for entry in results] == ["indexed"]
        loaded = sql_cache_store.load_object_location_index(identity)
        assert loaded is not None
        assert loaded.stored_procedures == {"spaddrecorderror"}
        assert loaded.tables == {"recorderror"}


def test_backfill_index_matches_the_shared_build_function_exactly() -> None:
    """No second way to build an index: the backfilled index must equal build_object_location_index()'s own output."""
    with CacheRoot() as cache_root:
        identity = CacheIdentity.of("vmsystest07", "PUR", "dbo")
        payload = _payload("PUR")
        write_cache(cache_root, identity.key, payload)

        backfill_all_caches()

        expected = sql_cache_store.build_object_location_index(identity, payload)
        loaded = sql_cache_store.load_object_location_index(identity)
        assert loaded == expected


def test_backfill_never_opens_a_sql_server_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    import pyodbc

    def _fail_connect(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("backfill must never open a SQL Server connection")

    monkeypatch.setattr(pyodbc, "connect", _fail_connect)

    with CacheRoot() as cache_root:
        identity = CacheIdentity.of("vmsystest07", "PUR", "dbo")
        write_cache(cache_root, identity.key, _payload("PUR"))

        results = backfill_all_caches()

        assert [entry["action"] for entry in results] == ["indexed"]


def test_backfill_does_not_modify_the_cache_content() -> None:
    with CacheRoot() as cache_root:
        identity = CacheIdentity.of("vmsystest07", "PUR", "dbo")
        write_cache(cache_root, identity.key, _payload("PUR"))
        data_path = cache_root / identity.filename
        raw_before = data_path.read_bytes()

        backfill_all_caches()

        assert data_path.read_bytes() == raw_before


def test_backfill_reports_indexed_and_skipped_caches_separately() -> None:
    with CacheRoot() as cache_root:
        good = CacheIdentity.of("vmsystest07", "PUR", "dbo")
        write_cache(cache_root, good.key, _payload("PUR"))

        stale = CacheIdentity.of("vmsystest07", "ETON", "dbo")
        write_cache(
            cache_root,
            stale.key,
            _payload("ETON"),
            cache_version=sql_cache_store._SQL_CACHE_VERSION - 1,
        )

        results = backfill_all_caches()

        by_database = {entry["database"]: entry["action"] for entry in results}
        assert by_database == {"PUR": "indexed", "ETON": "invalid_cache"}


def test_backfill_dry_run_writes_no_index_file() -> None:
    with CacheRoot() as cache_root:
        identity = CacheIdentity.of("vmsystest07", "PUR", "dbo")
        write_cache(cache_root, identity.key, _payload("PUR"))

        results = backfill_all_caches(dry_run=True)

        assert [entry["action"] for entry in results] == ["would_index"]
        assert not (cache_root / identity.index_filename).exists()


def test_rerunning_backfill_rebuilds_the_index() -> None:
    """Re-running is safe and rebuilds — there is no "already up to date" skip for the index itself."""
    with CacheRoot() as cache_root:
        identity = CacheIdentity.of("vmsystest07", "PUR", "dbo")
        write_cache(cache_root, identity.key, _payload("PUR"))

        first = backfill_all_caches()
        second = backfill_all_caches()

        assert [entry["action"] for entry in first] == ["indexed"]
        assert [entry["action"] for entry in second] == ["indexed"]


def test_deleting_a_backfilled_index_by_hand_falls_back_to_reading_the_cache_in_full() -> None:
    with CacheRoot() as cache_root:
        identity = CacheIdentity.of("vmsystest07", "PUR", "dbo")
        write_cache(cache_root, identity.key, _payload("PUR"))
        backfill_all_caches()
        assert sql_cache_store.load_object_location_index(identity) is not None

        (cache_root / identity.index_filename).unlink()

        assert sql_cache_store.load_object_location_index(identity) is None
        # The cache itself is untouched by the index having existed and then been removed.
        assert sql_cache_store.load_cached("PUR", "dbo", server="vmsystest07") is not None


def test_backfill_cache_row_skips_a_row_whose_identity_cannot_be_constructed() -> None:
    with CacheRoot():
        row = sql_cache_store.ScanRecordListing(
            server="", database="", schema="dbo", scanned_at=None
        )

        entry = backfill_cache_row(row)

        assert entry["action"] == "bad_identity"
