"""Ticket 04: a command object is recognised by the contract it implements, with the name
list ticket 01 widened as fallback.

A type is a command object when it implements `IDbCommand` -- the interface every ADO.NET
command type in .NET is required to implement, whichever provider or team wrote it. When the
analyzer holds enough type information to answer that question, it answers it: a provider named
nowhere in the analyzer resolves its Command Source, and a coincidental name that implements no
command contract stays unrecognised even though it would have matched the name list. When the
question cannot be answered -- an unresolvable external reference, or no semantic model at all
-- the widened name comparison ticket 01 delivered decides, so a project the analyzer cannot
fully bind still resolves the command shapes it has always resolved.

These tests assert the externally observable fact (a wrapper method's reported classification,
and the classified/unclassified sets a decompiled assembly or a local-source project reports),
not the shape of the resolver itself, per this repo's testing conventions.
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

# `System.Data.Common.DbCommand`/`DbConnection` are part of the net8.0 SDK's own base class
# library, so every fixture below needs no external ADO.NET package reference at all.
FOO_PROVIDER_TYPES = """
using System.Data;
using System.Data.Common;
public class FooProviderCommand : DbCommand {
    public override string CommandText { get; set; } = "";
    public override int CommandTimeout { get; set; }
    public override CommandType CommandType { get; set; }
    public override bool DesignTimeVisible { get; set; }
    public override UpdateRowSource UpdatedRowSource { get; set; }
    protected override DbConnection DbConnection { get; set; }
    protected override DbParameterCollection DbParameterCollection { get; } = null;
    protected override DbTransaction DbTransaction { get; set; }
    public FooProviderCommand() {}
    public FooProviderCommand(string sql, FooProviderConnection conn) { CommandText = sql; }
    public override void Cancel() {}
    public override int ExecuteNonQuery() => 1;
    public override object ExecuteScalar() => null;
    public override void Prepare() {}
    protected override DbParameter CreateDbParameter() => null;
    protected override DbDataReader ExecuteDbDataReader(CommandBehavior behavior) => null;
}
public class FooProviderConnection : DbConnection {
    public FooProviderConnection(string cn) {}
    public override string ConnectionString { get; set; } = "";
    public override string Database => "";
    public override string DataSource => "";
    public override string ServerVersion => "";
    public override ConnectionState State => ConnectionState.Closed;
    public override void ChangeDatabase(string databaseName) {}
    public override void Close() {}
    public override void Open() {}
    protected override DbTransaction BeginDbTransaction(IsolationLevel isolationLevel) => null;
    protected override DbCommand CreateDbCommand() => new FooProviderCommand();
}
"""


def _build_classlib(build_dir: Path, target_framework: str, source: str, assembly_name: str = "Wrapper") -> Path:
    build_dir.mkdir(parents=True, exist_ok=True)
    (build_dir / f"{assembly_name}.csproj").write_text(
        "<Project Sdk=\"Microsoft.NET.Sdk\">\n"
        "  <PropertyGroup>\n"
        f"    <TargetFramework>{target_framework}</TargetFramework>\n"
        f"    <AssemblyName>{assembly_name}</AssemblyName>\n"
        "    <Nullable>disable</Nullable>\n"
        "  </PropertyGroup>\n"
        "</Project>\n",
        encoding="utf-8",
    )
    (build_dir / f"{assembly_name}.cs").write_text(source, encoding="utf-8")
    bin_dir = build_dir / "bin"
    result = subprocess.run(
        [
            "dotnet",
            "build",
            str(build_dir / f"{assembly_name}.csproj"),
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
    return bin_dir / f"{assembly_name}.dll"


def _write_referenced_dll_project(
    root: Path,
    assembly_name: str,
    dll_bytes: bytes,
    extra_reference_hint_path: str | None = None,
) -> Path:
    dll_path = root / f"{assembly_name}.dll"
    dll_path.write_bytes(dll_bytes)
    extra_reference = ""
    if extra_reference_hint_path is not None:
        extra_reference = (
            "    <Reference Include=\"OtherProvider\">\n"
            f"      <HintPath>{extra_reference_hint_path}</HintPath>\n"
            "      <Private>false</Private>\n"
            "    </Reference>\n"
        )
    csproj_path = root / "Fake.csproj"
    csproj_path.write_text(
        "<Project ToolsVersion=\"12.0\">\n"
        "  <ItemGroup>\n"
        f"    <Reference Include=\"{assembly_name}, Version=1.0.0.0\">\n"
        f"      <HintPath>{dll_path.name}</HintPath>\n"
        "    </Reference>\n"
        f"{extra_reference}"
        "  </ItemGroup>\n"
        "</Project>\n",
        encoding="utf-8",
    )
    return csproj_path


@requires_dotnet
def test_decompiled_command_from_a_provider_named_nowhere_resolves_by_contract() -> None:
    """A command type from a provider this analyzer's name list has never heard of resolves
    its Command Source, because it implements `IDbCommand` -- no ticket needed the day a new
    team's convention enters the catalog."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    source = FOO_PROVIDER_TYPES + (
        "public class Wrapper {\n"
        "    public int usp_RunFooProvider(string sql) {\n"
        "        FooProviderConnection conn = new FooProviderConnection(\"cn\");\n"
        "        conn.Open();\n"
        "        FooProviderCommand cmd = new FooProviderCommand(sql, conn);\n"
        "        cmd.CommandText = sql;\n"
        "        int rows = cmd.ExecuteNonQuery();\n"
        "        int textLength = cmd.CommandText.Length;\n"
        "        conn.Close();\n"
        "        return rows + textLength;\n"
        "    }\n"
        "}\n"
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        wrapper_dll = _build_classlib(root / "wrapperlib", "net8.0", source)
        csproj_path = _write_referenced_dll_project(root, "Wrapper", wrapper_dll.read_bytes())

        result = host.decompile_wrapper(csproj_path, "Wrapper", cache_root=root / "cache")

    assert result["status"] == "resolved"
    definitions = [d for d in result["wrapper_definitions"] if d["method_name"] == "usp_RunFooProvider"]
    assert len(definitions) == 1
    assert definitions[0]["unresolved_reason"] is None
    assert definitions[0]["terminal_sink"] == "ExecuteNonQuery"

    snapshot = result["contract_proposals"][0]["implementation_snapshot"]
    assert snapshot["unclassified_public_methods"] == []


@requires_dotnet
def test_decompiled_coincidental_name_stays_unrecognized_when_contract_is_checkable() -> None:
    """A type whose name resembles a command type (`SqlCommand`) but implements no command
    contract stays unrecognised when the contract can be checked -- unlike the local-source
    case (no project compilation, contract unanswerable), this assembly's own `SqlCommand` is
    fully resolvable, so a coincidental name never manufactures a Command Source."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    source = (
        "public class SqlCommand {\n"
        "    public string CommandText { get; set; }\n"
        "    public SqlCommand(string sql) { CommandText = sql; }\n"
        "    public int ExecuteNonQuery() => 0;\n"
        "}\n"
        "public class Wrapper {\n"
        "    public int usp_RunFakeSql(string sql) {\n"
        "        SqlCommand cmd = new SqlCommand(sql);\n"
        "        cmd.CommandText = sql;\n"
        "        return cmd.ExecuteNonQuery();\n"
        "    }\n"
        "}\n"
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        wrapper_dll = _build_classlib(root / "wrapperlib", "net8.0", source)
        csproj_path = _write_referenced_dll_project(root, "Wrapper", wrapper_dll.read_bytes())

        result = host.decompile_wrapper(csproj_path, "Wrapper", cache_root=root / "cache")

    assert result["status"] == "resolved"
    assert [d for d in result["wrapper_definitions"] if d["method_name"] == "usp_RunFakeSql"] == []

    snapshot = result["contract_proposals"][0]["implementation_snapshot"]
    assert snapshot["unclassified_public_methods"] == ["Wrapper.usp_RunFakeSql(string)"]


@requires_dotnet
def test_decompiled_unresolvable_provider_reference_falls_back_to_the_name_comparison() -> None:
    """When the contract cannot be checked -- here, the provider assembly a wrapper method
    references was never shipped alongside the wrapper DLL, so the decompiler cannot resolve
    what the type actually implements -- the widened name comparison decides, and the wrapper
    still resolves the command shape it has always resolved (`NpgsqlCommand` is in the same
    provider list the data adapter rule already carries)."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    other_provider_source = (
        "using System.Data;\n"
        "using System.Data.Common;\n"
        "public class NpgsqlConnection : DbConnection {\n"
        "    public NpgsqlConnection(string cn) {}\n"
        "    public override string ConnectionString { get; set; } = \"\";\n"
        "    public override string Database => \"\";\n"
        "    public override string DataSource => \"\";\n"
        "    public override string ServerVersion => \"\";\n"
        "    public override ConnectionState State => ConnectionState.Closed;\n"
        "    public override void ChangeDatabase(string databaseName) {}\n"
        "    public override void Close() {}\n"
        "    public override void Open() {}\n"
        "    protected override DbTransaction BeginDbTransaction(IsolationLevel isolationLevel) => null;\n"
        "    protected override DbCommand CreateDbCommand() => new NpgsqlCommand();\n"
        "}\n"
        "public class NpgsqlCommand : DbCommand {\n"
        "    public NpgsqlCommand() {}\n"
        "    public NpgsqlCommand(string sql, NpgsqlConnection conn) { CommandText = sql; }\n"
        "    public override string CommandText { get; set; } = \"\";\n"
        "    public override int CommandTimeout { get; set; }\n"
        "    public override CommandType CommandType { get; set; }\n"
        "    public override bool DesignTimeVisible { get; set; }\n"
        "    public override UpdateRowSource UpdatedRowSource { get; set; }\n"
        "    protected override DbConnection DbConnection { get; set; }\n"
        "    protected override DbParameterCollection DbParameterCollection { get; } = null;\n"
        "    protected override DbTransaction DbTransaction { get; set; }\n"
        "    public override void Cancel() {}\n"
        "    public override int ExecuteNonQuery() => 1;\n"
        "    public override object ExecuteScalar() => null;\n"
        "    public override void Prepare() {}\n"
        "    protected override DbParameter CreateDbParameter() => null;\n"
        "    protected override DbDataReader ExecuteDbDataReader(CommandBehavior behavior) => null;\n"
        "}\n"
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        other_provider_dll = _build_classlib(
            root / "otherlib", "net8.0", other_provider_source, assembly_name="OtherProvider"
        )

        wrapper_dir = root / "wrapperlib"
        wrapper_dir.mkdir(parents=True, exist_ok=True)
        (wrapper_dir / "Wrapper.csproj").write_text(
            "<Project Sdk=\"Microsoft.NET.Sdk\">\n"
            "  <PropertyGroup>\n"
            "    <TargetFramework>net8.0</TargetFramework>\n"
            "    <AssemblyName>Wrapper</AssemblyName>\n"
            "    <Nullable>disable</Nullable>\n"
            "  </PropertyGroup>\n"
            "  <ItemGroup>\n"
            "    <Reference Include=\"OtherProvider\">\n"
            f"      <HintPath>{other_provider_dll}</HintPath>\n"
            "      <Private>false</Private>\n"
            "    </Reference>\n"
            "  </ItemGroup>\n"
            "</Project>\n",
            encoding="utf-8",
        )
        (wrapper_dir / "Wrapper.cs").write_text(
            "public class Wrapper {\n"
            "    private string strCn;\n"
            "    public Wrapper(string cn) { strCn = cn; }\n"
            "    public int usp_RunViaOtherProvider(string sql) {\n"
            "        NpgsqlConnection conn = new NpgsqlConnection(strCn);\n"
            "        conn.Open();\n"
            "        NpgsqlCommand cmd = new NpgsqlCommand(sql, conn);\n"
            "        cmd.CommandText = sql;\n"
            "        int rows = cmd.ExecuteNonQuery();\n"
            "        conn.Close();\n"
            "        return rows;\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )
        bin_dir = wrapper_dir / "bin"
        build = subprocess.run(
            ["dotnet", "build", str(wrapper_dir / "Wrapper.csproj"), "-c", "Release", "-o", str(bin_dir)],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert build.returncode == 0, build.stdout + build.stderr
        wrapper_dll_bytes = (bin_dir / "Wrapper.dll").read_bytes()

        # `Private=false` already kept OtherProvider.dll out of Wrapper's own bin directory;
        # this csproj root additionally never sees it at all, so the decompiler's assembly
        # resolver has no way to locate the type NpgsqlCommand actually derives from.
        csproj_path = _write_referenced_dll_project(root, "Wrapper", wrapper_dll_bytes)

        result = host.decompile_wrapper(csproj_path, "Wrapper", cache_root=root / "cache")

    assert result["status"] == "resolved"
    definitions = [d for d in result["wrapper_definitions"] if d["method_name"] == "usp_RunViaOtherProvider"]
    assert len(definitions) == 1
    assert definitions[0]["unresolved_reason"] is None


@requires_dotnet
def test_local_source_command_from_a_provider_named_nowhere_resolves_by_contract() -> None:
    """The recognition rule is shared by the local source wrapper path and the decompiled
    external assembly path with no scope switch: with a real project compilation available (a
    genuine `.csproj` under the given source root, per this repo's Semantic Binding
    Availability), the same contract check that recognises `FooProviderCommand` in a decompiled
    assembly also recognises it directly from project source."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    source = FOO_PROVIDER_TYPES + (
        "public class Wrapper {\n"
        "    public int RunFooProvider(string sql) {\n"
        "        FooProviderCommand cmd = new FooProviderCommand();\n"
        "        cmd.CommandText = sql;\n"
        "        return cmd.ExecuteNonQuery();\n"
        "    }\n"
        "}\n"
        "public class Caller {\n"
        "    private void Run() {\n"
        "        Wrapper w = new Wrapper();\n"
        "        w.RunFooProvider(\"usp_Foo\");\n"
        "    }\n"
        "}\n"
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        root.mkdir(exist_ok=True)
        (root / "Proj.csproj").write_text(
            "<Project Sdk=\"Microsoft.NET.Sdk\">\n"
            "  <PropertyGroup>\n"
            "    <TargetFramework>net8.0</TargetFramework>\n"
            "    <Nullable>disable</Nullable>\n"
            "  </PropertyGroup>\n"
            "</Project>\n",
            encoding="utf-8",
        )
        wrapper_path = root / "Wrapper.cs"
        wrapper_path.write_text(source, encoding="utf-8")

        results = host.analyze_csharp_files([wrapper_path], source_roots=[root])

    calls = [
        invocation
        for invocation in results[0]["db_invocations"]
        if invocation["wrapper_method_name"] == "RunFooProvider"
    ]
    assert len(calls) == 1
    assert calls[0]["wrapper_source_available"] is True
    assert calls[0]["wrapper_terminal_sink"] == "ExecuteNonQuery"
    assert calls[0]["wrapper_unresolved_reason"] is None
