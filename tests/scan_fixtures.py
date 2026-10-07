"""Hand-built C# Scan Results for the tests that ask a question of one scan."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Sequence

from code_analyzer.models import (
    CallSite,
    ClassInfo,
    FileAnalysisResult,
    FileType,
    FrameworkType,
    MethodInfo,
    MethodSourceSpan,
    SourceSnapshot,
)
from code_analyzer.project_scanner import CSharpTableRelation, ProjectScanResult


def csharp_file(root: Path, name: str, methods: list[MethodInfo]) -> FileAnalysisResult:
    """One WebForms C# file under the root, with one class named after the file."""
    path = root / name
    return FileAnalysisResult(
        file_path=str(path),
        file_type=FileType.CSHARP,
        framework=FrameworkType.WEBFORMS,
        classes=[ClassInfo(name=Path(name).name.split(".")[0], namespace="", file_path=str(path), methods=methods)],
    )


def scan_of(
    root: Path, files: list[FileAnalysisResult], table_relations: Iterable[CSharpTableRelation] = ()
) -> ProjectScanResult:
    """The C# Scan Result of the files under the root, with its table relations.

    Each method of the files gets its method span, as the analyzer host records it.
    """
    return with_declared_spans(
        ProjectScanResult(
            project_root=str(root),
            project_name="orders",
            scan_time=datetime.now(),
            csharp_results=files,
            aspx_results=[],
            table_relations=list(table_relations),
        )
    )


# The source place of each node in a hand-built scan. A node takes the next free slot
# the first time a test names it. Slot `n` is line `n + 1` of each snapshot, and the
# UTF-16 offsets `n * _LINE` to `n * _LINE + _LINE - 1`. So a test can place a Database
# Invocation or a table relation in a method before the scan exists.
_LINE = 100
_SLOTS: Dict[str, int] = {}


def node_of(name: str) -> str:
    """The call graph node that a test name gives: `Class.Method` is `Class.Method()`."""
    return name if name.endswith(")") else f"{name}()"


def _slot(name: str) -> int:
    return _SLOTS.setdefault(node_of(name), len(_SLOTS))


def source_offset(name: str) -> int:
    """A UTF-16 offset inside the method span of a node (`Class.Method` or `Class.Method(int)`)."""
    return _slot(name) * _LINE + 1


def source_line(name: str) -> int:
    """A 1-based line inside the method span of a node."""
    return _slot(name) + 1


def _span(node: str, calls: List[CallSite]) -> MethodSourceSpan:
    class_and_method = node.partition("(")[0]
    class_name, _, method_name = class_and_method.rpartition(".")
    start = _slot(node) * _LINE
    return MethodSourceSpan(class_name, method_name, start, start + _LINE - 1, calls, node=node)


def _add_spans(scan: ProjectScanResult, relative_path: str, spans: Sequence[MethodSourceSpan]) -> None:
    """Put the spans in the snapshot of one file; a span of the same node replaces the old one."""
    snapshot = scan.source_snapshots.get(relative_path)
    by_node = {span.node: span for span in (snapshot.method_spans if snapshot else [])}
    by_node.update({span.node: span for span in spans})
    method_spans = sorted(by_node.values(), key=lambda span: span.start_offset)
    if not method_spans:
        return
    lines = max(span.end_offset for span in method_spans) // _LINE + 1
    scan.source_snapshots[relative_path] = SourceSnapshot(
        relative_path=relative_path,
        content_hash="",
        content=("x" * (_LINE - 1) + "\n") * lines,
        method_spans=method_spans,
    )


def with_declared_spans(scan: ProjectScanResult) -> ProjectScanResult:
    """Add the method span of each C# parser declaration of the scan, with no calls.

    The node takes the parameter types of the declaration: `Class.Save(int)`.
    """
    for fr in scan.csharp_results:
        spans = [
            _span(f"{cls.name}.{m.name}({','.join(p.type for p in m.parameters)})", [])
            for cls in fr.classes
            for m in cls.methods
        ]
        if spans:
            relative_path = Path(fr.file_path).relative_to(scan.project_root).as_posix()
            _add_spans(scan, relative_path, spans)
    return scan


def with_bound_calls(
    scan: ProjectScanResult, relative_path: str, calls: Mapping[str, Sequence[str]]
) -> ProjectScanResult:
    """Add the Bound Call Targets of one source file, as the analyzer host records them.

    `calls` maps a caller node to the nodes its calls reach. A node is written
    `Class.Method` (no parameters) or `Class.Method(int)`. A target written as `!reason`
    or `!reason:ClassA,ClassB` is a call with no Bound Call Target, that reason and those
    candidate classes. Its call text is `x.<reason>`.
    """
    spans = []
    for caller, targets in calls.items():
        sites = []
        for target in targets:
            if target.startswith("!"):
                reason, _, candidates = target[1:].partition(":")
                sites.append(
                    CallSite(
                        call_text=f"x.{reason}",
                        start_offset=len(sites),
                        end_offset=len(sites) + 1,
                        unresolved_reason=reason,
                        candidate_classes=[name for name in candidates.split(",") if name],
                    )
                )
                continue
            target_span = _span(node_of(target), [])
            sites.append(
                CallSite(
                    call_text=f"x.{target_span.method_name}",
                    start_offset=0,
                    end_offset=0,
                    target_class=target_span.class_name,
                    target_method=target_span.method_name,
                    target_node=target_span.node,
                )
            )
        spans.append(_span(node_of(caller), sites))
    _add_spans(scan, relative_path, spans)
    return scan
