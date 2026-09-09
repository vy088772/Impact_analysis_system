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


def _nuget_org_reachable() -> bool:
    import urllib.request

    try:
        urllib.request.urlopen("https://api.nuget.org/v3/index.json", timeout=2)
        return True
    except Exception:
        return False


requires_network = pytest.mark.skipif(
    not _nuget_org_reachable(), reason="api.nuget.org is not reachable from this environment"
)

TTPUR_CSPROJ = (
    PROJECT_ROOT / "data" / "repos" / "System_Dept_1" / "Y-DOCs" / "TTPUR" / "TTPUR.csproj"
)

requires_ydocs_fixture = pytest.mark.skipif(
    not TTPUR_CSPROJ.exists(),
    reason="local data/repos/System_Dept_1/Y-DOCs/TTPUR fixture checkout is not present",
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
def test_old_style_project_with_no_packages_config_is_unchanged() -> None:
    """Ticket 01: a project that declares no packages.config never attempts a restore, and
    behaves exactly as it did before this ticket -- same unresolved references, named."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as scan_root:
        project_dir = Path(scan_root)
        (project_dir / "NoPackages.csproj").write_text(
            """<Project ToolsVersion="15.0" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
  <ItemGroup>
    <Reference Include="SomePackageAssembly, Version=1.0.0.0">
      <HintPath>..\\packages\\SomePackageAssembly.1.0.0\\lib\\net461\\SomePackageAssembly.dll</HintPath>
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
    assert result[0]["availability"] == "unavailable_reference_resolution_failed"
    assert result[0]["unresolved_references"] == ["SomePackageAssembly"]


@requires_dotnet
def test_old_style_project_restore_is_skipped_when_references_already_resolve(tmp_path) -> None:
    """Ticket 01: when every declared reference already resolves, restore never runs -- a
    project with a packages.config still reports available without needing a package fetch."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    project_dir = tmp_path / "AlreadyResolved"
    project_dir.mkdir()
    packages_dir = tmp_path / "packages" / "AlreadyThere.1.0.0" / "lib" / "net461"
    packages_dir.mkdir(parents=True)
    # Content does not need to be a real package assembly for this: STC's own SQLFunc.dll fixture
    # is already a real, loadable assembly used elsewhere in this suite.
    (packages_dir / "AlreadyThere.dll").write_bytes(SQLFUNC_DLL.read_bytes())

    (project_dir / "AlreadyResolved.csproj").write_text(
        """<Project ToolsVersion="15.0" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
  <ItemGroup>
    <Reference Include="AlreadyThere, Version=1.0.0.0">
      <HintPath>..\\packages\\AlreadyThere.1.0.0\\lib\\net461\\AlreadyThere.dll</HintPath>
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
    (project_dir / "packages.config").write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<packages>
  <package id="AlreadyThere" version="1.0.0" targetFramework="net461" />
</packages>
""",
        encoding="utf-8",
    )

    result = host.semantic_binding_availability([project_dir])

    assert len(result) == 1
    assert result[0]["availability"] == "available"
    assert result[0]["unresolved_references"] == []


@requires_dotnet
@requires_network
def test_old_style_project_restores_declared_package_before_compiling(tmp_path) -> None:
    """Ticket 01: a declared package missing from the clone is restored into the directory the
    reference's own HintPath points at, and the project reports available afterward."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    project_dir = tmp_path / "NeedsRestore"
    project_dir.mkdir()
    (project_dir / "NeedsRestore.csproj").write_text(
        """<Project ToolsVersion="15.0" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
  <ItemGroup>
    <Reference Include="System.Buffers, Version=4.0.3.0, Culture=neutral, PublicKeyToken=cc7b13ffcd2ddd51">
      <HintPath>..\\packages\\System.Buffers.4.5.1\\lib\\net461\\System.Buffers.dll</HintPath>
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
    (project_dir / "packages.config").write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<packages>
  <package id="System.Buffers" version="4.5.1" targetFramework="net461" />
</packages>
""",
        encoding="utf-8",
    )

    result = host.semantic_binding_availability([project_dir])

    assert len(result) == 1
    assert result[0]["availability"] == "available"
    assert result[0]["unresolved_references"] == []
    restored_dll = (
        tmp_path / "packages" / "System.Buffers.4.5.1" / "lib" / "net461" / "System.Buffers.dll"
    )
    assert restored_dll.exists()


@requires_dotnet
@requires_network
def test_old_style_project_names_the_cause_when_restore_fails(tmp_path) -> None:
    """Ticket 01: a declared package that cannot be restored (here, one that does not exist on
    the feed) keeps the project unavailable and names the restore failure as the cause."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    project_dir = tmp_path / "RestoreFails"
    project_dir.mkdir()
    (project_dir / "RestoreFails.csproj").write_text(
        """<Project ToolsVersion="15.0" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
  <ItemGroup>
    <Reference Include="TotallyNotARealNuGetPackage, Version=1.0.0.0">
      <HintPath>..\\packages\\TotallyNotARealNuGetPackage.1.0.0\\lib\\net461\\TotallyNotARealNuGetPackage.dll</HintPath>
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
    (project_dir / "packages.config").write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<packages>
  <package id="TotallyNotARealNuGetPackage" version="1.0.0" targetFramework="net461" />
</packages>
""",
        encoding="utf-8",
    )

    result = host.semantic_binding_availability([project_dir])

    assert len(result) == 1
    assert result[0]["availability"] == "unavailable_reference_resolution_failed"
    unresolved = result[0]["unresolved_references"]
    assert "TotallyNotARealNuGetPackage" in unresolved
    assert any("package_restore_failed" in entry for entry in unresolved)


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


@requires_dotnet
@requires_ydocs_fixture
@requires_network
def test_semantic_binding_reports_available_for_real_ttpur_project() -> None:
    """Ticket 01 end-to-end smoke test: the dominant Y-DOCs WebForms scan root (TTPUR) declares
    31 package references that a fresh clone never restored. Restoring its packages.config
    before compiling must resolve every one of them, with no unresolved references left."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    scan_root = TTPUR_CSPROJ.parent
    result = host.semantic_binding_availability([scan_root])

    matching = [entry for entry in result if entry["project_file"] == str(TTPUR_CSPROJ)]
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
