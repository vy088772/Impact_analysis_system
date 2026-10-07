"""Ticket 08: related program expansion follows the Bound Call Targets (ADR-0044).

`expand_related_programs` lists the files that a program calls into. It uses the
same Bound Call Target edges as the flow chain, so an interface call reaches its
Local Implementer, and the call text is never matched by name.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from code_analyzer.models import MethodInfo
from service import analyze_service
from service.reference_expander import expand_related_programs
from service.schemas import AnalyzeRequest
from tests.program_screen_fixtures import _controller_result, _scan
from tests.request_context_fixtures import RequestStores
from tests.scan_fixtures import csharp_file, scan_of, with_bound_calls
from tests.sql_cache_fixtures import cache_with_procedures


def _methods(*names: str) -> list[MethodInfo]:
    return [MethodInfo(name=name, access_modifier="public", return_type="void") for name in names]


def _found(related) -> list[tuple[str, str, str, int]]:
    return [(Path(r["file"]).name, r["method"], r["called_by"], r["depth"]) for r in related]


def _orders_page(tmp_path: Path, calls: dict, *files):
    """The OrderEntry page and the given files, with the Bound Call Targets of `calls`."""
    page = csharp_file(tmp_path, "OrderEntry.cs", _methods("Page_Load", "BindGrid"))
    scan = scan_of(tmp_path, [page, *files])
    for relative_path, file_calls in calls.items():
        with_bound_calls(scan, relative_path, file_calls)
    return scan, page


def test_a_static_helper_call_appears_in_the_expansion(tmp_path: Path) -> None:
    helper = csharp_file(tmp_path, "CommonFunction.cs", _methods("AlertMsg"))
    scan, page = _orders_page(
        tmp_path, {"OrderEntry.cs": {"OrderEntry.Page_Load": ["CommonFunction.AlertMsg"]}}, helper
    )

    related = expand_related_programs(scan, [page])

    assert _found(related) == [("CommonFunction.cs", "AlertMsg", "OrderEntry.Page_Load", 1)]
    assert related[0]["class"] == "CommonFunction"


def test_an_interface_call_lists_the_local_implementer_only(tmp_path: Path) -> None:
    """The interface and its implementation both declare InvalidateJobType."""
    contract = csharp_file(tmp_path, "IJobTypeService.cs", _methods("InvalidateJobType"))
    service = csharp_file(tmp_path, "JobTypeService.cs", _methods("InvalidateJobType"))
    scan, page = _orders_page(
        tmp_path,
        {"OrderEntry.cs": {"OrderEntry.Page_Load": ["JobTypeService.InvalidateJobType"]}},
        contract,
        service,
    )

    related = expand_related_programs(scan, [page])

    assert _found(related) == [("JobTypeService.cs", "InvalidateJobType", "OrderEntry.Page_Load", 1)]


def test_one_call_lists_one_of_two_methods_with_the_same_name(tmp_path: Path) -> None:
    orders = csharp_file(tmp_path, "OrderRepository.cs", _methods("Save"))
    invoices = csharp_file(tmp_path, "InvoiceRepository.cs", _methods("Save"))
    scan, page = _orders_page(
        tmp_path, {"OrderEntry.cs": {"OrderEntry.Page_Load": ["OrderRepository.Save"]}}, orders, invoices
    )

    related = expand_related_programs(scan, [page])

    assert _found(related) == [("OrderRepository.cs", "Save", "OrderEntry.Page_Load", 1)]


def test_a_call_with_no_bound_call_target_lists_nothing(tmp_path: Path) -> None:
    """The call text `x.Save` names a method that one file declares. The expansion
    does not match it by name."""
    orders = csharp_file(tmp_path, "OrderRepository.cs", _methods("Save"))
    scan, page = _orders_page(
        tmp_path, {"OrderEntry.cs": {"OrderEntry.Page_Load": ["!no_local_implementer"]}}, orders
    )
    page.classes[0].methods[0].calls = ["x.Save", "OrderRepository.Save"]

    assert expand_related_programs(scan, [page]) == []


def test_a_call_inside_the_program_lists_nothing_but_its_callees_appear(tmp_path: Path) -> None:
    helper = csharp_file(tmp_path, "CommonFunction.cs", _methods("AlertMsg"))
    scan, page = _orders_page(
        tmp_path,
        {
            "OrderEntry.cs": {
                "OrderEntry.Page_Load": ["OrderEntry.BindGrid"],
                "OrderEntry.BindGrid": ["CommonFunction.AlertMsg"],
            }
        },
        helper,
    )

    related = expand_related_programs(scan, [page])

    assert _found(related) == [("CommonFunction.cs", "AlertMsg", "OrderEntry.BindGrid", 1)]


def _service_chain(tmp_path: Path):
    """OrderEntry -> OrderService.Save -> (own Validate) -> OrderRepository.Insert.

    OrderService.Load calls AuditLog.Write, but no call reaches Load.
    """
    service = csharp_file(tmp_path, "OrderService.cs", _methods("Save", "Validate", "Load"))
    repository = csharp_file(tmp_path, "OrderRepository.cs", _methods("Insert"))
    audit = csharp_file(tmp_path, "AuditLog.cs", _methods("Write"))
    return _orders_page(
        tmp_path,
        {
            "OrderEntry.cs": {"OrderEntry.Page_Load": ["OrderService.Save"]},
            "OrderService.cs": {
                "OrderService.Save": ["OrderService.Validate"],
                "OrderService.Validate": ["OrderRepository.Insert"],
                "OrderService.Load": ["AuditLog.Write"],
            },
        },
        service,
        repository,
        audit,
    )


def test_depth_one_stops_at_the_files_that_the_program_calls(tmp_path: Path) -> None:
    scan, page = _service_chain(tmp_path)

    related = expand_related_programs(scan, [page], depth=1)

    assert _found(related) == [("OrderService.cs", "Save", "OrderEntry.Page_Load", 1)]


def test_depth_two_follows_only_the_methods_that_a_call_reaches(tmp_path: Path) -> None:
    scan, page = _service_chain(tmp_path)

    related = expand_related_programs(scan, [page], depth=2)

    assert _found(related) == [
        ("OrderService.cs", "Save", "OrderEntry.Page_Load", 1),
        ("OrderRepository.cs", "Insert", "OrderService.Validate", 2),
    ]


def test_depth_zero_lists_nothing(tmp_path: Path) -> None:
    scan, page = _service_chain(tmp_path)

    assert expand_related_programs(scan, [page], depth=0) == []


def test_max_programs_limits_the_list(tmp_path: Path) -> None:
    helper = csharp_file(tmp_path, "CommonFunction.cs", _methods("AlertMsg", "OpenWindow", "Close"))
    scan, page = _orders_page(
        tmp_path,
        {
            "OrderEntry.cs": {
                "OrderEntry.Page_Load": [
                    "CommonFunction.AlertMsg",
                    "CommonFunction.OpenWindow",
                    "CommonFunction.Close",
                ]
            }
        },
        helper,
    )

    related = expand_related_programs(scan, [page], max_programs=2)

    assert [r["method"] for r in related] == ["AlertMsg", "OpenWindow"]


def test_a_method_that_the_program_does_not_own_lists_nothing(tmp_path: Path) -> None:
    helper = csharp_file(tmp_path, "CommonFunction.cs", _methods("AlertMsg", "OpenWindow"))
    scan, page = _orders_page(
        tmp_path,
        {
            "OrderEntry.cs": {
                "OrderEntry.Page_Load": ["CommonFunction.AlertMsg"],
                "OrderEntry.BindGrid": ["CommonFunction.OpenWindow"],
            }
        },
        helper,
    )

    related = expand_related_programs(
        scan, [page], owns_action=lambda file_path, method_name: method_name == "Page_Load"
    )

    assert [r["method"] for r in related] == ["AlertMsg"]


def _analyze_related(monkeypatch, root: Path, scan, program_names: Sequence[str], depth: int):
    stores = RequestStores.of(root, scan, "OrdersDb")
    monkeypatch.setattr(
        analyze_service.sql_cache_store, "load_cached", lambda identity: cache_with_procedures()
    )
    monkeypatch.setattr(
        analyze_service,
        "_require_sql_execution_graph",
        lambda database, sql_cache_identity: ({}, {}),
    )
    response = analyze_service.analyze(
        AnalyzeRequest(
            database="OrdersDb",
            program_names=list(program_names),
            include_snippets=False,
            expand_depth=depth,
        ),
        evidence_source=lambda *args, **kwargs: analyze_service.DerivedExecutionEvidence([], {}),
        scan_store=stores.scan_store,
        cache_store=stores.cache_store,
    )
    return response.programs[0].related_programs


def test_an_mvc_screen_lists_the_service_that_its_action_calls(monkeypatch, tmp_path: Path) -> None:
    """The JobType screen owns Index. Delete is an action of another screen."""
    scan = _scan(
        tmp_path,
        views=["Views/JobType/Index.cshtml"],
        controllers={"Controllers/JobTypeController.cs": ["Index", "Delete"]},
    )
    scan.csharp_results += [
        _controller_result(tmp_path, "Services/IJobTypeService.cs", ["InvalidateJobType"]),
        _controller_result(tmp_path, "Services/JobTypeService.cs", ["InvalidateJobType", "Remove"]),
    ]
    with_bound_calls(
        scan,
        "Controllers/JobTypeController.cs",
        {
            "JobTypeController.Index": ["JobTypeService.InvalidateJobType"],
            "JobTypeController.Delete": ["JobTypeService.Remove"],
        },
    )

    related = _analyze_related(monkeypatch, tmp_path, scan, ["JobType"], depth=1)

    assert [(r.file, r.class_, r.method, r.called_by, r.depth) for r in related] == [
        ("Services/JobTypeService.cs", "JobTypeService", "InvalidateJobType", "JobTypeController.Index", 1)
    ]
