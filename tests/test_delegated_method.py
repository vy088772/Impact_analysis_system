"""Ticket 02: a method that delegates to a sibling is reported as delegated, not as a gap.

A wrapper method that constructs no command of its own, and whose only database contact is a
call to another method declared on the same type, is reported as a Delegated Method naming the
sibling it delegates to -- a third outcome beside "classified" and "unclassified". Before this
ticket such a method landed in the same unclassified bucket as a method the resolver genuinely
failed to understand; the behaviour surface completeness check now counts a Delegated Method as
understood, same as a classified one.

These tests assert the externally observable fact -- the decompile-wrapper response's classified
wrapper definitions, delegated methods, and unclassified public methods -- not the shape of the
resolver itself, per this repo's testing conventions.
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

STC_CSPROJ = PROJECT_ROOT / "data" / "repos" / "System_Dept_1" / "STC" / "STC" / "STC.csproj"
SQLFUNC_DLL = STC_CSPROJ.parent / "bin" / "SQLFunc.dll"

requires_stc_fixture = pytest.mark.skipif(
    not (STC_CSPROJ.exists() and SQLFUNC_DLL.exists()),
    reason="local data/repos/System_Dept_1/STC fixture checkout is not present",
)

TTPUR_CSPROJ = (
    PROJECT_ROOT / "data" / "repos" / "System_Dept_1" / "Y-DOCs" / "TTPUR" / "TTPUR.csproj"
)
SQLOBJECT_DLL = TTPUR_CSPROJ.parent / "bin" / "SQLObject.dll"

requires_sqlobject_fixture = pytest.mark.skipif(
    not (TTPUR_CSPROJ.exists() and SQLOBJECT_DLL.exists()),
    reason="local data/repos/System_Dept_1/Y-DOCs/TTPUR fixture checkout is not present",
)


def _build_delegation_shapes_dll(build_dir: Path) -> Path:
    """Compile a tiny classlib whose `Wrapper` type covers every Delegated Method shape this
    ticket needs: a method with its own command construct (classified), a method that only
    delegates to it, a method that reshapes the sibling's result while delegating, a method
    with both its own construct and a sibling call (classified by its own source), a method
    that touches an ADO.NET type but calls no sibling (stays unclassified), and a method that
    calls two distinct siblings (ambiguous -- names no single delegate, stays unclassified).

    `SqlConnection` here is a minimal real `System.Data.Common.DbConnection` subclass (ticket 04:
    command-object recognition now checks the `IDbCommand` contract first, so a wrapper method
    obtaining its command through `CreateCommand()` must actually resolve to a real ADO.NET
    command type -- a same-file stand-in class that merely shares the name `DbCommand` no longer
    qualifies, by design). No external ADO.NET package reference is needed: `DbConnection`/
    `DbCommand` are part of the base class library the net8.0 SDK already references.
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
        "using System.Data;\n"
        "using System.Data.Common;\n"
        "public class FakeCommand : DbCommand {\n"
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
        "public class SqlConnection : DbConnection {\n"
        "    public SqlConnection(string cn) {}\n"
        "    public override string ConnectionString { get; set; } = \"\";\n"
        "    public override string Database => \"\";\n"
        "    public override string DataSource => \"\";\n"
        "    public override string ServerVersion => \"\";\n"
        "    public override ConnectionState State => ConnectionState.Closed;\n"
        "    public override void ChangeDatabase(string databaseName) {}\n"
        "    public override void Close() {}\n"
        "    public override void Open() {}\n"
        "    protected override DbTransaction BeginDbTransaction(IsolationLevel isolationLevel) => null;\n"
        "    protected override DbCommand CreateDbCommand() => new FakeCommand();\n"
        "}\n"
        "public class Wrapper {\n"
        "    private string strCn;\n"
        "    public Wrapper(string cn) { strCn = cn; }\n"
        "\n"
        "    public int RunDirect(string sql) {\n"
        "        SqlConnection conn = new SqlConnection(strCn);\n"
        "        DbCommand cmd = conn.CreateCommand();\n"
        "        cmd.CommandText = sql;\n"
        "        return cmd.ExecuteNonQuery();\n"
        "    }\n"
        "\n"
        "    public bool RunDelegatedAndReshaped(string sql, SqlConnection conn) {\n"
        "        int rows = RunDirect(sql);\n"
        "        return rows > 0;\n"
        "    }\n"
        "\n"
        "    public int RunBothOwnAndSibling(string sql) {\n"
        "        RunDirect(\"usp_Touch\");\n"
        "        SqlConnection conn = new SqlConnection(strCn);\n"
        "        DbCommand cmd = conn.CreateCommand();\n"
        "        cmd.CommandText = sql;\n"
        "        return cmd.ExecuteNonQuery();\n"
        "    }\n"
        "\n"
        "    public string TouchesButCallsNoSibling(SqlConnection conn) {\n"
        "        return conn.ToString();\n"
        "    }\n"
        "\n"
        "    public int CallsTwoDistinctSiblings(string sql, SqlConnection conn) {\n"
        "        int rows = RunDirect(sql);\n"
        "        bool ok = RunDelegatedAndReshaped(sql, conn);\n"
        "        return ok ? rows : 0;\n"
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
def test_delegation_shapes_are_classified_correctly() -> None:
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        wrapper_dll = _build_delegation_shapes_dll(root / "wrapperlib")
        csproj_path = _write_referenced_dll_project(root, "Wrapper", wrapper_dll.read_bytes())

        result = host.decompile_wrapper(csproj_path, "Wrapper", cache_root=root / "cache")

    assert result["status"] == "resolved"
    classified_names = {d["method_name"] for d in result["wrapper_definitions"]}
    delegated_by_name = {
        d["method_identity"].split(".", 1)[1].split("(", 1)[0]: d["delegates_to"]
        for d in result["delegated_methods"]
    }
    unclassified_names = {
        identity.split(".", 1)[1].split("(", 1)[0]
        for identity in result["contract_proposals"][0]["implementation_snapshot"][
            "unclassified_public_methods"
        ]
    }

    # A method with no command construct of its own, whose only database contact is a sibling
    # call, is delegated and names that sibling.
    assert "RunDelegatedAndReshaped" in delegated_by_name
    assert delegated_by_name["RunDelegatedAndReshaped"] == "RunDirect"
    # It is delegated even though it also reshapes the sibling's result -- not a bare pass-through.
    assert "RunDelegatedAndReshaped" not in classified_names
    assert "RunDelegatedAndReshaped" not in unclassified_names

    # A method with both its own command construct and a sibling call is classified by its
    # own Command Source; delegation is never consulted for it.
    assert "RunBothOwnAndSibling" in classified_names
    assert "RunBothOwnAndSibling" not in delegated_by_name

    # A method that touches an ADO.NET type but calls no sibling stays unclassified.
    assert "TouchesButCallsNoSibling" in unclassified_names
    assert "TouchesButCallsNoSibling" not in delegated_by_name
    assert "TouchesButCallsNoSibling" not in classified_names

    # A method calling two distinct siblings names no single delegate and stays unclassified,
    # exactly like a method calling none.
    assert "CallsTwoDistinctSiblings" in unclassified_names
    assert "CallsTwoDistinctSiblings" not in delegated_by_name

    # The Delegated Method record states only where to look -- the sibling's name -- and
    # nothing about a database target, so delegation is never mistaken for inherited evidence.
    delegated_entry = next(
        d for d in result["delegated_methods"] if d["delegates_to"] == "RunDirect"
    )
    assert set(delegated_entry.keys()) == {"method_identity", "delegates_to"}

    # The behaviour surface completeness check counts a Delegated Method as understood: every
    # method here is either classified or delegated except the two designed to stay gaps.
    snapshot = result["contract_proposals"][0]["implementation_snapshot"]
    assert snapshot["public_database_operations_complete"] is False
    assert len(snapshot["unclassified_public_methods"]) == 2


# The three real `SQLDbContext` methods that delegate to a sibling, and the sibling each one
# names -- measured against the real `CommonLibrary.dll`, not the spec's guess (which named a
# fourth, `usp_ExecCmdGetJsonObjectListAsync`, that ticket 01 measured as constructing its own
# command directly and classifying on its own).
REAL_DELEGATIONS = {
    "SQLDbContext.usp_ExecCmdGetFisrtValueAsync(string,Microsoft.EntityFrameworkCore.SqlParameter[]?,bool)": "usp_ExecCmdGetDataTableAsync",
    "SQLDbContext.usp_ExecCmdGetDataTableAsync(string,Microsoft.EntityFrameworkCore.SqlParameter[]?,bool)": "usp_ExecCmdGetDataSetAsync",
    "SQLDbContext.usp_ExecCmdGetJsonObjectAsync(string,Microsoft.EntityFrameworkCore.SqlParameter[]?,bool)": "usp_ExecCmdGetJsonObjectListAsync",
}


@requires_iqcs_fixture
def test_real_sqldbcontext_delegating_methods_are_reported_as_delegated() -> None:
    """Fixture-gated smoke test against the real `CommonLibrary.dll` checked out under IQCS.

    The three methods whose only database contact is a call to a sibling move out of the
    unclassified set and name the sibling each one calls. `usp_ExecCmdGetCountAsync` -- EF
    Core's raw-SQL execution form -- classifies through its own rule (ticket 08), so the
    surface is complete: none of `SQLDbContext`'s seven public methods stay unclassified.
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
    delegations = {
        d["method_identity"]: d["delegates_to"] for d in result["delegated_methods"]
    }
    assert delegations == REAL_DELEGATIONS

    snapshot = result["contract_proposals"][0]["implementation_snapshot"]
    assert snapshot["public_database_operations_complete"] is True
    assert snapshot["unclassified_public_methods"] == []


@requires_stc_fixture
def test_real_sqlfunc_gains_no_delegated_method() -> None:
    """The existing `SQLFunc` classified surface is unchanged: it gains no delegated method
    it did not have, because every one of its methods already has its own Command Source."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as cache_dir:
        result = host.decompile_wrapper(
            STC_CSPROJ,
            "SQLFunc",
            cache_root=Path(cache_dir),
        )

    assert result["status"] == "resolved"
    assert result["delegated_methods"] == []
    assert result["contract_proposals"][0]["implementation_snapshot"][
        "unclassified_public_methods"
    ] == []


@requires_sqlobject_fixture
def test_real_sqlobject_gains_no_delegated_method() -> None:
    """The existing `SQLObject` classified surface is unchanged: it gains no delegated method
    it did not have."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as cache_dir:
        result = host.decompile_wrapper(
            TTPUR_CSPROJ,
            "SQLObject",
            cache_root=Path(cache_dir),
        )

    assert result["status"] == "resolved"
    assert result["delegated_methods"] == []
    assert result["contract_proposals"][0]["implementation_snapshot"][
        "unclassified_public_methods"
    ] == []
