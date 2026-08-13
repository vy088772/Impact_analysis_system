"""Ticket 02: decompile an unresolved external wrapper DLL into classified facts."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from code_analyzer.external_wrapper_contracts import validate_implementation_snapshot
from code_analyzer.static_analyzer_host import StaticAnalyzerHost
from service.contract_preflight import run_contract_preflight

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

    with tempfile.TemporaryDirectory() as cache_dir:
        result = host.decompile_wrapper(
            STC_CSPROJ,
            "SQLFunc",
            cache_root=Path(cache_dir),
        )
        cached = host.decompile_wrapper(
            STC_CSPROJ,
            "SQLFunc",
            cache_root=Path(cache_dir),
        )

    assert result["status"] == "resolved"
    assert result["attempt_outcome"] == "complete"
    assert result["cache_status"] == "miss"
    assert cached["attempt_outcome"] == "complete"
    assert cached["cache_status"] == "hit"
    assert cached["contract_proposals"] == result["contract_proposals"]
    assert result["dll_path"] == str(SQLFUNC_DLL.resolve())
    assert result["translation_problem_methods"] == []
    assert result["assembly_identity"] == hashlib.sha256(SQLFUNC_DLL.read_bytes()).hexdigest()

    definitions = result["wrapper_definitions"]
    assert len(definitions) > 0
    for definition in definitions:
        assert definition["assembly_identity"] == result["assembly_identity"]
        assert definition["unresolved_reason"] is None

    proposals = result["contract_proposals"]
    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal["name"] == "SQLFunc"
    assert proposal["receiver_types"] == ["SQLFunc"]
    snapshot = proposal["implementation_snapshot"]
    assert snapshot["artifact_identity"].endswith(
        f"@sha256:{result['assembly_identity']}"
    )
    assert snapshot["assembly_identity"] == result["assembly_identity"]
    assert snapshot["assembly_revision"] == result["assembly_identity"]
    assert snapshot["behavior_surface_unit"] == "SQLFunc"
    assert validate_implementation_snapshot(snapshot)["complete"] is True
    preflight = run_contract_preflight(
        [SimpleNamespace(contract_proposals=result["contract_proposals"])],
        registry={"contracts": {}},
    )
    assert preflight.onboarding_status == "created"
    assert preflight.formal_selector == "sqlfunc"

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


def _write_referenced_dll_project(
    root: Path,
    assembly_name: str,
    dll_bytes: bytes,
) -> Path:
    dll_path = root / f"{assembly_name}.dll"
    dll_path.write_bytes(dll_bytes)
    csproj_path = root / "Fake.csproj"
    csproj_path.write_text(
        "<Project ToolsVersion=\"12.0\">\n"
        "  <ItemGroup>\n"
        f"    <Reference Include=\"{assembly_name}, Version=1.0.0.0\">\n"
        f"      <HintPath>{dll_path.name}</HintPath>\n"
        "    </Reference>\n"
        "  </ItemGroup>\n"
        "</Project>\n",
        encoding="utf-8",
    )
    return csproj_path


def test_decompile_wrapper_caches_failed_attempt_by_dll_hash_and_supports_rerun() -> None:
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        cache_root = root / "decompilation-cache"
        csproj_path = _write_referenced_dll_project(root, "Broken", b"not a real dll")

        first = host.decompile_wrapper(csproj_path, "Broken", cache_root=cache_root)
        assert first["status"] == "decompile_failed"
        assert first["attempt_outcome"] == "incomplete"
        assert first["cache_status"] == "miss"

        cached = host.decompile_wrapper(csproj_path, "Broken", cache_root=cache_root)
        assert cached["status"] == first["status"]
        assert cached["assembly_identity"] == first["assembly_identity"]
        assert cached["attempt_outcome"] == "incomplete"
        assert cached["cache_status"] == "hit"
        assert cached["decompilation_attempt"]["attempted"] is False

        rerun = host.decompile_wrapper(
            csproj_path,
            "Broken",
            rerun=True,
            cache_root=cache_root,
        )
        assert rerun["status"] == "decompile_failed"
        assert rerun["attempt_outcome"] == "incomplete"
        assert rerun["cache_status"] == "bypassed"
        assert rerun["decompilation_attempt"]["attempted"] is True

        (root / "Broken.dll").write_bytes(b"a different invalid dll")
        changed = host.decompile_wrapper(csproj_path, "Broken", cache_root=cache_root)
        assert changed["status"] == "decompile_failed"
        assert changed["attempt_outcome"] == "incomplete"
        assert changed["cache_status"] == "miss"
        assert changed["assembly_identity"] != first["assembly_identity"]
        assert changed["decompilation_attempt"]["attempted"] is True
        assert (cache_root / f"{changed['assembly_identity']}.json").exists()

        client_cache_path = cache_root / f"{changed['assembly_identity']}.json"
        client_cache_path.unlink()
        host_cached = host.decompile_wrapper(csproj_path, "Broken", cache_root=cache_root)
        assert host_cached["cache_status"] == "hit"
        assert host_cached["decompilation_attempt"]["attempted"] is False


def test_decompile_wrapper_marks_unattempted_resolution_as_not_attempted() -> None:
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        result = host.decompile_wrapper(
            Path("/tmp/does-not-exist-impact-analysis.csproj"),
            "SQLFunc",
            cache_root=Path(temp_dir),
        )

    assert result["status"] == "csproj_not_found"
    assert result["attempt_outcome"] == "not_attempted"
    assert result["cache_status"] == "not_applicable"


def test_decompile_wrapper_console_command_caches_and_supports_rerun() -> None:
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        cache_root = root / "decompilation-cache"
        csproj_path = _write_referenced_dll_project(root, "Broken", b"not a real dll")

        def run_command(*extra_args: str) -> dict:
            result = subprocess.run(
                [
                    "dotnet",
                    str(host.dll_path),
                    "decompile-wrapper",
                    "--csproj",
                    str(csproj_path),
                    "--receiver-type",
                    "Broken",
                    "--cache-root",
                    str(cache_root),
                    *extra_args,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            assert result.returncode == 0, result.stderr
            return json.loads(result.stdout)

        first = run_command()
        cached = run_command()
        rerun = run_command("--rerun")
        (root / "Broken.dll").write_bytes(b"a different invalid dll")
        changed = run_command()

        assert first["cache_status"] == "miss"
        assert cached["cache_status"] == "hit"
        assert rerun["cache_status"] == "bypassed"
        assert changed["cache_status"] == "miss"
        assert changed["assembly_identity"] != first["assembly_identity"]
        assert first["attempt_outcome"] == cached["attempt_outcome"] == rerun["attempt_outcome"] == "incomplete"
