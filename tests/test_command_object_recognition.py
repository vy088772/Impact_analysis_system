"""Ticket 01: a command object declared as an abstract or provider type resolves its
Command Source.

The command-object recognition rule used to compare a type's short name against exactly one
name (`SqlCommand`). Its sibling, the data adapter rule, has always compared against a
multi-provider list. This widens the command rule to the same list shape -- adding the
abstract `DbCommand` type alongside the provider-specific ones -- and teaches the resolver to
recognize a command obtained through a factory call (e.g. a connection's `CreateCommand()`)
and bound to a locally declared variable, not only one built with `new`.

These tests assert the externally observable fact (a wrapper method's reported mode and
terminal sink, and the classified/unclassified sets a decompiled assembly reports), not the
shape of the resolver itself, per this repo's testing conventions.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from code_analyzer.static_analyzer_host import StaticAnalyzerHost

requires_dotnet = pytest.mark.skipif(
    shutil.which("dotnet") is None,
    reason="the .NET toolchain is not available",
)

IQCS_CSPROJ = PROJECT_ROOT / "data" / "repos" / "System_Dept_1" / "IQCS" / "IQCS.csproj"
COMMONLIBRARY_DLL = IQCS_CSPROJ.parent / "bin" / "Debug" / "net6.0" / "CommonLibrary.dll"

requires_iqcs_fixture = pytest.mark.skipif(
    not (IQCS_CSPROJ.exists() and COMMONLIBRARY_DLL.exists()),
    reason="local data/repos/System_Dept_1/IQCS fixture checkout is not present",
)


def _wrapper_call(source: str, wrapper_method_name: str) -> dict:
    """Analyze one C# source file and return the wrapper call to `wrapper_method_name`."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "CommandObjectWrapper.cs"
        source_path.write_text(source, encoding="utf-8")
        result = host.analyze_csharp(source_path)

    calls = [
        invocation
        for invocation in result["db_invocations"]
        if invocation["wrapper_method_name"] == wrapper_method_name
    ]
    assert len(calls) == 1, f"expected exactly one call to {wrapper_method_name}, got {calls}"
    return calls[0]


PROVIDER_TYPE_WRAPPER = """
public class Wrapper {
    private string strCn;
    public Wrapper(string cn) { strCn = cn; }
    public int RunProvider(string sql) {
        SqlConnection conn = new SqlConnection(strCn);
        conn.Open();
        SqlCommand cmd = new SqlCommand(sql, conn);
        cmd.CommandType = CommandType.StoredProcedure;
        int rows = cmd.ExecuteNonQuery();
        conn.Close();
        return rows;
    }
}
public class Caller {
    private void Run() {
        Wrapper w = new Wrapper("cn");
        w.RunProvider("usp_Foo");
    }
}
"""

ABSTRACT_TYPE_VIA_CREATE_COMMAND_WRAPPER = """
public class Wrapper {
    private string strCn;
    public Wrapper(string cn) { strCn = cn; }
    public int RunAbstract(string sql) {
        SqlConnection conn = new SqlConnection(strCn);
        conn.Open();
        DbCommand cmd = conn.CreateCommand();
        cmd.CommandText = sql;
        cmd.CommandType = CommandType.StoredProcedure;
        int rows = cmd.ExecuteNonQuery();
        conn.Close();
        return rows;
    }
}
public class Caller {
    private void Run() {
        Wrapper w = new Wrapper("cn");
        w.RunAbstract("usp_Bar");
    }
}
"""


def test_provider_type_constructed_with_new_resolves_its_command_source() -> None:
    """Baseline: the previously-recognised shape, unaffected by the widened rule."""
    call = _wrapper_call(PROVIDER_TYPE_WRAPPER, "RunProvider")

    assert call["wrapper_source_available"] is True
    assert call["wrapper_method_semantics"] == "fixed_stored_procedure"
    assert call["wrapper_terminal_sink"] == "ExecuteNonQuery"
    assert call["wrapper_unresolved_reason"] is None


def test_abstract_type_obtained_through_create_command_resolves_identically() -> None:
    """A command declared as the abstract `DbCommand` type and obtained through a
    connection's `CreateCommand()` -- as `SQLDbContext.usp_ExecCmdGetDataSetAsync` does --
    resolves its Command Source exactly as the equivalently-shaped provider-type method does."""
    provider = _wrapper_call(PROVIDER_TYPE_WRAPPER, "RunProvider")
    abstract_type = _wrapper_call(ABSTRACT_TYPE_VIA_CREATE_COMMAND_WRAPPER, "RunAbstract")

    assert abstract_type["wrapper_source_available"] is True
    assert abstract_type["wrapper_method_semantics"] == provider["wrapper_method_semantics"]
    assert abstract_type["wrapper_terminal_sink"] == provider["wrapper_terminal_sink"]
    assert abstract_type["wrapper_unresolved_reason"] is None


@pytest.mark.parametrize(
    "provider_command_type",
    ["OleDbCommand", "OdbcCommand", "NpgsqlCommand", "MySqlCommand"],
)
def test_widened_provider_list_matches_the_data_adapter_rules_providers(
    provider_command_type: str,
) -> None:
    """The widened comparison names the same providers the data adapter rule already
    names, so the two sibling rules no longer disagree about which providers exist."""
    source = f"""
public class Wrapper {{
    public int Run(string sql, SqlConnection conn) {{
        {provider_command_type} cmd = new {provider_command_type}(sql, conn);
        cmd.CommandType = CommandType.StoredProcedure;
        return cmd.ExecuteNonQuery();
    }}
}}
public class Caller {{
    private void Run() {{
        Wrapper w = new Wrapper();
        w.Run("usp_Foo", null);
    }}
}}
"""
    call = _wrapper_call(source, "Run")

    assert call["wrapper_source_available"] is True
    assert call["wrapper_method_semantics"] == "fixed_stored_procedure"
    assert call["wrapper_terminal_sink"] == "ExecuteNonQuery"


def test_command_declared_abstract_but_constructed_with_new_is_not_double_counted() -> None:
    """`DbCommand cmd = new SqlCommand(...)` is one Command Source, not two: the
    object-creation rule already covers it, so the declared-type rule must not also fire."""
    source = """
public class Wrapper {
    public int Run(string sql, SqlConnection conn) {
        DbCommand cmd = new SqlCommand(sql, conn);
        cmd.CommandType = CommandType.StoredProcedure;
        return cmd.ExecuteNonQuery();
    }
}
public class Caller {
    private void Run() {
        Wrapper w = new Wrapper();
        w.Run("usp_Foo", null);
    }
}
"""
    call = _wrapper_call(source, "Run")

    assert call["wrapper_unresolved_reason"] is None
    assert call["wrapper_method_semantics"] == "fixed_stored_procedure"


def test_a_type_that_only_resembles_a_command_type_by_name_stays_unrecognized() -> None:
    """A coincidental name (not in the widened list) never manufactures a Command Source."""
    source = """
public class Wrapper {
    public string Run(string sql) {
        MyCommand cmd = new MyCommand(sql);
        return cmd.ToString();
    }
}
public class Caller {
    private void Run() {
        Wrapper w = new Wrapper();
        w.Run("x");
    }
}
"""
    call = _wrapper_call(source, "Run")

    assert call["wrapper_source_available"] is False


def _build_create_command_dll(build_dir: Path) -> Path:
    """Compile a tiny classlib mirroring the real `SQLDbContext.usp_ExecCmdGetDataSetAsync`
    shape: a command obtained through a connection's `CreateCommand()` and declared as the
    abstract type, never constructed with `new` inside the wrapper method itself.

    The `SqlConnection`/`DbCommand` types here are stand-ins declared in the same file, not the
    real ADO.NET types: the decompiler's Command Source recognition matches by syntactic type
    name only, so this exercises the exact same path without an external ADO.NET reference.
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
        "public enum CommandType { Text = 1, StoredProcedure = 4, TableDirect = 512 }\n"
        "public class DbCommand {\n"
        "    public string CommandText;\n"
        "    public object CommandType;\n"
        "    public int ExecuteNonQuery() => 0;\n"
        "}\n"
        "public class SqlConnection {\n"
        "    public SqlConnection(string cn) {}\n"
        "    public DbCommand CreateCommand() => new DbCommand();\n"
        "    public void Open() {}\n"
        "    public void Close() {}\n"
        "}\n"
        "public class Wrapper {\n"
        "    private string strCn;\n"
        "    public Wrapper(string cn) { strCn = cn; }\n"
        "    public int usp_RunAsync(string sql) {\n"
        "        SqlConnection conn = new SqlConnection(strCn);\n"
        "        conn.Open();\n"
        "        DbCommand cmd = conn.CreateCommand();\n"
        "        cmd.CommandText = sql;\n"
        "        cmd.CommandType = CommandType.StoredProcedure;\n"
        "        int rows = cmd.ExecuteNonQuery();\n"
        "        conn.Close();\n"
        "        return rows;\n"
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


def _write_referenced_dll_project(root: Path, assembly_name: str, dll_bytes: bytes) -> Path:
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


@requires_dotnet
def test_decompile_wrapper_classifies_command_obtained_through_create_command() -> None:
    """The recognition rule is shared by both classification paths -- local source wrapper
    and decompiled external assembly -- with no scope switch. A method whose command is
    obtained through `CreateCommand()` and declared as the abstract type is classified in the
    decompiled path exactly as the local-source test above shows it is in the source path."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        wrapper_dll = _build_create_command_dll(root / "wrapperlib")
        csproj_path = _write_referenced_dll_project(root, "Wrapper", wrapper_dll.read_bytes())

        result = host.decompile_wrapper(csproj_path, "Wrapper", cache_root=root / "cache")

    assert result["status"] == "resolved"
    definitions = result["wrapper_definitions"]
    matches = [d for d in definitions if d["method_name"] == "usp_RunAsync"]
    assert len(matches) == 1
    assert matches[0]["unresolved_reason"] is None
    assert matches[0]["terminal_sink"] == "ExecuteNonQuery"

    snapshot = result["contract_proposals"][0]["implementation_snapshot"]
    assert snapshot["public_database_operations_complete"] is True
    assert snapshot["unclassified_public_methods"] == []


# The full IQCS unclassified surface before this ticket: seven `SQLDbContext` public methods,
# none classified. After this ticket, three resolve through the widened rule -- including the
# measured `usp_ExecCmdGetDataSetAsync`. The other three that used to remain here
# (`usp_ExecCmdGetFisrtValueAsync`, `usp_ExecCmdGetDataTableAsync`, `usp_ExecCmdGetJsonObjectAsync`)
# now resolve as Delegated Methods instead (ticket 02; see
# tests/test_delegated_method.py::test_real_sqldbcontext_delegating_methods_are_reported_as_delegated).
# One method remains unclassified for its own, still out-of-scope reason: it uses EF Core's
# high-level raw-SQL form, a structurally different shape its own ticket covers.
REMAINING_UNCLASSIFIED_METHODS = {
    "SQLDbContext.usp_ExecCmdGetCountAsync(string,Microsoft.EntityFrameworkCore.SqlParameter[]?,bool)",
}


@requires_iqcs_fixture
def test_real_sqldbcontext_usp_execcmdgetdatasetasync_becomes_classified() -> None:
    """Fixture-gated smoke test against the real `CommonLibrary.dll` checked out under IQCS.

    `usp_ExecCmdGetDataSetAsync` obtains its command through
    `Database.GetDbConnection().CreateCommand()`, declared as `DbCommand`. It moves from the
    unclassified set to a classified wrapper definition, carrying its reachable
    stored-procedure command semantics and its terminal sink. The behaviour surface stays
    incomplete -- a partial repair is not presented as a whole one -- and the remaining
    unclassified methods are named.
    """
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as cache_dir:
        result = host.decompile_wrapper(
            IQCS_CSPROJ,
            "SQLDbContext",
            cache_root=Path(cache_dir),
        )

    assert result["status"] == "resolved"
    definitions = result["wrapper_definitions"]

    data_set = [d for d in definitions if d["method_name"] == "usp_ExecCmdGetDataSetAsync"]
    assert len(data_set) == 1
    assert data_set[0]["unresolved_reason"] is None
    assert data_set[0]["terminal_sink"] == "ExecuteReaderAsync"
    assert data_set[0]["reaches_stored_procedure_sink"] is True

    snapshot = result["contract_proposals"][0]["implementation_snapshot"]
    assert snapshot["public_database_operations_complete"] is False
    assert set(snapshot["unclassified_public_methods"]) == REMAINING_UNCLASSIFIED_METHODS
