"""`/path_evidence` and `/analyze` agree on which program files a name matches.

Both endpoints receive the same program names for the same scan. A name that
`/analyze` reports as not found must not pick up files by substring in
`/path_evidence`.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Sequence

import pytest

from service import analyze_service
from service.schemas import PathEvidenceRequest
from tests.sql_cache_fixtures import one_server_holds_every_database
from tests.test_program_screen_resolution import _analyze, _scan


class _FilesCaptured(Exception):
    def __init__(self, files: Sequence) -> None:
        self.files = list(files)


def _path_evidence_files(monkeypatch, root: Path, scan, program_names: List[str]) -> List[str]:
    """The base names of the C# files `/path_evidence` selects for the names."""
    monkeypatch.setattr(analyze_service, "resolve_source", lambda req: [root])
    monkeypatch.setattr(analyze_service, "_get_scan", lambda r, refresh=False: scan)
    monkeypatch.setattr(
        analyze_service.sql_cache_store, "find_cache_identity", one_server_holds_every_database
    )
    monkeypatch.setattr(analyze_service.sql_cache_store, "load_cached", lambda identity: {})
    monkeypatch.setattr(
        analyze_service,
        "_require_sql_execution_graph",
        lambda database, db_server: ({}, {}),
    )

    def capture(scope, scan_, matched_files, root_):
        raise _FilesCaptured(matched_files)

    monkeypatch.setattr(analyze_service, "_rated_execution_invocations", capture)
    with pytest.raises(_FilesCaptured) as captured:
        analyze_service.get_path_evidence(
            PathEvidenceRequest(path_id="P-1", database="OrdersDb", program_names=program_names)
        )
    return sorted(Path(r.file_path).name for r in captured.value.files)


def _order_scan(tmp_path: Path):
    return _scan(
        tmp_path,
        views=["Views/Orders/Index.cshtml"],
        controllers={
            "Controllers/OrdersController.cs": ["Index"],
            "Controllers/OrderHistoryController.cs": ["Index"],
        },
    )


def test_a_name_analyze_reports_not_found_matches_no_file_in_path_evidence(
    monkeypatch, tmp_path: Path
) -> None:
    scan = _order_scan(tmp_path)

    analyzed = _analyze(monkeypatch, tmp_path, scan, ["Order"])
    files = _path_evidence_files(monkeypatch, tmp_path, scan, ["Order"])

    assert analyzed.programs == []
    assert analyzed.not_found == ["Order"]
    assert files == []


def test_a_scan_without_razor_files_keeps_the_substring_match_on_path_evidence(
    monkeypatch, tmp_path: Path
) -> None:
    scan = _scan(
        tmp_path,
        controllers={
            "Controllers/OrdersController.cs": ["Index"],
            "Controllers/OrderHistoryController.cs": ["Index"],
        },
    )

    files = _path_evidence_files(monkeypatch, tmp_path, scan, ["Order"])

    assert files == ["OrderHistoryController.cs", "OrdersController.cs"]
