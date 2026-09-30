"""Tests for the clone root function of the analyzer package."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from code_analyzer.clone_root import find_clone_root


def test_the_clone_root_is_the_nearest_directory_that_holds_a_git_directory(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)

    assert find_clone_root(nested) == tmp_path.resolve()
    assert find_clone_root(tmp_path) == tmp_path.resolve()


def test_there_is_no_clone_root_without_a_git_directory(tmp_path: Path):
    nested = tmp_path / "a"
    nested.mkdir()

    assert find_clone_root(nested) is None


def test_the_search_goes_up_six_levels_at_most(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    level5 = tmp_path.joinpath(*"abcde")
    level6 = tmp_path.joinpath(*"abcdef")
    level6.mkdir(parents=True)

    assert find_clone_root(level5) == tmp_path.resolve()
    assert find_clone_root(level6) is None
