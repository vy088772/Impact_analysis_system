"""Ticket 07: wrapper command text resolves from a same-method variable.

`WrapperAnalyzer.CreateUnavailableCandidate` -- the path an external wrapper call takes when its
method is declared in an assembly this analysis cannot see (every measured ASP.NET Core
repository's data access, per ADR-0020) -- read a call's command text only when the call site
passed a string literal directly. Any other expression read as ``dynamic``, so a variable or
field assigned the literal a few lines above the call, the ordinary style, resolved nothing.

`ReadWrapperCommandTextCandidates` already walks an identifier back to the declarations and
assignments that precede it inside the same method, wired to the source-available wrapper path
since before this ticket. This ticket wires the same tracer to the external-wrapper path. A
command text arriving as a method parameter, or as two same-method assignments that disagree, is
not something the tracer can honestly answer, so each stays unresolved and names its own reason
rather than reading as an ordinary ``dynamic`` expression.
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

from code_analyzer.csharp_analysis_gateway import CSharpAnalysisGateway, SpCatalog
from code_analyzer.static_analyzer_host import StaticAnalyzerHost

requires_dotnet = pytest.mark.skipif(
    shutil.which("dotnet") is None,
    reason="the .NET toolchain is not available",
)


def _analyze_one(source: str) -> dict:
    """Analyze one synthetic file and return its one `RunProc` external-wrapper call."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "OrderService.cs"
        path.write_text(source, encoding="utf-8")
        results = host.analyze_csharp_files([path])

    assert len(results) == 1
    calls = [
        invocation
        for invocation in results[0]["db_invocations"]
        if invocation.get("wrapper_method_name") == "RunProc"
    ]
    assert len(calls) == 1, "expected exactly one RunProc call in the fixture"
    return calls[0]


@requires_dotnet
def test_local_variable_command_text_resolves() -> None:
    """A local variable assigned a literal earlier in the same method resolves."""
    call = _analyze_one(
        "public class OrderService {\n"
        "    private readonly ExternalDbContext _db;\n"
        "    public void Save() {\n"
        "        string usp = \"[dbo].[usp_SaveOrder]\";\n"
        "        _db.RunProc(usp, 1);\n"
        "    }\n"
        "}\n"
    )
    assert call["command_text_kind"] == "literal"
    assert call["command_text"] == "[dbo].[usp_SaveOrder]"
    assert not call.get("command_text_unresolved_reason")


@requires_dotnet
def test_field_command_text_resolves() -> None:
    """A field assigned a literal earlier in the same method resolves the same way."""
    call = _analyze_one(
        "public class OrderService {\n"
        "    private readonly ExternalDbContext _db;\n"
        "    private string _spName;\n"
        "    public void Save() {\n"
        "        _spName = \"[dbo].[usp_SaveOrderField]\";\n"
        "        _db.RunProc(_spName, 1);\n"
        "    }\n"
        "}\n"
    )
    assert call["command_text_kind"] == "literal"
    assert call["command_text"] == "[dbo].[usp_SaveOrderField]"
    assert not call.get("command_text_unresolved_reason")


@requires_dotnet
def test_literal_at_call_site_is_unchanged() -> None:
    """A literal written at the call site resolves exactly as it did before this ticket."""
    call = _analyze_one(
        "public class OrderService {\n"
        "    private readonly ExternalDbContext _db;\n"
        "    public void Save() {\n"
        "        _db.RunProc(\"[dbo].[usp_Direct]\", 1);\n"
        "    }\n"
        "}\n"
    )
    assert call["command_text_kind"] == "literal"
    assert call["command_text"] == "[dbo].[usp_Direct]"
    assert not call.get("command_text_unresolved_reason")


@requires_dotnet
def test_method_parameter_command_text_stays_unresolved_with_its_own_reason() -> None:
    """A command text that arrives as a method parameter stays unresolved (ADR-0020) and
    carries a reason distinct from an ordinary dynamic expression."""
    call = _analyze_one(
        "public class OrderService {\n"
        "    private readonly ExternalDbContext _db;\n"
        "    public void Save(string commandText) {\n"
        "        _db.RunProc(commandText, 1);\n"
        "    }\n"
        "}\n"
    )
    assert call["command_text_kind"] == "dynamic"
    assert call.get("command_text") is None
    assert call["command_text_unresolved_reason"] == "command_text_method_parameter"


@requires_dotnet
def test_conflicting_literal_assignments_stay_unresolved_rather_than_picking_one() -> None:
    """Two same-method assignments that disagree are a real ambiguity: the analyzer stays
    unresolved and names it, rather than silently choosing the first or the last."""
    call = _analyze_one(
        "public class OrderService {\n"
        "    private readonly ExternalDbContext _db;\n"
        "    public void Save(bool flag) {\n"
        "        string usp;\n"
        "        if (flag) { usp = \"[dbo].[usp_A]\"; } else { usp = \"[dbo].[usp_B]\"; }\n"
        "        _db.RunProc(usp, 1);\n"
        "    }\n"
        "}\n"
    )
    assert call["command_text_kind"] == "dynamic"
    assert call.get("command_text") is None
    assert call["command_text_unresolved_reason"] == "command_text_conflicting_assignments"


@requires_dotnet
def test_call_inside_one_branch_resolves_that_branchs_assignment_not_a_conflict() -> None:
    """A call written inside one arm of an `if`/`else` can only ever read that arm's own
    assignment -- the other arm's assignment cannot reach it, so this is not the same
    ambiguity as two assignments that both precede an unconditional call."""
    call = _analyze_one(
        "public class OrderService {\n"
        "    private readonly ExternalDbContext _db;\n"
        "    public void Save(bool flag) {\n"
        "        string usp;\n"
        "        if (flag) {\n"
        "            usp = \"[dbo].[usp_A]\";\n"
        "        } else {\n"
        "            usp = \"[dbo].[usp_B]\";\n"
        "            _db.RunProc(usp, 1);\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    assert call["command_text_kind"] == "literal"
    assert call["command_text"] == "[dbo].[usp_B]"
    assert not call.get("command_text_unresolved_reason")


@requires_dotnet
def test_traced_literal_reaches_the_executed_procedure_name_through_the_gateway() -> None:
    """The gateway seam: once a Contract exists for the receiver, a traced local-variable
    literal resolves an Executed Procedure Name the same way a call-site literal does."""
    call = _analyze_one(
        "public class OrderService {\n"
        "    private readonly ExternalDbContext _db;\n"
        "    public void Save() {\n"
        "        string usp = \"[dbo].[usp_SaveOrder]\";\n"
        "        _db.RunProc(usp, 1);\n"
        "    }\n"
        "}\n"
    )
    contract = {
        "name": "externaldbcontext",
        "receiver_types": ["ExternalDbContext"],
        "methods": {
            "RunProc": [
                {
                    "method_arity": 2,
                    "mode": "stored_procedure",
                    "sink": "ExecuteNonQuery",
                }
            ],
        },
    }
    gateway = CSharpAnalysisGateway(
        SpCatalog.from_databases({}),
        external_wrapper_contract=contract,
    )

    invocations = gateway.resolve_direct_invocations("OrderService.cs", [call])

    assert len(invocations) == 1
    invocation = invocations[0]
    assert invocation.wrapper_status == "explicit_selected"
    assert invocation.procedure_name == "usp_saveorder"
    assert invocation.executed_procedure_name == "usp_saveorder"


@requires_dotnet
def test_method_parameter_reason_survives_into_the_gateway_evidence() -> None:
    """The host's command-text reason is not lost once the gateway rates the evidence."""
    call = _analyze_one(
        "public class OrderService {\n"
        "    private readonly ExternalDbContext _db;\n"
        "    public void Save(string commandText) {\n"
        "        _db.RunProc(commandText, 1);\n"
        "    }\n"
        "}\n"
    )
    contract = {
        "name": "externaldbcontext",
        "receiver_types": ["ExternalDbContext"],
        "methods": {
            "RunProc": [
                {
                    "method_arity": 2,
                    "mode": "stored_procedure",
                    "sink": "ExecuteNonQuery",
                }
            ],
        },
    }
    gateway = CSharpAnalysisGateway(
        SpCatalog.from_databases({}),
        external_wrapper_contract=contract,
    )

    invocations = gateway.resolve_direct_invocations("OrderService.cs", [call])

    assert len(invocations) == 1
    invocation = invocations[0]
    assert invocation.procedure_name is None
    assert invocation.reason == "command_text_method_parameter"
