"""Ticket 02: decompile an unresolved external wrapper DLL into classified facts."""

from __future__ import annotations

import hashlib
import json
import shutil
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

requires_dotnet = pytest.mark.skipif(
    shutil.which("dotnet") is None,
    reason="the .NET toolchain is not available",
)

TTPUR_CSPROJ = (
    PROJECT_ROOT / "data" / "repos" / "System_Dept_1" / "Y-DOCs" / "TTPUR" / "TTPUR.csproj"
)
SQLOBJECT_DLL = TTPUR_CSPROJ.parent / "bin" / "SQLObject.dll"

requires_sqlobject_fixture = pytest.mark.skipif(
    not (TTPUR_CSPROJ.exists() and SQLOBJECT_DLL.exists()),
    reason="local data/repos/System_Dept_1/Y-DOCs/TTPUR fixture checkout is not present",
)


def _definitions_by_method(wrapper_definitions: list[dict], method_name: str) -> list[dict]:
    return [d for d in wrapper_definitions if d["method_name"] == method_name]


# The whole classified surface of SQLFunc.dll, keyed by method identity. Asserting the map
# whole keeps a new Command Source rule from quietly changing an unrelated method's facts.
SQLFUNC_CLASSIFIED_SURFACE = {
    "SQLFunc.EditData(string)": ("fixed_inline_sql", "ExecuteNonQuery"),
    "SQLFunc.EditData(string,System.Data.SqlClient.SqlParameter[])": ("fixed_inline_sql", "ExecuteNonQuery"),
    "SQLFunc.ExeProcNon(string)": ("fixed_stored_procedure", "ExecuteNonQuery"),
    "SQLFunc.ExeProcNon(string,System.Data.SqlClient.SqlParameter[])": ("fixed_stored_procedure", "ExecuteNonQuery"),
    "SQLFunc.ExeProcNon(string,System.Data.SqlClient.SqlParameter[],int)": ("fixed_stored_procedure", "ExecuteNonQuery"),
    "SQLFunc.ExeProcNonLong(string)": ("fixed_stored_procedure", "ExecuteNonQuery"),
    "SQLFunc.ExeProcNonLong(string,System.Data.SqlClient.SqlParameter[])": ("fixed_stored_procedure", "ExecuteNonQuery"),
    "SQLFunc.CreateReader(string)": ("fixed_inline_sql", "ExecuteReader"),
    "SQLFunc.CreateReader(string,System.Data.SqlClient.SqlParameter)": ("fixed_inline_sql", "ExecuteReader"),
    "SQLFunc.CreateReader(string,System.Data.SqlClient.SqlParameter[])": ("fixed_inline_sql", "ExecuteReader"),
    "SQLFunc.ExeProcRead(string)": ("fixed_stored_procedure", "ExecuteReader"),
    "SQLFunc.ExeProcRead(string,System.Data.SqlClient.SqlParameter)": ("fixed_stored_procedure", "ExecuteReader"),
    "SQLFunc.ExeProcRead(string,System.Data.SqlClient.SqlParameter[])": ("fixed_stored_procedure", "ExecuteReader"),
    "SQLFunc.ExeProcReadLong(string,System.Data.SqlClient.SqlParameter[])": ("fixed_stored_procedure", "ExecuteReader"),
    "SQLFunc.CreateTable(string,string)": ("fixed_inline_sql", "Fill"),
    "SQLFunc.CreateTable(string,System.Data.SqlClient.SqlParameter,string)": ("fixed_inline_sql", "Fill"),
    "SQLFunc.CreateTable(string,System.Data.SqlClient.SqlParameter[],string)": ("fixed_inline_sql", "Fill"),
    "SQLFunc.ExeTable(string,string)": ("fixed_stored_procedure", "Fill"),
    "SQLFunc.ExeTable(string,System.Data.SqlClient.SqlParameter[],string)": ("fixed_stored_procedure", "Fill"),
    "SQLFunc.CreateAdapterTsql(string)": ("fixed_inline_sql", None),
    "SQLFunc.CreateAdapter(string)": ("fixed_stored_procedure", None),
    "SQLFunc.CreateAdapter(string,System.Data.SqlClient.SqlParameter[])": ("fixed_stored_procedure", None),
    "SQLFunc.ExeProcDataSet(string)": ("fixed_stored_procedure", "Fill"),
    "SQLFunc.ExeProcDataSet(string,System.Data.SqlClient.SqlParameter[])": ("fixed_stored_procedure", "Fill"),
    "SQLFunc.GetFirstValue(string)": ("fixed_inline_sql", "ExecuteScalar"),
    "SQLFunc.GetFirstValue(string,System.Data.SqlClient.SqlParameter)": ("fixed_inline_sql", "ExecuteScalar"),
    "SQLFunc.GetFirstValue(string,System.Data.SqlClient.SqlParameter[])": ("fixed_inline_sql", "ExecuteScalar"),
}


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
    assert snapshot["public_database_operations_complete"] is True
    assert snapshot["unclassified_public_methods"] == []
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


@requires_dotnet
@requires_stc_fixture
def test_decompile_wrapper_classifies_every_public_create_table_overload() -> None:
    """The two-argument CreateTable builds its command through a data adapter, not a command
    object; it is a database operation all the same, and the other methods are untouched."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    result = host.decompile_wrapper(STC_CSPROJ, "SQLFunc", rerun=True)

    assert result["status"] == "resolved"
    definitions = result["wrapper_definitions"]

    create_table = _definitions_by_method(definitions, "CreateTable")
    assert len(create_table) == 3
    two_argument = [d for d in create_table if len(d["parameter_types"]) == 2]
    assert len(two_argument) == 1
    assert two_argument[0]["parameter_types"] == ["string", "string"]
    assert two_argument[0]["method_semantics"] == "fixed_inline_sql"
    assert two_argument[0]["terminal_sink"] == "Fill"
    assert two_argument[0]["unresolved_reason"] is None

    classified_surface = {
        definition["method_identity"]: (
            definition["method_semantics"],
            definition["terminal_sink"],
        )
        for definition in definitions
    }
    assert classified_surface == SQLFUNC_CLASSIFIED_SURFACE

    operations = result["contract_proposals"][0]["implementation_snapshot"]["methods"]
    two_argument_operation = next(
        operation
        for operation in operations
        if operation["method_identity"] == "SQLFunc.CreateTable(string,string)"
    )
    assert two_argument_operation["effective_command_semantics"] == "inline_sql"
    assert two_argument_operation["terminal_sink"] == "Fill"


def _build_unclassified_method_dll(build_dir: Path) -> Path:
    """Compile a tiny classlib whose `Wrapper` type holds one method the Command Source
    resolver cannot classify (a data adapter built and filled inline, bound to no variable —
    the known limit ticket 01 left for this ticket) alongside one non-database method.

    The `SqlConnection`/`SqlCommand`/`SqlDataAdapter` types here are stand-ins declared in the
    same file, not the real System.Data.SqlClient types: the decompiler's ADO.NET and Command
    Source recognition match by syntactic type name only, so this exercises the exact same path
    without needing an external ADO.NET package reference.
    """
    build_dir.mkdir(parents=True, exist_ok=True)
    (build_dir / "Wrapper.csproj").write_text(
        "<Project Sdk=\"Microsoft.NET.Sdk\">\n"
        "  <PropertyGroup>\n"
        "    <TargetFramework>net8.0</TargetFramework>\n"
        "    <AssemblyName>Wrapper</AssemblyName>\n"
        "    <Nullable>disable</Nullable>\n"
        "  </PropertyGroup>\n"
        "</Project>\n",
        encoding="utf-8",
    )
    (build_dir / "Wrapper.cs").write_text(
        "public class SqlConnection { public SqlConnection(string cn) {} }\n"
        "public class SqlCommand {\n"
        "    public SqlCommand(string sql, SqlConnection conn) {}\n"
        "    public object CommandType;\n"
        "}\n"
        "public class SqlDataAdapter {\n"
        "    public SqlDataAdapter(string sql, SqlConnection conn) {}\n"
        "    public SqlDataAdapter(SqlCommand cmd) {}\n"
        "    public SqlCommand SelectCommand;\n"
        "    public void Fill(object dataSet) {}\n"
        "}\n"
        "public class Wrapper {\n"
        "    public void Save(string sql, SqlConnection conn) {\n"
        "        new SqlDataAdapter(sql, conn).Fill(new object());\n"
        "    }\n"
        "    public string Format(string input) {\n"
        "        return input.Trim();\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    bin_dir = build_dir / "bin"
    result = subprocess.run(
        [
            "dotnet",
            "build",
            str(build_dir / "Wrapper.csproj"),
            "-c",
            "Release",
            "-o",
            str(bin_dir),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return bin_dir / "Wrapper.dll"


@requires_dotnet
def test_decompile_wrapper_reports_unclassified_public_method_and_preflight_rejects_it() -> None:
    """Ticket 02: a public method that touches an ADO.NET type but yields no Command Source is
    recorded as unclassified, the surface is reported incomplete, and Contract Preflight rejects
    the snapshot instead of accepting a contract with a silent gap."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        wrapper_dll = _build_unclassified_method_dll(root / "wrapperlib")
        csproj_path = _write_referenced_dll_project(root, "Wrapper", wrapper_dll.read_bytes())

        result = host.decompile_wrapper(csproj_path, "Wrapper", cache_root=root / "cache")

    assert result["status"] == "resolved"
    definitions = result["wrapper_definitions"]
    assert _definitions_by_method(definitions, "Save") == []
    assert _definitions_by_method(definitions, "Format") == []

    snapshot = result["contract_proposals"][0]["implementation_snapshot"]
    assert snapshot["public_database_operations_complete"] is False
    assert snapshot["unclassified_public_methods"] == ["Wrapper.Save(string,SqlConnection)"]

    assert validate_implementation_snapshot(snapshot)["complete"] is False
    preflight = run_contract_preflight(
        [SimpleNamespace(contract_proposals=result["contract_proposals"])],
        registry={"contracts": {}},
    )
    assert preflight.onboarding_status != "created"
    assert "wrapper" not in preflight.formal_registry.get("contracts", {})
    reasons = preflight.review_candidates[0]["unresolved_reasons"]
    assert (
        "unclassified_public_method:Wrapper.Save(string,SqlConnection)" in reasons
    )


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


@requires_sqlobject_fixture
def test_implementation_snapshot_operation_carries_required_parameter_count() -> None:
    """A trailing optional parameter survives into the Implementation Snapshot.

    `SQLObject.CreateDataSet(string, SqlParameter[], string, int)` declares four
    parameters and requires three -- a three-argument call still binds to it. The
    wrapper definition already knows that; overload selection reads the snapshot,
    so the count has to reach the snapshot or the registry can never express it.
    """
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    # A private cache root: the shared one is keyed by assembly identity alone, so it
    # would serve a response recorded by an older build of the host.
    with tempfile.TemporaryDirectory() as temp_dir:
        result = host.decompile_wrapper(
            TTPUR_CSPROJ, "SQLObject", cache_root=Path(temp_dir)
        )

    assert result["status"] == "resolved"
    definition = next(
        definition
        for definition in result["wrapper_definitions"]
        if definition["method_identity"]
        == "SQLObject.CreateDataSet(string,System.Data.SqlClient.SqlParameter[],string,int)"
    )
    assert definition["required_parameter_count"] == 3

    operation = next(
        operation
        for operation in result["contract_proposals"][0]["implementation_snapshot"]["methods"]
        if operation["method_identity"]
        == "SQLObject.CreateDataSet(string,System.Data.SqlClient.SqlParameter[],string,int)"
    )
    assert operation["method_arity"] == 4
    assert operation["required_parameter_count"] == 3
