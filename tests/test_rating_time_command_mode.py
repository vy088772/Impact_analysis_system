"""Ticket 02 (accepted-contract-resolves-its-calls): the Command Mode resolves at rating
time, not at scan time.

Before this ticket, `usp_ExecCmdGetDataSetAsync` (62 calls) and `usp_ExecCmdGetCountAsync`
(1 call) in the real IQCS checkout carried a resolved stored-procedure name but an unresolved
Command Mode: the scan decided the mode from a fixed method-name list, `usp_ExecCmd*` was not
on it, and the accepted `sqldbcontext` Contract -- which does name the mode argument, by index
-- arrived too late to change an already-cached scan. See ADR-0028 and the "Observed Argument
Facts" / "Rating-Time Command Mode" glossary entries in CONTEXT.md.

The main seam, per the spec's own Testing Decisions, is the rating step over a scan of the
real IQCS checkout: one scan, asserted twice -- the scan recorded Observed Argument Facts, and
the rating step resolved `executed_procedure_name` for the affected calls. The synthetic cases
(a variable argument stays unresolved; `false` rates inline SQL; `true` rates a stored
procedure) hang off the same gateway module and open no new seam.

The `sqldbcontext` Contract fixtures below deliberately declare the call's own true parameter
types (`Microsoft.Data.SqlClient.SqlParameter[]`, confirmed directly against
`CommonLibrary.dll` with `ICSharpCode.Decompiler` -- the same library `WrapperDecompiler.cs`
uses) rather than reusing `config/external_wrapper_contracts.json`'s accepted `sqldbcontext`
entry verbatim: that on-disk entry still carries a stale decompilation-cache artifact,
`Microsoft.EntityFrameworkCore.SqlParameter[]?`, that predates the current decompiler code (no
such namespace string exists anywhere under `tools/StaticAnalyzerHost/`). That staleness is
independent of this ticket -- fixing it means re-decompiling and re-accepting the Contract, a
separate piece of work -- and is recorded in the ticket file's Notes rather than worked around
silently here.
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
    InvocationEvidence,
    SpCatalog,
)
from code_analyzer.static_analyzer_host import StaticAnalyzerHost

IQCS_ROOT = PROJECT_ROOT / "data" / "repos" / "System_Dept_1" / "IQCS"
DATASET_SERVICE = IQCS_ROOT / "Services" / "IQCResultCfmService.cs"
COUNT_SERVICE = IQCS_ROOT / "Services" / "FileService.cs"

requires_dotnet = pytest.mark.skipif(
    shutil.which("dotnet") is None,
    reason="the .NET toolchain is not available",
)
requires_iqcs_fixture = pytest.mark.skipif(
    not DATASET_SERVICE.exists(),
    reason="local data/repos/System_Dept_1/IQCS fixture checkout is not present",
)

# The true parameter types for these two SQLDbContext methods, confirmed directly against
# CommonLibrary.dll with ICSharpCode.Decompiler -- see the module docstring.
_TRUE_PARAMETER_TYPES = ["string", "Microsoft.Data.SqlClient.SqlParameter[]", "bool"]


def _sqldbcontext_contract() -> dict:
    return {
        "name": "sqldbcontext",
        "receiver_types": ["SQLDbContext"],
        "methods": {
            "usp_ExecCmdGetDataSetAsync": {
                "mode": "call_site",
                "sink": "ExecuteReaderAsync",
                "argument_roles": {"command_text": 0, "command_type": 2},
                "parameter_types": _TRUE_PARAMETER_TYPES,
                "required_parameter_count": 1,
            },
            "usp_ExecCmdGetCountAsync": {
                "mode": "call_site",
                "sink": "ExecuteSqlInterpolatedAsync",
                "argument_roles": {"command_text": 0, "command_type": 2},
                "parameter_types": _TRUE_PARAMETER_TYPES,
                "required_parameter_count": 1,
            },
        },
    }


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
def test_scan_records_observed_argument_facts_for_every_argument_of_the_wrapper_call() -> None:
    """`usp_ExecCmdGetDataSetAsync(_spName, _sqlParameters.ToArray())` omits its third
    argument, `isSP`, relying on that parameter's own `= true` default -- the scan reads no
    Contract, so it cannot know that omission carries a Command Mode, but it does read the
    bound method's own declared default (semantic binding, not a Contract) and records it as
    a literal fact at that position. The first two arguments (a variable, a call) stay
    unresolved and name why."""
    call = _call(_analyze(DATASET_SERVICE, IQCS_ROOT), "usp_ExecCmdGetDataSetAsync")

    facts = call["observed_arguments"]
    assert len(facts) == 3
    assert facts[0]["kind"] == "dynamic"
    assert facts[0]["unresolved_reason"] == "variable"
    assert facts[1]["kind"] == "dynamic"
    assert facts[1]["unresolved_reason"] == "call"
    assert facts[2] == {"kind": "literal", "literal": "true", "unresolved_reason": None}


@requires_dotnet
@requires_iqcs_fixture
def test_accepted_contract_resolves_the_executed_procedure_name_for_usp_exec_cmd_get_data_set_async() -> None:
    """The primary acceptance target: a `call_site` Contract accepted after this scan was
    captured still resolves the Command Mode -- and therefore the Executed Procedure Name --
    for `usp_ExecCmdGetDataSetAsync`, previously stuck at `wrapper_mode_unresolved` because
    the method name is not on the analyzer's fixed stored-procedure name list."""
    call = _call(_analyze(DATASET_SERVICE, IQCS_ROOT), "usp_ExecCmdGetDataSetAsync")
    gateway = CSharpAnalysisGateway(SpCatalog.from_databases({}))

    reconciliation = gateway.reconcile_wrapper(
        str(DATASET_SERVICE), call, explicit_contract=_sqldbcontext_contract()
    )
    assert reconciliation.status == "explicit_selected"
    assert reconciliation.stored_procedure_mode is True
    assert reconciliation.mode_reason == ""

    invocation = gateway.resolve_direct_invocations(
        str(DATASET_SERVICE), [call], explicit_contract=_sqldbcontext_contract()
    )[0]
    assert invocation.executed_procedure_name == "usp_iqcmgmt_iqcresultcfm_dtl"


@requires_dotnet
@requires_iqcs_fixture
def test_accepted_contract_resolves_the_executed_procedure_name_for_usp_exec_cmd_get_count_async() -> None:
    """The spec's second named call: `usp_ExecCmdGetCountAsync` (1 call), whose declared sink
    is `ExecuteSqlInterpolatedAsync` -- also resolves once the Command Mode does."""
    call = _call(_analyze(COUNT_SERVICE, IQCS_ROOT), "usp_ExecCmdGetCountAsync")
    gateway = CSharpAnalysisGateway(SpCatalog.from_databases({}))

    invocation = gateway.resolve_direct_invocations(
        str(COUNT_SERVICE), [call], explicit_contract=_sqldbcontext_contract()
    )[0]
    assert invocation.executed_procedure_name == "usp_file_clearlogfiledelete"


def _call_site_contract(method_name: str) -> dict:
    return {
        "name": "sqldbcontext",
        "receiver_types": ["SQLDbContext"],
        "methods": {
            method_name: {
                "mode": "call_site",
                "sink": "ExecuteReaderAsync",
                "argument_roles": {"command_text": 0, "command_type": 2},
            },
        },
    }


def _raw_call_site_invocation(*, mode_argument: dict, method_name: str = "Query") -> dict:
    return {
        "class_name": "Reader",
        "method_name": "Run",
        "invocation_kind": "source_wrapper",
        "wrapper_method_name": method_name,
        "wrapper_receiver_type": "SQLDbContext",
        "wrapper_source_available": False,
        "wrapper_mode": "unknown",
        "command_text_kind": "literal",
        "command_text": "usp_Thing",
        "connection_expression": "conn",
        "start_offset": 0,
        "end_offset": 10,
        "terminal_sink": "ExecuteReaderAsync",
        "observed_arguments": [
            {"kind": "literal", "literal": "usp_Thing", "unresolved_reason": None},
            {"kind": "dynamic", "literal": None, "unresolved_reason": "variable"},
            mode_argument,
        ],
    }


def test_mode_argument_holding_the_literal_true_rates_a_stored_procedure() -> None:
    gateway = CSharpAnalysisGateway(SpCatalog.from_databases({}))
    raw = _raw_call_site_invocation(
        mode_argument={"kind": "literal", "literal": "true", "unresolved_reason": None}
    )

    reconciliation = gateway.reconcile_wrapper(
        "f.cs", raw, explicit_contract=_call_site_contract("Query")
    )

    assert reconciliation.status == "explicit_selected"
    assert reconciliation.stored_procedure_mode is True
    assert reconciliation.mode_reason == ""


@pytest.mark.parametrize("literal", ["SP", "StoredProcedure", "sp", "storedprocedure"])
def test_mode_argument_holding_sp_or_storedprocedure_rates_a_stored_procedure(literal: str) -> None:
    gateway = CSharpAnalysisGateway(SpCatalog.from_databases({}))
    raw = _raw_call_site_invocation(
        mode_argument={"kind": "literal", "literal": literal, "unresolved_reason": None}
    )

    reconciliation = gateway.reconcile_wrapper(
        "f.cs", raw, explicit_contract=_call_site_contract("Query")
    )

    assert reconciliation.stored_procedure_mode is True
    assert reconciliation.mode_reason == ""


def test_mode_argument_holding_the_literal_false_rates_an_inline_sql_command() -> None:
    gateway = CSharpAnalysisGateway(SpCatalog.from_databases({}))
    raw = _raw_call_site_invocation(
        mode_argument={"kind": "literal", "literal": "false", "unresolved_reason": None}
    )

    reconciliation = gateway.reconcile_wrapper(
        "f.cs", raw, explicit_contract=_call_site_contract("Query")
    )

    assert reconciliation.status == "explicit_selected"
    assert reconciliation.stored_procedure_mode is False
    assert reconciliation.mode_reason == "inline_sql"


def test_mode_argument_holding_a_variable_keeps_the_command_mode_unresolved() -> None:
    """The gateway never falls back to a default: a variable at the mode-argument index leaves
    the Command Mode unresolved, and the Executed Procedure Name unresolved with it, even
    though the command text itself is a known literal. The raw scan record -- not
    `mode_reason` -- names why the argument itself stayed unresolved (`"variable"`)."""
    gateway = CSharpAnalysisGateway(SpCatalog.from_databases({}))
    raw = _raw_call_site_invocation(
        mode_argument={"kind": "dynamic", "literal": None, "unresolved_reason": "variable"}
    )
    assert raw["observed_arguments"][2]["unresolved_reason"] == "variable"

    reconciliation = gateway.reconcile_wrapper(
        "f.cs", raw, explicit_contract=_call_site_contract("Query")
    )
    assert reconciliation.stored_procedure_mode is False
    assert reconciliation.mode_reason != ""

    invocation = gateway.resolve_direct_invocations(
        "f.cs", [raw], explicit_contract=_call_site_contract("Query")
    )[0]
    assert invocation.evidence is InvocationEvidence.UNRESOLVED
    assert invocation.executed_procedure_name is None


def test_a_declared_command_type_role_owns_the_answer_even_when_scan_time_mode_disagrees() -> None:
    """A Contract that names a `command_type` role owns the Command Mode answer completely --
    once the role is declared, the scan-time `wrapper_mode` guess (`ResolveUnknownCallMode`,
    which scans every argument of the call for *any* recognisable mode literal, using a wider
    inline-mode set than this ticket's own true/false convention) must never resolve the mode
    behind rating time's back. Here the scan-time guess claims `stored_procedure` while the
    Contract's own declared mode argument is an unresolved variable; the gateway must still
    report the mode unresolved, not silently trust the older, broader guess."""
    gateway = CSharpAnalysisGateway(SpCatalog.from_databases({}))
    raw = _raw_call_site_invocation(
        mode_argument={"kind": "dynamic", "literal": None, "unresolved_reason": "variable"}
    )
    raw["wrapper_mode"] = "stored_procedure"

    reconciliation = gateway.reconcile_wrapper(
        "f.cs", raw, explicit_contract=_call_site_contract("Query")
    )

    assert reconciliation.stored_procedure_mode is False
    assert reconciliation.mode_reason == "wrapper_mode_unresolved"


def test_a_contract_with_no_command_type_role_falls_back_to_the_scan_time_mode() -> None:
    """A `call_site` Contract that declares no `command_type` argument role (every accepted
    Contract in this repository today does, but nothing requires it) is unaffected by this
    ticket -- rating falls back to the scan-time `wrapper_mode` fact exactly as it did before,
    per `_sqlobject_wrapper_contract`-shaped fixtures elsewhere in this test suite."""
    gateway = CSharpAnalysisGateway(SpCatalog.from_databases({}))
    contract = {
        "name": "sqlobject",
        "receiver_types": ["SQLObject"],
        "methods": {"CreateTable": {"mode": "call_site", "sink": "ExecuteReader"}},
    }
    raw = {
        "class_name": "Reader",
        "method_name": "Run",
        "invocation_kind": "source_wrapper",
        "wrapper_method_name": "CreateTable",
        "wrapper_receiver_type": "SQLObject",
        "wrapper_source_available": False,
        "wrapper_mode": "unknown",
        "start_offset": 0,
        "end_offset": 10,
    }

    reconciliation = gateway.reconcile_wrapper("f.cs", raw, explicit_contract=contract)

    assert reconciliation.contract_mode == "call_site"
    assert reconciliation.stored_procedure_mode is False
    assert reconciliation.mode_reason == "call_site_requires_explicit_stored_procedure_mode"
