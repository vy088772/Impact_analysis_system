"""Ticket 01: a Command Source may come from a data adapter, not only a command object.

A Command Source is the construct that supplies a wrapper method's command text and terminal
sink. These tests exercise the two rules the resolver holds through the real analyzer host, so
they assert the externally visible mode and terminal sink of a wrapper method, not the shape of
the resolver itself.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from code_analyzer.static_analyzer_host import StaticAnalyzerHost

pytestmark = pytest.mark.skipif(
    shutil.which("dotnet") is None,
    reason="the .NET toolchain is not available",
)


def _wrapper_call(source: str, wrapper_method_name: str) -> dict:
    """Analyze one C# source file and return the wrapper call to `wrapper_method_name`."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "CommandSourceWrapper.cs"
        source_path.write_text(source, encoding="utf-8")
        result = host.analyze_csharp(source_path)

    calls = [
        invocation
        for invocation in result["db_invocations"]
        if invocation["wrapper_method_name"] == wrapper_method_name
    ]
    assert len(calls) == 1, f"expected exactly one call to {wrapper_method_name}, got {calls}"
    return calls[0]


ADAPTER_TEXT_WRAPPER = """
public class Wrapper {
    private string strCn;
    public Wrapper(string cn) { strCn = cn; }
    public DataTable CreateTable(string strSql, string strTableName) {
        SqlConnection conn = new SqlConnection(strCn);
        conn.Open();
        DataSet ds = new DataSet();
        SqlDataAdapter da = new SqlDataAdapter(strSql, conn);
        da.Fill(ds, strTableName);
        conn.Close();
        return ds.Tables[strTableName];
    }
}
public class Caller {
    private void Run() {
        Wrapper w = new Wrapper("cn");
        w.CreateTable("SELECT * FROM Foo", "Foo");
    }
}
"""

ADAPTER_FROM_COMMAND_WRAPPER = """
public class Wrapper {
    private string strCn;
    public Wrapper(string cn) { strCn = cn; }
    public DataTable ExeTable(string strSql, string strTableName) {
        SqlConnection conn = new SqlConnection(strCn);
        conn.Open();
        DataSet ds = new DataSet();
        SqlCommand cmd = new SqlCommand(strSql, conn);
        cmd.CommandType = CommandType.StoredProcedure;
        SqlDataAdapter da = new SqlDataAdapter(cmd);
        da.Fill(ds, strTableName);
        conn.Close();
        return ds.Tables[strTableName];
    }
}
public class Caller {
    private void Run() {
        Wrapper w = new Wrapper("cn");
        w.ExeTable("usp_Bar", "Bar");
    }
}
"""

ADAPTER_STORED_PROCEDURE_WRAPPER = """
public class Wrapper {
    private string strCn;
    public Wrapper(string cn) { strCn = cn; }
    public DataTable ProcTable(string strSql, string strTableName) {
        SqlConnection conn = new SqlConnection(strCn);
        conn.Open();
        DataSet ds = new DataSet();
        SqlDataAdapter da = new SqlDataAdapter(strSql, conn);
        da.SelectCommand.CommandType = CommandType.StoredProcedure;
        da.Fill(ds, strTableName);
        conn.Close();
        return ds.Tables[strTableName];
    }
}
public class Caller {
    private void Run() {
        Wrapper w = new Wrapper("cn");
        w.ProcTable("usp_Bar", "Bar");
    }
}
"""


def test_data_adapter_with_command_text_and_connection_is_a_command_source() -> None:
    """A method that builds its command through a data adapter still gets a mode and a sink."""
    call = _wrapper_call(ADAPTER_TEXT_WRAPPER, "CreateTable")

    assert call["wrapper_source_available"] is True
    assert call["wrapper_method_identity"] == "Wrapper.CreateTable(string,string)"
    assert call["wrapper_method_semantics"] == "fixed_inline_sql"
    assert call["wrapper_terminal_sink"] == "Fill"
    assert call["wrapper_unresolved_reason"] is None


def test_data_adapter_built_from_a_command_object_yields_no_second_command_source() -> None:
    """The command object rule already covers that command, so the adapter adds no Command Source."""
    call = _wrapper_call(ADAPTER_FROM_COMMAND_WRAPPER, "ExeTable")

    assert call["wrapper_source_available"] is True
    assert call["wrapper_method_semantics"] == "fixed_stored_procedure"
    assert call["wrapper_terminal_sink"] == "Fill"
    assert call["wrapper_unresolved_reason"] is None


def test_data_adapter_command_source_honors_a_stored_procedure_command_type() -> None:
    """The adapter rule yields inline_sql only until the method assigns a stored-procedure type."""
    call = _wrapper_call(ADAPTER_STORED_PROCEDURE_WRAPPER, "ProcTable")

    assert call["wrapper_source_available"] is True
    assert call["wrapper_method_semantics"] == "fixed_stored_procedure"
    assert call["wrapper_terminal_sink"] == "Fill"
    assert call["wrapper_unresolved_reason"] is None
