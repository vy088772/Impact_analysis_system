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
from code_analyzer.clone_synchroniser import SynchroniseError


class _RecordingSynchroniser:
    def __init__(self):
        self.calls = []

    @staticmethod
    def is_cloned(target):
        return (Path(target) / ".git").exists()

    def synchronise(self, target, remote_url, branch):
        self.calls.append((Path(target), remote_url, branch))


class _FailingSynchroniser:
    def __init__(self, message):
        self._message = message

    @staticmethod
    def is_cloned(target):
        return (Path(target) / ".git").exists()

    def synchronise(self, target, remote_url, branch):
        raise SynchroniseError(self._message)


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
