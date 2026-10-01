"""Hand-built C# Scan Results for the tests that ask a question of one scan."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable

from code_analyzer.models import ClassInfo, FileAnalysisResult, FileType, FrameworkType, MethodInfo
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
