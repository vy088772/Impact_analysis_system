"""Ticket 02: decompile an unresolved external wrapper DLL into classified facts."""

from __future__ import annotations

import hashlib
import sys
import tempfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from code_analyzer.static_analyzer_host import StaticAnalyzerHost

STC_CSPROJ = PROJECT_ROOT / "data" / "repos" / "System_Dept_1" / "STC" / "STC" / "STC.csproj"
SQLFUNC_DLL = STC_CSPROJ.parent / "bin" / "SQLFunc.dll"

requires_stc_fixture = pytest.mark.skipif(
    not (STC_CSPROJ.exists() and SQLFUNC_DLL.exists()),
    reason="local data/repos/System_Dept_1/STC fixture checkout is not present",
)


def _definitions_by_method(wrapper_definitions: list[dict], method_name: str) -> list[dict]:
    return [d for d in wrapper_definitions if d["method_name"] == method_name]


@requires_stc_fixture
def test_decompile_wrapper_classifies_sqlfunc_dll_end_to_end() -> None:
    """Smoke test: the real StaticAnalyzerHost decompiles SQLFunc.dll and classifies it
    exactly like local wrapper source, keeping Fill distinct from ExecuteReader."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    result = host.decompile_wrapper(STC_CSPROJ, "SQLFunc")

    assert result["status"] == "resolved"
    assert result["dll_path"] == str(SQLFUNC_DLL.resolve())
    assert result["translation_problem_methods"] == []
    assert result["assembly_identity"] == hashlib.sha256(SQLFUNC_DLL.read_bytes()).hexdigest()

    definitions = result["wrapper_definitions"]
    assert len(definitions) > 0
    for definition in definitions:
        assert definition["assembly_identity"] == result["assembly_identity"]
        assert definition["unresolved_reason"] is None

    create_adapter = _definitions_by_method(definitions, "CreateAdapter")[0]
    assert create_adapter["method_semantics"] == "fixed_stored_procedure"

    create_adapter_tsql = _definitions_by_method(definitions, "CreateAdapterTsql")[0]
    assert create_adapter_tsql["method_semantics"] == "fixed_inline_sql"

    fill_sink_methods = _definitions_by_method(definitions, "ExeTable")
    assert fill_sink_methods and all(d["terminal_sink"] == "Fill" for d in fill_sink_methods)

    reader_sink_methods = _definitions_by_method(definitions, "ExeProcRead")
    assert reader_sink_methods and all(d["terminal_sink"] == "ExecuteReader" for d in reader_sink_methods)


@requires_stc_fixture
def test_decompile_wrapper_leaves_untraceable_receiver_as_review_candidate() -> None:
    """A receiver type with no matching <Reference> stays a review candidate, not a best-effort decompile."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    result = host.decompile_wrapper(STC_CSPROJ, "SomeDynamicallyLoadedWrapper")

    assert result["status"] == "receiver_not_referenced"
    assert result["dll_path"] is None
    assert result["wrapper_definitions"] == []


def test_decompile_wrapper_reports_missing_csproj() -> None:
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    result = host.decompile_wrapper(Path("/tmp/does-not-exist-impact-analysis.csproj"), "SQLFunc")

    assert result["status"] == "csproj_not_found"
    assert result["wrapper_definitions"] == []


def test_decompile_wrapper_reports_referenced_dll_missing() -> None:
    """A <Reference>/<HintPath> pointing at a non-existent file is never scanned for elsewhere."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        csproj_path = Path(temp_dir) / "Fake.csproj"
        csproj_path.write_text(
            "<Project ToolsVersion=\"12.0\">\n"
            "  <ItemGroup>\n"
            "    <Reference Include=\"MissingWrapper, Version=1.0.0.0\">\n"
            "      <HintPath>bin\\MissingWrapper.dll</HintPath>\n"
            "    </Reference>\n"
            "  </ItemGroup>\n"
            "</Project>\n",
            encoding="utf-8",
        )

        result = host.decompile_wrapper(csproj_path, "MissingWrapper")

        assert result["status"] == "referenced_dll_missing"
        assert result["wrapper_definitions"] == []


def test_decompile_wrapper_reports_hint_path_missing_for_gac_reference() -> None:
    """A bare GAC-style <Reference> with no <HintPath> is never guessed at."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        csproj_path = Path(temp_dir) / "Fake.csproj"
        csproj_path.write_text(
            "<Project ToolsVersion=\"12.0\">\n"
            "  <ItemGroup>\n"
            "    <Reference Include=\"System\" />\n"
            "  </ItemGroup>\n"
            "</Project>\n",
            encoding="utf-8",
        )

        result = host.decompile_wrapper(csproj_path, "System")

        assert result["status"] == "hint_path_missing"
        assert result["wrapper_definitions"] == []


def test_decompile_wrapper_reports_decompile_failure_for_unreadable_dll() -> None:
    """A referenced file that is not a valid assembly fails gracefully with its own hash, not a crash."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        dll_bytes = b"not a real dll"
        (Path(temp_dir) / "Broken.dll").write_bytes(dll_bytes)
        csproj_path = Path(temp_dir) / "Fake.csproj"
        csproj_path.write_text(
            "<Project ToolsVersion=\"12.0\">\n"
            "  <ItemGroup>\n"
            "    <Reference Include=\"Broken, Version=1.0.0.0\">\n"
            "      <HintPath>Broken.dll</HintPath>\n"
            "    </Reference>\n"
            "  </ItemGroup>\n"
            "</Project>\n",
            encoding="utf-8",
        )

        result = host.decompile_wrapper(csproj_path, "Broken")

        assert result["status"] == "decompile_failed"
        assert result["assembly_identity"] == hashlib.sha256(dll_bytes).hexdigest()
        assert result["wrapper_definitions"] == []
