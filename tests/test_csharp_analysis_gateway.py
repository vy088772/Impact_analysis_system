"""Ticket 02 behavior checks: direct SqlClient invocation detection via CSharpAnalysisGateway."""

from __future__ import annotations

import sys
import tempfile
from unittest.mock import patch
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from code_analyzer.csharp_analysis_gateway import (
    CSharpAnalysisGateway,
    InvocationEvidence,
    SpCatalog,
    normalize_procedure_name,
)
from code_analyzer.static_analyzer_host import StaticAnalyzerHost
import code_analyzer.static_analyzer_host as static_analyzer_host_module


def _raw_invocation(**overrides) -> dict:
    base = {
        "class_name": "PUR_SOMaintain",
        "method_name": "DeleteData",
        "command_text_kind": "literal",
        "command_text": "usp_SO_Delete",
        "command_type_stored_procedure": True,
        "connection_expression": "conn",
        "start_offset": 10,
        "end_offset": 90,
    }
    base.update(overrides)
    return base


def test_normalize_procedure_name_strips_schema_and_brackets() -> None:
    """Only the bare, case-insensitive procedure name is used for catalog matching."""
    assert normalize_procedure_name("usp_SO_Delete") == "usp_so_delete"
    assert normalize_procedure_name("dbo.usp_SO_Delete") == "usp_so_delete"
    assert normalize_procedure_name("[dbo].[usp_SO_Delete]") == "usp_so_delete"


def test_explicit_stored_procedure_type_with_catalog_hit_is_proven() -> None:
    """An explicit CommandType.StoredProcedure call matching the resolved database's catalog is proven."""
    catalog = SpCatalog.from_databases({"Y-Docs_TTPUR": ["usp_SO_Delete"]})
    gateway = CSharpAnalysisGateway(catalog, connection_sources={"conn": "Y-Docs_TTPUR"})

    invocations = gateway.resolve_direct_invocations("Ship/PUR_SOMaintain.aspx.cs", [_raw_invocation()])

    assert len(invocations) == 1
    invocation = invocations[0]
    assert invocation.class_name == "PUR_SOMaintain"
    assert invocation.method_name == "DeleteData"
    assert invocation.database == "Y-Docs_TTPUR"
    assert invocation.procedure_name == "usp_so_delete"
    assert invocation.evidence is InvocationEvidence.PROVEN
    assert invocation.source.relative_path == "Ship/PUR_SOMaintain.aspx.cs"
    assert invocation.source.start_offset == 10
    assert invocation.source.end_offset == 90


def test_schema_qualified_catalog_matching_does_not_cross_same_name_schemas() -> None:
    catalog = SpCatalog.from_databases({
        "Y-Docs_TTPUR": ["dbo.usp_SO_Delete", "sales.usp_SO_Delete"],
    })
    gateway = CSharpAnalysisGateway(catalog, connection_sources={"conn": "Y-Docs_TTPUR"})

    proven = gateway.resolve_direct_invocations(
        "f.cs",
        [_raw_invocation(command_text="sales.usp_SO_Delete")],
    )[0]
    unresolved = gateway.resolve_direct_invocations(
        "f.cs",
        [_raw_invocation(command_text="reporting.usp_SO_Delete")],
    )[0]

    assert proven.evidence is InvocationEvidence.PROVEN
    assert proven.procedure_schema == "sales"
    assert unresolved.evidence is InvocationEvidence.UNRESOLVED
    assert unresolved.reason == "not_in_resolved_catalog"


def test_bare_catalog_entries_are_scoped_to_default_schema_for_qualified_calls() -> None:
    catalog = SpCatalog.from_databases({"Y-Docs_TTPUR": ["usp_SO_Delete"]})
    gateway = CSharpAnalysisGateway(catalog, connection_sources={"conn": "Y-Docs_TTPUR"})

    invocation = gateway.resolve_direct_invocations(
        "f.cs",
        [_raw_invocation(command_text="sales.usp_SO_Delete")],
    )[0]

    assert invocation.evidence is InvocationEvidence.UNRESOLVED
    assert invocation.reason == "not_in_resolved_catalog"


def test_inline_sql_without_stored_procedure_type_is_not_reported() -> None:
    """A SqlCommand call that never sets CommandType.StoredProcedure is plain SQL, not an SP invocation."""
    catalog = SpCatalog.from_databases({"Y-Docs_TTPUR": ["usp_SO_Delete"]})
    gateway = CSharpAnalysisGateway(catalog, connection_sources={"conn": "Y-Docs_TTPUR"})

    raw = _raw_invocation(command_text="SELECT * FROM SOrder", command_type_stored_procedure=False)
    invocations = gateway.resolve_direct_invocations("Ship/PUR_SOMaintain.aspx.cs", [raw])

    assert invocations == []


def test_dynamic_command_text_is_unresolved() -> None:
    """A variable-built command text cannot be identified statically, so it stays unresolved."""
    catalog = SpCatalog.from_databases({"Y-Docs_TTPUR": ["usp_SO_Delete"]})
    gateway = CSharpAnalysisGateway(catalog, connection_sources={"conn": "Y-Docs_TTPUR"})

    raw = _raw_invocation(command_text_kind="dynamic", command_text=None)
    invocations = gateway.resolve_direct_invocations("f.cs", [raw])

    assert len(invocations) == 1
    assert invocations[0].evidence is InvocationEvidence.UNRESOLVED
    assert invocations[0].procedure_name is None
    assert invocations[0].database == "Y-Docs_TTPUR"


def test_resolved_database_without_catalog_hit_is_unresolved_not_guessed() -> None:
    """A resolved database that does not contain the named procedure must not be fabricated as proven."""
    catalog = SpCatalog.from_databases({"Y-Docs_TTPUR": ["usp_SO_Insert"]})
    gateway = CSharpAnalysisGateway(catalog, connection_sources={"conn": "Y-Docs_TTPUR"})

    invocations = gateway.resolve_direct_invocations("f.cs", [_raw_invocation()])

    assert invocations[0].evidence is InvocationEvidence.UNRESOLVED
    assert invocations[0].database == "Y-Docs_TTPUR"
    assert invocations[0].procedure_name == "usp_so_delete"


def test_unknown_connection_source_unique_across_catalogs_is_likely() -> None:
    """When the connection source cannot be resolved, a globally unique procedure name is only likely."""
    catalog = SpCatalog.from_databases({
        "Y-Docs_TTPUR": ["usp_SO_Delete"],
        "OtherDb": ["usp_Something_Else"],
    })
    gateway = CSharpAnalysisGateway(catalog, connection_sources={})

    invocations = gateway.resolve_direct_invocations("f.cs", [_raw_invocation()])

    assert invocations[0].evidence is InvocationEvidence.LIKELY
    assert invocations[0].database == "Y-Docs_TTPUR"
    assert invocations[0].procedure_name == "usp_so_delete"


def test_unknown_connection_source_ambiguous_across_catalogs_is_unresolved() -> None:
    """A same-named procedure in multiple databases must remain unresolved without a known connection source."""
    catalog = SpCatalog.from_databases({
        "Y-Docs_TTPUR": ["usp_SO_Delete"],
        "Y-Docs_TTRDQ": ["usp_SO_Delete"],
    })
    gateway = CSharpAnalysisGateway(catalog, connection_sources={})

    invocations = gateway.resolve_direct_invocations("f.cs", [_raw_invocation()])

    assert invocations[0].evidence is InvocationEvidence.UNRESOLVED
    assert invocations[0].database is None
    assert invocations[0].procedure_name == "usp_so_delete"


def test_unknown_connection_source_and_unknown_name_is_unresolved() -> None:
    """A procedure name absent from every known catalog stays unresolved, never guessed."""
    catalog = SpCatalog.from_databases({"Y-Docs_TTPUR": ["usp_SO_Insert"]})
    gateway = CSharpAnalysisGateway(catalog, connection_sources={})

    invocations = gateway.resolve_direct_invocations("f.cs", [_raw_invocation()])

    assert invocations[0].evidence is InvocationEvidence.UNRESOLVED
    assert invocations[0].database is None
    assert invocations[0].procedure_name == "usp_so_delete"


def test_gateway_detects_real_direct_sqlclient_invocation_via_static_analyzer_host() -> None:
    """End-to-end: the real Roslyn host output feeds the gateway to a proven Database Invocation."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "Foo.cs"
        source_path.write_text(
            "public class Foo {\n"
            "    private void Run() {\n"
            "        var conn = new SqlConnection(\"x\");\n"
            "        var cmd = new SqlCommand(\"usp_DoThing\", conn);\n"
            "        cmd.CommandType = CommandType.StoredProcedure;\n"
            "        cmd.ExecuteNonQuery();\n"
            "    }\n"
            "    private void Inline() {\n"
            "        var conn2 = new SqlConnection(\"x\");\n"
            "        var cmd2 = new SqlCommand(\"SELECT * FROM Foo\", conn2);\n"
            "        cmd2.ExecuteReader();\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )

        result = host.analyze_csharp(source_path)
        raw_invocations = result["db_invocations"]
        assert len(raw_invocations) == 2
        assert raw_invocations[1]["command_type_stored_procedure"] is False

        catalog = SpCatalog.from_databases({"MyDb": ["usp_DoThing"]})
        gateway = CSharpAnalysisGateway(catalog, connection_sources={"conn": "MyDb"})
        invocations = gateway.resolve_direct_invocations("Foo.cs", raw_invocations)

        assert len(invocations) == 1
        assert invocations[0].evidence is InvocationEvidence.PROVEN
        assert invocations[0].procedure_name == "usp_dothing"
        assert invocations[0].database == "MyDb"


def test_gateway_detects_source_wrapper_sp_mode_but_skips_inline_mode() -> None:
    """A source-backed wrapper is proven only when its call-site mode selects SP execution."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "WrapperFixture.cs"
        source_path.write_text(
            "using System.Data;\n"
            "using System.Data.SqlClient;\n"
            "public class DbWrapper {\n"
            "    private readonly SqlConnection _connection;\n"
            "    public DbWrapper(SqlConnection connection) { _connection = connection; }\n"
            "    public void Execute(string commandText, bool storedProcedure) {\n"
            "        var command = new SqlCommand(commandText, _connection);\n"
            "        command.CommandType = storedProcedure ? CommandType.StoredProcedure : CommandType.Text;\n"
            "        command.ExecuteNonQuery();\n"
            "    }\n"
            "}\n"
            "public class OrderPage {\n"
            "    private void Save() {\n"
            "        var wrapper = new DbWrapper(null);\n"
            "        wrapper.Execute(\"usp_SaveOrder\", true);\n"
            "    }\n"
            "    private void Preview() {\n"
            "        var wrapper = new DbWrapper(null);\n"
            "        wrapper.Execute(\"SELECT * FROM SOrder\", false);\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )

        result = host.analyze_csharp(source_path)
        catalog = SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]})
        gateway = CSharpAnalysisGateway(catalog, connection_sources={"wrapper": "OrdersDb"})

        invocations = gateway.resolve_direct_invocations("WrapperFixture.cs", result["db_invocations"])

        assert len(invocations) == 1
        assert invocations[0].class_name == "OrderPage"
        assert invocations[0].method_name == "Save"
        assert invocations[0].procedure_name == "usp_saveorder"
        assert invocations[0].evidence is InvocationEvidence.PROVEN


def test_static_analyzer_host_traces_source_wrapper_across_files() -> None:
    """Batch C# analysis makes a wrapper in one source file available to its caller."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        wrapper_path = Path(temp_dir) / "DbWrapper.cs"
        wrapper_path.write_text(
            "using System.Data;\n"
            "using System.Data.SqlClient;\n"
            "public class DbWrapper {\n"
            "    private readonly SqlConnection _connection;\n"
            "    public DbWrapper(SqlConnection connection) { _connection = connection; }\n"
            "    public void Execute(string commandText, bool storedProcedure) {\n"
            "        var command = new SqlCommand(commandText, _connection);\n"
            "        command.CommandType = storedProcedure ? CommandType.StoredProcedure : CommandType.Text;\n"
            "        command.ExecuteNonQuery();\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )
        caller_path = Path(temp_dir) / "OrderPage.cs"
        caller_path.write_text(
            "public class OrderPage {\n"
            "    private void Save() {\n"
            "        var wrapper = new DbWrapper(null);\n"
            "        wrapper.Execute(\"usp_SaveOrder\", true);\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )

        results = host.analyze_csharp_files([wrapper_path, caller_path])

        assert len(results) == 2
        caller_result = results[1]
        wrapper_invocations = [
            invocation
            for invocation in caller_result["db_invocations"]
            if invocation.get("invocation_kind") == "source_wrapper"
        ]
        assert len(wrapper_invocations) == 1
        assert wrapper_invocations[0]["method_chain"] == ["Save", "Execute"]


def test_static_analyzer_host_disambiguates_same_named_wrappers_by_namespace() -> None:
    """A fully qualified caller receiver selects the matching same-named wrapper definition."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        first_wrapper_path = root / "FirstWrapper.cs"
        first_wrapper_path.write_text(
            "using System.Data;\n"
            "using System.Data.SqlClient;\n"
            "namespace First {\n"
            "    public class DbWrapper {\n"
            "        private readonly SqlConnection _connection;\n"
            "        public DbWrapper(SqlConnection connection) { _connection = connection; }\n"
            "        public void Execute(string commandText, bool storedProcedure) {\n"
            "            var command = new SqlCommand(commandText, _connection);\n"
            "            command.CommandType = storedProcedure ? CommandType.StoredProcedure : CommandType.Text;\n"
            "            command.ExecuteNonQuery();\n"
            "        }\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )
        second_wrapper_path = root / "SecondWrapper.cs"
        second_wrapper_path.write_text(
            "using System.Data;\n"
            "using System.Data.SqlClient;\n"
            "namespace Second {\n"
            "    public class DbWrapper {\n"
            "        private readonly SqlConnection _connection;\n"
            "        public DbWrapper(SqlConnection connection) { _connection = connection; }\n"
            "        public void Execute(string commandText, bool storedProcedure) {\n"
            "            var command = new SqlCommand(commandText, _connection);\n"
            "            command.CommandType = storedProcedure ? CommandType.StoredProcedure : CommandType.Text;\n"
            "            command.ExecuteNonQuery();\n"
            "        }\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )
        caller_path = root / "OrderPage.cs"
        caller_path.write_text(
            "public class OrderPage {\n"
            "    private void Save() {\n"
            "        var conn = new object();\n"
            "        var wrapper = new First.DbWrapper(null);\n"
            "        wrapper.Execute(\"usp_SaveOrder\", true);\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )

        results = host.analyze_csharp_files(
            [first_wrapper_path, second_wrapper_path, caller_path],
            source_roots=[root],
        )

        caller_invocations = [
            invocation
            for invocation in results[2]["db_invocations"]
            if invocation.get("invocation_kind") == "source_wrapper"
        ]
        assert len(caller_invocations) == 1
        assert caller_invocations[0]["wrapper_source_available"] is True
        assert caller_invocations[0]["wrapper_class_name"] == "DbWrapper"
        assert caller_invocations[0]["wrapper_method_name"] == "Execute"

        gateway = CSharpAnalysisGateway(
            SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]}),
            connection_sources={"wrapper": "OrdersDb"},
        )
        invocations = gateway.resolve_direct_invocations("OrderPage.cs", caller_invocations)

        assert len(invocations) == 1
        assert invocations[0].evidence is InvocationEvidence.PROVEN


def test_static_analyzer_host_keeps_wrapper_source_available_across_batches() -> None:
    """Every C# batch keeps the full source root as wrapper-analysis context."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        wrapper_path = root / "DbWrapper.cs"
        wrapper_path.write_text(
            "using System.Data;\n"
            "using System.Data.SqlClient;\n"
            "public class DbWrapper {\n"
            "    public void Execute(string commandText, bool storedProcedure) {\n"
            "        var command = new SqlCommand(commandText, null);\n"
            "        command.CommandType = storedProcedure ? CommandType.StoredProcedure : CommandType.Text;\n"
            "        command.ExecuteNonQuery();\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )
        caller_path = root / "OrderPage.cs"
        caller_path.write_text(
            "public class OrderPage {\n"
            "    private void Save() {\n"
            "        var wrapper = new DbWrapper();\n"
            "        wrapper.Execute(\"usp_SaveOrder\", true);\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )

        with patch.object(static_analyzer_host_module, "_MAX_HOST_COMMAND_CHARS", 1):
            results = host.analyze_csharp_files([caller_path, wrapper_path], source_roots=[root])

        caller_result = results[0]
        assert any(
            invocation.get("invocation_kind") == "source_wrapper"
            and invocation.get("wrapper_source_available") is True
            for invocation in caller_result["db_invocations"]
        )


def test_source_wrapper_string_sp_mode_is_catalog_validated() -> None:
    """A wrapper selecting SP mode through a string discriminator is proven and inline mode is skipped."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "StringModeFixture.cs"
        source_path.write_text(
            "using System.Data;\n"
            "using System.Data.SqlClient;\n"
            "public class DbWrapper {\n"
            "    public void Execute(string commandText, string mode) {\n"
            "        var command = new SqlCommand(commandText, null);\n"
            "        if (mode == \"SP\")\n"
            "            command.CommandType = CommandType.StoredProcedure;\n"
            "        else\n"
            "            command.CommandType = CommandType.Text;\n"
            "        command.ExecuteNonQuery();\n"
            "    }\n"
            "}\n"
            "public class OrderPage {\n"
            "    private void Save() {\n"
            "        var wrapper = new DbWrapper();\n"
            "        wrapper.Execute(\"usp_SaveOrder\", \"SP\");\n"
            "    }\n"
            "    private void Preview() {\n"
            "        var wrapper = new DbWrapper();\n"
            "        wrapper.Execute(\"SELECT * FROM SOrder\", \"Text\");\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )

        result = host.analyze_csharp(source_path)
        gateway = CSharpAnalysisGateway(
            SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]}),
            connection_sources={"wrapper": "OrdersDb"},
        )
        invocations = gateway.resolve_direct_invocations("StringModeFixture.cs", result["db_invocations"])

        assert len(invocations) == 1
        assert invocations[0].method_name == "Save"
        assert invocations[0].evidence is InvocationEvidence.PROVEN


def test_source_wrapper_propagates_constructor_connection_to_catalog() -> None:
    """A wrapper field assigned from its constructor receives the caller's database source."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        wrapper_path = root / "DbWrapper.cs"
        wrapper_path.write_text(
            "using System.Data;\n"
            "using System.Data.SqlClient;\n"
            "public class DbWrapper {\n"
            "    private readonly SqlConnection _connection;\n"
            "    public DbWrapper(SqlConnection connection) { _connection = connection; }\n"
            "    public void Execute(string commandText, bool storedProcedure) {\n"
            "        var command = new SqlCommand(commandText, _connection);\n"
            "        command.CommandType = storedProcedure ? CommandType.StoredProcedure : CommandType.Text;\n"
            "        command.ExecuteNonQuery();\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )
        caller_path = root / "OrderPage.cs"
        caller_path.write_text(
            "public class OrderPage {\n"
            "    private void Save() {\n"
            "        var conn = new SqlConnection(\"x\");\n"
            "        var wrapper = new DbWrapper(conn);\n"
            "        wrapper.Execute(\"usp_SaveOrder\", true);\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )

        results = host.analyze_csharp_files([wrapper_path, caller_path], source_roots=[root])
        raw_invocations = results[1]["db_invocations"]
        gateway = CSharpAnalysisGateway(
            SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]}),
            connection_sources={"conn": "OrdersDb"},
        )
        invocations = gateway.resolve_direct_invocations("OrderPage.cs", raw_invocations)

        assert len(invocations) == 1
        assert invocations[0].database == "OrdersDb"
        assert invocations[0].evidence is InvocationEvidence.PROVEN


def test_source_wrapper_without_ado_net_sink_is_unresolved() -> None:
    """StoredProcedure configuration without command execution is not sink proof."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "NoSinkFixture.cs"
        source_path.write_text(
            "using System.Data;\n"
            "using System.Data.SqlClient;\n"
            "public class DbWrapper {\n"
            "    public void Execute(string commandText, bool storedProcedure) {\n"
            "        var command = new SqlCommand(commandText, null);\n"
            "        command.CommandType = storedProcedure ? CommandType.StoredProcedure : CommandType.Text;\n"
            "    }\n"
            "}\n"
            "public class OrderPage {\n"
            "    private void Save() {\n"
            "        var wrapper = new DbWrapper();\n"
            "        wrapper.Execute(\"usp_SaveOrder\", true);\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )

        result = host.analyze_csharp(source_path)
        raw_invocation = result["db_invocations"][0]
        assert raw_invocation["wrapper_reaches_stored_procedure_sink"] is False

        gateway = CSharpAnalysisGateway(
            SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]}),
            connection_sources={"wrapper": "OrdersDb"},
        )
        invocation = gateway.resolve_direct_invocations("NoSinkFixture.cs", [raw_invocation])[0]

        assert invocation.evidence is InvocationEvidence.UNRESOLVED
        assert invocation.reason == "wrapper_sink_unresolved"


def test_source_wrapper_tracks_command_properties_assigned_after_creation() -> None:
    """A wrapper that configures an empty SqlCommand through properties still yields a proven SP call."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "PropertySetupFixture.cs"
        source_path.write_text(
            "using System.Data;\n"
            "using System.Data.SqlClient;\n"
            "public class DbWrapper {\n"
            "    private readonly SqlConnection _connection;\n"
            "    public DbWrapper(SqlConnection connection) { _connection = connection; }\n"
            "    public void Execute(string commandText, string mode) {\n"
            "        var command = new SqlCommand();\n"
            "        command.CommandText = commandText;\n"
            "        command.Connection = _connection;\n"
            "        if (mode == \"SP\")\n"
            "            command.CommandType = CommandType.StoredProcedure;\n"
            "        command.ExecuteNonQuery();\n"
            "    }\n"
            "}\n"
            "public class OrderPage {\n"
            "    private void Save() {\n"
            "        var conn = new SqlConnection(\"x\");\n"
            "        var wrapper = new DbWrapper(conn);\n"
            "        wrapper.Execute(\"usp_SaveOrder\", \"SP\");\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )

        result = host.analyze_csharp(source_path)
        gateway = CSharpAnalysisGateway(
            SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]}),
            connection_sources={"conn": "OrdersDb"},
        )
        invocations = gateway.resolve_direct_invocations("PropertySetupFixture.cs", result["db_invocations"])

        assert len(invocations) == 1
        assert invocations[0].procedure_name == "usp_saveorder"
        assert invocations[0].evidence is InvocationEvidence.PROVEN


def test_unavailable_wrapper_source_is_unresolved_instead_of_proven() -> None:
    """A wrapper-shaped fact without its implementation cannot become catalog-proven."""
    catalog = SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]})
    gateway = CSharpAnalysisGateway(catalog, connection_sources={"conn": "OrdersDb"})

    raw = _raw_invocation(
        command_text="usp_SaveOrder",
        invocation_kind="source_wrapper",
        wrapper_source_available=False,
        wrapper_reaches_stored_procedure_sink=False,
        wrapper_mode="stored_procedure",
        connection_expression="conn",
    )

    invocations = gateway.resolve_direct_invocations("f.cs", [raw])

    assert len(invocations) == 1
    assert invocations[0].evidence is InvocationEvidence.UNRESOLVED
    assert invocations[0].reason == "wrapper_source_unavailable"


def test_inline_wrapper_mode_is_not_a_stored_procedure_invocation() -> None:
    """A source-backed wrapper selecting inline SQL is omitted from SP invocations."""
    catalog = SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]})
    gateway = CSharpAnalysisGateway(catalog, connection_sources={"conn": "OrdersDb"})

    raw = _raw_invocation(
        invocation_kind="source_wrapper",
        command_text="SELECT * FROM SOrder",
        command_type_stored_procedure=False,
        wrapper_source_available=True,
        wrapper_reaches_stored_procedure_sink=True,
        wrapper_mode="inline_sql",
        connection_expression="conn",
    )

    assert gateway.resolve_direct_invocations("f.cs", [raw]) == []


def test_static_analyzer_host_preserves_unavailable_wrapper_candidate() -> None:
    """A missing wrapper implementation leaves unresolved source evidence, never a proven call."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "OrderPage.cs"
        source_path.write_text(
            "public class OrderPage {\n"
            "    private void Save() {\n"
            "        var wrapper = GetExternalWrapper();\n"
            "        wrapper.Execute(\"usp_SaveOrder\", true);\n"
            "    }\n"
            "    private object GetExternalWrapper() { return null; }\n"
            "}\n",
            encoding="utf-8",
        )

        result = host.analyze_csharp(source_path)
        raw_invocations = [
            invocation
            for invocation in result["db_invocations"]
            if invocation.get("invocation_kind") == "source_wrapper"
        ]

        assert len(raw_invocations) == 1
        assert raw_invocations[0]["wrapper_source_available"] is False
        assert raw_invocations[0]["wrapper_mode"] == "stored_procedure"

        gateway = CSharpAnalysisGateway(
            SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]}),
            connection_sources={"wrapper": "OrdersDb"},
        )
        invocations = gateway.resolve_direct_invocations("OrderPage.cs", raw_invocations)

        assert len(invocations) == 1
        assert invocations[0].evidence is InvocationEvidence.UNRESOLVED
        assert invocations[0].reason == "wrapper_source_unavailable"


if __name__ == "__main__":
    test_normalize_procedure_name_strips_schema_and_brackets()
    test_explicit_stored_procedure_type_with_catalog_hit_is_proven()
    test_inline_sql_without_stored_procedure_type_is_not_reported()
    test_dynamic_command_text_is_unresolved()
    test_resolved_database_without_catalog_hit_is_unresolved_not_guessed()
    test_unknown_connection_source_unique_across_catalogs_is_likely()
    test_unknown_connection_source_ambiguous_across_catalogs_is_unresolved()
    test_unknown_connection_source_and_unknown_name_is_unresolved()
    test_gateway_detects_real_direct_sqlclient_invocation_via_static_analyzer_host()
    print("CSharpAnalysisGateway tests passed")
