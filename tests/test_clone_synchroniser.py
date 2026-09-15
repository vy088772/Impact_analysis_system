"""Ticket 02: the clone synchroniser replaces pull with fetch + reset + clean.

Drives CloneSynchroniser directly against a local bare repository — no
network, no PAT, no organisation or project name. Asserts the state of the
target directory afterwards, never which git commands ran.

See .scratch/refresh-resets-the-clone-to-the-remote/issues/
02-synchroniser-replaces-pull-with-fetch-reset-clean.md
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from code_analyzer.clone_synchroniser import CloneSynchroniser


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
    result = subprocess.run(
        ["git", "-C", str(target), "status", "--porcelain"],
        check=True, capture_output=True, text=True,
    )
    return result.stdout.strip() == ""


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
