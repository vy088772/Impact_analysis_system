"""Ticket 02 (wrapper-receiver-resolves-through-interface): two or more local classes tied for
an interface-typed wrapper receiver report a distinct, reviewable `ambiguous_implementation`
outcome, naming every tied candidate class, instead of the unchanged/unresolved outcome ticket 01
left this case with.

The interface-to-implementer *matching* is ticket 01's real-host logic (`tests/
test_wrapper_receiver_local_implementer.py` already covers the tied case at the host-fact level);
this file's job is the gateway classification this ticket adds on top of it, plus one end-to-end
confirmation that the tied candidate names actually reach that classification through the real
host, not just through a synthetic raw fact.
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

from code_analyzer.csharp_analysis_gateway import (
    CSharpAnalysisGateway,
    InvocationEvidence,
    SpCatalog,
)
from code_analyzer.static_analyzer_host import StaticAnalyzerHost

requires_dotnet = pytest.mark.skipif(
    shutil.which("dotnet") is None,
    reason="the .NET toolchain is not available",
)


def _raw_invocation(**overrides) -> dict:
    base = {
        "class_name": "Caller",
        "method_name": "Qry",
        "command_text_kind": "dynamic",
        "command_text": None,
        "command_type_stored_procedure": False,
        "connection_expression": None,
        "start_offset": 10,
        "end_offset": 90,
    }
    base.update(overrides)
    return base


def test_two_tied_implementation_candidates_report_ambiguous_implementation() -> None:
    """A synthetic raw fact carrying two tied class names -- no real multi-implementer fixture
    required -- reports the new outcome and names both candidates, distinguishable from every
    other unresolved/ambiguous reason by its own `multiple_classes_implement_receiver_type`."""
    gateway = CSharpAnalysisGateway(SpCatalog.from_databases({}))
    raw = _raw_invocation(
        invocation_kind="source_wrapper",
        wrapper_method_name="SqlParam",
        wrapper_receiver_type="IUtilityService",
        wrapper_source_available=False,
        wrapper_implementation_candidates=["UtilityServiceA", "UtilityServiceB"],
    )

    reconciliation = gateway.reconcile_wrapper("Caller.cs", raw)

    assert reconciliation.wrapper_kind == "source_wrapper"
    assert reconciliation.status == "ambiguous_implementation"
    assert reconciliation.selection_source == "ambiguous_local_implementation"
    assert reconciliation.candidate_contracts == ("UtilityServiceA", "UtilityServiceB")
    assert reconciliation.reason == "multiple_classes_implement_receiver_type"
    assert reconciliation.review_candidate is True
    # Same review-candidate treatment as the existing ambiguous_contract outcome: never a passed,
    # resolved contract.
    assert reconciliation.active_contract is False

    invocation = gateway.resolve_direct_invocations("Caller.cs", [raw])[0]
    assert invocation.evidence is InvocationEvidence.UNRESOLVED
    assert invocation.wrapper_status == "ambiguous_implementation"
    assert invocation.wrapper_review_candidate is True
    assert invocation.wrapper_unresolved_reason == "multiple_classes_implement_receiver_type"
    assert invocation.wrapper_contract_candidates == ("UtilityServiceA", "UtilityServiceB")


def test_zero_candidate_interface_receiver_is_unaffected() -> None:
    """No `wrapper_implementation_candidates` fact at all -- a genuinely external interface, or
    an interface with no local implementer -- still reports the pre-existing unresolved_contract
    outcome. This ticket adds no new status for that case, only for a real tie."""
    gateway = CSharpAnalysisGateway(SpCatalog.from_databases({}))

    reconciliation = gateway.reconcile_wrapper(
        "Caller.cs",
        _raw_invocation(
            wrapper_method_name="SqlParam",
            wrapper_receiver_type="IUtilityService",
            wrapper_source_available=False,
        ),
    )

    assert reconciliation.status == "unresolved_contract"
    assert reconciliation.reason == "no_contract_matches_receiver_type"


IFACE_SOURCE = """
using Microsoft.Data.SqlClient;
namespace IQCS.Interfaces
{
    public interface IUtilityService
    {
        SqlParameter SqlParam(string paramKey, object? value, string? typeName = null);
    }
}
"""

CALLER_SOURCE = """
using IQCS.Interfaces;
using Microsoft.Data.SqlClient;
namespace IQCS.Services
{
    public class Caller
    {
        private readonly IUtilityService _utility;
        public Caller(IUtilityService utility) { _utility = utility; }
        public void Qry()
        {
            var p = _utility.SqlParam("UserID", 1);
        }
    }
}
"""

TIED_IMPLEMENTER_SOURCE = """
using IQCS.Interfaces;
using Microsoft.Data.SqlClient;
namespace IQCS.Services
{{
    public class {class_name} : IUtilityService
    {{
        public SqlParameter SqlParam(string paramKey, object? value, string? typeName = null)
            => new SqlParameter(paramKey, value);
    }}
}}
"""


def _write_fixture(root: Path, files: dict[str, str]) -> None:
    for name, content in files.items():
        (root / name).write_text(content, encoding="utf-8")


def _analyze(target: Path, source_root: Path) -> list[dict]:
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()
    results = host.analyze_csharp_files([target], source_roots=[source_root])
    assert len(results) == 1
    return results[0]["db_invocations"]


def _sql_param_call(invocations: list[dict]) -> dict:
    return next(
        invocation
        for invocation in invocations
        if invocation.get("wrapper_method_name") == "SqlParam"
    )


@requires_dotnet
def test_two_local_implementers_reach_ambiguous_implementation_end_to_end() -> None:
    """The real host's tied-candidate names (ticket 01's `FindLocalImplementers`, exercised
    against a throwaway two-implementer scan root, not the real IQCS checkout) surface all the
    way through `reconcile_wrapper` to the reported `ambiguous_implementation` outcome, naming
    both classes -- confirming the wiring between host and gateway, not just the gateway rule in
    isolation."""
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        _write_fixture(root, {
            "IUtilityService.cs": IFACE_SOURCE,
            "UtilityServiceA.cs": TIED_IMPLEMENTER_SOURCE.format(class_name="UtilityServiceA"),
            "UtilityServiceB.cs": TIED_IMPLEMENTER_SOURCE.format(class_name="UtilityServiceB"),
            "Caller.cs": CALLER_SOURCE,
        })
        call = _sql_param_call(_analyze(root / "Caller.cs", root))

    assert call["wrapper_source_available"] is False
    assert call["receiver_implementation_identity"] is None
    assert sorted(call["wrapper_implementation_candidates"]) == [
        "UtilityServiceA",
        "UtilityServiceB",
    ]

    gateway = CSharpAnalysisGateway(SpCatalog.from_databases({}))
    reconciliation = gateway.reconcile_wrapper("Caller.cs", call)

    assert reconciliation.status == "ambiguous_implementation"
    assert reconciliation.review_candidate is True
    assert sorted(reconciliation.candidate_contracts) == ["UtilityServiceA", "UtilityServiceB"]


SINGLE_IMPLEMENTER_SOURCE = """
using IQCS.Interfaces;
using Microsoft.Data.SqlClient;
namespace IQCS.Services
{
    public class UtilityService : IUtilityService
    {
        public SqlParameter SqlParam(string paramKey, object? value, string? typeName = null)
            => new SqlParameter(paramKey, value);
    }
}
"""


@requires_dotnet
def test_single_local_implementer_is_unaffected_by_this_ticket() -> None:
    """Ticket 01's case -- exactly one local implementer -- still resolves source-backed and
    never carries `wrapper_implementation_candidates`; this ticket only changes what happens when
    the search finds more than one."""
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        _write_fixture(root, {
            "IUtilityService.cs": IFACE_SOURCE,
            "UtilityService.cs": SINGLE_IMPLEMENTER_SOURCE,
            "Caller.cs": CALLER_SOURCE,
        })
        call = _sql_param_call(_analyze(root / "Caller.cs", root))

    assert call["wrapper_source_available"] is True
    assert call["receiver_implementation_identity"] == "UtilityService"
    assert not call.get("wrapper_implementation_candidates")

    gateway = CSharpAnalysisGateway(SpCatalog.from_databases({}))
    reconciliation = gateway.reconcile_wrapper("Caller.cs", call)

    assert reconciliation.status == "source_wrapper"
