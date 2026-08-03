"""Ticket 02 behavior checks: direct SqlClient invocation detection via CSharpAnalysisGateway."""

from __future__ import annotations

import sys
import tempfile
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
