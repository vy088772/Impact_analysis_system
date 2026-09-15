"""Ticket 02: AzureDevOpsFetcher delegates every git operation to the
clone synchroniser, keeping only URL construction and PAT masking.

See .scratch/refresh-resets-the-clone-to-the-remote/issues/
02-synchroniser-replaces-pull-with-fetch-reset-clean.md
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from code_analyzer.azure_fetcher import AzureDevOpsFetcher, AzureFetchError
from code_analyzer.clone_synchroniser import SynchroniseError, SynchroniseResult


class _FakeSynchroniser:
    """假同步器的共用底子：只認得 .git 是否存在，跟真正的
    CloneSynchroniser.is_cloned() 判斷方式一致。各假同步器只需各自定義
    synchronise() 要回傳或拋出什麼。"""

    @staticmethod
    def is_cloned(target):
        return (Path(target) / ".git").exists()


class _RecordingSynchroniser(_FakeSynchroniser):
    def __init__(self):
        self.calls = []

    def synchronise(self, target, remote_url, branch):
        self.calls.append((Path(target), remote_url, branch))
        return SynchroniseResult.SYNCHRONISED


class _FailingSynchroniser(_FakeSynchroniser):
    def __init__(self, message):
        self._message = message

    def synchronise(self, target, remote_url, branch):
        raise SynchroniseError(self._message)


class _BusySynchroniser(_FakeSynchroniser):
    """模擬目錄的鎖被另一次 refresh 握著：synchronise() 不拋例外，
    回傳 SynchroniseResult.BUSY，且完全沒有改動 target。"""

    def synchronise(self, target, remote_url, branch):
        return SynchroniseResult.BUSY


def _fetcher(tmp_path, synchroniser):
    return AzureDevOpsFetcher(
        org="myorg",
        project="MyProject",
        repo="MyRepo",
        pat="s3cr3t-pat",
        branch="main",
        clone_dir=str(tmp_path / "clone"),
        synchroniser=synchroniser,
    )


def test_fetch_delegates_the_authenticated_url_and_branch_to_the_synchroniser(tmp_path):
    synchroniser = _RecordingSynchroniser()
    fetcher = _fetcher(tmp_path, synchroniser)

    target = fetcher.fetch()

    assert len(synchroniser.calls) == 1
    called_target, remote_url, branch = synchroniser.calls[0]
    assert called_target == target
    assert branch == "main"
    assert "s3cr3t-pat" in remote_url
    assert remote_url.startswith("https://:")


def test_fetch_masks_the_pat_in_a_synchronise_failure(tmp_path):
    leaking_message = "git 操作失敗（exit 1）\nfatal: https://:s3cr3t-pat@dev.azure.com/x not found"
    fetcher = _fetcher(tmp_path, _FailingSynchroniser(leaking_message))

    with pytest.raises(AzureFetchError) as exc_info:
        fetcher.fetch()

    assert "s3cr3t-pat" not in str(exc_info.value)
    assert "https://***@dev.azure.com" in str(exc_info.value)


def test_fetch_raises_when_the_synchroniser_reports_busy(tmp_path):
    """User Story 10: the operator sees that the mirror is busy, not a false
    success. AzureDevOpsFetcher.fetch() must read the SynchroniseResult and
    refuse to claim completion on BUSY."""
    fetcher = _fetcher(tmp_path, _BusySynchroniser())

    with pytest.raises(AzureFetchError, match="忙碌"):
        fetcher.fetch()


def test_fetch_with_update_false_on_an_existing_clone_does_not_call_the_synchroniser(tmp_path):
    clone_dir = tmp_path / "clone"
    clone_dir.mkdir()
    (clone_dir / ".git").mkdir()

    synchroniser = _RecordingSynchroniser()
    fetcher = AzureDevOpsFetcher(
        org="myorg", project="MyProject", repo="MyRepo", pat="s3cr3t-pat",
        branch="main", clone_dir=str(clone_dir), synchroniser=synchroniser,
    )

    fetcher.fetch(update=False)

    assert synchroniser.calls == []
