"""Ticket 08: raw SQL executed through a context's `Database` facade resolves its Command Source.

The Command Source resolver used to recognise a command object bound to a variable only. EF
Core's raw-SQL execution API -- `Database.ExecuteSqlRaw`, `ExecuteSqlInterpolated`, and their
asynchronous forms -- constructs no command object at all, so every rule built around a command
object missed it. The measured real method, `SQLDbContext.usp_ExecCmdGetCountAsync`, was the one
public method left unclassified after tickets 01, 02, 04 and 07 -- and a single unclassified
public method blocks Contract creation completely.

This ticket adds a fourth Command Source rule for that shape. It reads the command text from the
argument the caller supplies (tracing back through the local-variable indirection EF Core's own
`FormattableString` construction introduces), reports the execution call itself as the terminal
sink, and reports `context_connection` for its Connection Behavior Boundary the same last-resort
way a command factory's receiver already does (ticket 07). The deferred `FromSqlRaw`/
`FromSqlInterpolated` forms stay unrecognised -- they hang off a `DbSet`, not the `Database`
facade, and belong to their own ticket.

These tests assert the externally observable fact -- the decompile-wrapper response's classified
wrapper definitions and contract proposal, and the `/refresh` outcome -- not the shape of the
resolver itself, per this repo's testing conventions.
"""

from __future__ import annotations

import json
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

from code_analyzer.external_wrapper_contracts import validate_implementation_snapshot
from code_analyzer.project_scanner import ProjectScanResult
from code_analyzer.static_analyzer_host import StaticAnalyzerHost
from service import analyze_service

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

# Minimal real ADO.NET types plus a `Database`-facade stand-in exposing the four raw-SQL
# execution methods and the factory shape ticket 07 already covers -- modelled on the real
# `SQLDbContext` shape, not invented: `FakeDatabaseFacade` is the same stand-in
# test_connection_behavior_boundary.py uses for `Database.GetDbConnection()`, widened here with
# `ExecuteSqlRaw`/`ExecuteSqlInterpolated` and their async forms.
_ADO_NET_STAND_INS = """
using System;
using System.Data;
using System.Data.Common;
using System.Threading.Tasks;
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
public class FakeDatabaseFacade {
    private readonly DbConnection _connection;
    public FakeDatabaseFacade(DbConnection connection) { _connection = connection; }
    public DbConnection GetDbConnection() => _connection;
    public int ExecuteSqlRaw(string sql, params object[] parameters) => 0;
    public Task<int> ExecuteSqlRawAsync(string sql, params object[] parameters) => Task.FromResult(0);
    public int ExecuteSqlInterpolated(FormattableString sql) => 0;
    public Task<int> ExecuteSqlInterpolatedAsync(FormattableString sql) => Task.FromResult(0);
}
// Not a real ADO.NET type, but named like one -- IsAdoNetType matches purely by name, the same
// way it recognises any other provider's SqlParameter, so this is enough to mark a method as
// touching the database (matching the real SQLDbContext methods, which all carry an actual
// `SqlParameter[]? sqlParameters` parameter for exactly this reason).
public class SqlParameter {}
public class FakeDbSet {
    public object FromSqlRaw(string sql, SqlParameter[] parameters) => null;
    public object FromSqlInterpolated(FormattableString sql, SqlParameter[] parameters) => null;
}
"""


def _build_dll(build_dir: Path, wrapper_source: str, config: str = "Release") -> Path:
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


WRAPPER_HEADER = """
public class Wrapper {
    private readonly FakeDatabaseFacade _database;
    private readonly FakeDbSet _foos;
    protected FakeDatabaseFacade Database => _database;
    public Wrapper(string cn) {
        _database = new FakeDatabaseFacade(new SqlConnection(cn));
        _foos = new FakeDbSet();
    }
"""


RAW_SQL_FORMS_WRAPPER = (
    WRAPPER_HEADER
    + """
    public int usp_RunRaw(string sql) => Database.ExecuteSqlRaw(sql);
    public System.Threading.Tasks.Task<int> usp_RunRawAsync(string sql) => Database.ExecuteSqlRawAsync(sql);
    public int usp_RunInterpolated(System.FormattableString sql) => Database.ExecuteSqlInterpolated(sql);
    public System.Threading.Tasks.Task<int> usp_RunInterpolatedAsync(System.FormattableString sql)
        => Database.ExecuteSqlInterpolatedAsync(sql);
}
"""
)


@requires_dotnet
@pytest.mark.parametrize(
    "method_name,terminal_sink",
    [
        ("usp_RunRaw", "ExecuteSqlRaw"),
        ("usp_RunRawAsync", "ExecuteSqlRawAsync"),
        ("usp_RunInterpolated", "ExecuteSqlInterpolated"),
        ("usp_RunInterpolatedAsync", "ExecuteSqlInterpolatedAsync"),
    ],
)
def test_all_four_execute_forms_resolve(method_name: str, terminal_sink: str) -> None:
    """All four `Execute` forms -- raw and interpolated, synchronous and asynchronous -- resolve
    a Command Source, are reported as classified wrapper definitions rather than unclassified
    public methods, and each names its own execution call as its terminal sink."""
    result = _decompile(RAW_SQL_FORMS_WRAPPER)

    assert result["status"] == "resolved"
    snapshot = result["contract_proposals"][0]["implementation_snapshot"]
    assert method_name not in snapshot["unclassified_public_methods"]

    definition = _definition(result, method_name)
    assert definition["unresolved_reason"] is None
    assert definition["terminal_sink"] == terminal_sink

    operation = _operation(result, method_name)
    assert operation["terminal_sink"] == terminal_sink
    assert operation["connection_behavior_boundary"] == "context_connection"


COMMAND_TEXT_FROM_PARAMETER_WRAPPER = (
    WRAPPER_HEADER
    + """
    public int usp_RunRaw(string sql) => Database.ExecuteSqlRaw(sql);
}
"""
)


@requires_dotnet
def test_command_text_is_read_from_the_callers_argument() -> None:
    """The command text is read from the argument the caller supplies: a call site that invokes
    this wrapper method is traced to its `sql` parameter -- `command_text` at argument index 0 --
    exactly as it is for a sibling method that does construct a command object."""
    result = _decompile(COMMAND_TEXT_FROM_PARAMETER_WRAPPER)

    assert result["status"] == "resolved"
    operation = _operation(result, "usp_RunRaw")
    assert operation["argument_roles"]["command_text"] == 0


# Modelled directly on the real, measured `SQLDbContext.usp_ExecCmdGetCountAsync`: a command-text
# local assigned from the method's own parameter, conditionally reassigned under a boolean
# parameter, then wrapped through `FormattableStringFactory.Create` before reaching the execution
# call -- the exact indirection the command-text tracer exists to see through.
MODE_ARGUMENT_WRAPPER = (
    WRAPPER_HEADER
    + """
    public System.Threading.Tasks.Task<int> usp_ExecCmdGetCountAsync(string sqlCmd, bool isSP) {
        string text = sqlCmd;
        if (isSP) { text = "exec " + sqlCmd + " "; }
        System.FormattableString formattableString =
            System.Runtime.CompilerServices.FormattableStringFactory.Create(text, System.Array.Empty<object>());
        return Database.ExecuteSqlInterpolatedAsync(formattableString);
    }
}
"""
)


@requires_dotnet
def test_method_carrying_a_mode_argument_reports_call_site_semantics() -> None:
    """A method carrying a mode argument (`isSP`, guarding a conditional that reshapes the raw
    SQL text) reports `call_site` command semantics, and the command text still traces back to
    `sqlCmd` through the local-variable and `FormattableStringFactory.Create` indirection the real
    measured method carries."""
    result = _decompile(MODE_ARGUMENT_WRAPPER)

    assert result["status"] == "resolved"
    operation = _operation(result, "usp_ExecCmdGetCountAsync")
    assert operation["effective_command_semantics"] == "call_site"
    assert operation["argument_roles"]["command_text"] == 0
    assert operation["argument_roles"]["command_type"] == 1
    assert operation["connection_behavior_boundary"] == "context_connection"
    assert operation["terminal_sink"] == "ExecuteSqlInterpolatedAsync"


FIXED_MODE_WRAPPER = (
    WRAPPER_HEADER
    + """
    public int usp_RunRaw(string sql) => Database.ExecuteSqlRaw(sql);
}
"""
)


@requires_dotnet
def test_method_with_no_mode_argument_reports_the_fixed_mode() -> None:
    """A method whose mode is fixed in the body (no parameter guards how the SQL text is built)
    reports the fixed, inline-SQL mode -- raw SQL executed through the facade is never
    definitively a stored procedure, so it never reports the stored-procedure mode."""
    result = _decompile(FIXED_MODE_WRAPPER)

    assert result["status"] == "resolved"
    operation = _operation(result, "usp_RunRaw")
    assert operation["effective_command_semantics"] == "inline_sql"
    assert "command_type" not in operation["argument_roles"]


DEFERRED_FROM_SQL_WRAPPER = (
    WRAPPER_HEADER
    + """
    public object usp_FromSqlRaw(string sql, SqlParameter[] parameters) => _foos.FromSqlRaw(sql, parameters);
    public object usp_FromSqlInterpolated(System.FormattableString sql, SqlParameter[] parameters)
        => _foos.FromSqlInterpolated(sql, parameters);
}
"""
)


@requires_dotnet
def test_deferred_fromsql_forms_stay_unclassified_and_named() -> None:
    """The deferred `FromSqlRaw`/`FromSqlInterpolated` forms are not recognised by this ticket's
    rule -- they return a queryable, execute later, and hang off a `DbSet` rather than the
    `Database` facade. Both methods stay in the unclassified set, named rather than silently
    dropped."""
    result = _decompile(DEFERRED_FROM_SQL_WRAPPER)

    assert result["status"] == "resolved"
    snapshot = result["contract_proposals"][0]["implementation_snapshot"]
    unclassified = snapshot["unclassified_public_methods"]
    assert any(identity.startswith("Wrapper.usp_FromSqlRaw(") for identity in unclassified)
    assert any(identity.startswith("Wrapper.usp_FromSqlInterpolated(") for identity in unclassified)


# The full IQCS surface after tickets 01, 02, 04 and 07: three methods classify through the
# widened command-object rule, three more resolve as Delegated Methods, and
# `usp_ExecCmdGetCountAsync` -- EF Core's raw-SQL execution form, this ticket's shape -- was the
# one method left unclassified. This ticket closes that last gap.
REAL_SEVEN_METHOD_NAMES = {
    "usp_ExecCmdGetDataSetAsync",
    "usp_ExecCmdGetFisrtValueAsync",
    "usp_ExecCmdGetDataTableAsync",
    "usp_ExecCmdGetJsonObjectAsync",
    "usp_ExecCmdGetJsonObjectListAsync",
    "usp_ExecCmdGetJsonToTabletListAsync",
    "usp_ExecCmdGetCountAsync",
}


@requires_iqcs_fixture
def test_real_sqldbcontext_reports_all_seven_methods_classified_or_delegated() -> None:
    """Fixture-gated smoke test against the real `CommonLibrary.dll` checked out under IQCS.
    `usp_ExecCmdGetCountAsync` -- the last unclassified public method -- resolves its Command
    Source: its command text traces to `sqlCmd`, its mode traces to `isSP` and reports
    `call_site` (matching its six sibling methods), its Connection Behavior Boundary is
    `context_connection`, and its terminal sink is the execution call itself. All seven public
    `SQLDbContext` methods are now accounted for -- classified or delegated, none unclassified --
    and the proposal passes the completeness check."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as cache_dir:
        result = host.decompile_wrapper(
            IQCS_CSPROJ,
            "SQLDbContext",
            cache_root=Path(cache_dir),
        )

    assert result["status"] == "resolved"
    snapshot = result["contract_proposals"][0]["implementation_snapshot"]
    assert snapshot["unclassified_public_methods"] == []
    assert snapshot["public_database_operations_complete"] is True

    operation = _operation(result, "usp_ExecCmdGetCountAsync")
    assert operation["argument_roles"]["command_text"] == 0
    assert operation["argument_roles"]["command_type"] == 2
    assert operation["effective_command_semantics"] == "call_site"
    assert operation["connection_behavior_boundary"] == "context_connection"
    assert operation["terminal_sink"] == "ExecuteSqlInterpolatedAsync"

    definition = _definition(result, "usp_ExecCmdGetCountAsync")
    assert definition["unresolved_reason"] is None

    reported_methods = {op["method_name"] for op in snapshot["methods"]}
    # method_identity is "TypeName.MethodName(ParamType,...)"; a parameter type can itself
    # contain dots (e.g. "Microsoft.EntityFrameworkCore.SqlParameter[]?"), so the method name is
    # taken from the portion before the argument list's opening paren, not from a naive split.
    delegated_names = {
        method["method_identity"].split("(")[0].rsplit(".", 1)[-1]
        for method in result["delegated_methods"]
    }
    assert reported_methods | delegated_names >= REAL_SEVEN_METHOD_NAMES

    validation = validate_implementation_snapshot(snapshot)
    assert validation["complete"] is True
    assert validation["unresolved_reasons"] == []


# --- The measured outcome: a full IQCS refresh reports a created Contract, and both the external
# wrapper registry and the system catalog carry it afterwards, with no manual step. ---


def _iqcs_scan(root: Path) -> ProjectScanResult:
    """A scan whose only role is to name `SQLDbContext` as an external (decompiled) wrapper
    receiver for `_populate_decompilation_proposals`, the same indirection
    test_refresh_decompile_onboarding.py's `_scan()` helper uses for the real SQLFunc fixture:
    `scan.project_root` points at the real IQCS checkout, so the real `IQCS.csproj` and the real
    `CommonLibrary.dll` it references are what actually get decompiled -- nothing here is a stand-in
    for that DLL's content."""
    source_file = root / "SomeService.cs"
    return ProjectScanResult(
        project_root=str(root),
        project_name=root.name,
        scan_time=datetime.now(),
        db_invocations={
            str(source_file): [
                {
                    "invocation_kind": "source_wrapper",
                    "class_name": "SomeService",
                    "method_name": "Run",
                    "wrapper_method_name": "usp_ExecCmdGetCountAsync",
                    "wrapper_receiver_type": "SQLDbContext",
                    "wrapper_source_available": False,
                    "wrapper_method_arity": 3,
                    "wrapper_parameter_types": [
                        "string",
                        "Microsoft.EntityFrameworkCore.SqlParameter[]?",
                        "bool",
                    ],
                    "wrapper_mode": "call_site",
                    "command_text_kind": "literal",
                    "command_text": "usp_SomeProc",
                    "connection_expression": "",
                    "start_offset": 1,
                    "end_offset": 20,
                }
            ]
        },
    )


def _patch_refresh(monkeypatch, root: Path, scan: ProjectScanResult) -> None:
    monkeypatch.setattr(
        analyze_service,
        "resolve_scan_roots",
        lambda source, refresh=False: [root],
    )
    monkeypatch.setattr(
        analyze_service,
        "get_or_scan",
        lambda scan_root, refresh=False: scan,
    )
    monkeypatch.setattr(
        analyze_service,
        "load_contract_registry",
        lambda: {"contracts": {}},
    )


@requires_iqcs_fixture
def test_real_iqcs_refresh_creates_and_commits_a_contract(monkeypatch, tmp_path) -> None:
    """Fixture-gated end-to-end test against the real IQCS checkout. A full refresh -- decompiling
    the real `SQLDbContext`, running Contract Preflight against its now-complete behaviour
    surface, and committing the result -- reports a created Contract rather than
    `preflight_failed`, and both the external wrapper registry and the system catalog carry it
    afterwards, with no manual step."""
    scan = _iqcs_scan(IQCS_CSPROJ.parent)
    _patch_refresh(monkeypatch, IQCS_CSPROJ.parent, scan)

    registry_path = tmp_path / "external_wrapper_contracts.json"
    catalog_path = tmp_path / "system_catalog.json"
    registry_path.write_text(json.dumps({"contracts": {}}), encoding="utf-8")
    catalog_path.write_text(
        json.dumps({"systems": [{"system_id": "IQCS", "wrapper_contract": ""}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(analyze_service, "cached_commit", lambda scan_root: "deadbeef")
    monkeypatch.setattr(analyze_service, "CONTRACT_TRANSACTION_REGISTRY_PATH", registry_path)
    monkeypatch.setattr(analyze_service, "CONTRACT_TRANSACTION_CATALOG_PATH", catalog_path)

    result = analyze_service.refresh_source(
        {"project": "p", "repo": "r"},
        database="IQCS",
    )

    assert result["wrapper_summary"]["contract_onboarding_status"] == "created"
    assert result["contract_transaction"]["status"] == "committed"

    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    assert registry["contracts"], "expected the external wrapper registry to carry a new contract"

    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    assert catalog["systems"][0]["wrapper_contract"], (
        "expected the system catalog's IQCS entry to name the committed contract"
    )
