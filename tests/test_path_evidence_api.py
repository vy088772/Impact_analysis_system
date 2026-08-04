"""HTTP boundary checks for exact path evidence."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from service import analyze_service, api
from service.schemas import (
    AnalyzeRequest,
    FindBySPRequest,
    FindByTableRequest,
    FlowChainRequest,
    PathEvidenceRequest,
    PathEvidenceResponse,
)


def test_path_evidence_route_rejects_empty_path_id() -> None:
    with pytest.raises(HTTPException) as error:
        api.path_evidence(PathEvidenceRequest(path_id=""))

    assert error.value.status_code == 400
    assert error.value.detail == {
        "code": "invalid_path_id",
        "message": "path_id 不可為空",
    }


def test_path_evidence_route_maps_stale_path_to_conflict(monkeypatch) -> None:
    def raise_stale(request):
        raise analyze_service.PathEvidenceError("stale_path", "snapshot changed")

    monkeypatch.setattr(analyze_service, "get_path_evidence", raise_stale)

    with pytest.raises(HTTPException) as error:
        api.path_evidence(PathEvidenceRequest(path_id="P-stale"))

    assert error.value.status_code == 409
    assert error.value.detail == {
        "code": "stale_path",
        "message": "snapshot changed",
    }


def test_path_evidence_route_maps_unknown_path_to_not_found(monkeypatch) -> None:
    def raise_not_found(request):
        raise analyze_service.PathEvidenceError("path_not_found", "unknown path")

    monkeypatch.setattr(analyze_service, "get_path_evidence", raise_not_found)

    with pytest.raises(HTTPException) as error:
        api.path_evidence(PathEvidenceRequest(path_id="P-missing"))

    assert error.value.status_code == 404
    assert error.value.detail == {
        "code": "path_not_found",
        "message": "unknown path",
    }


def test_path_evidence_route_returns_service_response(monkeypatch) -> None:
    expected = PathEvidenceResponse(path_id="P-valid")
    monkeypatch.setattr(analyze_service, "get_path_evidence", lambda request: expected)

    assert api.path_evidence(PathEvidenceRequest(path_id="P-valid")) == expected


def test_analyze_route_maps_graph_readiness_to_conflict(monkeypatch) -> None:
    def raise_graph_readiness(request):
        raise analyze_service.SqlExecutionGraphRequiredError(
            database="OrdersDb",
            reason="missing",
        )

    monkeypatch.setattr(analyze_service, "analyze", raise_graph_readiness)

    with pytest.raises(HTTPException) as error:
        api.analyze(
            AnalyzeRequest(program_names=["OrderPage"], database="OrdersDb")
        )

    assert error.value.status_code == 409
    assert error.value.detail["code"] == "sql_execution_graph_required"
    assert error.value.detail["database"] == "OrdersDb"
    assert error.value.detail["reason"] == "missing"
    assert error.value.detail["rebuild_action"] == "POST /refresh_sql"


def test_require_sql_execution_graph_exposes_machine_readable_failure(monkeypatch) -> None:
    monkeypatch.setattr(analyze_service.sql_cache_store, "load_cached", lambda database, schema: None)

    with pytest.raises(analyze_service.SqlExecutionGraphRequiredError) as error:
        analyze_service._require_sql_execution_graph("OrdersDb")

    assert error.value.code == "sql_execution_graph_required"
    assert error.value.database == "OrdersDb"
    assert error.value.reason == "missing_or_invalid"
    assert error.value.rebuild_action == "POST /refresh_sql"


def test_path_evidence_route_maps_graph_readiness_to_conflict(monkeypatch) -> None:
    def raise_graph_readiness(request):
        raise analyze_service.SqlExecutionGraphRequiredError(
            database="OrdersDb",
            reason="stale",
        )

    monkeypatch.setattr(analyze_service, "get_path_evidence", raise_graph_readiness)

    with pytest.raises(HTTPException) as error:
        api.path_evidence(PathEvidenceRequest(path_id="P-stale", database="OrdersDb"))

    assert error.value.status_code == 409
    assert error.value.detail == {
        "code": "sql_execution_graph_required",
        "database": "OrdersDb",
        "reason": "stale",
        "rebuild_action": "POST /refresh_sql",
        "message": str(error.value.detail["message"]),
    }


def test_find_by_sp_route_keeps_missing_database_as_bad_request(monkeypatch) -> None:
    def raise_invalid(request):
        raise ValueError("database 不可為空")

    monkeypatch.setattr(analyze_service, "find_by_sp", raise_invalid)

    with pytest.raises(HTTPException) as error:
        api.find_by_sp(FindBySPRequest(sp_name="dbo.usp_SaveOrder"))

    assert error.value.status_code == 400
    assert error.value.detail == "database 不可為空"


@pytest.mark.parametrize(
    ("route_name", "service_name", "payload"),
    [
        (
            "find_by_sp",
            "find_by_sp",
            FindBySPRequest(sp_name="dbo.usp_SaveOrder", database="OrdersDb"),
        ),
        (
            "find_by_table",
            "find_by_table",
            FindByTableRequest(table_name="dbo.SOrder", database="OrdersDb"),
        ),
        (
            "flow_chain",
            "flow_chain",
            FlowChainRequest(
                direction="forward",
                program_name="OrderPage",
                anchor_method="Save",
                database="OrdersDb",
            ),
        ),
    ],
)
def test_relationship_routes_map_graph_readiness_to_conflict(
    monkeypatch,
    route_name: str,
    service_name: str,
    payload,
) -> None:
    def raise_graph_readiness(request):
        raise analyze_service.SqlExecutionGraphRequiredError(
            database="OrdersDb",
            reason="mismatched",
        )

    monkeypatch.setattr(analyze_service, service_name, raise_graph_readiness)

    with pytest.raises(HTTPException) as error:
        getattr(api, route_name)(payload)

    assert error.value.status_code == 409
    assert error.value.detail["code"] == "sql_execution_graph_required"
    assert error.value.detail["database"] == "OrdersDb"
    assert error.value.detail["reason"] == "mismatched"
    assert error.value.detail["rebuild_action"] == "POST /refresh_sql"


def test_find_by_sp_cache_only_skip_precedes_graph_readiness(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        analyze_service,
        "peek_scan_roots",
        lambda source: [tmp_path],
    )
    monkeypatch.setattr(analyze_service, "has_cache", lambda root: False)
    monkeypatch.setattr(
        analyze_service,
        "resolve_scan_roots",
        lambda source, refresh=False: (_ for _ in ()).throw(
            AssertionError("cache-only skip must not resolve or scan source")
        ),
    )

    response = analyze_service.find_by_sp(
        FindBySPRequest(
            source={"project": "orders", "repo": "orders"},
            sp_name="dbo.usp_SaveOrder",
            database="OrdersDb",
        )
    )

    assert response.skipped is True
    assert response.matches == []