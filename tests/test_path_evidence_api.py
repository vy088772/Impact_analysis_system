"""HTTP boundary checks for exact path evidence."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from service import analyze_service, api
from service.schemas import PathEvidenceRequest, PathEvidenceResponse


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