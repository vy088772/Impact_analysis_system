"""The call graph nodes of one scan, found by source location (ADR-0044).

A node is one bound method symbol. The analyzer host builds it for each method span
and for each Bound Call Target, so those two join with no translation. Every other
record finds its node by where it is in the source:

- a Database Invocation and an Execution Path by the offset of their source span,
- a table relation by its line,
- a C# parser declaration by its file: the parser gives no signature, so the
  spans of the file stand in for its methods.

A record that no method span holds has no node. Its class name and method name never
make one.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Mapping, Optional, Tuple

from code_analyzer.models import MethodSourceSpan, SourceSnapshot
from code_analyzer.project_scanner import ProjectScanResult


class MethodNodes:
    """The method spans of one scan, by source file."""

    def __init__(self, scan: ProjectScanResult) -> None:
        # The file name -> (the relative path, its snapshot). A file name is the
        # last part of each path that a lookup can give, so it narrows the search.
        self._by_name: Dict[str, List[Tuple[str, SourceSnapshot]]] = {}
        for key, snapshot in getattr(scan, "source_snapshots", {}).items():
            relative = _normalized(snapshot.relative_path or key)
            self._by_name.setdefault(relative.rpartition("/")[2], []).append((relative, snapshot))

    def snapshot_of(self, path: str) -> Optional[SourceSnapshot]:
        """The snapshot of a source file, from its absolute path or a path relative to any root.

        A merged scan keeps its paths relative to the common root of its scan roots, and a
        request counts its paths from its own root, so the lookup matches the longest snapshot
        path that ends the given path.
        """
        wanted = _normalized(path)
        matches = [
            (relative, snapshot)
            for relative, snapshot in self._by_name.get(wanted.rpartition("/")[2], [])
            if wanted == relative or wanted.endswith("/" + relative)
        ]
        return max(matches, key=lambda match: len(match[0]))[1] if matches else None

    def spans_of(self, path: str) -> List[MethodSourceSpan]:
        """The method spans of a source file that have a node, in source order."""
        snapshot = self.snapshot_of(path)
        return [span for span in snapshot.method_spans if span.node] if snapshot else []

    def at_offset(self, path: str, utf16_offset: int) -> str:
        """The node of the method that holds a source offset, or "" when none does."""
        snapshot = self.snapshot_of(path)
        return snapshot.node_at(utf16_offset) if snapshot else ""

    def at_line(self, path: str, line_number: int) -> str:
        """The node of the method that holds a 1-based line, or "" when none does."""
        snapshot = self.snapshot_of(path)
        return snapshot.node_at_line(line_number) if snapshot else ""

    def of_source_span(self, source_span: object) -> str:
        """The node of the method that holds a `source_span` mapping, or "" when none does."""
        if not isinstance(source_span, Mapping):
            return ""
        path = str(source_span.get("relative_path") or "")
        if not path:
            return ""
        return self.at_offset(path, int(source_span.get("start_offset") or 0))


def _normalized(path: str) -> str:
    return Path(str(path).replace("\\", "/")).as_posix().casefold()
