"""Ticket 02 of `.scratch/sql-cache-behind-source/`: the check marks a changed SQL cache `behind_source`.

The seam is the Impact HTTP API (`GET /cache_freshness`, `POST /cache_freshness/check`,
`POST /refresh_jobs/update_all`), through the FastAPI test client. A fake reader replaces the
one Fingerprint reader, as the `behind_source` API tests replace the remote head reader.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

import pytest

import code_analyzer.sql_analyzer as sql_analyzer_module
from code_analyzer.sql_fingerprint import Fingerprint
from service import analyze_service, environment_check, source_check, sql_cache_store
from service.sql_cache_store import CacheIdentity, ScanConnection
from tests.sql_cache_fixtures import CACHE_VERSION, cache_payload, fingerprint, write_cache
from tests.test_behind_source_api import check, checked_at, remote, row_of  # noqa: F401  (fixtures and helpers)
from tests.test_cache_freshness_api import (  # noqa: F401  (fixtures and helpers)
    SERVER,
    GatedRebuild,
    client,
    fresh_queue,
    listing,
    sql_payload,
    sql_root,
    submit_sql,
    wait_for,
    world,
    write_sql,
)

MORNING = datetime(2026, 10, 1, 9, 0, 0)
EVENING = datetime(2026, 10, 30, 18, 0, 0)


def procedures(count: int, latest_modified: datetime = MORNING) -> Fingerprint:
    return fingerprint(procedures=(count, latest_modified))


class FakeReader:
    """Stands in for the one Fingerprint reader: the current Fingerprint of each Database."""

    def __init__(self) -> None:
        self.current: dict[str, Optional[Fingerprint]] = {}
        self.calls: list[tuple[CacheIdentity, ScanConnection]] = []

    def __call__(self, identity: CacheIdentity, connection: ScanConnection) -> Optional[Fingerprint]:
        self.calls.append((identity, connection))
        return self.current.get(identity.database)


@pytest.fixture
def reader(monkeypatch, remote):
    fake = FakeReader()
    monkeypatch.setattr(sql_cache_store, "read_fingerprint", fake)
    monkeypatch.setattr(source_check, "_fingerprints", {})
    return fake


def test_a_sql_cache_whose_fingerprint_changed_lists_as_behind_source(world, sql_root, reader) -> None:
    write_sql(sql_root, "AlphaDb", fingerprint=procedures(3))
    reader.current = {"AlphaDb": procedures(3, EVENING)}

    row = row_of(check(), "Alpha", "AlphaDb")

    assert row["freshness"] == "behind_source"
    assert row["last_scanned_at"]


def test_a_different_count_with_the_same_time_lists_as_behind_source(world, sql_root, reader) -> None:
    write_sql(sql_root, "AlphaDb", fingerprint=procedures(3))
    # Someone dropped a procedure: the count falls, and the latest time stays.
    reader.current = {"AlphaDb": procedures(2)}

    assert row_of(check(), "Alpha", "AlphaDb")["freshness"] == "behind_source"


def test_an_equal_fingerprint_lists_as_current(world, sql_root, reader) -> None:
    write_sql(sql_root, "AlphaDb", fingerprint=procedures(3))
    reader.current = {"AlphaDb": procedures(3)}

    assert row_of(check(), "Alpha", "AlphaDb")["freshness"] == "current"


def test_the_check_reads_a_shared_sql_cache_one_time_and_each_system_shows_its_state(
    world, sql_root, reader
) -> None:
    write_sql(sql_root, "SharedDb", fingerprint=procedures(3))
    reader.current = {"SharedDb": procedures(4, EVENING)}

    body = check()

    assert [identity.database for identity, _ in reader.calls] == ["SharedDb"]
    assert row_of(body, "Alpha", "SharedDb")["freshness"] == "behind_source"
    assert row_of(body, "Beta", "SharedDb")["freshness"] == "behind_source"


def test_the_check_reads_only_usable_sql_caches(world, sql_root, reader) -> None:
    write_sql(sql_root, "AlphaDb", fingerprint=procedures(3))
    write_sql(sql_root, "SharedDb", fingerprint=procedures(3), cache_version=CACHE_VERSION - 1)

    check()

    assert [identity.database for identity, _ in reader.calls] == ["AlphaDb"]


def test_one_check_asks_the_remote_and_reads_the_fingerprint_and_keeps_one_time_for_each_system(
    world, sql_root, reader, remote
) -> None:
    write_sql(sql_root, "AlphaDb", fingerprint=procedures(3))
    assert checked_at(client.get("/cache_freshness").json(), "Alpha") is None

    body = check()

    assert remote.calls and reader.calls
    assert checked_at(body, "Alpha")
    assert checked_at(client.get("/cache_freshness").json(), "Alpha") == checked_at(body, "Alpha")


def test_check_again_reads_the_fingerprint_again_and_forgets_the_previous_answer(
    world, sql_root, reader
) -> None:
    write_sql(sql_root, "AlphaDb", fingerprint=procedures(3))
    reader.current = {"AlphaDb": procedures(4, EVENING)}
    assert row_of(check(), "Alpha", "AlphaDb")["freshness"] == "behind_source"

    # The server is now unreachable: the check keeps no Fingerprint for it.
    reader.current = {}

    assert row_of(check(), "Alpha", "AlphaDb")["freshness"] == "current"


def test_a_plain_listing_never_reads_the_fingerprint_and_shows_no_behind_source(
    world, sql_root, reader
) -> None:
    write_sql(sql_root, "AlphaDb", fingerprint=procedures(3))
    reader.current = {"AlphaDb": procedures(4, EVENING)}

    assert listing()["Alpha"]["AlphaDb"]["freshness"] == "current"
    assert reader.calls == []


def test_a_reader_failure_gives_no_behind_source(world, sql_root, reader) -> None:
    write_sql(sql_root, "AlphaDb", fingerprint=procedures(3))
    reader.current = {"AlphaDb": None}

    assert row_of(check(), "Alpha", "AlphaDb")["freshness"] == "current"


def test_a_locked_row_gets_no_read_and_no_behind_source(world, sql_root, reader, monkeypatch) -> None:
    write_sql(sql_root, "AlphaDb", fingerprint=procedures(3))
    reader.current = {"AlphaDb": procedures(4, EVENING)}
    monkeypatch.setattr(
        environment_check,
        "_last",
        environment_check.LastCheck(locks={"sql_server": {SERVER: "無法登入 SQL Server"}}),
    )

    row = row_of(check(), "Alpha", "AlphaDb")

    assert row["freshness"] == "current"
    assert row["locked_reason"]
    assert reader.calls == []


def test_a_row_that_a_later_environment_check_locks_shows_no_behind_source(
    world, sql_root, reader, monkeypatch
) -> None:
    write_sql(sql_root, "AlphaDb", fingerprint=procedures(3))
    reader.current = {"AlphaDb": procedures(4, EVENING)}
    assert row_of(check(), "Alpha", "AlphaDb")["freshness"] == "behind_source"

    monkeypatch.setattr(
        environment_check,
        "_last",
        environment_check.LastCheck(locks={"sql_server": {SERVER: "無法登入 SQL Server"}}),
    )

    assert listing()["Alpha"]["AlphaDb"]["freshness"] == "current"


def test_no_recorded_fingerprint_gives_no_behind_source(world, sql_root, reader) -> None:
    write_sql(sql_root, "AlphaDb", fingerprint=None)
    reader.current = {"AlphaDb": procedures(4, EVENING)}

    assert row_of(check(), "Alpha", "AlphaDb")["freshness"] == "current"


def test_outdated_wins_over_behind_source(world, sql_root, reader) -> None:
    write_sql(sql_root, "AlphaDb", fingerprint=procedures(3))
    reader.current = {"AlphaDb": procedures(4, EVENING)}
    check()

    meta = sql_root / CacheIdentity.of(SERVER, "AlphaDb").meta_filename
    record = json.loads(meta.read_text(encoding="utf-8"))
    record["cache_version"] = CACHE_VERSION - 1
    meta.write_text(json.dumps(record), encoding="utf-8")
    sql_cache_store._mem_cache.clear()

    assert listing()["Alpha"]["AlphaDb"]["freshness"] == "outdated"


def test_refreshing_wins_over_behind_source(world, sql_root, reader, monkeypatch) -> None:
    write_sql(sql_root, "AlphaDb", fingerprint=procedures(3))
    reader.current = {"AlphaDb": procedures(4, EVENING)}
    assert row_of(check(), "Alpha", "AlphaDb")["freshness"] == "behind_source"
    fake = GatedRebuild()
    monkeypatch.setattr(analyze_service, "refresh_sql_source", fake.sql)
    job = submit_sql("AlphaDb")
    wait_for(job["job_id"], "running")

    assert listing()["Alpha"]["AlphaDb"]["freshness"] == "refreshing"

    fake.gate("AlphaDb").set()
    wait_for(job["job_id"], "succeeded")


@pytest.fixture
def analyzer(monkeypatch):
    """A fake SQL connection for a real scan: its dump returns a valid payload."""

    class FakeAnalyzer:
        def __init__(self, database_alias=None, server=None, database_name=None, **_kwargs):
            self.database = database_name

        def connect(self) -> bool:
            return True

        def disconnect(self) -> None:
            pass

        def dump_all_sql_objects(self, progress_callback=None) -> dict:
            return cache_payload(self.database)

    monkeypatch.setattr(sql_analyzer_module, "SQLAnalyzer", FakeAnalyzer)
    return FakeAnalyzer


def test_a_finished_refresh_clears_behind_source_with_no_second_check(
    world, sql_root, reader, analyzer
) -> None:
    write_sql(sql_root, "AlphaDb", fingerprint=procedures(3))
    reader.current = {"AlphaDb": procedures(4, EVENING)}
    assert row_of(check(), "Alpha", "AlphaDb")["freshness"] == "behind_source"
    wait_for(submit_sql("AlphaDb")["job_id"], "succeeded")
    reader.calls.clear()

    assert listing()["Alpha"]["AlphaDb"]["freshness"] == "current"
    assert reader.calls == []


def test_update_all_leaves_a_behind_source_sql_cache_out(world, sql_root, reader, monkeypatch) -> None:
    write_sql(sql_root, "AlphaDb", fingerprint=procedures(3))
    reader.current = {"AlphaDb": procedures(4, EVENING)}
    assert row_of(check(), "Alpha", "AlphaDb")["freshness"] == "behind_source"
    monkeypatch.setattr(analyze_service, "refresh_source", lambda source, **_kw: {})
    monkeypatch.setattr(analyze_service, "refresh_sql_source", lambda **_kw: {})

    response = client.post("/refresh_jobs/update_all", json={})

    assert response.status_code == 200
    jobs = response.json()["jobs"]
    assert jobs and not any("AlphaDb" in job["key"] for job in jobs)
    for job in jobs:
        wait_for(job["job_id"], "succeeded", "failed")


def test_a_question_never_reads_the_fingerprint_and_a_behind_source_cache_never_blocks_it(
    world, sql_root, reader
) -> None:
    write_sql(sql_root, "AlphaDb", fingerprint=procedures(3))
    reader.current = {"AlphaDb": procedures(4, EVENING)}
    assert row_of(check(), "Alpha", "AlphaDb")["freshness"] == "behind_source"
    reader.calls.clear()

    response = client.post(
        "/find_by_sp",
        json={"database": "AlphaDb", "db_server": SERVER, "sp_name": "usp_Save"},
    )

    assert response.status_code == 200
    assert response.json()["unusable_caches"] == []
    assert reader.calls == []


def test_the_check_connects_to_the_catalog_address_so_a_named_instance_connects(
    world, sql_root, reader
) -> None:
    catalog = {
        "systems": [
            {
                "system_id": "Named",
                "azure": {"project": "", "repo": ""},
                "databases": [{"name": "AlphaDb", "server": "dbhost\\NAMED"}],
            }
        ]
    }
    (world / "spec_rag" / "catalog" / "system_catalog.json").write_text(json.dumps(catalog), encoding="utf-8")
    identity = CacheIdentity.of("dbhost\\NAMED", "AlphaDb")
    write_cache(sql_root, identity, sql_payload("AlphaDb"), fingerprint=procedures(3))

    check()

    assert reader.calls == [(identity, ScanConnection("dbhost\\NAMED"))]


# Ticket 03: the check uses the scan account of each server (ADR-0010).


def test_the_check_gives_the_reader_the_scan_account_of_its_server(world, sql_root, reader) -> None:
    write_sql(sql_root, "AlphaDb", fingerprint=procedures(3))

    response = client.post(
        "/cache_freshness/check",
        json={"sql_credentials": {SERVER: {"db_user_id": "scan", "db_password": "secret"}}},
    )

    assert response.status_code == 200
    assert reader.calls == [(CacheIdentity.of(SERVER, "AlphaDb"), ScanConnection(SERVER, "scan", "secret"))]


def test_a_server_with_no_override_gets_no_override(world, sql_root, reader) -> None:
    write_sql(sql_root, "AlphaDb", fingerprint=procedures(3))

    response = client.post(
        "/cache_freshness/check",
        json={"sql_credentials": {"otherhost": {"db_user_id": "scan", "db_password": "secret"}}},
    )

    assert response.status_code == 200
    assert reader.calls == [(CacheIdentity.of(SERVER, "AlphaDb"), ScanConnection(SERVER))]


def test_a_named_instance_gets_the_override_of_its_server_as_the_row_shows_it(world, sql_root, reader) -> None:
    catalog = {
        "systems": [
            {
                "system_id": "Named",
                "azure": {"project": "", "repo": ""},
                "databases": [{"name": "AlphaDb", "server": "dbhost\\NAMED"}],
            }
        ]
    }
    (world / "spec_rag" / "catalog" / "system_catalog.json").write_text(json.dumps(catalog), encoding="utf-8")
    identity = CacheIdentity.of("dbhost\\NAMED", "AlphaDb")
    write_cache(sql_root, identity, sql_payload("AlphaDb"), fingerprint=procedures(3))

    response = client.post(
        "/cache_freshness/check",
        json={"sql_credentials": {identity.server: {"db_user_id": "scan", "db_password": "secret"}}},
    )

    assert response.status_code == 200
    assert reader.calls == [(identity, ScanConnection("dbhost\\NAMED", "scan", "secret"))]
