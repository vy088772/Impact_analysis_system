"""Hand-built C# Scan Results for the tests that ask a question of one scan."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping, Sequence

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
    """The C# Scan Result of the files under the root, with its table relations."""
    return ProjectScanResult(
        project_root=str(root),
        project_name="orders",
        scan_time=datetime.now(),
        csharp_results=files,
        aspx_results=[],
        table_relations=list(table_relations),
    )


def with_bound_calls(
    scan: ProjectScanResult, relative_path: str, calls: Mapping[str, Sequence[str]]
) -> ProjectScanResult:
    """Add the Bound Call Targets of one source file, as the analyzer host records them.

    `calls` maps a caller node (`Class.Method`) to the nodes its calls reach. A target
    written as `!reason` or `!reason:ClassA,ClassB` is a call with no Bound Call Target,
    that reason and those candidate classes. Its call text is `x.<reason>`.
    """
    spans = []
    for caller, targets in calls.items():
        class_name, method_name = caller.rsplit(".", 1)
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
            target_class, target_method = target.rsplit(".", 1)
            sites.append(
                CallSite(
                    call_text=f"x.{target_method}",
                    start_offset=0,
                    end_offset=0,
                    target_class=target_class,
                    target_method=target_method,
                )
            )
        spans.append(MethodSourceSpan(class_name, method_name, 0, 0, sites))
    scan.source_snapshots[relative_path] = SourceSnapshot(
        relative_path=relative_path, content_hash="", content="", method_spans=spans
    )
    return scan
