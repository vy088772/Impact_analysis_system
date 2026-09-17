"""Ticket 01 (sqldbcontext-contract-resolves-its-real-calls): the re-decompiled
`sqldbcontext` entry resolves the real IQCS calls the stale one never could.

`accepted-contract-resolves-its-calls` shipped Rating-Time Command Mode, Delegation Alias, and
Observed Call Evidence, proven only against a Contract fixture built with the true parameter
types (`Microsoft.Data.SqlClient.SqlParameter[]`) -- never against the real, on-disk
`sqldbcontext` entry, which still declared `Microsoft.EntityFrameworkCore.SqlParameter[]?`, a
stale decompilation-cache artifact from before the current decompiler existed (see
test_rating_time_command_mode.py and test_delegation_alias.py's own docstrings). This ticket
re-decompiled `SQLDbContext` with the fixed decompiler (`tools/StaticAnalyzerHost/WrapperDecompiler.cs`,
which used to misresolve a parameter's namespace when decompiling one method at a time) and
committed the result as a new, fingerprint-suffixed registry entry --
`config/external_wrapper_contracts.json`'s `sqldbcontext-53e5d16df832` -- leaving the original
`sqldbcontext` entry untouched (an accepted Contract is immutable).

The two seams this ticket needs, per its own Testing Decisions:

1. A real-checkout test scans the real IQCS checkout and asserts the three affected methods
   resolve to their real Executed Procedure Name against the NEW entry -- proving the fix
   against the real, on-disk result, not a fixture built to sidestep the defect.
2. A registry-read test asserts the original `sqldbcontext` entry is unchanged, and that the
   new entry carries a different name and a different Contract Fingerprint.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from code_analyzer.csharp_analysis_gateway import CSharpAnalysisGateway, SpCatalog
from code_analyzer.static_analyzer_host import StaticAnalyzerHost
from service.contract_registry import DEFAULT_REGISTRY_PATH

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

# The new entry ticket 01 committed for the real, on-disk CommonLibrary.dll checked out under
# IQCS today. A different DLL revision would earn a different fingerprint suffix; this name is
# this ticket's own concrete result, the same way the real Executed Procedure Names below are
# tied to today's real IQCS source, not a name this test invents.
NEW_CONTRACT_NAME = "sqldbcontext-53e5d16df832"
ORIGINAL_CONTRACT_NAME = "sqldbcontext"


def _load_registry() -> dict:
    return json.loads(DEFAULT_REGISTRY_PATH.read_text(encoding="utf-8"))


def _analyze(target: Path, source_root: Path) -> list[dict]:
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()
    results = host.analyze_csharp_files([target], source_roots=[source_root])
    assert len(results) == 1
    return results[0]["db_invocations"]


def _call(invocations: list[dict], method_name: str) -> dict:
    return next(i for i in invocations if i.get("wrapper_method_name") == method_name)


def test_original_sqldbcontext_entry_is_unchanged_and_the_new_entry_differs() -> None:
    """The immutability guarantee: an accepted Contract is never mutated in place. The original
    `sqldbcontext` entry's own Contract Fingerprint (and every other field) is exactly what it
    was before this ticket; the new entry is a different name with a different fingerprint."""
    registry = _load_registry()["contracts"]

    assert ORIGINAL_CONTRACT_NAME in registry
    assert NEW_CONTRACT_NAME in registry
    original = registry[ORIGINAL_CONTRACT_NAME]
    new = registry[NEW_CONTRACT_NAME]

    assert original["contract_fingerprint"] == "caae2859194fd7ad80cfbaca7a22d2901826cf6bcf43fb9adbd5b806a2bf3fc9"
    assert new["contract_fingerprint"] != original["contract_fingerprint"]
    assert NEW_CONTRACT_NAME != ORIGINAL_CONTRACT_NAME

    # The stale parameter types stay exactly as they were -- this ticket never edits them.
    assert (
        original["methods"]["usp_ExecCmdGetDataSetAsync"]["parameter_types"][1]
        == "microsoft.entityframeworkcore.sqlparameter[]?"
    )
    assert (
        new["methods"]["usp_ExecCmdGetDataSetAsync"]["parameter_types"][1]
        == "microsoft.data.sqlclient.sqlparameter[]"
    )


@requires_dotnet
@requires_iqcs_fixture
def test_real_checkout_resolves_usp_exec_cmd_get_data_set_async_against_the_new_entry() -> None:
    """The primary acceptance target the whole ticket exists for: the new, on-disk registry
    entry -- not a fixture -- resolves the real call's Executed Procedure Name."""
    contract = _load_registry()["contracts"][NEW_CONTRACT_NAME]
    call = _call(_analyze(DATASET_SERVICE, IQCS_ROOT), "usp_ExecCmdGetDataSetAsync")
    gateway = CSharpAnalysisGateway(SpCatalog.from_databases({}))

    invocation = gateway.resolve_direct_invocations(
        str(DATASET_SERVICE), [call], explicit_contract=contract
    )[0]
    assert invocation.executed_procedure_name == "usp_iqcmgmt_iqcresultcfm_dtl"


@requires_dotnet
@requires_iqcs_fixture
def test_real_checkout_resolves_usp_exec_cmd_get_count_async_against_the_new_entry() -> None:
    """The spec's second named call, whose declared sink is `ExecuteSqlInterpolatedAsync`."""
    contract = _load_registry()["contracts"][NEW_CONTRACT_NAME]
    call = _call(_analyze(COUNT_SERVICE, IQCS_ROOT), "usp_ExecCmdGetCountAsync")
    gateway = CSharpAnalysisGateway(SpCatalog.from_databases({}))

    invocation = gateway.resolve_direct_invocations(
        str(COUNT_SERVICE), [call], explicit_contract=contract
    )[0]
    assert invocation.executed_procedure_name == "usp_file_clearlogfiledelete"


@requires_dotnet
@requires_iqcs_fixture
def test_real_checkout_resolves_usp_exec_cmd_get_data_table_async_through_its_alias() -> None:
    """The third named call: `usp_ExecCmdGetDataTableAsync` constructs no command of its own --
    it resolves only through the new entry's own Delegation Alias, proving that alias survived
    the re-decompile intact."""
    contract = _load_registry()["contracts"][NEW_CONTRACT_NAME]
    call = _call(_analyze(DATASET_SERVICE, IQCS_ROOT), "usp_ExecCmdGetDataTableAsync")
    gateway = CSharpAnalysisGateway(SpCatalog.from_databases({}))

    invocation = gateway.resolve_direct_invocations(
        str(DATASET_SERVICE), [call], explicit_contract=contract
    )[0]
    assert invocation.executed_procedure_name == "usp_iqcmgmt_iqcresultcfm_qry"
    assert invocation.wrapper_method == "usp_ExecCmdGetDataTableAsync"
