"""Ticket 02: the clone synchroniser replaces pull with fetch + reset + clean.

Drives CloneSynchroniser directly against a local bare repository — no
network, no PAT, no organisation or project name. Asserts the state of the
target directory afterwards, never which git commands ran.

See .scratch/refresh-resets-the-clone-to-the-remote/issues/
02-synchroniser-replaces-pull-with-fetch-reset-clean.md
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from code_analyzer.clone_synchroniser import CloneSynchroniser, SynchroniseError, SynchroniseResult


def _run(cmd: list, cwd: Path = None) -> None:
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=True,
                    capture_output=True, text=True)


def _make_remote(tmp_path: Path, branch: str = "main") -> Path:
    """Create a bare repo with one commit on `branch`, return its path."""
    bare = tmp_path / "remote.git"
    _run(["git", "init", "--bare", "-q", str(bare)])

    seed = tmp_path / "seed"
    _run(["git", "init", "-q", str(seed)])
    _run(["git", "-C", str(seed), "checkout", "-q", "-b", branch])
    _run(["git", "-C", str(seed), "config", "user.email", "test@example.com"])
    _run(["git", "-C", str(seed), "config", "user.name", "Test"])
    (seed / "a.txt").write_text("one\n", encoding="utf-8")
    _run(["git", "-C", str(seed), "add", "."])
    _run(["git", "-C", str(seed), "commit", "-q", "-m", "init"])
    _run(["git", "-C", str(seed), "push", "-q", str(bare), branch])

    return bare


def _push_second_commit(tmp_path: Path, bare: Path, branch: str) -> str:
    """Add a second commit to the remote, adding b.txt and changing a.txt.

    Returns the new commit hash.
    """
    seed = tmp_path / "seed"
    (seed / "a.txt").write_text("two\n", encoding="utf-8")
    (seed / "b.txt").write_text("new file\n", encoding="utf-8")
    _run(["git", "-C", str(seed), "add", "."])
    _run(["git", "-C", str(seed), "commit", "-q", "-m", "second"])
    _run(["git", "-C", str(seed), "push", "-q", str(bare), branch])
    result = subprocess.run(
        ["git", "-C", str(seed), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    )
    return result.stdout.strip()


def _head_commit(target: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(target), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    )
    return result.stdout.strip()


def _is_clean(target: Path) -> bool:
    """"Clean" ignoring `meta.json`: ticket 04 adds it as an untracked,
    intentional bookkeeping file that every successful synchronise() writes
    back, so its presence alone must not read as a dirty working tree."""
    result = subprocess.run(
        ["git", "-C", str(target), "status", "--porcelain"],
        check=True, capture_output=True, text=True,
    )
    lines = [line for line in result.stdout.splitlines() if line.strip() != "?? meta.json"]
    return "\n".join(lines).strip() == ""


def test_first_synchronise_clones_target_to_the_remote_branch(tmp_path):
    branch = "main"
    bare = _make_remote(tmp_path, branch)
    target = tmp_path / "clone"

    CloneSynchroniser().synchronise(target, str(bare), branch)

    assert (target / "a.txt").read_text(encoding="utf-8") == "one\n"
    assert _is_clean(target)


def test_a_clone_whose_tracked_files_all_differ_reaches_the_newest_commit(tmp_path):
    branch = "main"
    bare = _make_remote(tmp_path, branch)
    target = tmp_path / "clone"
    CloneSynchroniser().synchronise(target, str(bare), branch)

    newest = _push_second_commit(tmp_path, bare, branch)

    # Rewrite the tracked file so every byte differs from the remote,
    # simulating the line-ending mismatch that broke `git pull --ff-only`.
    (target / "a.txt").write_text("one\r\n\r\ngarbage\r\n", encoding="utf-8")

    CloneSynchroniser().synchronise(target, str(bare), branch)

    assert _head_commit(target) == newest
    assert (target / "a.txt").read_text(encoding="utf-8") == "two\n"
    assert (target / "b.txt").read_text(encoding="utf-8") == "new file\n"
    assert _is_clean(target)


def test_a_clone_holding_an_untracked_file_loses_it(tmp_path):
    branch = "main"
    bare = _make_remote(tmp_path, branch)
    target = tmp_path / "clone"
    CloneSynchroniser().synchronise(target, str(bare), branch)

    (target / "leftover.txt").write_text("build output\n", encoding="utf-8")
    (target / "leftover_dir").mkdir()
    (target / "leftover_dir" / "inner.txt").write_text("x\n", encoding="utf-8")

    CloneSynchroniser().synchronise(target, str(bare), branch)

    assert not (target / "leftover.txt").exists()
    assert not (target / "leftover_dir").exists()
    assert _is_clean(target)


def test_synchronise_reaches_the_newest_commit_from_a_clean_clone_too(tmp_path):
    """The same call succeeds whether the working tree started dirty or clean —
    one unconditional sequence, not a clean/dirty branch."""
    branch = "main"
    bare = _make_remote(tmp_path, branch)
    target = tmp_path / "clone"
    CloneSynchroniser().synchronise(target, str(bare), branch)

    newest = _push_second_commit(tmp_path, bare, branch)

    CloneSynchroniser().synchronise(target, str(bare), branch)

    assert _head_commit(target) == newest
    assert _is_clean(target)


def test_a_conversion_enabled_clone_matches_a_conversion_disabled_one_after_refresh(tmp_path):
    """Ticket 03: the refresh states its line-ending behaviour in the git
    command itself, so a host whose git converts line endings on checkout
    ends up byte-identical to one that never did."""
    branch = "main"
    bare = _make_remote(tmp_path, branch)

    # A clone made as if on a host whose git config turns conversion on.
    converting = tmp_path / "converting_clone"
    _run([
        "git", "-c", "core.autocrlf=true",
        "clone", "-q", "--branch", branch, "--single-branch", "--depth", "1",
        str(bare), str(converting),
    ])

    # A clone made through the synchroniser, which pins conversion off.
    pinned = tmp_path / "pinned_clone"
    CloneSynchroniser().synchronise(pinned, str(bare), branch)

    newest = _push_second_commit(tmp_path, bare, branch)

    # Refresh both through the synchroniser. The host-level setting on
    # `converting` must not survive the refresh.
    CloneSynchroniser().synchronise(converting, str(bare), branch)
    CloneSynchroniser().synchronise(pinned, str(bare), branch)

    assert _head_commit(converting) == newest
    assert _head_commit(pinned) == newest
    assert (converting / "a.txt").read_bytes() == (pinned / "a.txt").read_bytes()
    assert (converting / "b.txt").read_bytes() == (pinned / "b.txt").read_bytes()


def test_no_clone_config_records_the_line_ending_setting(tmp_path):
    """Ticket 03: the setting is passed with `-c` on each command, never
    written into the clone's own git config."""
    branch = "main"
    bare = _make_remote(tmp_path, branch)
    target = tmp_path / "clone"
    CloneSynchroniser().synchronise(target, str(bare), branch)

    _push_second_commit(tmp_path, bare, branch)
    CloneSynchroniser().synchronise(target, str(bare), branch)

    # `--local` reads only this clone's own config file, never the host's
    # system/global config — the setting must be absent here specifically.
    result = subprocess.run(
        ["git", "-C", str(target), "config", "--local", "--get", "core.autocrlf"],
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert result.stdout.strip() == ""


# ----------------------------------------------------------------------
# Ticket 04: meta.json records what the clone holds.
#
# See .scratch/refresh-resets-the-clone-to-the-remote/issues/
# 04-meta-json-records-what-the-clone-holds.md
# ----------------------------------------------------------------------

def _read_meta(target: Path) -> dict:
    return json.loads((target / "meta.json").read_text(encoding="utf-8"))


def test_a_first_time_clone_writes_meta_json_immediately(tmp_path):
    branch = "main"
    bare = _make_remote(tmp_path, branch)
    target = tmp_path / "clone"

    CloneSynchroniser().synchronise(target, str(bare), branch)

    meta = _read_meta(target)
    assert meta["branch"] == branch
    assert meta["commit"] == _head_commit(target)
    assert isinstance(meta["refreshed_at"], str) and meta["refreshed_at"] != ""


def test_a_successful_refresh_records_the_new_branch_commit_and_time(tmp_path):
    branch = "main"
    bare = _make_remote(tmp_path, branch)
    target = tmp_path / "clone"
    CloneSynchroniser().synchronise(target, str(bare), branch)
    first_refreshed_at = _read_meta(target)["refreshed_at"]

    newest = _push_second_commit(tmp_path, bare, branch)
    CloneSynchroniser().synchronise(target, str(bare), branch)

    meta = _read_meta(target)
    assert meta["branch"] == branch
    assert meta["commit"] == newest
    assert isinstance(meta["refreshed_at"], str) and meta["refreshed_at"] != ""
    # Not asserting the two timestamps differ: a fast machine can complete
    # both refreshes within the same clock tick.
    assert first_refreshed_at is not None


def test_a_refresh_that_finds_no_meta_json_still_ends_with_a_correct_one(tmp_path):
    """A missing meta.json is not a reason to clone again — the existing
    clone is fetched/reset/cleaned as usual, and ends with a meta.json that
    reflects the completed refresh (known time), not the rebuilt stand-in."""
    branch = "main"
    bare = _make_remote(tmp_path, branch)
    target = tmp_path / "clone"
    CloneSynchroniser().synchronise(target, str(bare), branch)
    original_dot_git = target / ".git"
    assert original_dot_git.exists()

    (target / "meta.json").unlink()
    newest = _push_second_commit(tmp_path, bare, branch)

    with patch.object(CloneSynchroniser, "_clone") as mocked_clone:
        CloneSynchroniser().synchronise(target, str(bare), branch)
        mocked_clone.assert_not_called()

    meta = _read_meta(target)
    assert meta["branch"] == branch
    assert meta["commit"] == newest
    assert isinstance(meta["refreshed_at"], str) and meta["refreshed_at"] != ""


def test_a_rebuilt_meta_records_the_time_as_unknown_when_the_refresh_then_fails(tmp_path):
    """When meta.json is missing, the clone is asked which branch it holds
    and a stand-in meta.json is written with an unknown time before the
    risky fetch/reset run. If that fetch then fails, the stand-in survives —
    an honest, if incomplete, record beats no record at all.

    Also checks that "unknown" is an explicit JSON `null`, not merely an
    absent key: the two states must stay distinguishable on disk."""
    branch = "main"
    bare = _make_remote(tmp_path, branch)
    target = tmp_path / "clone"
    CloneSynchroniser().synchronise(target, str(bare), branch)
    commit_before_failure = _head_commit(target)

    (target / "meta.json").unlink()

    broken_remote = str(tmp_path / "does-not-exist.git")
    with pytest.raises(SynchroniseError):
        CloneSynchroniser().synchronise(target, broken_remote, branch)

    raw_text = (target / "meta.json").read_text(encoding="utf-8")
    meta = json.loads(raw_text)
    assert meta["branch"] == branch
    assert meta["commit"] == commit_before_failure
    assert "refreshed_at" in meta
    assert meta["refreshed_at"] is None
    assert '"refreshed_at": null' in raw_text


# ----------------------------------------------------------------------
# Ticket 05: the declared branch decides; a mismatch re-clones.
#
# See .scratch/refresh-resets-the-clone-to-the-remote/issues/
# 05-declared-branch-decides-and-a-mismatch-re-clones.md
# ----------------------------------------------------------------------

def _push_new_branch(tmp_path: Path, bare: Path, branch: str, filename: str, content: str) -> str:
    """Branch off the seed's current HEAD, add one file unique to the new
    branch, and push it to `bare`. Returns the new commit hash.

    The seed is left checked out on `branch` afterwards.
    """
    seed = tmp_path / "seed"
    _run(["git", "-C", str(seed), "checkout", "-q", "-b", branch])
    (seed / filename).write_text(content, encoding="utf-8")
    _run(["git", "-C", str(seed), "add", "."])
    _run(["git", "-C", str(seed), "commit", "-q", "-m", f"add {filename} on {branch}"])
    _run(["git", "-C", str(seed), "push", "-q", str(bare), branch])
    result = subprocess.run(
        ["git", "-C", str(seed), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    )
    return result.stdout.strip()


def test_a_refresh_whose_declared_branch_equals_the_recorded_branch_fetches_and_resets(tmp_path):
    branch = "main"
    bare = _make_remote(tmp_path, branch)
    target = tmp_path / "clone"
    CloneSynchroniser().synchronise(target, str(bare), branch)

    newest = _push_second_commit(tmp_path, bare, branch)

    with patch.object(CloneSynchroniser, "_clone") as mocked_clone:
        CloneSynchroniser().synchronise(target, str(bare), branch)
        mocked_clone.assert_not_called()

    assert _head_commit(target) == newest
    assert _is_clean(target)


def test_a_refresh_whose_declared_branch_differs_from_the_recorded_branch_reclones_it(tmp_path):
    main_branch = "main"
    feature_branch = "feature"
    bare = _make_remote(tmp_path, main_branch)
    target = tmp_path / "clone"

    CloneSynchroniser().synchronise(target, str(bare), main_branch)
    # A single-branch, shallow clone has no `origin/feature` to reset onto —
    # this is exactly why a plain fetch/reset cannot serve a branch change.
    feature_commit = _push_new_branch(tmp_path, bare, feature_branch, "feature_only.txt", "only on feature\n")

    # A marker planted inside .git survives an ordinary fetch/reset/clean
    # (which never touches .git's own contents), so its disappearance
    # proves the whole directory was deleted, not merely refreshed.
    marker = target / ".git" / "planted_before_mismatch.marker"
    marker.write_text("still here?\n", encoding="utf-8")

    CloneSynchroniser().synchronise(target, str(bare), feature_branch)

    assert not marker.exists()
    assert (target / "feature_only.txt").read_text(encoding="utf-8") == "only on feature\n"
    assert _head_commit(target) == feature_commit
    assert _is_clean(target)

    meta = _read_meta(target)
    assert meta["branch"] == feature_branch
    assert meta["commit"] == feature_commit


def test_a_missing_meta_json_is_not_treated_as_a_branch_mismatch(tmp_path):
    """Rebuilding a missing meta.json asks git for the branch the clone is
    actually on. When that matches the declared branch, the refresh must
    take the fetch/reset/clean path, not the delete-and-reclone path —
    "no record" and "different record" are not the same thing."""
    branch = "main"
    bare = _make_remote(tmp_path, branch)
    target = tmp_path / "clone"
    CloneSynchroniser().synchronise(target, str(bare), branch)

    (target / "meta.json").unlink()
    newest = _push_second_commit(tmp_path, bare, branch)

    with patch.object(CloneSynchroniser, "_clone") as mocked_clone:
        CloneSynchroniser().synchronise(target, str(bare), branch)
        mocked_clone.assert_not_called()

    assert _head_commit(target) == newest
    assert _is_clean(target)


# ----------------------------------------------------------------------
# Ticket 06: a lock guards each clone directory.
#
# See .scratch/refresh-resets-the-clone-to-the-remote/issues/
# 06-a-lock-guards-each-clone-directory.md
# ----------------------------------------------------------------------

def _lock_path(target: Path) -> Path:
    return target.parent / f"{target.name}.lock"


def test_a_successful_refresh_reports_synchronised_and_leaves_no_lock_behind(tmp_path):
    branch = "main"
    bare = _make_remote(tmp_path, branch)
    target = tmp_path / "clone"

    result = CloneSynchroniser().synchronise(target, str(bare), branch)

    assert result is SynchroniseResult.SYNCHRONISED
    assert not _lock_path(target).exists()


def test_the_lock_file_sits_beside_the_target_directory_not_inside_it(tmp_path):
    branch = "main"
    bare = _make_remote(tmp_path, branch)
    target = tmp_path / "clone"

    # A lock held at the moment of the call must live in target.parent,
    # never inside target itself where `clean -fd` could reach it.
    lock = _lock_path(target)
    lock.write_text("held\n", encoding="utf-8")

    result = CloneSynchroniser().synchronise(target, str(bare), branch)

    assert result is SynchroniseResult.BUSY
    assert lock.parent == target.parent
    assert not (target / "clone.lock").exists()


def test_a_second_refresh_finding_the_lock_held_returns_busy_and_changes_nothing(tmp_path):
    """Two Systems can point the catalog at the same clone directory. The
    lock is keyed on that directory, not on either System, so a refresh
    started while the directory's lock is held must stop untouched."""
    branch = "main"
    bare = _make_remote(tmp_path, branch)
    target = tmp_path / "clone"
    CloneSynchroniser().synchronise(target, str(bare), branch)
    commit_before = _head_commit(target)
    meta_before = _read_meta(target)
    _push_second_commit(tmp_path, bare, branch)

    # Simulate a second System's refresh already running against the same
    # directory by planting a fresh lock file ourselves.
    _lock_path(target).write_text(
        json.dumps({"pid": 999999, "acquired_at": "now"}), encoding="utf-8"
    )

    with patch.object(CloneSynchroniser, "_fetch") as mocked_fetch:
        result = CloneSynchroniser().synchronise(target, str(bare), branch)
        mocked_fetch.assert_not_called()

    assert result is SynchroniseResult.BUSY
    assert _head_commit(target) == commit_before
    assert _read_meta(target) == meta_before
    assert _lock_path(target).exists()


def test_git_clean_never_reaches_a_lock_file_beside_the_target(tmp_path):
    """The lock's placement, not a special case inside `_clean()`, is what
    protects it: `git clean -fd` runs scoped to `target` and cannot reach a
    file beside it. Driving `_clean()` directly (rather than a full
    synchronise() cycle) proves this independently of whether the lock has
    already been released by the time synchronise() returns."""
    branch = "main"
    bare = _make_remote(tmp_path, branch)
    target = tmp_path / "clone"
    CloneSynchroniser().synchronise(target, str(bare), branch)

    lock = _lock_path(target)
    lock.write_text("still here?\n", encoding="utf-8")
    (target / "leftover.txt").write_text("build output\n", encoding="utf-8")

    CloneSynchroniser()._clean(target)

    assert lock.exists()
    assert not (target / "leftover.txt").exists()


def test_a_failure_while_writing_the_lock_file_leaves_no_orphan_lock(tmp_path):
    """A lock file that fails to finish writing must not linger on disk —
    otherwise it sits there, unowned, until the 30-minute abandonment
    timeout, blocking every refresh in between for no reason."""
    branch = "main"
    bare = _make_remote(tmp_path, branch)
    target = tmp_path / "clone"
    lock = _lock_path(target)

    with patch("code_analyzer.clone_synchroniser.os.write", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            CloneSynchroniser().synchronise(target, str(bare), branch)

    assert not lock.exists()


def test_a_release_never_deletes_a_lock_that_was_taken_over_while_it_ran(tmp_path):
    """A refresh that runs past the abandonment timeout may find its own
    lock already taken over by the next refresh. Its own release at the end
    must not delete that new lock -- doing so would let a third refresh
    start concurrently with the one that took over, defeating the point of
    the lock."""
    branch = "main"
    bare = _make_remote(tmp_path, branch)
    target = tmp_path / "clone"
    CloneSynchroniser().synchronise(target, str(bare), branch)

    lock = _lock_path(target)
    synchroniser = CloneSynchroniser()
    token = synchroniser._acquire_lock(lock)
    assert token is not None

    # Simulate a second refresh stealing this (now-abandoned, in this
    # scenario) lock while the first is still running.
    lock.write_text("someone-elses-token", encoding="utf-8")

    synchroniser._release_lock(lock, token)

    assert lock.read_text(encoding="utf-8") == "someone-elses-token"


def test_a_lock_older_than_thirty_minutes_counts_as_abandoned_and_is_taken_over(tmp_path):
    branch = "main"
    bare = _make_remote(tmp_path, branch)
    target = tmp_path / "clone"
    CloneSynchroniser().synchronise(target, str(bare), branch)
    newest = _push_second_commit(tmp_path, bare, branch)

    lock = _lock_path(target)
    lock.write_text("stale\n", encoding="utf-8")
    stale_time = time.time() - CloneSynchroniser.ABANDONED_LOCK_SECONDS - 60
    os.utime(lock, (stale_time, stale_time))

    result = CloneSynchroniser().synchronise(target, str(bare), branch)

    assert result is SynchroniseResult.SYNCHRONISED
    assert _head_commit(target) == newest
    assert not lock.exists()


def test_a_lock_younger_than_thirty_minutes_is_not_abandoned(tmp_path):
    branch = "main"
    bare = _make_remote(tmp_path, branch)
    target = tmp_path / "clone"
    CloneSynchroniser().synchronise(target, str(bare), branch)
    commit_before = _head_commit(target)
    _push_second_commit(tmp_path, bare, branch)

    lock = _lock_path(target)
    lock.write_text("recent\n", encoding="utf-8")
    recent_time = time.time() - CloneSynchroniser.ABANDONED_LOCK_SECONDS + 60
    os.utime(lock, (recent_time, recent_time))

    result = CloneSynchroniser().synchronise(target, str(bare), branch)

    assert result is SynchroniseResult.BUSY
    assert _head_commit(target) == commit_before


def test_a_refresh_releases_its_lock_when_it_fails(tmp_path):
    branch = "main"
    bare = _make_remote(tmp_path, branch)
    target = tmp_path / "clone"
    CloneSynchroniser().synchronise(target, str(bare), branch)

    broken_remote = str(tmp_path / "does-not-exist.git")
    with pytest.raises(SynchroniseError):
        CloneSynchroniser().synchronise(target, broken_remote, branch)

    assert not _lock_path(target).exists()


def test_a_refresh_releases_its_lock_after_a_first_time_clone(tmp_path):
    branch = "main"
    bare = _make_remote(tmp_path, branch)
    target = tmp_path / "clone"

    result = CloneSynchroniser().synchronise(target, str(bare), branch)

    assert result is SynchroniseResult.SYNCHRONISED
    assert not _lock_path(target).exists()
