"""Issue #9 of `TCCDIV1/AI_LlamaIndex`: the `behind_source` check of one system.

The seam is the Impact HTTP API (`POST /cache_freshness/check` with a `system_id`, and
`GET /cache_freshness`), through the FastAPI test client. A fake remote replaces `git ls-remote`
and a fake reader replaces the one Fingerprint reader, as in the other `behind_source` tests.
"""

from __future__ import annotations

from tests.test_behind_source_api import record_commit, remote, row_of  # noqa: F401  (fixtures and helpers)
from tests.test_cache_freshness_api import (  # noqa: F401  (fixtures and helpers)
    build_scan,
    client,
    fresh_queue,
    sql_root,
    world,
    write_sql,
)
from tests.test_sql_behind_source_api import EVENING, procedures, reader  # noqa: F401

from service import environment_check


def check(system_id: str | None = None) -> dict:
    body = {"system_id": system_id} if system_id else {}
    response = client.post("/cache_freshness/check", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def checked_at(body: dict) -> dict[str, str | None]:
    return {system["system_id"]: system["source_checked_at"] for system in body["systems"]}


def test_a_system_check_reads_only_the_repository_and_the_sql_caches_of_that_system(
    world, sql_root, remote, reader
) -> None:
    write_sql(sql_root, "AlphaDb", fingerprint=procedures(3))
    write_sql(sql_root, "SharedDb", fingerprint=procedures(3))

    check("Beta")

    assert remote.calls == ["BetaRepo"]
    assert [identity.database for identity, _ in reader.calls] == ["SharedDb"]


def test_a_check_with_no_system_reads_every_system(world, sql_root, remote, reader) -> None:
    write_sql(sql_root, "AlphaDb", fingerprint=procedures(3))
    write_sql(sql_root, "SharedDb", fingerprint=procedures(3))

    check()

    assert sorted(remote.calls) == ["AlphaRepo", "BetaRepo"]
    assert sorted(identity.database for identity, _ in reader.calls) == ["AlphaDb", "SharedDb"]


def test_a_system_check_keeps_the_results_of_the_other_systems(world, sql_root, remote, reader) -> None:
    build_scan("AlphaRepo")
    build_scan("BetaRepo")
    record_commit("AlphaRepo", "aaa")
    record_commit("BetaRepo", "bbb")
    write_sql(sql_root, "AlphaDb", fingerprint=procedures(3))
    remote.heads = {"AlphaRepo": "new", "BetaRepo": "new"}
    reader.current = {"AlphaDb": procedures(4, EVENING)}
    check()

    # The Database and the remote of Alpha go silent: only a check of Alpha could forget them.
    remote.heads = {"BetaRepo": "bbb"}
    reader.current = {}
    body = check("Beta")

    assert row_of(body, "Beta", "Beta")["freshness"] == "current"
    assert row_of(body, "Alpha", "Alpha")["freshness"] == "behind_source"
    assert row_of(body, "Alpha", "AlphaDb")["freshness"] == "behind_source"


def test_a_system_check_replaces_the_results_of_the_sources_that_it_read(
    world, sql_root, remote, reader
) -> None:
    build_scan("AlphaRepo")
    record_commit("AlphaRepo", "aaa")
    remote.heads = {"AlphaRepo": "new"}
    assert row_of(check(), "Alpha", "Alpha")["freshness"] == "behind_source"

    remote.heads = {}

    assert row_of(check("Alpha"), "Alpha", "Alpha")["freshness"] == "current"


def test_each_system_has_its_own_check_time(world, remote, reader) -> None:
    assert set(checked_at(client.get("/cache_freshness").json()).values()) == {None}

    body = check("Beta")

    times = checked_at(body)
    assert times["Beta"]
    assert times["Alpha"] is None
    assert times["NoCode"] is None
    assert checked_at(client.get("/cache_freshness").json()) == times


def test_a_full_check_sets_the_time_of_every_system(world, remote, reader) -> None:
    times = checked_at(check())

    assert all(times.values())
    assert set(times) == {"Alpha", "Beta", "NoCode"}


def test_a_shared_sql_cache_shows_the_new_result_under_every_system_and_only_the_checked_time_changes(
    world, sql_root, remote, reader
) -> None:
    write_sql(sql_root, "SharedDb", fingerprint=procedures(3))
    reader.current = {"SharedDb": procedures(4, EVENING)}

    body = check("Beta")

    assert row_of(body, "Beta", "SharedDb")["freshness"] == "behind_source"
    assert row_of(body, "Alpha", "SharedDb")["freshness"] == "behind_source"
    assert checked_at(body)["Alpha"] is None


def test_a_locked_row_stays_out_of_a_system_check(world, sql_root, remote, reader, monkeypatch) -> None:
    write_sql(sql_root, "AlphaDb", fingerprint=procedures(3))
    monkeypatch.setattr(environment_check, "sql_lock_reason", lambda server: "登入失敗")
    monkeypatch.setattr(environment_check, "csharp_lock_reason", lambda source: "無法連線" if source else "")

    check("Alpha")

    assert remote.calls == []
    assert reader.calls == []


def test_an_unknown_system_gets_404(world, remote, reader) -> None:
    response = client.post("/cache_freshness/check", json={"system_id": "Gamma"})

    assert response.status_code == 404
    assert remote.calls == []
