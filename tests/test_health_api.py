"""Issue TCCDIV1/AI_LlamaIndex#17: `GET /health` reports the Impact Code Time.

The Impact Code Time is the newest modification time of the Python files in the
service package. The Impact service records it one time, when it starts. The web
and the launcher compare it with the same time on the disk.

The seams are the Impact HTTP API (the FastAPI test client) and the calculation
function `impact_code_time()` (a temporary directory as the Impact code). The tests
set file times in local time, so they need no time zone setting.
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from service import api, code_time
from service.code_time import impact_code_time

ISO_SECONDS_WITH_OFFSET = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$")

client = TestClient(api.app)


def _touch(path: Path, local_time: str) -> Path:
    """Write an empty file and set its modification time (`local_time` has no offset)."""
    path.write_text("", encoding="utf-8")
    stamp = datetime.fromisoformat(local_time).timestamp()
    os.utime(path, (stamp, stamp))
    return path


def test_health_keeps_status_ok_and_adds_code_time():
    body = client.get("/health").json()

    assert body["status"] == "ok"
    assert ISO_SECONDS_WITH_OFFSET.match(body["code_time"])


def test_code_time_is_the_newest_python_file_time_in_the_package(tmp_path):
    (tmp_path / "sub").mkdir()
    _touch(tmp_path / "api.py", "2026-11-02T10:20:00")
    _touch(tmp_path / "sub" / "queue.py", "2026-11-02T15:09:07")
    _touch(tmp_path / "notes.txt", "2026-11-02T16:44:00")

    result = impact_code_time(tmp_path)

    assert result.startswith("2026-11-02T15:09:07")
    assert ISO_SECONDS_WITH_OFFSET.match(result)


def test_code_time_cuts_the_fraction_of_a_second(tmp_path):
    _touch(tmp_path / "api.py", "2026-11-02T15:09:07.900")

    assert impact_code_time(tmp_path).startswith("2026-11-02T15:09:07")


def test_code_time_stays_the_start_value_after_a_file_changes_on_the_disk(tmp_path, monkeypatch):
    first = client.get("/health").json()["code_time"]
    _touch(tmp_path / "api.py", "2099-01-01T00:00:00")
    monkeypatch.setattr(code_time, "SERVICE_PACKAGE_DIR", tmp_path)
    assert impact_code_time() != first  # the service package on the disk now has newer code

    second = client.get("/health").json()["code_time"]
    third = client.get("/health").json()["code_time"]

    assert second == first
    assert third == first


def test_code_time_is_none_when_the_package_has_no_python_file(tmp_path):
    # The same rule as the web: no Python file means no Impact Code Time, not an error.
    _touch(tmp_path / "notes.txt", "2026-11-02T16:44:00")

    assert impact_code_time(tmp_path) is None
