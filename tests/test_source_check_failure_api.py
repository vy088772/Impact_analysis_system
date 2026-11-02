"""Issue #10 of `TCCDIV1/AI_LlamaIndex`: a row tells when the source check could not read its source.

The seam is the Impact HTTP API (`POST /cache_freshness/check` and `GET /cache_freshness`),
through the FastAPI test client. A fake remote replaces `git ls-remote` and a fake reader replaces
the one Fingerprint reader, as in the other `behind_source` tests.
"""

from __future__ import annotations

from tests.test_behind_source_api import check, record_commit, remote, row_of  # noqa: F401  (fixtures and helpers)
from tests.test_cache_freshness_api import (  # noqa: F401  (fixtures and helpers)
    build_scan,
    client,
    fresh_queue,
    sql_root,
    world,
    write_sql,
)
from tests.test_sql_behind_source_api import procedures, reader  # noqa: F401

from service import environment_check


def test_a_failed_ls_remote_gives_the_row_a_failure_with_its_reason(world, remote) -> None:
    build_scan("AlphaRepo")
    remote.failures = {"AlphaRepo": "Azure Repos 在 30 秒內沒有回應"}

    row = row_of(check(), "Alpha", "Alpha")

    assert row["source_check_failure"] == "Azure Repos 在 30 秒內沒有回應"


def test_a_failed_fingerprint_read_gives_the_row_a_failure_with_its_reason(world, sql_root, reader) -> None:
    write_sql(sql_root, "AlphaDb", fingerprint=procedures(3))
    reader.failures = {"AlphaDb": "SQL Server 拒絕這個登入帳號"}

    row = row_of(check(), "Alpha", "AlphaDb")

    assert row["source_check_failure"] == "SQL Server 拒絕這個登入帳號"


def test_a_later_successful_read_clears_the_failure(world, sql_root, remote, reader) -> None:
    build_scan("AlphaRepo")
    record_commit("AlphaRepo", "aaa")
    write_sql(sql_root, "AlphaDb", fingerprint=procedures(3))
    check()

    remote.heads = {"AlphaRepo": "aaa"}
    reader.current = {"AlphaDb": procedures(3)}
    body = check()

    assert row_of(body, "Alpha", "Alpha")["source_check_failure"] == ""
    assert row_of(body, "Alpha", "AlphaDb")["source_check_failure"] == ""
    assert row_of(client.get("/cache_freshness").json(), "Alpha", "Alpha")["source_check_failure"] == ""


def test_a_failure_does_not_change_the_cache_freshness_of_the_row(world, sql_root, remote, reader) -> None:
    build_scan("AlphaRepo")
    record_commit("AlphaRepo", "aaa")
    write_sql(sql_root, "AlphaDb", fingerprint=procedures(3))
    remote.heads = {"AlphaRepo": "new"}
    reader.current = {"AlphaDb": procedures(4)}
    body = check()
    assert row_of(body, "Alpha", "Alpha")["freshness"] == "behind_source"

    remote.heads, reader.current = {}, {}
    body = check()

    # The check forgets the old answer, as before this issue: the row is current, with a failure.
    for label in ("Alpha", "AlphaDb"):
        row = row_of(body, "Alpha", label)
        assert row["freshness"] == "current"
        assert row["source_check_failure"]


def test_a_row_with_no_check_has_no_failure(world, sql_root, remote, reader) -> None:
    build_scan("AlphaRepo")
    write_sql(sql_root, "AlphaDb", fingerprint=procedures(3))

    body = client.get("/cache_freshness").json()

    assert row_of(body, "Alpha", "Alpha")["source_check_failure"] == ""
    assert row_of(body, "Alpha", "AlphaDb")["source_check_failure"] == ""


def test_a_locked_row_gets_no_failure(world, sql_root, remote, reader, monkeypatch) -> None:
    build_scan("AlphaRepo")
    write_sql(sql_root, "AlphaDb", fingerprint=procedures(3))
    check()

    # The lock arrives after the check: its Lock Reason explains the row, not the failure.
    monkeypatch.setattr(environment_check, "sql_lock_reason", lambda server: "登入失敗")
    monkeypatch.setattr(environment_check, "csharp_lock_reason", lambda source: "無法連線" if source else "")
    body = client.get("/cache_freshness").json()

    assert row_of(body, "Alpha", "Alpha")["source_check_failure"] == ""
    assert row_of(body, "Alpha", "AlphaDb")["source_check_failure"] == ""
