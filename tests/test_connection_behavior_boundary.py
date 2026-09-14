"""Ticket 07: the connection behind a command factory is read from the factory's receiver.

The connection resolver used to read a wrapper method's connection from two places only: the
second argument of a command constructor, and a `Connection` property assignment. A command
obtained through a factory call -- `connection.CreateCommand()` -- gives neither: the connection
is the *receiver* of the factory call, and the resolver never read that receiver. Three real
`SQLDbContext` methods build their command this way, so all three reported an empty Connection
Behavior Boundary and failed the completeness check with `connection_behavior_boundary_missing`.

This ticket adds a third rule, read only when the constructor-argument rule and the `Connection`
property-assignment rule both resolve nothing: the factory call's receiver becomes the
connection. The boundary vocabulary gains a third value, `context_connection`, reported when
that receiver is a database context's own `Database` facade (e.g.
`Database.GetDbConnection().CreateCommand()`); every other factory receiver keeps reporting
`wrapper_connection`, the value a Field-Held Connection already produces.

These tests assert the externally observable fact -- the decompile-wrapper response's
`connection_behavior_boundary` -- not the shape of the resolver itself, per this repo's testing
conventions.
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

from code_analyzer.external_wrapper_contracts import validate_implementation_snapshot
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

# Minimal real ADO.NET types -- a `DbCommand`/`DbConnection` subclass, not a same-file stand-in.
# Ticket 04's command-object recognition checks the `IDbCommand` contract first, so the declared
# `DbCommand` type must resolve to the real ADO.NET type for the CreateCommand()-factory shape to
# exercise the path this ticket changes. No external ADO.NET package reference is needed:
# `DbConnection`/`DbCommand` are part of the base class library the net8.0 SDK already references.
_ADO_NET_STAND_INS = """
using System.Data;
using System.Data.Common;
public class FakeCommand : DbCommand {
    public override string CommandText { get; set; } = "";
    public override int CommandTimeout { get; set; }
    public override CommandType CommandType { get; set; }
    public override bool DesignTimeVisible { get; set; }
    public override UpdateRowSource UpdatedRowSource { get; set; }
    protected override DbConnection DbConnection { get; set; }
    protected override DbParameterCollection DbParameterCollection { get; } = null;
    protected override DbTransaction DbTransaction { get; set; }
    public override void Cancel() {}
    public override int ExecuteNonQuery() => 0;
    public override object ExecuteScalar() => null;
    public override void Prepare() {}
    protected override DbParameter CreateDbParameter() => null;
    protected override DbDataReader ExecuteDbDataReader(CommandBehavior behavior) => null;
}
public class SqlConnection : DbConnection {
    public SqlConnection(string cn) {}
    public override string ConnectionString { get; set; } = "";
    public override string Database => "";
    public override string DataSource => "";
    public override string ServerVersion => "";
    public override ConnectionState State => ConnectionState.Closed;
    public override void ChangeDatabase(string databaseName) {}
    public override void Close() {}
    public override void Open() {}
    protected override DbTransaction BeginDbTransaction(IsolationLevel isolationLevel) => null;
    protected override DbCommand CreateDbCommand() => new FakeCommand();
}
"""


def _build_dll(build_dir: Path, wrapper_source: str, config: str = "Release") -> Path:
    """Compile `_ADO_NET_STAND_INS` plus `wrapper_source` into a tiny classlib.

    `config` defaults to `Release`, matching this repo's other decompile-wrapper fixtures. One
    fixture below needs `Debug`: a Release build's optimizer folds a command built with `new`,
    given no other use of its variable, into a bare `new SqlCommand(...) { ... }.ExecuteNonQuery()`
    expression with no named local at all -- a real optimizer behaviour, but not the shape this
    ticket's rule (or the one it must leave alone) is about; a Debug build keeps the local.
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
        _ADO_NET_STAND_INS + wrapper_source,
        encoding="utf-8",
    )
    bin_dir = build_dir / "bin"
    result = subprocess.run(
        [
            "dotnet",
            "build",
            str(build_dir / "Wrapper.csproj"),
            "-c",
            config,
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


def _decompile(wrapper_source: str, config: str = "Release") -> dict:
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        wrapper_dll = _build_dll(root / "wrapperlib", wrapper_source, config)
        csproj_path = _write_referenced_dll_project(root, "Wrapper", wrapper_dll.read_bytes())
        return host.decompile_wrapper(csproj_path, "Wrapper", cache_root=root / "cache")


def _operation(result: dict, method_name: str) -> dict:
    operations = result["contract_proposals"][0]["implementation_snapshot"]["methods"]
    matches = [operation for operation in operations if operation["method_name"] == method_name]
    assert len(matches) == 1, f"expected exactly one operation for {method_name}, got {matches}"
    return matches[0]


def _definition(result: dict, method_name: str) -> dict:
    matches = [d for d in result["wrapper_definitions"] if d["method_name"] == method_name]
    assert len(matches) == 1, f"expected exactly one definition for {method_name}, got {matches}"
    return matches[0]


FIELD_HELD_CONNECTION_FACTORY_WRAPPER = """
public class Wrapper {
    private string strCn;
    public Wrapper(string cn) { strCn = cn; }
    public int usp_RunAsync(string sql) {
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
"""


@requires_dotnet
def test_field_held_connection_factory_reports_wrapper_connection_boundary() -> None:
    """A factory receiver that is a Field-Held Connection (a local variable, not a database
    context's `Database` facade) reports `wrapper_connection` -- the value that shape already
    produced for every other rule -- not an empty boundary and not `context_connection`."""
    result = _decompile(FIELD_HELD_CONNECTION_FACTORY_WRAPPER)

    assert result["status"] == "resolved"
    operation = _operation(result, "usp_RunAsync")
    assert operation["connection_behavior_boundary"] == "wrapper_connection"

    # The exact text is decompiler-assigned (a decompiled assembly carries no local variable
    # names), so only its presence is asserted here -- the boundary value above is the fact
    # this ticket adds.
    definition = _definition(result, "usp_RunAsync")
    assert definition["connection_expression"]
    assert definition["connection_is_context_connection"] is False


DATABASE_FACADE_FACTORY_WRAPPER = """
public class FakeDatabaseFacade {
    private readonly DbConnection _connection;
    public FakeDatabaseFacade(DbConnection connection) { _connection = connection; }
    public DbConnection GetDbConnection() => _connection;
}
public class Wrapper {
    private readonly FakeDatabaseFacade _database;
    protected FakeDatabaseFacade Database => _database;
    public Wrapper(string cn) { _database = new FakeDatabaseFacade(new SqlConnection(cn)); }
    public int usp_RunAsync(string sql) {
        DbCommand cmd = Database.GetDbConnection().CreateCommand();
        cmd.CommandText = sql;
        cmd.CommandType = CommandType.StoredProcedure;
        int rows = cmd.ExecuteNonQuery();
        return rows;
    }
}
"""


@requires_dotnet
def test_database_facade_factory_reports_context_connection_boundary() -> None:
    """A factory receiver that is a database context's own `Database` facade --
    `Database.GetDbConnection().CreateCommand()`, the real `SQLDbContext` shape -- reports the
    third boundary value, `context_connection`, distinct from `wrapper_connection`."""
    result = _decompile(DATABASE_FACADE_FACTORY_WRAPPER)

    assert result["status"] == "resolved"
    operation = _operation(result, "usp_RunAsync")
    assert operation["connection_behavior_boundary"] == "context_connection"

    definition = _definition(result, "usp_RunAsync")
    assert definition["connection_expression"] == "Database.GetDbConnection()"
    assert definition["connection_is_context_connection"] is True


PROPERTY_ASSIGNED_CONNECTION_WITH_FACTORY_INITIALIZER_WRAPPER = """
public class Wrapper {
    public int usp_RunAsync(string sql, SqlConnection explicitConn, SqlConnection conn) {
        DbCommand cmd = conn.CreateCommand();
        cmd.CommandText = sql;
        cmd.CommandType = CommandType.StoredProcedure;
        cmd.Connection = explicitConn;
        int rows = cmd.ExecuteNonQuery();
        return rows;
    }
}
"""


@requires_dotnet
def test_property_assigned_connection_is_unaffected_by_a_sibling_factory_receiver() -> None:
    """The command-factory rule runs only when the constructor-argument rule and the
    `Connection` property-assignment rule both resolve nothing. Here the same Command Source's
    own construct is a factory call (`conn.CreateCommand()`), but its `Connection` property is
    also assigned explicitly (`cmd.Connection = explicitConn;`); the property assignment wins,
    exactly as it does today, and the factory receiver is never read."""
    result = _decompile(PROPERTY_ASSIGNED_CONNECTION_WITH_FACTORY_INITIALIZER_WRAPPER)

    assert result["status"] == "resolved"
    definition = _definition(result, "usp_RunAsync")
    assert definition["connection_expression"] == "explicitConn"

    operation = _operation(result, "usp_RunAsync")
    assert operation["connection_behavior_boundary"] == "wrapper_connection"


CONSTRUCTOR_CONNECTION_WRAPPER = """
public class Wrapper {
    private SqlConnection _conn;
    public Wrapper(SqlConnection conn) { _conn = conn; }
    public int usp_RunAsync(string sql) {
        SqlCommand cmd = new SqlCommand(sql, _conn);
        cmd.CommandType = CommandType.StoredProcedure;
        int rows = cmd.ExecuteNonQuery();
        return rows;
    }
}
public class SqlCommand : FakeCommand {
    public SqlCommand(string sql, SqlConnection conn) { CommandText = sql; }
}
"""


@requires_dotnet
def test_constructor_argument_connection_is_unaffected_by_the_new_rule() -> None:
    """A method that already resolves its connection through a command constructor argument
    reports exactly the value it reports today (`constructor_connection`): the new rule is read
    only as a last resort, and this Command Source is not a factory call at all."""
    result = _decompile(CONSTRUCTOR_CONNECTION_WRAPPER, config="Debug")

    assert result["status"] == "resolved"
    operation = _operation(result, "usp_RunAsync")
    assert operation["connection_behavior_boundary"] == "constructor_connection"


# The full IQCS surface after tickets 01, 02, 04 and 07: `usp_ExecCmdGetDataSetAsync`,
# `usp_ExecCmdGetJsonObjectListAsync` and `usp_ExecCmdGetJsonToTabletListAsync` classify through
# the widened command-object rule; the three delegating methods report as Delegated Methods. Now
# that ticket 08 has landed, `usp_ExecCmdGetCountAsync` -- EF Core's raw-SQL execution form --
# classifies too, and reports `context_connection` the same last-resort way: its receiver is
# also the `Database` facade. The four together were the classified methods that used to report
# an empty Connection Behavior Boundary before ticket 07.
REAL_CLASSIFIED_METHODS = {
    "usp_ExecCmdGetDataSetAsync",
    "usp_ExecCmdGetJsonObjectListAsync",
    "usp_ExecCmdGetJsonToTabletListAsync",
    "usp_ExecCmdGetCountAsync",
}


@requires_iqcs_fixture
def test_real_sqldbcontext_methods_report_context_connection_boundary() -> None:
    """Fixture-gated smoke test against the real `CommonLibrary.dll` checked out under IQCS.
    All four classified `SQLDbContext` methods report `context_connection` -- the three whose
    command comes from `Database.GetDbConnection().CreateCommand()`, and
    `usp_ExecCmdGetCountAsync`, whose raw-SQL execution call runs directly on the same `Database`
    facade (ticket 08). The proposal no longer fails on `connection_behavior_boundary_missing`,
    and the behaviour surface is complete: none of the seven public methods stay unclassified."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as cache_dir:
        result = host.decompile_wrapper(
            IQCS_CSPROJ,
            "SQLDbContext",
            cache_root=Path(cache_dir),
        )

    assert result["status"] == "resolved"
    operations = result["contract_proposals"][0]["implementation_snapshot"]["methods"]
    for method_name in REAL_CLASSIFIED_METHODS:
        matches = [op for op in operations if op["method_name"] == method_name]
        assert len(matches) == 1, f"expected exactly one operation for {method_name}"
        assert matches[0]["connection_behavior_boundary"] == "context_connection"

    snapshot = result["contract_proposals"][0]["implementation_snapshot"]
    validation = validate_implementation_snapshot(snapshot)
    assert "connection_behavior_boundary_missing" not in validation["unresolved_reasons"]
    assert snapshot["public_database_operations_complete"] is True
    assert snapshot["unclassified_public_methods"] == []


@requires_stc_fixture
def test_real_sqlfunc_connection_boundary_unchanged() -> None:
    """The existing `SQLFunc` classified surface reports the same Connection Behavior Boundary
    it reported before this ticket -- `wrapper_connection` for every operation, since `SQLFunc`
    contains no `CreateCommand` call at all."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as cache_dir:
        result = host.decompile_wrapper(
            STC_CSPROJ,
            "SQLFunc",
            cache_root=Path(cache_dir),
        )

    assert result["status"] == "resolved"
    operations = result["contract_proposals"][0]["implementation_snapshot"]["methods"]
    assert operations, "expected SQLFunc to report at least one operation"
    assert all(
        operation["connection_behavior_boundary"] == "wrapper_connection"
        for operation in operations
    )


@requires_sqlobject_fixture
def test_real_sqlobject_connection_boundary_unchanged() -> None:
    """The existing `SQLObject` classified surface reports the same Connection Behavior
    Boundary it reported before this ticket -- `wrapper_connection` for every operation, since
    `SQLObject` contains no `CreateCommand` call at all."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as cache_dir:
        result = host.decompile_wrapper(
            TTPUR_CSPROJ,
            "SQLObject",
            cache_root=Path(cache_dir),
        )

    assert result["status"] == "resolved"
    operations = result["contract_proposals"][0]["implementation_snapshot"]["methods"]
    assert operations, "expected SQLObject to report at least one operation"
    assert all(
        operation["connection_behavior_boundary"] == "wrapper_connection"
        for operation in operations
    )
