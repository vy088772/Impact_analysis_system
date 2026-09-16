"""Ticket 03 (accepted-contract-resolves-its-calls): a delegating method matches its Contract
through an alias.

`usp_ExecCmdGetDataTableAsync` is `SQLDbContext`'s most-used method in the IQCS codebase (196
calls) and constructs no command of its own -- its only database contact is a call to
`usp_ExecCmdGetDataSetAsync`, which does the work. The decompiler has always recorded that
relation as a Delegated Method in the decompilation cache; before this ticket the Contract
never carried it, so every one of those 196 calls matched no operation and stayed
`unresolved_method`. A Delegation Alias is the entry a Contract now carries for that relation:
the delegating name, pointing at the operation that performs the work (ADR-0027). The call
site match consults it only when the method name matches no operation directly -- a direct
match always wins -- and a call matched through an alias still reports the method name the
source code uses, with the alias recorded beside it as provenance.

The main seam, per the spec's own Testing Decisions, is the rating step over a scan of the
real IQCS checkout. The `sqldbcontext` Contract fixture below deliberately omits
`usp_ExecCmdGetDataTableAsync` from `methods` and relies entirely on `delegation_aliases` to
resolve it -- proving the alias is load-bearing, not incidental -- and declares the call's own
true parameter types (`Microsoft.Data.SqlClient.SqlParameter[]`) rather than reusing
`config/external_wrapper_contracts.json`'s on-disk `sqldbcontext` entry verbatim, for the same
reason `tests/test_rating_time_command_mode.py` gives: that on-disk entry still carries a
stale decompilation-cache artifact (`Microsoft.EntityFrameworkCore.SqlParameter[]?`) that
predates the current decompiler and is independent of this ticket.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from code_analyzer.csharp_analysis_gateway import (
    CSharpAnalysisGateway,
    SpCatalog,
    _wrapper_contract_method,
)
from code_analyzer.external_wrapper_contracts import flatten_delegation_aliases
from code_analyzer.static_analyzer_host import StaticAnalyzerHost

IQCS_ROOT = PROJECT_ROOT / "data" / "repos" / "System_Dept_1" / "IQCS"
QRY_SERVICE = IQCS_ROOT / "Services" / "IQCResultCfmService.cs"

requires_dotnet = pytest.mark.skipif(
    shutil.which("dotnet") is None,
    reason="the .NET toolchain is not available",
)
requires_iqcs_fixture = pytest.mark.skipif(
    not QRY_SERVICE.exists(),
    reason="local data/repos/System_Dept_1/IQCS fixture checkout is not present",
)

# The true parameter types for SQLDbContext's ExecCmd family, confirmed directly against
# CommonLibrary.dll with ICSharpCode.Decompiler -- see the module docstring and
# test_rating_time_command_mode.py.
_TRUE_PARAMETER_TYPES = ["string", "Microsoft.Data.SqlClient.SqlParameter[]", "bool"]

# The real three Delegated Methods `WrapperDecompiler.cs` reports for `SQLDbContext`, byte-
# identical to `tests/test_delegated_method.py::REAL_DELEGATIONS`.
_REAL_DELEGATED_METHODS = [
    {
        "method_identity": "SQLDbContext.usp_ExecCmdGetFisrtValueAsync(string,Microsoft.EntityFrameworkCore.SqlParameter[]?,bool)",
        "delegates_to": "usp_ExecCmdGetDataTableAsync",
    },
    {
        "method_identity": "SQLDbContext.usp_ExecCmdGetDataTableAsync(string,Microsoft.EntityFrameworkCore.SqlParameter[]?,bool)",
        "delegates_to": "usp_ExecCmdGetDataSetAsync",
    },
    {
        "method_identity": "SQLDbContext.usp_ExecCmdGetJsonObjectAsync(string,Microsoft.EntityFrameworkCore.SqlParameter[]?,bool)",
        "delegates_to": "usp_ExecCmdGetJsonObjectListAsync",
    },
]


def _sqldbcontext_contract_with_aliases() -> dict:
    return {
        "name": "sqldbcontext",
        "receiver_types": ["SQLDbContext"],
        "methods": {
            # usp_ExecCmdGetDataTableAsync is deliberately absent: this method only resolves
            # through the alias below.
            "usp_ExecCmdGetDataSetAsync": {
                "mode": "call_site",
                "sink": "ExecuteReaderAsync",
                "argument_roles": {"command_text": 0, "command_type": 2},
                "parameter_types": _TRUE_PARAMETER_TYPES,
                "required_parameter_count": 1,
            },
        },
        "delegation_aliases": flatten_delegation_aliases(_REAL_DELEGATED_METHODS),
    }


def _sqldbcontext_contract_without_aliases() -> dict:
    contract = _sqldbcontext_contract_with_aliases()
    contract.pop("delegation_aliases")
    return contract


def _analyze(target: Path, source_root: Path) -> list[dict]:
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()
    results = host.analyze_csharp_files([target], source_roots=[source_root])
    assert len(results) == 1
    return results[0]["db_invocations"]


def _call(invocations: list[dict], method_name: str) -> dict:
    return next(i for i in invocations if i.get("wrapper_method_name") == method_name)


@requires_dotnet
@requires_iqcs_fixture
def test_the_real_usp_exec_cmd_get_data_table_async_call_resolves_through_its_alias() -> None:
    """`Qry()` calls `usp_ExecCmdGetDataTableAsync(_spName, ...)` with
    `_spName = "usp_IQCMgmt_IQCResultCfm_Qry"` -- the delegating name matches no operation
    directly, but the alias flattens it to `usp_ExecCmdGetDataSetAsync`, which does."""
    call = _call(_analyze(QRY_SERVICE, IQCS_ROOT), "usp_ExecCmdGetDataTableAsync")
    gateway = CSharpAnalysisGateway(SpCatalog.from_databases({}))

    reconciliation = gateway.reconcile_wrapper(
        str(QRY_SERVICE), call, explicit_contract=_sqldbcontext_contract_with_aliases()
    )
    assert reconciliation.status == "explicit_selected"
    # The review line names the method the source code used, not the operation the alias
    # resolved to, and records the alias separately as provenance.
    assert reconciliation.wrapper_method == "usp_ExecCmdGetDataTableAsync"
    assert reconciliation.contract_delegation_alias == "usp_ExecCmdGetDataSetAsync"

    invocation = gateway.resolve_direct_invocations(
        str(QRY_SERVICE), [call], explicit_contract=_sqldbcontext_contract_with_aliases()
    )[0]
    assert invocation.executed_procedure_name == "usp_iqcmgmt_iqcresultcfm_qry"
    assert invocation.wrapper_method == "usp_ExecCmdGetDataTableAsync"


@requires_dotnet
@requires_iqcs_fixture
def test_without_the_alias_the_same_call_stays_unresolved() -> None:
    """Regression guard: the alias is load-bearing. Remove it from the same Contract fixture
    and the call goes back to matching nothing -- proving the resolution above came from the
    alias, not from some other path."""
    call = _call(_analyze(QRY_SERVICE, IQCS_ROOT), "usp_ExecCmdGetDataTableAsync")
    gateway = CSharpAnalysisGateway(SpCatalog.from_databases({}))

    reconciliation = gateway.reconcile_wrapper(
        str(QRY_SERVICE), call, explicit_contract=_sqldbcontext_contract_without_aliases()
    )
    assert reconciliation.status == "unresolved_method"
    assert reconciliation.reason == "method_not_in_contract"
    assert reconciliation.contract_delegation_alias == ""


def _minimal_contract(*, methods: dict, delegation_aliases: dict | None = None) -> dict:
    contract = {"methods": methods}
    if delegation_aliases is not None:
        contract["delegation_aliases"] = delegation_aliases
    return contract


def test_a_direct_match_always_wins_over_an_alias_of_the_same_name() -> None:
    """A method name that matches an operation directly never consults an alias, even when the
    Contract also (nonsensically) declares an alias under that same name."""
    contract = _minimal_contract(
        methods={
            "Direct": {"mode": "stored_procedure", "sink": "ExecuteReader"},
            "Target": {"mode": "inline_sql", "sink": "ExecuteReader"},
        },
        delegation_aliases={"Direct": "Target"},
    )

    method_contract, reason, _candidates, alias_target = _wrapper_contract_method(
        contract, "Direct"
    )

    assert method_contract is not None
    assert method_contract["mode"] == "stored_procedure"
    assert reason == ""
    assert alias_target == ""


def test_an_alias_pointing_at_a_missing_operation_reports_the_original_failure() -> None:
    """The alias itself resolving to no operation in this Contract must not invent a new,
    confusing failure reason -- it reports the original direct-match failure."""
    contract = _minimal_contract(
        methods={"Other": {"mode": "stored_procedure", "sink": "ExecuteReader"}},
        delegation_aliases={"Delegating": "NoSuchOperation"},
    )

    method_contract, reason, _candidates, alias_target = _wrapper_contract_method(
        contract, "Delegating"
    )

    assert method_contract is None
    assert reason == "method_not_in_contract"
    assert alias_target == ""


def test_case_insensitive_alias_lookup() -> None:
    """Method name matching is case-insensitive everywhere else in this module; alias lookup
    follows the same convention."""
    contract = _minimal_contract(
        methods={"Target": {"mode": "stored_procedure", "sink": "ExecuteReader"}},
        delegation_aliases={"Delegating": "Target"},
    )

    method_contract, _reason, _candidates, alias_target = _wrapper_contract_method(
        contract, "DELEGATING"
    )

    assert method_contract is not None
    assert alias_target == "Target"


def test_a_contract_with_no_delegation_aliases_key_behaves_exactly_as_before() -> None:
    contract = _minimal_contract(methods={"Target": {"mode": "stored_procedure", "sink": "ExecuteReader"}})

    method_contract, reason, _candidates, alias_target = _wrapper_contract_method(
        contract, "Delegating"
    )

    assert method_contract is None
    assert reason == "method_not_in_contract"
    assert alias_target == ""
