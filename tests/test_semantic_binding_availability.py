"""Ticket 05: build a compilation per project and report Semantic Binding Availability.

The analyzer host previously performed no semantic analysis: it read syntax trees alone. This
ticket adds a compilation per scanned project and reports the result of that attempt as a named
state — Semantic Binding Availability — so a degraded analysis never looks like a confident one.
Classification results (db_invocations etc.) are untouched by this ticket; that is covered
separately by tests/test_wrapper_decompilation.py and tests/test_csharp_analysis_gateway.py.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from code_analyzer.project_scanner import ProjectScanResult
from code_analyzer.static_analyzer_host import StaticAnalyzerHost
from service import analyze_service

STC_CSPROJ = PROJECT_ROOT / "data" / "repos" / "System_Dept_1" / "STC" / "STC" / "STC.csproj"
SQLFUNC_DLL = STC_CSPROJ.parent / "bin" / "SQLFunc.dll"

requires_stc_fixture = pytest.mark.skipif(
    not (STC_CSPROJ.exists() and SQLFUNC_DLL.exists()),
    reason="local data/repos/System_Dept_1/STC fixture checkout is not present",
)

requires_dotnet = pytest.mark.skipif(
    shutil.which("dotnet") is None,
    reason="the .NET toolchain is not available",
)


@requires_dotnet
def test_semantic_binding_reports_unavailable_no_project_file() -> None:
    """A scan root that holds no .csproj yields unavailable_no_project_file, and names no
    project file (there is none), rather than silently reporting nothing."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as scan_root:
        (Path(scan_root) / "Loose.cs").write_text(
            "public class Loose { public void Run() { } }", encoding="utf-8"
        )
        result = host.semantic_binding_availability([Path(scan_root)])

    assert len(result) == 1
    assert result[0]["availability"] == "unavailable_no_project_file"
    assert result[0]["project_file"] is None
    assert result[0]["unresolved_references"] == []


@requires_dotnet
def test_semantic_binding_reports_unavailable_reference_resolution_failed() -> None:
    """A reference the compilation cannot resolve (neither the reference assembly package
    nor the project's own output directory) fails the whole project's attempt, and names
    every reference that could not be resolved."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as scan_root:
        project_dir = Path(scan_root)
        (project_dir / "Broken.csproj").write_text(
            """<Project ToolsVersion="15.0" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
  <ItemGroup>
    <Reference Include="TotallyMadeUpFrameworkAssembly" />
    <Reference Include="SomeExternalThing, Version=1.0.0.0">
      <HintPath>bin\\SomeExternalThing.dll</HintPath>
    </Reference>
  </ItemGroup>
  <ItemGroup>
    <Compile Include="Foo.cs" />
  </ItemGroup>
</Project>
""",
            encoding="utf-8",
        )
        (project_dir / "Foo.cs").write_text("public class Foo { }", encoding="utf-8")

        result = host.semantic_binding_availability([project_dir])

    assert len(result) == 1
    entry = result[0]
    assert entry["availability"] == "unavailable_reference_resolution_failed"
    assert entry["project_file"] == str(project_dir / "Broken.csproj")
    assert set(entry["unresolved_references"]) == {
        "TotallyMadeUpFrameworkAssembly",
        "SomeExternalThing",
    }


@requires_dotnet
def test_semantic_binding_availability_builds_one_compilation_per_project_not_per_file() -> None:
    """A project with several source files still yields exactly one attempt entry: the
    analyzer builds one compilation for the whole project, never one per file."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as scan_root:
        project_dir = Path(scan_root)
        (project_dir / "Multi.csproj").write_text(
            """<Project ToolsVersion="15.0" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
  <ItemGroup>
    <Reference Include="System" />
  </ItemGroup>
  <ItemGroup>
    <Compile Include="One.cs" />
    <Compile Include="Two.cs" />
    <Compile Include="Three.cs" />
  </ItemGroup>
</Project>
""",
            encoding="utf-8",
        )
        for name in ("One", "Two", "Three"):
            (project_dir / f"{name}.cs").write_text(f"public class {name} {{ }}", encoding="utf-8")

        result = host.semantic_binding_availability([project_dir])

    assert len(result) == 1
    assert result[0]["availability"] == "available"
    assert result[0]["unresolved_references"] == []


@requires_dotnet
def test_semantic_binding_reports_unavailable_for_unresolved_project_reference() -> None:
    """A <ProjectReference> names another project's own output, which this ticket does not
    build. It must be surfaced as an unresolved reference rather than silently dropped, so a
    project depending on one never gets reported as available by mistake."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as scan_root:
        project_dir = Path(scan_root)
        (project_dir / "HasProjRef.csproj").write_text(
            """<Project ToolsVersion="15.0" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
  <ItemGroup>
    <Reference Include="System" />
  </ItemGroup>
  <ItemGroup>
    <ProjectReference Include="..\\OtherLib\\OtherLib.csproj" />
  </ItemGroup>
  <ItemGroup>
    <Compile Include="Foo.cs" />
  </ItemGroup>
</Project>
""",
            encoding="utf-8",
        )
        (project_dir / "Foo.cs").write_text("public class Foo { }", encoding="utf-8")

        result = host.semantic_binding_availability([project_dir])

    assert len(result) == 1
    assert result[0]["availability"] == "unavailable_reference_resolution_failed"
    assert "OtherLib" in result[0]["unresolved_references"]


@requires_dotnet
@requires_stc_fixture
def test_semantic_binding_reports_available_for_real_stc_project() -> None:
    """End-to-end smoke test against the real STC.csproj: its framework references resolve
    against the .NET Framework reference assembly package, and its external SQLFunc/DataCheck
    references resolve against the project's own bin output directory."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    scan_root = STC_CSPROJ.parent.parent
    result = host.semantic_binding_availability([scan_root])

    matching = [entry for entry in result if entry["project_file"] == str(STC_CSPROJ)]
    assert len(matching) == 1
    assert matching[0]["availability"] == "available"
    assert matching[0]["unresolved_references"] == []


def test_refresh_source_reports_semantic_binding_availability(monkeypatch, tmp_path) -> None:
    """The refresh output surfaces the Semantic Binding Availability the scan captured, so a
    maintainer can see whether the analyzer had a semantic model for each scanned project."""
    root = tmp_path / "SomeSystem"
    root.mkdir()

    fake_binding = [
        {
            "scan_root": str(root),
            "project_file": str(root / "SomeSystem.csproj"),
            "availability": "available",
            "unresolved_references": [],
        }
    ]
    scan = ProjectScanResult(
        project_root=str(root),
        project_name=root.name,
        scan_time=datetime.now(),
        total_files=1,
        scanned_files=1,
    )
    scan.semantic_binding_availability = fake_binding

    monkeypatch.setattr(analyze_service, "resolve_scan_roots", lambda source, refresh=False: [root])
    monkeypatch.setattr(analyze_service, "get_or_scan", lambda r, refresh=False: scan)

    result = analyze_service.refresh_source({"project": "p", "repo": "r"})

    assert result["semantic_binding_availability"] == fake_binding
