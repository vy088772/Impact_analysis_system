# code_analyzer/clone_root.py
"""The clone root: the directory that holds the `.git` entry of a clone.

One function finds it. The scan store uses it for the source commit, and the
Connection Lookup uses it to bound the search for a Parent Application.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

# The search goes up at most this many levels, so a deep sub-path does not
# search without end.
MAX_LEVELS = 6


def find_clone_root(path: Union[str, Path]) -> Optional[Path]:
    """The nearest directory above a path that holds a `.git` entry.

    A `.git` file (a worktree or a submodule) counts as well as a directory.

    The path itself counts. Gives None when no such directory is within
    `MAX_LEVELS` levels.
    """
    current = Path(path).resolve()
    for _ in range(MAX_LEVELS):
        if (current / ".git").exists():
            return current
        if current.parent == current:
            break
        current = current.parent
    return None
