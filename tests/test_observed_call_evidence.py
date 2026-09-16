"""Ticket 04 (accepted-contract-resolves-its-calls): Observed Call Evidence clears a
wrapper call resolved to a Local Implementer by itself, with no exclusion entry written
for it, when the whole scan's own facts prove the implementer's method touches no
database (ADR-0029).

`IUtilityService.SqlParam` -- 233 calls in the real IQCS checkout -- is the running
example: its only Local Implementer, `UtilityService.SqlParam` (`Services/
UtilityService.cs`), never touches a command object itself. Its body only calls
`DateTime.TryParse`/`DateTime.ToString`, so the scan holds two Database Invocation
records for it and neither names a database receiver type. `IUtilityService.
GetListFromSysParam` looks the same at a glance -- its implementer holds zero records --
but it must stay in review: it reaches a database only through a sibling method
(`GetMstCodes`), and the scan does not record a call to another method inside the same
project (ADR-0029), so an absent record is never read the same as a record that proves
nothing. `IUtilityService.GetMstCodes` itself must never be cleared, because its
implementer's own record names `SQLDbContext`, the receiver type the accepted
`sqldbcontext` Contract registers.

The primary seam is the real host run against the real IQCS checkout, per this
repository's existing convention for this class of wrapper-classification change
(mirrors `tests/test_wrapper_receiver_local_implementer.py`). Unlike that ticket, this
rule needs facts from a file other than the one holding the call site being rated --
`UtilityService.cs` for the Local Implementer's own records, a controller file for the
call -- so every real-checkout test here builds the index from both files together,
exactly as `build_observed_call_evidence_index` is meant to be built once per whole scan
and shared by every per-file gateway (see `service/analyze_service.py` and
`service/coverage_report.py`). `GetMstCodes` has no real call site through the interface
anywhere in the IQCS checkout, so its case uses a synthetic call-site fact shaped exactly
like the real, ticket-01-resolved facts above -- the same technique
`tests/test_rating_time_command_mode.py` and `tests/test_delegation_alias.py` used for
tickets 02 and 03.
"""

from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from code_analyzer.csharp_analysis_gateway import (  # noqa: E402
    CSharpAnalysisGateway,
    SpCatalog,
    build_observed_call_evidence_index,
    load_wrapper_review_exclusions,
)
from code_analyzer.project_scanner import ProjectScanResult  # noqa: E402
from code_analyzer.static_analyzer_host import StaticAnalyzerHost  # noqa: E402
from service import coverage_report  # noqa: E402

IQCS_ROOT = PROJECT_ROOT / "data" / "repos" / "System_Dept_1" / "IQCS"
UTILITY_SERVICE = IQCS_ROOT / "Services" / "UtilityService.cs"
HOME_SERVICE = IQCS_ROOT / "Services" / "HomeService.cs"
VEH_NG_APR_CONTROLLER = IQCS_ROOT / "Controllers" / "VehNGAprController.cs"
HOME_CONTROLLER = IQCS_ROOT / "Controllers" / "HomeController.cs"
EXCLUSIONS_CONFIG = PROJECT_ROOT / "config" / "wrapper_review_exclusions.json"

requires_dotnet = pytest.mark.skipif(
    shutil.which("dotnet") is None,
    reason="the .NET toolchain is not available",
)
requires_iqcs_fixture = pytest.mark.skipif(
    not UTILITY_SERVICE.exists(),
    reason="local data/repos/System_Dept_1/IQCS fixture checkout is not present",
)

SQLDBCONTEXT_REGISTRY = {
    "sqldbcontext": {"name": "sqldbcontext", "receiver_types": ["SQLDbContext"]},
}


def _scan_file(host: StaticAnalyzerHost, target: Path) -> list[dict]:
    results = host.analyze_csharp_files([target], source_roots=[IQCS_ROOT])
    assert len(results) == 1
    return results[0]["db_invocations"]


def _call(invocations: list[dict], wrapper_method_name: str) -> dict:
    return next(
        invocation
        for invocation in invocations
        if invocation.get("wrapper_method_name") == wrapper_method_name
    )


@pytest.fixture(scope="module")
def host() -> StaticAnalyzerHost:
    instance = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    instance.ensure_ready()
    return instance


@requires_dotnet
@requires_iqcs_fixture
def test_index_spans_the_whole_scan_not_one_file(host: StaticAnalyzerHost) -> None:
    """The rating step's own Implementation Decision: one index built from the whole
    scan, before any gateway exists -- `UtilityService.SqlParam`'s own records live only
    in `UtilityService.cs`'s scan, yet the index must still carry that key when built from
    every file's raw facts together."""
    index = build_observed_call_evidence_index(
        {
            str(UTILITY_SERVICE): _scan_file(host, UTILITY_SERVICE),
            str(HOME_SERVICE): _scan_file(host, HOME_SERVICE),
        }
    )

    assert index[("utilityservice", "sqlparam")] is False
    assert ("utilityservice", "getlistfromsysparam") not in index


@requires_dotnet
@requires_iqcs_fixture
def test_sql_param_clears_by_rule_without_any_exclusion_entry(host: StaticAnalyzerHost) -> None:
    """`IUtilityService.SqlParam` reports `not_applicable` by rule alone:
    `UtilityService.SqlParam`'s own body holds two Database Invocation records
    (`DateTime.TryParse`, `DateTime.ToString`), and neither names a database receiver
    type. No exclusion entry is passed here at all -- the hand-written entry for `SqlParam`
    is gone from `config/wrapper_review_exclusions.json` (see the config test below)."""
    index = build_observed_call_evidence_index(
        {
            str(UTILITY_SERVICE): _scan_file(host, UTILITY_SERVICE),
            str(HOME_SERVICE): _scan_file(host, HOME_SERVICE),
        }
    )
    call = _call(_scan_file(host, HOME_SERVICE), "SqlParam")
    gateway = CSharpAnalysisGateway(
        SpCatalog.from_databases({}),
        observed_call_evidence_index=index,
    )

    reconciliation = gateway.reconcile_wrapper("HomeService.cs", call)

    assert reconciliation.status == "not_applicable"
    assert reconciliation.selection_source == "observed_call_evidence"


@requires_dotnet
@requires_iqcs_fixture
def test_get_list_from_sys_param_stays_in_review_with_no_record_at_all(
    host: StaticAnalyzerHost,
) -> None:
    """`IUtilityService.GetListFromSysParam` stays in review: its implementer's body only
    calls `GetMstCodes`, a sibling method in the same project, and the scan does not
    record a call to another method inside the same project (ADR-0029) -- an absent
    record is never read the same as a record that names no database receiver type."""
    index = build_observed_call_evidence_index(
        {
            str(UTILITY_SERVICE): _scan_file(host, UTILITY_SERVICE),
            str(VEH_NG_APR_CONTROLLER): _scan_file(host, VEH_NG_APR_CONTROLLER),
        }
    )
    assert ("utilityservice", "getlistfromsysparam") not in index
    call = _call(_scan_file(host, VEH_NG_APR_CONTROLLER), "GetListFromSysParam")
    gateway = CSharpAnalysisGateway(
        SpCatalog.from_databases({}),
        observed_call_evidence_index=index,
    )

    reconciliation = gateway.reconcile_wrapper("VehNGAprController.cs", call)

    assert reconciliation.status != "not_applicable"
    assert reconciliation.status == "source_wrapper"


@requires_dotnet
@requires_iqcs_fixture
def test_view_path_stays_in_review_and_its_exclusion_entry_still_applies(
    host: StaticAnalyzerHost,
) -> None:
    """`IUtilityService.ViewPath` holds no record at all -- it only builds a path string
    -- so the rule cannot clear it, exactly like `GetListFromSysParam`. Its hand-written
    exclusion entry in `config/wrapper_review_exclusions.json` still applies and still
    clears it, independent of this rule."""
    index = build_observed_call_evidence_index(
        {
            str(UTILITY_SERVICE): _scan_file(host, UTILITY_SERVICE),
            str(HOME_CONTROLLER): _scan_file(host, HOME_CONTROLLER),
        }
    )
    assert ("utilityservice", "viewpath") not in index
    call = _call(_scan_file(host, HOME_CONTROLLER), "ViewPath")

    gateway_without_exclusion = CSharpAnalysisGateway(
        SpCatalog.from_databases({}),
        observed_call_evidence_index=index,
    )
    without_exclusion = gateway_without_exclusion.reconcile_wrapper("HomeController.cs", call)
    assert without_exclusion.status != "not_applicable"

    gateway_with_exclusion = CSharpAnalysisGateway(
        SpCatalog.from_databases({}),
        observed_call_evidence_index=index,
        wrapper_review_exclusions=load_wrapper_review_exclusions("IQCS"),
    )
    with_exclusion = gateway_with_exclusion.reconcile_wrapper("HomeController.cs", call)
    assert with_exclusion.status == "not_applicable"
    assert with_exclusion.selection_source == "reviewed_exclusion"


@requires_dotnet
@requires_iqcs_fixture
def test_get_mst_codes_is_never_cleared_because_its_record_names_a_database_receiver_type(
    host: StaticAnalyzerHost,
) -> None:
    """`IUtilityService.GetMstCodes` must never be cleared: its implementer's own body
    holds one Database Invocation record naming `SQLDbContext`, the receiver type the
    accepted `sqldbcontext` Contract registers. No controller in the real IQCS checkout
    calls `GetMstCodes` directly through `IUtilityService`, so the call site here is
    synthetic -- shaped exactly like the real, ticket-01-resolved facts `SqlParam` and
    `ViewPath` show above -- while the implementer-side record is the real one."""
    index = build_observed_call_evidence_index(
        {str(UTILITY_SERVICE): _scan_file(host, UTILITY_SERVICE)},
        SQLDBCONTEXT_REGISTRY,
    )
    assert index[("utilityservice", "getmstcodes")] is True

    synthetic_call = {
        "class_name": "SomeController",
        "method_name": "Caller",
        "invocation_kind": "source_wrapper",
        "wrapper_method_name": "GetMstCodes",
        "wrapper_receiver_type": "IUtilityService",
        "wrapper_source_available": True,
        "receiver_implementation_identity": "UtilityService",
        "wrapper_method_semantics": None,
        "wrapper_mode": "unknown",
        "start_offset": 0,
        "end_offset": 1,
    }
    gateway = CSharpAnalysisGateway(
        SpCatalog.from_databases({}),
        external_wrapper_contracts=SQLDBCONTEXT_REGISTRY,
        observed_call_evidence_index=index,
    )

    reconciliation = gateway.reconcile_wrapper("SomeController.cs", synthetic_call)

    assert reconciliation.status != "not_applicable"


def test_a_local_implementer_that_already_reaches_a_terminal_sink_is_never_reconsidered() -> None:
    """Safety guard: this rule only ever intervenes where the call would otherwise stay
    `wrapper_mode_unresolved` forever. A Local Implementer method that already reached a
    real terminal sink in its own body (`fixed_inline_sql`) keeps that answer -- this rule
    never second-guesses a call that already carries real database evidence, even if the
    index (built only from the Contract registry's own receiver types) has no entry for
    the raw ADO.NET type that sink construct used."""
    call = {
        "class_name": "Caller",
        "method_name": "Do",
        "invocation_kind": "source_wrapper",
        "wrapper_method_name": "Run",
        "wrapper_receiver_type": "IFooService",
        "wrapper_source_available": True,
        "receiver_implementation_identity": "Concrete",
        "wrapper_method_semantics": "fixed_inline_sql",
        "wrapper_terminal_sink": "ExecuteNonQuery",
        "wrapper_mode": "unknown",
        "start_offset": 0,
        "end_offset": 1,
    }
    # No record at all for ("concrete", "run") -- an empty index is the worst case, and
    # the call must still keep its own resolved mode rather than fall into this rule.
    gateway = CSharpAnalysisGateway(SpCatalog.from_databases({}), observed_call_evidence_index={})

    reconciliation = gateway.reconcile_wrapper("Caller.cs", call)

    assert reconciliation.status == "source_wrapper"
    assert reconciliation.mode_reason == "inline_sql"


def test_sql_param_exclusion_entry_is_gone_and_view_path_entry_stays() -> None:
    """The hand-written `SqlParam` exclusion entry is redundant now that Observed Call
    Evidence clears it by rule, and this ticket removes it. `ViewPath` carries no record
    at all, so the rule cannot clear it and its entry stays."""
    payload = json.loads(EXCLUSIONS_CONFIG.read_text(encoding="utf-8"))
    iqcs_entries = payload["systems"]["IQCS"]
    method_names = {entry["method_name"] for entry in iqcs_entries}

    assert "SqlParam" not in method_names
    assert "ViewPath" in method_names


def _fake_scan(root: Path, db_invocations: dict) -> ProjectScanResult:
    scan = ProjectScanResult(
        project_root=str(root),
        project_name=root.name,
        scan_time=datetime(2026, 9, 16, 0, 0, 0),
    )
    scan.db_invocations = db_invocations
    return scan


def test_rating_step_wires_one_index_through_every_per_file_gateway(tmp_path: Path) -> None:
    """Ticket 04's own Implementation Decision: 'the rating step therefore builds one
    index first ... and passes it to each gateway.' Proven here at
    `coverage_report.rate_scan_invocations`, the seam that already builds one gateway per
    source file for the acceptance measurement -- with the Local Implementer's own method
    declared in one file and the call resolved from a different one, exactly the shape
    that requires a whole-scan index rather than a per-file one."""
    implementer_file = str((tmp_path / "UtilityService.cs").resolve())
    cleared_caller_file = str((tmp_path / "ClearedCaller.cs").resolve())
    kept_caller_file = str((tmp_path / "KeptCaller.cs").resolve())

    implementer_records = [
        {
            "class_name": "UtilityService",
            "method_name": "SqlParam",
            "invocation_kind": "source_wrapper",
            "wrapper_method_name": "TryParse",
            "wrapper_receiver_type": None,
            "start_offset": 1,
            "end_offset": 2,
        },
        {
            "class_name": "UtilityService",
            "method_name": "SqlParam",
            "invocation_kind": "source_wrapper",
            "wrapper_method_name": "ToString",
            "wrapper_receiver_type": None,
            "start_offset": 3,
            "end_offset": 4,
        },
        {
            "class_name": "UtilityService",
            "method_name": "GetMstCodes",
            "invocation_kind": "source_wrapper",
            "wrapper_method_name": "usp_ExecCmdGetDataTableAsync",
            "wrapper_receiver_type": "SQLDbContext",
            "start_offset": 5,
            "end_offset": 6,
        },
    ]

    def _wrapper_call(method_name: str, **overrides) -> dict:
        base = {
            "class_name": "Caller",
            "method_name": "Do",
            "invocation_kind": "source_wrapper",
            "wrapper_method_name": method_name,
            "wrapper_receiver_type": "IUtilityService",
            "wrapper_source_available": True,
            "receiver_implementation_identity": "UtilityService",
            "wrapper_method_semantics": None,
            "wrapper_mode": "unknown",
            "start_offset": 10,
            "end_offset": 40,
        }
        base.update(overrides)
        return base

    scan = _fake_scan(
        tmp_path,
        {
            implementer_file: implementer_records,
            cleared_caller_file: [_wrapper_call("SqlParam")],
            kept_caller_file: [_wrapper_call("GetMstCodes")],
        },
    )

    rated = coverage_report.rate_scan_invocations(
        tmp_path,
        scan,
        catalog=SpCatalog.from_databases({}),
        contract_registry=SQLDBCONTEXT_REGISTRY,
    )

    # `not_applicable` never becomes a DbInvocation at all -- the same behaviour the
    # existing reviewed-exclusion mechanism already relies on.
    assert rated[cleared_caller_file] == []
    assert len(rated[kept_caller_file]) == 1
