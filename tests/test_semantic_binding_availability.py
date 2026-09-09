"""Ticket 05: build a compilation per project and report Semantic Binding Availability.

The analyzer host previously performed no semantic analysis: it read syntax trees alone. This
ticket adds a compilation per scanned project and reports the result of that attempt as a named
state — Semantic Binding Availability — so a degraded analysis never looks like a confident one.
Classification results (db_invocations etc.) are untouched by this ticket; that is covered
separately by tests/test_wrapper_decompilation.py and tests/test_csharp_analysis_gateway.py.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
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
def test_semantic_binding_reports_unavailable_for_sdk_style_project_with_no_source_files() -> None:
    """Ticket 02: a project that yields no source files at all holds an empty compilation, and
    an empty compilation must never read as an empty-but-successful one: it reports unavailable,
    and names why, so a maintainer can tell this apart from a project that failed to parse.
    Ticket 05 taught the reader to glob an SDK-style project's source, so this project now has
    to hold no source file for the case to arise at all."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as scan_root:
        project_dir = Path(scan_root)
        (project_dir / "CoreApp.csproj").write_text(
            """<Project Sdk="Microsoft.NET.Sdk.Web">
  <PropertyGroup>
    <TargetFramework>net6.0</TargetFramework>
  </PropertyGroup>
</Project>
""",
            encoding="utf-8",
        )

        result = host.semantic_binding_availability([project_dir])

    assert len(result) == 1
    entry = result[0]
    assert entry["availability"] == "unavailable_reference_resolution_failed"
    assert entry["project_file"] == str(project_dir / "CoreApp.csproj")
    assert any("no_compile_items" in reason for reason in entry["unresolved_references"])


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


# --- Ticket 05: SDK-style projects compile -------------------------------------------------
#
# An SDK-style project declares no explicit <Compile> items: its source files come from
# implicit globbing, and its references from package references resolved through the
# project's restore assets. Ticket 02 made such a project report unavailable rather than
# pretend; this ticket gives it a real semantic model instead.

SDK_TARGET_FRAMEWORK = "net8.0"


def _sdk_project(directory: Path, name: str, body: str = "") -> Path:
    """Writes a minimal SDK-style project file and returns its path."""
    project_file = directory / f"{name}.csproj"
    project_file.write_text(
        f"""<Project Sdk="Microsoft.NET.Sdk.Web">
  <PropertyGroup>
    <TargetFramework>{SDK_TARGET_FRAMEWORK}</TargetFramework>
  </PropertyGroup>
{body}</Project>
""",
        encoding="utf-8",
    )
    return project_file


@requires_dotnet
@requires_network
def test_sdk_style_source_files_come_from_implicit_globbing(tmp_path) -> None:
    """An SDK-style project declares no <Compile> items at all. Its source files come from
    implicit globbing over its own directory, so a file in a subdirectory counts too, and
    the build output directories never do."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    project_dir = tmp_path / "Globbed"
    project_dir.mkdir()
    _sdk_project(project_dir, "Globbed")
    (project_dir / "Root.cs").write_text("public class Root { }", encoding="utf-8")
    (project_dir / "Controllers").mkdir()
    (project_dir / "Controllers" / "HomeController.cs").write_text(
        "public class HomeController { }", encoding="utf-8"
    )
    # Build output: MSBuild's own default excludes drop these, and so must this reader --
    # otherwise a stale copy of a type would be compiled beside the type itself.
    (project_dir / "obj" / "Debug").mkdir(parents=True)
    (project_dir / "obj" / "Debug" / "Stale.cs").write_text(
        "public class Stale { }", encoding="utf-8"
    )
    (project_dir / "bin").mkdir()
    (project_dir / "bin" / "AlsoStale.cs").write_text(
        "public class AlsoStale { }", encoding="utf-8"
    )

    result = host.semantic_binding_availability([project_dir])

    assert len(result) == 1
    entry = result[0]
    assert entry["availability"] == "available", entry["unresolved_references"]
    assert entry["source_file_count"] == 2


@requires_dotnet
@requires_network
def test_sdk_style_removal_item_excludes_the_directory_it_names(tmp_path) -> None:
    """A <Compile Remove> item names files the implicit glob would otherwise have found.
    An excluded directory contributes no source at all -- the real IQCS project removes two
    such directories, and compiling them would fail on source that project never builds."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    project_dir = tmp_path / "Removed"
    project_dir.mkdir()
    _sdk_project(
        project_dir,
        "Removed",
        '  <ItemGroup>\n    <Compile Remove="HisFiles\\**" />\n  </ItemGroup>\n',
    )
    (project_dir / "Kept.cs").write_text("public class Kept { }", encoding="utf-8")
    (project_dir / "HisFiles" / "Deep").mkdir(parents=True)
    (project_dir / "HisFiles" / "Dropped.cs").write_text(
        "public class Dropped { }", encoding="utf-8"
    )
    (project_dir / "HisFiles" / "Deep" / "AlsoDropped.cs").write_text(
        "public class AlsoDropped { }", encoding="utf-8"
    )

    result = host.semantic_binding_availability([project_dir])

    assert len(result) == 1
    entry = result[0]
    assert entry["availability"] == "available", entry["unresolved_references"]
    assert entry["source_file_count"] == 1


@requires_dotnet
@requires_network
def test_sdk_style_package_references_resolve_through_restore_assets(tmp_path) -> None:
    """A package reference names no file on disk. It resolves through the project's restore
    assets, which name the exact package folder and the exact compile-time assembly inside
    it -- so a project declaring one reports available with nothing unresolved."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    project_dir = tmp_path / "HasPackage"
    project_dir.mkdir()
    _sdk_project(
        project_dir,
        "HasPackage",
        '  <ItemGroup>\n'
        '    <PackageReference Include="Newtonsoft.Json" Version="13.0.3" />\n'
        '  </ItemGroup>\n',
    )
    (project_dir / "Program.cs").write_text(
        "public class Program { public static void Main() { } }", encoding="utf-8"
    )

    result = host.semantic_binding_availability([project_dir])

    assert len(result) == 1
    entry = result[0]
    assert entry["availability"] == "available", entry["unresolved_references"]
    assert entry["unresolved_references"] == []


@requires_dotnet
def test_sdk_style_project_carrying_restore_assets_is_not_restored_again(tmp_path) -> None:
    """A project that already carries restore assets reports available with no restore run.
    The proof is behavioural: this project's only package reference names a package that
    exists on no feed, while its hand-written assets resolve it to a real assembly on disk.
    A restore would have failed, so reporting available means none was run -- and the assets
    file is left exactly as it was found."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    package_folder = tmp_path / "packages"
    package_lib = package_folder / "notarealpackage" / "1.0.0" / "lib" / SDK_TARGET_FRAMEWORK
    package_lib.mkdir(parents=True)
    # Content only has to be a loadable assembly; STC's SQLFunc.dll fixture already is one.
    (package_lib / "NotARealPackage.dll").write_bytes(SQLFUNC_DLL.read_bytes())

    project_dir = tmp_path / "AlreadyRestored"
    project_dir.mkdir()
    _sdk_project(
        project_dir,
        "AlreadyRestored",
        '  <ItemGroup>\n'
        '    <PackageReference Include="NotARealPackage" Version="1.0.0" />\n'
        '  </ItemGroup>\n',
    )
    (project_dir / "Program.cs").write_text("public class Program { }", encoding="utf-8")

    assets_file = project_dir / "obj" / "project.assets.json"
    assets_file.parent.mkdir()
    assets_file.write_text(
        json.dumps(
            {
                "version": 3,
                "targets": {
                    SDK_TARGET_FRAMEWORK: {
                        "NotARealPackage/1.0.0": {
                            "type": "package",
                            "compile": {
                                f"lib/{SDK_TARGET_FRAMEWORK}/NotARealPackage.dll": {}
                            },
                        }
                    }
                },
                "libraries": {
                    "NotARealPackage/1.0.0": {
                        "type": "package",
                        "path": "notarealpackage/1.0.0",
                    }
                },
                "packageFolders": {str(package_folder): {}},
                # No framework references: this fixture proves only that no restore ran. The
                # framework-reference path is covered by the restore test and by the real
                # IQCS smoke test below.
                "project": {
                    "frameworks": {
                        SDK_TARGET_FRAMEWORK: {
                            "targetAlias": SDK_TARGET_FRAMEWORK,
                            "frameworkReferences": {},
                            "downloadDependencies": [],
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    assets_before = assets_file.read_bytes()

    result = host.semantic_binding_availability([project_dir])

    assert len(result) == 1
    entry = result[0]
    assert entry["availability"] == "available", entry["unresolved_references"]
    assert assets_file.read_bytes() == assets_before


@requires_dotnet
@requires_network
def test_sdk_style_project_without_restore_assets_is_restored_once(tmp_path) -> None:
    """A project with no restore assets is restored once, and only then reports available.
    A fresh clone never carries an obj directory, so this is the state every measured
    ASP.NET Core repository starts in."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    project_dir = tmp_path / "NeedsRestore"
    project_dir.mkdir()
    _sdk_project(
        project_dir,
        "NeedsRestore",
        '  <ItemGroup>\n'
        '    <PackageReference Include="Newtonsoft.Json" Version="13.0.3" />\n'
        '  </ItemGroup>\n',
    )
    (project_dir / "Program.cs").write_text("public class Program { }", encoding="utf-8")
    assets_file = project_dir / "obj" / "project.assets.json"
    assert not assets_file.exists()

    result = host.semantic_binding_availability([project_dir])

    assert len(result) == 1
    assert result[0]["availability"] == "available", result[0]["unresolved_references"]
    assert assets_file.exists()


@requires_dotnet
def test_sdk_style_project_names_the_cause_when_no_dotnet_sdk_is_available(tmp_path) -> None:
    """With no .NET SDK to restore with, the project reports
    unavailable_reference_resolution_failed and names that as the cause -- never a silent
    empty compilation. DOTNET_ROOT is the documented way to name a .NET installation, so
    pointing it at a directory holding none is exactly the "no SDK" condition."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    project_dir = tmp_path / "NoSdk"
    project_dir.mkdir()
    _sdk_project(project_dir, "NoSdk")
    (project_dir / "Program.cs").write_text("public class Program { }", encoding="utf-8")
    empty_root = tmp_path / "no-dotnet-here"
    empty_root.mkdir()

    completed = subprocess.run(
        [
            "dotnet",
            str(host.dll_path),
            "semantic-binding",
            "--source-root",
            str(project_dir),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "DOTNET_ROOT": str(empty_root)},
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)

    result = payload["semantic_binding_availability"]
    assert len(result) == 1
    entry = result[0]
    assert entry["availability"] == "unavailable_reference_resolution_failed"
    assert any("no_dotnet_sdk" in reason for reason in entry["unresolved_references"])


@requires_dotnet
@requires_network
def test_sdk_style_project_names_the_cause_when_restore_fails(tmp_path) -> None:
    """A restore that fails keeps the project unavailable and names the restore failure, so
    a maintainer can tell a broken restore apart from a missing SDK."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    project_dir = tmp_path / "RestoreFails"
    project_dir.mkdir()
    _sdk_project(
        project_dir,
        "RestoreFails",
        '  <ItemGroup>\n'
        '    <PackageReference Include="TotallyNotARealNuGetPackage" Version="1.0.0" />\n'
        '  </ItemGroup>\n',
    )
    (project_dir / "Program.cs").write_text("public class Program { }", encoding="utf-8")

    result = host.semantic_binding_availability([project_dir])

    assert len(result) == 1
    entry = result[0]
    assert entry["availability"] == "unavailable_reference_resolution_failed"
    assert any("restore_failed" in reason for reason in entry["unresolved_references"])


@requires_dotnet
@requires_network
def test_sdk_style_project_reference_stays_unresolved(tmp_path) -> None:
    """A <ProjectReference> names another project's own output, which this ticket does not
    build. The referencing project reports unavailable and names it, exactly as an old-style
    project already does -- an incomplete compilation must never claim available."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    project_dir = tmp_path / "DependsOnOther"
    project_dir.mkdir()
    _sdk_project(
        project_dir,
        "DependsOnOther",
        '  <ItemGroup>\n'
        '    <ProjectReference Include="..\\OtherLib\\OtherLib.csproj" />\n'
        '  </ItemGroup>\n',
    )
    (project_dir / "Program.cs").write_text("public class Program { }", encoding="utf-8")

    result = host.semantic_binding_availability([project_dir])

    assert len(result) == 1
    entry = result[0]
    assert entry["availability"] == "unavailable_reference_resolution_failed"
    assert "OtherLib" in entry["unresolved_references"]


IQCS_CSPROJ = PROJECT_ROOT / "data" / "repos" / "System_Dept_1" / "IQCS" / "IQCS.csproj"

requires_iqcs_fixture = pytest.mark.skipif(
    not IQCS_CSPROJ.exists(),
    reason="local data/repos/System_Dept_1/IQCS fixture checkout is not present",
)


@requires_dotnet
@requires_iqcs_fixture
@requires_network
def test_semantic_binding_reports_available_for_real_iqcs_project() -> None:
    """End-to-end smoke test against the real IQCS project, the measured single-project
    ASP.NET Core repository: 23 package references, two removed directories, and one
    external assembly reference in its own build output. It reported available while
    holding an empty compilation before ticket 02, unavailable after it, and now reports
    available holding real source.

    The second pass is the measured half of "a project that already carries restore assets
    reports available with no restore run": the first pass leaves the assets behind, and the
    second must report the same answer without touching them."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    result = host.semantic_binding_availability([IQCS_CSPROJ.parent])

    matching = [entry for entry in result if entry["project_file"] == str(IQCS_CSPROJ)]
    assert len(matching) == 1
    assert matching[0]["availability"] == "available", matching[0]["unresolved_references"]
    assert matching[0]["unresolved_references"] == []
    assert matching[0]["source_file_count"] > 0

    assets_file = IQCS_CSPROJ.parent / "obj" / "project.assets.json"
    assert assets_file.exists(), "the first pass must have restored this project"
    restored_at = assets_file.stat().st_mtime_ns

    again = [
        entry
        for entry in host.semantic_binding_availability([IQCS_CSPROJ.parent])
        if entry["project_file"] == str(IQCS_CSPROJ)
    ]
    assert again[0]["availability"] == "available", again[0]["unresolved_references"]
    assert assets_file.stat().st_mtime_ns == restored_at


RTTALENTDB_ROOT = PROJECT_ROOT / "data" / "repos" / "System_Dept_1" / "RTTalentDB"
RTTALENTDB_CSPROJ = RTTALENTDB_ROOT / "RTTalentDB" / "RTTalentDB.csproj"
RTTALENTDB_APP_CSPROJ = RTTALENTDB_ROOT / "RTTalentDBMailJobApp" / "RTTalentDBMailJobApp.csproj"

requires_rttalentdb_fixture = pytest.mark.skipif(
    not RTTALENTDB_CSPROJ.exists(),
    reason="local data/repos/System_Dept_1/RTTalentDB fixture checkout is not present",
)


@requires_dotnet
@requires_rttalentdb_fixture
@requires_network
def test_semantic_binding_reports_each_project_of_the_real_rttalentdb_repository() -> None:
    """End-to-end smoke test against the real RTTalentDB repository, the measured
    multi-project ASP.NET Core shape: three project files, one attempt each. The web project
    reports available over its own source; the job app depends on a sibling project this
    ticket does not build, so it reports unavailable and names that sibling. One repository
    therefore reports two different states, which is the point of reporting per project."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    result = host.semantic_binding_availability([RTTALENTDB_ROOT])
    by_project = {entry["project_file"]: entry for entry in result}

    web = by_project[str(RTTALENTDB_CSPROJ)]
    assert web["availability"] == "available", web["unresolved_references"]
    assert web["source_file_count"] > 0

    job_app = by_project[str(RTTALENTDB_APP_CSPROJ)]
    assert job_app["availability"] == "unavailable_reference_resolution_failed"
    assert "RTTalentDBMailJobAPI" in job_app["unresolved_references"]
