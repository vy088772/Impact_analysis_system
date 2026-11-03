"""Impact Code Time: the newest modification time of the Python files in the service package.

The Impact service records it one time, when it starts, and reports it in `GET /health`.
The web and the launcher calculate the same value from the Impact code on the disk.
When the two values are different, the running Impact service uses older code.

The rule, so that another program can calculate the same text:
- The files are the `*.py` files under `<Impact code dir>/service`, subdirectories included.
  `__pycache__` holds only `.pyc` files, so it adds nothing.
- The text is ISO 8601 with whole seconds and the local offset as `+HH:MM`, for example
  `2026-11-02T15:09:00+08:00`. The fraction of a second is cut, not rounded.
- A package with no `*.py` file has no Impact Code Time (None), not an error.

The web and the launcher compare two texts. The comparison is correct only when both
processes use the same time zone, which is true for two processes on one machine with
the same `TZ` setting.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

SERVICE_PACKAGE_DIR = Path(__file__).resolve().parent


def impact_code_time(package_dir: Optional[Path] = None) -> Optional[str]:
    """Return the Impact Code Time of `package_dir` (default: this service package),
    or None when the package has no Python file."""
    root = SERVICE_PACKAGE_DIR if package_dir is None else package_dir
    mtimes = []
    for path in root.rglob("*.py"):
        try:
            mtimes.append(path.stat().st_mtime)
        except FileNotFoundError:
            continue  # an editor or sync tool removed the file after rglob saw it
    if not mtimes:
        return None
    newest = datetime.fromtimestamp(max(mtimes)).astimezone()
    return newest.isoformat(timespec="seconds")
