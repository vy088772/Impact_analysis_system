"""Ticket 16: the Coverage Report states two ratios per System, each with named reasons.

Every test here asserts on what the report says — a share, a reason code, a per-System
row — never on how it was reached. A ratio alone cannot tell a resolution that improved
from one that merely became confident, so every test that asserts a number below the
line also asserts the reason given for it.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from code_analyzer.csharp_analysis_gateway import SpCatalog  # noqa: E402
from code_analyzer.project_scanner import ProjectScanResult  # noqa: E402
from service import coverage_report  # noqa: E402
import tools.coverage_report as tool  # noqa: E402


SQLOBJECT_CONTRACT = {
    "name": "sqlobject",
    "receiver_types": ["SQLDbContext"],
    "methods": {
        "ExecProc": {"mode": "stored_procedure", "sink": "ExecuteNonQuery"},
    },
}


def _scan(root: Path, **overrides) -> ProjectScanResult:
    scan = ProjectScanResult(
        project_root=str(root),
        project_name=root.name,
        scan_time=datetime(2026, 9, 11, 0, 0, 0),
    )
    for name, value in overrides.items():
        setattr(scan, name, value)
    return scan


def _file_key(root: Path, name: str) -> str:
    return str((root / name).resolve())


def _direct_call(**overrides) -> dict:
    """One raw direct-ADO.NET stored-procedure fact, the shape the host emits."""
    base = {
        "class_name": "OrderController",
        "method_name": "Save",
        "command_text_kind": "literal",
        "command_text": "usp_SaveOrder",
        "command_type_stored_procedure": True,
        "connection_expression": "conn",
        "start_offset": 10,
        "end_offset": 90,
        "terminal_sink": "ExecuteNonQuery",
    }
    base.update(overrides)
    return base


def _wrapper_call(**overrides) -> dict:
    """One raw external-wrapper fact whose contract puts it in stored-procedure mode."""
    base = _direct_call(
        invocation_kind="source_wrapper",
        wrapper_method_name="ExecProc",
        wrapper_receiver_type="SQLDbContext",
        receiver_type="SQLDbContext",
        wrapper_source_available=False,
        wrapper_mode="stored_procedure",
    )
    base.update(overrides)
    return base


def _coverage(
    root: Path,
    scan: ProjectScanResult,
    *,
    databases: dict | None = None,
) -> dict:
    catalog = SpCatalog.from_databases(databases or {"OrdersDb": ["usp_SaveOrder"]})
    rated = coverage_report.rate_scan_invocations(
        root,
        scan,
        catalog=catalog,
        explicit_contract=SQLOBJECT_CONTRACT,
        external_wrapper_contract=SQLOBJECT_CONTRACT,
    )
    return coverage_report.build_scan_coverage(root, scan, rated)


def test_the_two_ratios_are_reported_separately_and_are_never_one_number(tmp_path: Path) -> None:
    """One call resolves its procedure name, both resolve their connection. The two
    shares differ, and neither is folded into a single coverage number."""
    root = tmp_path / "IQCS"
    root.mkdir()
    key = _file_key(root, "OrderController.cs")
    scan = _scan(
        root,
        db_invocations={
            key: [
                _direct_call(),
                _wrapper_call(
                    command_text_kind="dynamic",
                    command_text=None,
                    command_text_unresolved_reason="command_text_method_parameter",
                ),
            ]
        },
        connection_sources={key: {"conn": {"database": "OrdersDb", "server": "sql01"}}},
    )

    coverage = _coverage(root, scan)

    assert coverage["database_invocations"] == 2
    assert coverage["executed_procedure_name"]["resolved"] == 1
    assert coverage["executed_procedure_name"]["ratio"] == 0.5
    assert coverage["executed_procedure_name"]["reasons"] == {
        "command_text_method_parameter": 1
    }
    assert coverage["resolved_connection_source"]["resolved"] == 2
    assert coverage["resolved_connection_source"]["ratio"] == 1.0
    assert coverage["resolved_connection_source"]["reasons"] == {}
    assert coverage["executed_procedure_name"] is not coverage["resolved_connection_source"]
    assert "coverage" not in coverage
    assert "combined" not in coverage


def test_every_unresolved_invocation_is_counted_under_a_named_reason(tmp_path: Path) -> None:
    """The reason counts account for exactly the invocations below the line, and no
    invocation is filed under a blank reason."""
    root = tmp_path / "IQCS"
    root.mkdir()
    key = _file_key(root, "OrderController.cs")
    scan = _scan(
        root,
        db_invocations={
            key: [
                _direct_call(),
                _direct_call(
                    command_text_kind="dynamic",
                    command_text=None,
                    command_text_unresolved_reason="command_text_method_parameter",
                ),
                _direct_call(command_text="usp_NotInCatalog"),
            ]
        },
        connection_sources={key: {"conn": {"database": "OrdersDb", "server": "sql01"}}},
    )

    coverage = _coverage(root, scan)

    for ratio_name in ("executed_procedure_name", "resolved_connection_source"):
        measured = coverage[ratio_name]
        reasons = measured["reasons"]
        assert all(str(code).strip() for code in reasons)
        assert sum(reasons.values()) == measured["unresolved"]
        assert measured["resolved"] + measured["unresolved"] == coverage["database_invocations"]


def test_command_text_across_a_method_boundary_names_its_own_reason(tmp_path: Path) -> None:
    """A wrapper call whose command text arrives as a method parameter is below the
    procedure-name line under its own reason, not under the generic one."""
    root = tmp_path / "IQCS"
    root.mkdir()
    key = _file_key(root, "OrderService.cs")
    scan = _scan(
        root,
        db_invocations={
            key: [
                _wrapper_call(
                    command_text_kind="dynamic",
                    command_text=None,
                    command_text_unresolved_reason="command_text_method_parameter",
                )
            ]
        },
        connection_sources={key: {"conn": {"database": "OrdersDb", "server": "sql01"}}},
    )

    coverage = _coverage(root, scan)

    assert coverage["executed_procedure_name"]["resolved"] == 0
    assert coverage["executed_procedure_name"]["reasons"] == {"command_text_method_parameter": 1}


def test_a_lookup_key_outside_the_connection_strings_namespace_names_its_own_reason(
    tmp_path: Path,
) -> None:
    """The Configuration Root Namespace read that returns null at runtime is reported as
    itself, not as an unexplained absence."""
    root = tmp_path / "ETR"
    root.mkdir()
    key = _file_key(root, "HomeController.cs")
    scan = _scan(
        root,
        db_invocations={key: [_direct_call(connection_expression="_connetStr")]},
        connection_sources={key: {}},
        unresolved_connections={
            key: [
                {
                    "variable_name": "_connetStr",
                    "lookup_key": "dbConnect",
                    "namespace": "root_configuration",
                    "reason": "root_configuration_namespace_not_connection_strings",
                    "line_number": 21,
                }
            ]
        },
    )

    coverage = _coverage(root, scan)

    assert coverage["resolved_connection_source"]["resolved"] == 0
    assert coverage["resolved_connection_source"]["reasons"] == {
        "root_configuration_namespace_not_connection_strings": 1
    }


def test_no_project_file_above_the_source_names_its_own_reason(tmp_path: Path) -> None:
    """A source file that belongs to no project has no lookup table, and the report says
    exactly that rather than reporting a merged repository-wide guess."""
    root = tmp_path / "Loose"
    root.mkdir()
    key = _file_key(root, "Stray.cs")
    scan = _scan(
        root,
        db_invocations={key: [_direct_call(connection_expression="conn")]},
        connection_sources={key: {}},
        unresolved_connections={
            key: [
                {
                    "variable_name": "conn",
                    "lookup_key": "Default",
                    "namespace": "connection_strings",
                    "reason": "no_project_connection_scope",
                    "line_number": 12,
                }
            ]
        },
    )

    coverage = _coverage(root, scan)

    assert coverage["resolved_connection_source"]["reasons"] == {"no_project_connection_scope": 1}


def test_a_project_with_no_semantic_model_names_its_own_reason(tmp_path: Path) -> None:
    """When the project reports no semantic model, an invocation that named no reason of
    its own is filed under the missing model rather than under a generic absence."""
    root = tmp_path / "EnterpriseApp"
    root.mkdir()
    (root / "Web").mkdir()
    key = _file_key(root, "Web/OrderController.cs")
    scan = _scan(
        root,
        db_invocations={
            key: [_direct_call(command_text_kind="dynamic", command_text=None)]
        },
        connection_sources={key: {"conn": {"database": "OrdersDb", "server": "sql01"}}},
        semantic_binding_availability=[
            {
                "scan_root": str(root),
                "project_file": str(root / "Web" / "Web.csproj"),
                "availability": "unavailable_reference_resolution_failed",
                "unresolved_references": ["Microsoft.Data.SqlClient"],
                "source_file_count": 0,
            }
        ],
    )

    coverage = _coverage(root, scan)

    assert coverage["executed_procedure_name"]["reasons"] == {"no_semantic_model": 1}


def test_a_named_reason_is_never_replaced_by_the_missing_semantic_model(tmp_path: Path) -> None:
    """A method-parameter command text is a fact about the call, not about the model, so
    it keeps its own name even where the project built no semantic model."""
    root = tmp_path / "EnterpriseApp"
    root.mkdir()
    (root / "Web").mkdir()
    key = _file_key(root, "Web/OrderController.cs")
    scan = _scan(
        root,
        db_invocations={
            key: [
                _wrapper_call(
                    command_text_kind="dynamic",
                    command_text=None,
                    command_text_unresolved_reason="command_text_method_parameter",
                )
            ]
        },
        connection_sources={key: {"conn": {"database": "OrdersDb", "server": "sql01"}}},
        semantic_binding_availability=[
            {
                "scan_root": str(root),
                "project_file": str(root / "Web" / "Web.csproj"),
                "availability": "unavailable_reference_resolution_failed",
                "unresolved_references": [],
                "source_file_count": 0,
            }
        ],
    )

    coverage = _coverage(root, scan)

    assert coverage["executed_procedure_name"]["reasons"] == {"command_text_method_parameter": 1}


def test_the_four_named_reasons_stay_four_distinct_codes(tmp_path: Path) -> None:
    """The report separates the four causes the ticket names; none of them collapses into
    another, and none of them reads as a generic failure."""
    root = tmp_path / "Mixed"
    root.mkdir()
    (root / "Web").mkdir()
    scoped_key = _file_key(root, "Web/OrderController.cs")
    stray_key = _file_key(root, "Stray.cs")
    scan = _scan(
        root,
        db_invocations={
            scoped_key: [
                _wrapper_call(
                    command_text_kind="dynamic",
                    command_text=None,
                    command_text_unresolved_reason="command_text_method_parameter",
                    connection_expression="rootRead",
                ),
                _direct_call(command_text_kind="dynamic", command_text=None),
            ],
            stray_key: [_direct_call(connection_expression="conn")],
        },
        connection_sources={scoped_key: {}, stray_key: {}},
        unresolved_connections={
            scoped_key: [
                {
                    "variable_name": "rootRead",
                    "lookup_key": "dbConnect",
                    "namespace": "root_configuration",
                    "reason": "root_configuration_namespace_not_connection_strings",
                    "line_number": 21,
                }
            ],
            stray_key: [
                {
                    "variable_name": "conn",
                    "lookup_key": "Default",
                    "namespace": "connection_strings",
                    "reason": "no_project_connection_scope",
                    "line_number": 12,
                }
            ],
        },
        semantic_binding_availability=[
            {
                "scan_root": str(root),
                "project_file": str(root / "Web" / "Web.csproj"),
                "availability": "unavailable_reference_resolution_failed",
                "unresolved_references": [],
                "source_file_count": 0,
            }
        ],
    )

    coverage = _coverage(root, scan)

    assert "command_text_method_parameter" in coverage["executed_procedure_name"]["reasons"]
    assert "no_semantic_model" in coverage["executed_procedure_name"]["reasons"]
    assert (
        "root_configuration_namespace_not_connection_strings"
        in coverage["resolved_connection_source"]["reasons"]
    )
    assert "no_project_connection_scope" in coverage["resolved_connection_source"]["reasons"]


def test_a_call_site_that_names_no_connection_names_that_absence(tmp_path: Path) -> None:
    """An external wrapper opens its own connection inside an assembly this analysis
    cannot see, so the call site names none. That is its own reason, never a lookup that
    resolved to nothing and never a missing semantic model."""
    root = tmp_path / "TTPUR"
    root.mkdir()
    key = _file_key(root, "PUR_SOMaintain.aspx.cs")
    scan = _scan(
        root,
        db_invocations={key: [_wrapper_call(connection_expression="")]},
        connection_sources={key: {}},
        semantic_binding_availability=[
            {
                "scan_root": str(root),
                "project_file": str(root / "TTPUR.csproj"),
                "availability": "unavailable_reference_resolution_failed",
                "unresolved_references": [],
                "source_file_count": 0,
            }
        ],
    )

    coverage = _coverage(root, scan)

    assert coverage["resolved_connection_source"]["reasons"] == {"no_connection_expression": 1}


def test_a_system_with_no_database_invocations_reports_no_ratio(tmp_path: Path) -> None:
    """Nothing measured is not the same as nothing resolved, so the share is absent
    rather than zero."""
    root = tmp_path / "Empty"
    root.mkdir()
    coverage = _coverage(root, _scan(root))

    assert coverage["database_invocations"] == 0
    assert coverage["executed_procedure_name"]["ratio"] is None
    assert coverage["resolved_connection_source"]["ratio"] is None


def test_the_report_states_one_row_per_system_and_merges_no_two(tmp_path: Path) -> None:
    """Two Systems keep two sets of numbers; the report never adds them together."""
    first = tmp_path / "IQCS"
    first.mkdir()
    second = tmp_path / "ETR"
    second.mkdir()
    first_key = _file_key(first, "A.cs")
    second_key = _file_key(second, "B.cs")
    first_scan = _scan(
        first,
        db_invocations={first_key: [_direct_call()]},
        connection_sources={first_key: {"conn": {"database": "OrdersDb", "server": "sql01"}}},
    )
    second_scan = _scan(
        second,
        db_invocations={
            second_key: [_direct_call(command_text_kind="dynamic", command_text=None)]
        },
        connection_sources={second_key: {}},
    )

    report = coverage_report.build_coverage_report(
        [
            coverage_report.build_system_coverage("IQCS", [_coverage(first, first_scan)]),
            coverage_report.build_system_coverage("ETR", [_coverage(second, second_scan)]),
        ]
    )

    rows = {row["system_id"]: row for row in report["systems"]}
    assert rows["IQCS"]["executed_procedure_name"]["ratio"] == 1.0
    assert rows["ETR"]["executed_procedure_name"]["ratio"] == 0.0
    assert rows["ETR"]["resolved_connection_source"]["ratio"] == 0.0
    assert rows["IQCS"]["database_invocations"] == 1
    assert rows["ETR"]["database_invocations"] == 1


def test_a_system_scanned_under_several_roots_sums_its_roots(tmp_path: Path) -> None:
    """One System may hold several scan roots; its two shares cover all of them, and each
    root stays visible underneath."""
    first = tmp_path / "Y-DOCs" / "ATV"
    first.mkdir(parents=True)
    second = tmp_path / "Y-DOCs" / "TTPUR"
    second.mkdir(parents=True)
    first_key = _file_key(first, "A.cs")
    second_key = _file_key(second, "B.cs")
    first_scan = _scan(
        first,
        db_invocations={first_key: [_direct_call()]},
        connection_sources={first_key: {"conn": {"database": "OrdersDb", "server": "sql01"}}},
    )
    second_scan = _scan(
        second,
        db_invocations={
            second_key: [_direct_call(command_text_kind="dynamic", command_text=None)]
        },
        connection_sources={second_key: {"conn": {"database": "OrdersDb", "server": "sql01"}}},
    )

    system = coverage_report.build_system_coverage(
        "Y-Docs_TTPUR",
        [_coverage(first, first_scan), _coverage(second, second_scan)],
    )

    assert system["database_invocations"] == 2
    assert system["executed_procedure_name"]["ratio"] == 0.5
    assert system["resolved_connection_source"]["ratio"] == 1.0
    assert [scan["root"] for scan in system["scans"]] == [str(first), str(second)]


def test_a_webforms_system_is_reported_by_the_same_measurement(tmp_path: Path) -> None:
    """A Web.config-resolved System carrying no Razor view and no Project Connection
    Scope is measured by the same code path, so its numbers compare with the baseline."""
    root = tmp_path / "TTPUR"
    root.mkdir()
    key = _file_key(root, "PUR_SOMaintain.aspx.cs")
    scan = _scan(
        root,
        db_invocations={key: [_direct_call(class_name="PUR_SOMaintain")]},
        connection_sources={key: {"conn": {"database": "OrdersDb", "server": "sql01"}}},
    )

    coverage = _coverage(root, scan)

    assert coverage["database_invocations"] == 1
    assert coverage["executed_procedure_name"]["resolved"] == 1
    assert coverage["resolved_connection_source"]["resolved"] == 1
    assert coverage["executed_procedure_name"]["reasons"] == {}


def test_the_rendered_report_states_both_shares_and_the_reasons(tmp_path: Path) -> None:
    """A maintainer reading the printed report sees two shares and the reason under each
    one, not a single number."""
    root = tmp_path / "IQCS"
    root.mkdir()
    key = _file_key(root, "A.cs")
    scan = _scan(
        root,
        db_invocations={
            key: [
                _direct_call(),
                _wrapper_call(
                    command_text_kind="dynamic",
                    command_text=None,
                    command_text_unresolved_reason="command_text_method_parameter",
                ),
            ]
        },
        connection_sources={key: {"conn": {"database": "OrdersDb", "server": "sql01"}}},
    )
    report = coverage_report.build_coverage_report(
        [coverage_report.build_system_coverage("IQCS", [_coverage(root, scan)])]
    )

    text = coverage_report.render_coverage_report_text(report)

    assert "executed_procedure_name" in text
    assert "resolved_connection_source" in text
    assert "command_text_method_parameter" in text
    assert "IQCS" in text


# --- the command -------------------------------------------------------------


def _measurable_scan(root: Path) -> ProjectScanResult:
    key = _file_key(root, "OrderController.cs")
    return _scan(
        root,
        db_invocations={
            key: [
                _direct_call(),
                _direct_call(command_text_kind="dynamic", command_text=None),
            ]
        },
        connection_sources={key: {"conn": {"database": "OrdersDb", "server": "sql01"}}},
    )


def _stub_measurement(monkeypatch, scans_by_root: dict, *, cache: str = "current") -> list:
    """Serve prepared scans instead of touching the clone root or SQL Server."""
    calls: list = []

    def fake_get_or_scan(root: Path, refresh: bool = False) -> ProjectScanResult:
        calls.append((Path(root), refresh))
        return scans_by_root[str(Path(root))]

    monkeypatch.setattr(tool.scan_store, "get_or_scan", fake_get_or_scan)
    monkeypatch.setattr(tool.scan_store, "has_cache", lambda root: cache == "current")
    monkeypatch.setattr(tool.scan_store, "cache_status", lambda root: cache)
    monkeypatch.setattr(
        tool.analyze_service,
        "load_sp_catalog",
        lambda database="": SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]}),
    )
    monkeypatch.setattr(tool, "load_contract_registry", lambda: {"contracts": {}})
    monkeypatch.setattr(tool, "load_external_wrapper_contract", lambda name: None)
    monkeypatch.setattr(tool, "load_wrapper_review_exclusions", lambda system: ())
    return calls


def test_the_report_runs_against_a_named_system(tmp_path: Path, monkeypatch) -> None:
    """A maintainer names one System and gets that System's two shares back."""
    root = tmp_path / "IQCS"
    root.mkdir()
    _stub_measurement(monkeypatch, {str(root): _measurable_scan(root)})

    report = tool.build_report(
        [{"system_id": "IQCS", "root": root, "configured_contract": ""}]
    )

    assert [row["system_id"] for row in report["systems"]] == ["IQCS"]
    assert report["systems"][0]["database_invocations"] == 2
    assert report["systems"][0]["executed_procedure_name"]["ratio"] == 0.5
    assert report["systems"][0]["resolved_connection_source"]["ratio"] == 1.0


def test_a_repeat_run_never_forces_a_re_scan(tmp_path: Path, monkeypatch) -> None:
    """Where a current cache exists the measurement reuses it, every time it runs."""
    root = tmp_path / "IQCS"
    root.mkdir()
    calls = _stub_measurement(monkeypatch, {str(root): _measurable_scan(root)})
    target = {"system_id": "IQCS", "root": root, "configured_contract": ""}

    first = tool.build_report([target])
    second = tool.build_report([target])

    assert [refresh for _, refresh in calls] == [False, False]
    assert first["systems"][0]["executed_procedure_name"] == (
        second["systems"][0]["executed_procedure_name"]
    )


def test_a_root_without_a_current_cache_reports_its_cache_state(
    tmp_path: Path, monkeypatch
) -> None:
    """`--cached-only` measures nothing it cannot measure cheaply, and names why rather
    than reporting a share of zero."""
    root = tmp_path / "IQCS"
    root.mkdir()
    calls = _stub_measurement(monkeypatch, {}, cache="missing")

    report = tool.build_report(
        [{"system_id": "IQCS", "root": root, "configured_contract": ""}],
        cached_only=True,
    )

    assert calls == []
    assert report["systems"][0]["scans"][0]["reason"] == "scan_cache_missing"
    assert report["systems"][0]["executed_procedure_name"]["ratio"] is None


def test_a_system_whose_source_root_is_unresolved_says_so(monkeypatch) -> None:
    """A System that reported nothing and a System that resolved nothing never read the
    same."""
    report = tool.build_report(
        [
            {
                "system_id": "NotCloned",
                "root": None,
                "configured_contract": "",
                "reason": "source_root_unresolved",
            }
        ],
        ["Unknown"],
    )

    assert report["systems"][0]["reason"] == "source_root_unresolved"
    assert report["systems"][0]["executed_procedure_name"]["ratio"] is None
    assert report["missing_systems"] == ["Unknown"]


def test_the_webforms_system_is_reported_by_the_same_command(
    tmp_path: Path, monkeypatch
) -> None:
    """The captured baseline is a WebForms System, so the same command must measure one —
    several scan roots, Web.config connections, no Razor view."""
    first = tmp_path / "Y-DOCs" / "ATV"
    first.mkdir(parents=True)
    second = tmp_path / "Y-DOCs" / "TTPUR"
    second.mkdir(parents=True)
    _stub_measurement(
        monkeypatch,
        {str(first): _measurable_scan(first), str(second): _measurable_scan(second)},
    )

    report = tool.build_report(
        [
            {"system_id": "Y-Docs_TTPUR", "root": first, "configured_contract": ""},
            {"system_id": "Y-Docs_TTPUR", "root": second, "configured_contract": ""},
        ]
    )

    assert [row["system_id"] for row in report["systems"]] == ["Y-Docs_TTPUR"]
    assert report["systems"][0]["database_invocations"] == 4
    assert report["systems"][0]["executed_procedure_name"]["resolved"] == 2
    assert [scan["root"] for scan in report["systems"][0]["scans"]] == [
        str(first),
        str(second),
    ]
