"""Ticket 06: resolve a wrapper overload from a bound symbol.

Before this ticket, the analyzer reported only an argument count for a call to an external
wrapper. `CreateReader(string, SqlParameter)` and `CreateReader(string, SqlParameter[])` share
an argument count, so a call to either sat in the review list as `ambiguous_overload` forever,
even though the compiler could always have told them apart.

This ticket gives the analyzer host a real Roslyn semantic model (built on top of ticket 05's
Semantic Binding Availability) and uses it to bind a wrapper call to one exact method symbol,
reporting the full method identity and parameter types instead of only an argument count. The
end-to-end seam (running the real host against the real STC project) is the primary one: the
defect this ticket fixes occurs entirely on the producing (C#) side, so a test that only
exercises the validating (Python gateway) side would repeat the mistake. Seam-2 tests for the
symbol acceptance rule (no candidate set required, assembly identity must match the contract's)
live alongside the rest of CSharpAnalysisGateway's tests in test_csharp_analysis_gateway.py.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from code_analyzer.csharp_analysis_gateway import (
    CSharpAnalysisGateway,
    SpCatalog,
    load_external_wrapper_contract,
)
from code_analyzer.static_analyzer_host import StaticAnalyzerHost
from service import analyze_service

STC_CSPROJ = PROJECT_ROOT / "data" / "repos" / "System_Dept_1" / "STC" / "STC" / "STC.csproj"
STC_ROOT = STC_CSPROJ.parent
SQLFUNC_DLL = STC_ROOT / "bin" / "SQLFunc.dll"

requires_stc_fixture = pytest.mark.skipif(
    not (STC_CSPROJ.exists() and SQLFUNC_DLL.exists()),
    reason="local data/repos/System_Dept_1/STC fixture checkout is not present",
)

requires_dotnet = pytest.mark.skipif(
    shutil.which("dotnet") is None,
    reason="the .NET toolchain is not available",
)


def _sqlfunc_contract() -> dict:
    contract = load_external_wrapper_contract("sqlfunc")
    assert contract is not None, "config/external_wrapper_contracts.json must hold the sqlfunc contract"
    return contract


@requires_dotnet
@requires_stc_fixture
def test_host_binds_createreader_array_overload_end_to_end() -> None:
    """A `CreateReader` call that passes a `SqlParameter[]` argument resolves to the array
    overload -- not its SqlParameter sibling, which shares its argument count -- once the
    host's semantic model is available."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    target = STC_ROOT / "CusAppQryDetail.aspx.cs"
    results = host.analyze_csharp_files([target], source_roots=[STC_ROOT])
    assert len(results) == 1
    invocations = results[0]["db_invocations"]

    array_calls = [
        invocation
        for invocation in invocations
        if invocation.get("wrapper_method_name") == "CreateReader"
        and invocation.get("wrapper_method_arity") == 2
    ]
    assert array_calls, "expected at least one two-argument CreateReader call in the fixture"
    for call in array_calls:
        assert call["wrapper_method_identity"] == (
            "SQLFunc.CreateReader(string,System.Data.SqlClient.SqlParameter[])"
        )
        assert call["wrapper_parameter_types"] == [
            "string",
            "System.Data.SqlClient.SqlParameter[]",
        ]
        assert call["wrapper_assembly_identity"] == _sqlfunc_contract_assembly_identity()


@requires_dotnet
@requires_stc_fixture
def test_host_binds_exeprocread_array_overload_end_to_end() -> None:
    """An `ExeProcRead` call that passes a `SqlParameter[]` argument resolves to the array
    overload, exactly as the `CreateReader` case does."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    target = STC_ROOT / "ApprovalQry.aspx.cs"
    results = host.analyze_csharp_files([target], source_roots=[STC_ROOT])
    assert len(results) == 1
    invocations = results[0]["db_invocations"]

    array_calls = [
        invocation
        for invocation in invocations
        if invocation.get("wrapper_method_name") == "ExeProcRead"
        and invocation.get("wrapper_method_arity") == 2
    ]
    assert array_calls, "expected at least one two-argument ExeProcRead call in the fixture"
    for call in array_calls:
        assert call["wrapper_method_identity"] == (
            "SQLFunc.ExeProcRead(string,System.Data.SqlClient.SqlParameter[])"
        )
        assert call["wrapper_parameter_types"] == [
            "string",
            "System.Data.SqlClient.SqlParameter[]",
        ]


def _sqlfunc_contract_assembly_identity() -> str:
    import hashlib

    return hashlib.sha256(SQLFUNC_DLL.read_bytes()).hexdigest()


@requires_dotnet
@requires_stc_fixture
def test_bound_symbol_selects_one_overload_through_the_gateway() -> None:
    """The real bound facts, fed through the real sqlfunc contract, resolve to one overload
    instead of `ambiguous_overload` -- the exact defect this ticket fixes."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    target = STC_ROOT / "CusAppQryDetail.aspx.cs"
    results = host.analyze_csharp_files([target], source_roots=[STC_ROOT])
    invocations = results[0]["db_invocations"]
    array_call = next(
        invocation
        for invocation in invocations
        if invocation.get("wrapper_method_name") == "CreateReader"
        and invocation.get("wrapper_method_arity") == 2
    )

    catalog = SpCatalog.from_databases({})
    gateway = CSharpAnalysisGateway(catalog, external_wrapper_contract=_sqlfunc_contract())
    reconciliation = gateway.reconcile_wrapper("CusAppQryDetail.aspx.cs", array_call)

    assert reconciliation.status == "explicit_selected"
    assert reconciliation.status != "ambiguous_overload"
    assert reconciliation.contract_mode == "inline_sql"
    assert reconciliation.contract_sink == "ExecuteReader"
    assert reconciliation.review_candidate is False


@requires_dotnet
@requires_stc_fixture
def test_refresh_of_stc_reports_proven_evidence_for_previously_missing_create_table_overload() -> None:
    """Spec regression (User Story 15): before this ticket, the two-argument `CreateTable`
    overload had no contract entry, so `CommonFunction.GetDept`'s call sat at Evidence Status
    `unresolved` with reason `overload_not_found`. Ticket 01/02 gave the decompiler a Command
    Source rule for the data-adapter construction that overload uses, so the rebuilt sqlfunc
    contract now covers it end to end and the call should evidence as `proven`."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    target = STC_ROOT / "CommonFunction.cs"
    results = host.analyze_csharp_files([target], source_roots=[STC_ROOT])
    assert len(results) == 1
    db_invocations = {str(target): results[0].get("db_invocations", [])}
    scan = SimpleNamespace(
        project_root=str(STC_ROOT),
        db_invocations=db_invocations,
        connection_sources={},
    )

    refresh = analyze_service.reconcile_refresh_wrappers(
        [scan],
        contract_registry={"sqlfunc": _sqlfunc_contract()},
        explicit_contract="sqlfunc",
    )

    create_table_observations = [
        observation
        for observation in refresh["observations"]
        if observation["wrapper_method"] == "CreateTable"
        and observation.get("method_arity") == 2
    ]
    assert create_table_observations, (
        "expected the CommonFunction.GetDept two-argument CreateTable call in the fixture"
    )
    for observation in create_table_observations:
        assert observation["evidence_status"] == "proven"
        assert observation["status"] != "unresolved"
        assert observation["classification_reason"] != "overload_not_found"


@requires_dotnet
@requires_stc_fixture
def test_refresh_of_stc_reports_no_ambiguous_overload_for_bound_calls() -> None:
    """A refresh of STC reports no `ambiguous_overload` review candidate for a call the
    semantic model could bind, and the wrapper summary reports how many calls it resolved."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    targets = [
        STC_ROOT / "CusAppQryDetail.aspx.cs",
        STC_ROOT / "ApprovalQry.aspx.cs",
    ]
    results = host.analyze_csharp_files(targets, source_roots=[STC_ROOT])
    db_invocations = {
        str(target): result.get("db_invocations", [])
        for target, result in zip(targets, results)
    }
    scan = SimpleNamespace(
        project_root=str(STC_ROOT),
        db_invocations=db_invocations,
        connection_sources={},
    )

    refresh = analyze_service.reconcile_refresh_wrappers(
        [scan],
        contract_registry={"sqlfunc": _sqlfunc_contract()},
        explicit_contract="sqlfunc",
    )

    two_argument_reader_or_proc_read_statuses = {
        observation["status"]
        for observation in refresh["observations"]
        if observation["wrapper_method"] in {"CreateReader", "ExeProcRead"}
        and observation.get("method_arity") == 2
    }
    assert "ambiguous_overload" not in two_argument_reader_or_proc_read_statuses

    assert refresh["totals"]["semantic_binding_resolved"] > 0
