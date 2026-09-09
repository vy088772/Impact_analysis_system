"""Ticket 06: wrapper receiver resolution walks the inheritance chain.

Every measured ASP.NET Core repository writes its data access the same way: a local database
context derives from a base class shipped in a shared external library, and the wrapper method
is declared on that base. The analyzer keyed the Contract on the *receiver's own declared type*,
so `IQCSContext` matched no Contract and the call was never recognised as a wrapper invocation.

The defect lives entirely on the producing (C#) side -- the host already binds the call to
`SQLDbContext.usp_ExecCmdGetDataSetAsync(...)` and then reports `IQCSContext` beside it -- so the
primary seam here is the real host run against the real repositories. The gateway-side reason
code and the Assembly Revision Boundary guard are asserted at their own seams below.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from code_analyzer.csharp_analysis_gateway import CSharpAnalysisGateway, SpCatalog
from code_analyzer.static_analyzer_host import StaticAnalyzerHost
from service.contract_preflight import run_contract_preflight

IQCS_ROOT = PROJECT_ROOT / "data" / "repos" / "System_Dept_1" / "IQCS"
IQCS_SERVICE = IQCS_ROOT / "Services" / "DefMonthlyQryService.cs"
STC_ROOT = PROJECT_ROOT / "data" / "repos" / "System_Dept_1" / "STC" / "STC"
STC_SOURCE = STC_ROOT / "CusAppQryDetail.aspx.cs"

requires_dotnet = pytest.mark.skipif(
    shutil.which("dotnet") is None,
    reason="the .NET toolchain is not available",
)
requires_iqcs_fixture = pytest.mark.skipif(
    not IQCS_SERVICE.exists(),
    reason="local data/repos/System_Dept_1/IQCS fixture checkout is not present",
)
requires_stc_fixture = pytest.mark.skipif(
    not STC_SOURCE.exists(),
    reason="local data/repos/System_Dept_1/STC fixture checkout is not present",
)


def _analyze(target: Path, source_root: Path) -> list[dict]:
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()
    results = host.analyze_csharp_files([target], source_roots=[source_root])
    assert len(results) == 1
    return results[0]["db_invocations"]


@requires_dotnet
@requires_iqcs_fixture
def test_inherited_wrapper_call_reports_the_declaring_type_as_its_receiver() -> None:
    """`IQCSContext : SQLDbContext` declares no `usp_ExecCmdGetDataSetAsync`. The call is keyed
    on `SQLDbContext`, the external base that declares it, not on the local subclass."""
    calls = [
        invocation
        for invocation in _analyze(IQCS_SERVICE, IQCS_ROOT)
        if invocation.get("wrapper_method_name") == "usp_ExecCmdGetDataSetAsync"
    ]

    assert calls, "expected the IQCSContext wrapper calls in the fixture"
    for call in calls:
        assert call["wrapper_receiver_type"] == "SQLDbContext"
        assert call["wrapper_receiver_type"] != "IQCSContext"
        assert call["wrapper_receiver_type_provenance"] == "declaring_type"


@requires_dotnet
@requires_iqcs_fixture
def test_inherited_wrapper_call_is_recognised_as_a_wrapper_invocation() -> None:
    """The gateway now selects the base class's Contract for the call. Before this ticket the
    same call reached `unresolved_contract` / `no_contract_matches_receiver_type`."""
    call = next(
        invocation
        for invocation in _analyze(IQCS_SERVICE, IQCS_ROOT)
        if invocation.get("wrapper_method_name") == "usp_ExecCmdGetDataSetAsync"
    )
    contract = {
        "name": "sqldbcontext",
        "receiver_types": ["SQLDbContext"],
        "methods": [
            {
                "method_name": "usp_ExecCmdGetDataSetAsync",
                "method_arity": 3,
                "required_parameter_count": 2,
                "mode": "stored_procedure",
                "sink": "Fill",
            }
        ],
    }
    gateway = CSharpAnalysisGateway(
        SpCatalog.from_databases({}),
        external_wrapper_contract=contract,
    )

    reconciliation = gateway.reconcile_wrapper("DefMonthlyQryService.cs", call)

    assert reconciliation.receiver_type == "SQLDbContext"
    assert reconciliation.status not in {"receiver_mismatch", "unresolved_contract"}
    assert reconciliation.wrapper_kind == "external_wrapper"


@requires_dotnet
@requires_stc_fixture
def test_wrapper_declared_on_the_receivers_own_type_is_unchanged() -> None:
    """`SQLFunc` declares `CreateReader` itself, so the declaring type is the receiver's own
    type and the reported receiver type is exactly what it was before this ticket."""
    calls = [
        invocation
        for invocation in _analyze(STC_SOURCE, STC_ROOT)
        if invocation.get("wrapper_method_name") == "CreateReader"
    ]

    assert calls, "expected the SQLFunc wrapper calls in the fixture"
    for call in calls:
        assert call["wrapper_receiver_type"] == "SQLFunc"


UNBINDABLE_SUBCLASS_SOURCE = """
using System.Data;

public partial class LocalContext : SQLDbContext
{
}

public class LocalService
{
    private readonly LocalContext _db;

    public LocalService(LocalContext db) { _db = db; }

    public DataSet Query()
    {
        string usp = "usp_Thing_GetList";
        return _db.usp_ExecCmdGetDataSet(usp);
    }
}
"""


@requires_dotnet
def test_receiver_whose_declaring_type_is_unknown_stays_unresolved() -> None:
    """With no semantic model, `LocalContext` is known to inherit and known not to declare the
    method. Reporting it as the receiver type would key the Contract on a guess, so the host
    reports no receiver type and names why instead."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "LocalService.cs"
        source_path.write_text(UNBINDABLE_SUBCLASS_SOURCE, encoding="utf-8")
        result = host.analyze_csharp(source_path)

    call = next(
        invocation
        for invocation in result["db_invocations"]
        if invocation.get("wrapper_method_name") == "usp_ExecCmdGetDataSet"
    )
    assert not call.get("wrapper_receiver_type")
    assert call["wrapper_receiver_type_provenance"] == "declaring_type_unresolved"


def test_unresolved_declaring_type_names_its_own_reason() -> None:
    """`receiver_type_missing` would say only that a receiver type was absent. The gateway
    reports the reason the host actually gave: the declaring type could not be determined."""
    gateway = CSharpAnalysisGateway(SpCatalog.from_databases({}))

    reconciliation = gateway.reconcile_wrapper(
        "LocalService.cs",
        {
            "invocation_kind": "source_wrapper",
            "wrapper_method_name": "usp_ExecCmdGetDataSet",
            "wrapper_source_available": False,
            "wrapper_receiver_type": "",
            "wrapper_receiver_type_provenance": "declaring_type_unresolved",
            "wrapper_method_arity": 1,
        },
    )

    assert reconciliation.status == "unresolved_contract"
    assert reconciliation.reason == "declaring_type_unresolved"
    assert reconciliation.review_candidate is True


def _shared_base_proposal(assembly_identity: str, revision: str) -> dict:
    """One repository's snapshot of the same shared base class, at its own library revision."""
    return {
        "name": "sqldbcontext",
        "receiver_types": ["SQLDbContext"],
        "implementation_snapshot": {
            "artifact_identity": f"CommonLibrary.dll@sha256:{assembly_identity}",
            "assembly_identity": assembly_identity,
            "assembly_revision": revision,
            "behavior_surface_unit": "CommonLibrary.SQLDbContext",
            "complete": True,
            "methods": [
                {
                    "method_identity": "CommonLibrary.SQLDbContext.Run(System.String)",
                    "method_name": "Run",
                    "method_arity": 1,
                    "parameter_types": ["System.String"],
                    "argument_roles": {"command_text": 0},
                    "effective_command_semantics": "stored_procedure",
                    "terminal_sink": "ExecuteNonQuery",
                    "connection_behavior_boundary": "constructor_connection",
                    "branch_rules": [
                        {"mode": "stored_procedure", "sink": "ExecuteNonQuery"}
                    ],
                    "assembly_revision": revision,
                    "body_complete": True,
                }
            ],
            "helper_operations_complete": True,
            "inherited_operations_complete": True,
        },
    }


def test_two_revisions_of_one_shared_base_stay_two_snapshots() -> None:
    """Keying the Contract on the declaring type makes three repositories name the same
    receiver type. The Assembly Revision Boundary still keeps their snapshots apart."""
    scans = [
        SimpleNamespace(contract_proposals=[_shared_base_proposal("aaa111", "1.0.0")]),
        SimpleNamespace(contract_proposals=[_shared_base_proposal("bbb222", "2.0.0")]),
    ]

    result = run_contract_preflight(scans, selector=None, registry={"contracts": {}})

    entries = result.formal_registry["contracts"]
    assert len(entries) == 2, f"expected one entry per assembly revision, got {sorted(entries)}"
    assembly_identities = {
        snapshot["assembly_identity"]
        for entry in entries.values()
        for snapshot in entry["implementation_snapshots"]
    }
    assert assembly_identities == {"aaa111", "bbb222"}
    for entry in entries.values():
        assert entry["receiver_types"] == ["SQLDbContext"]
        assert len(entry["implementation_snapshots"]) == 1
