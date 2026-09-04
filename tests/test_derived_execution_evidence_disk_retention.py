"""Ticket 06: Derived Execution Evidence survives a restart and an eviction.

ADR-0013 already avoided re-deriving Derived Execution Evidence twice inside
one process (ticket 04/05), but only for as long as the in-memory retention
holds the scope. This module proves the disk-backed second tier
(`service.derived_execution_evidence_store`, ADR-0017) added on top: a scope
derived once is read back after a process restart and after an in-memory
eviction, instead of being derived again.

Prior art for the fixtures below: tests/test_derived_execution_evidence_reuse.py
builds the same kind of scan and wires the same stubs; this module reuses that
file's `_scan`/`_wire`/`_request`/`_graph` shapes rather than inventing a
second set (see that file's own docstring for why each reuse test module is
otherwise self-contained).

A restart is simulated by clearing the in-memory retention without touching
the disk store -- exactly what `RatedInvocationsRetention.__exit__` does not
do to the disk store between two `with` blocks that share one `store_root`.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from code_analyzer.models import ClassInfo, FileAnalysisResult, FileType, FrameworkType, MethodInfo
from code_analyzer.project_scanner import ProjectScanResult
from service import analyze_service
from service import derived_execution_evidence_store as store
from service.schemas import FindBySPRequest, FindByTableRequest
from tests.derived_execution_evidence_fixtures import RatedInvocationsRetention


def _graph(*procedure_names: str) -> dict:
    return {
        "graph_version": 2,
        "database": "OrdersDb",
        "nodes": [
            {"id": f"stored_procedure:dbo.{name}", "type": "stored_procedure", "schema": "dbo", "name": name}
            for name in procedure_names
        ],
        "relationships": [],
        "parse_errors": [],
    }


def _file(root: Path) -> FileAnalysisResult:
    path = root / "AlphaPage.cs"
    return FileAnalysisResult(
        file_path=str(path),
        file_type=FileType.CSHARP,
        framework=FrameworkType.WEBFORMS,
        classes=[
            ClassInfo(
                name="AlphaPage",
                namespace="",
                file_path=str(path),
                methods=[MethodInfo(name="SaveAlpha", access_modifier="private", return_type="void")],
            )
        ],
    )


def _scan(root: Path, *, alpha_calls: str = "usp_Alpha") -> ProjectScanResult:
    alpha = _file(root)
    raw = {
        str((root / "AlphaPage.cs").resolve()): [
            {
                "class_name": "AlphaPage",
                "method_name": "SaveAlpha",
                "command_text_kind": "literal",
                "command_text": f"dbo.{alpha_calls}",
                "command_type_stored_procedure": True,
                "terminal_sink": "ExecuteNonQuery",
                "connection_expression": "conn",
                "start_offset": 10,
                "end_offset": 90,
            }
        ]
    }
    return ProjectScanResult(
        project_root=str(root),
        project_name="orders",
        scan_time=datetime.now(),
        csharp_results=[alpha],
        db_invocations=raw,
        connection_sources={str((root / "AlphaPage.cs").resolve()): {"conn": "OrdersDb"}},
    )


def _wire(
    monkeypatch,
    scan: ProjectScanResult,
    tmp_path: Path,
    graph: dict,
    *,
    scan_saved_at: str = "scan-v1",
    scan_commit: Optional[str] = "commit-v1",
    sql_cache_saved_at: str = "sql-cache-v1",
) -> None:
    cache_payload = {"database": "OrdersDb", "schema": "dbo", "sql_execution_graph": graph}
    monkeypatch.setattr(analyze_service, "resolve_scan_roots", lambda source, refresh=False: [tmp_path])
    monkeypatch.setattr(analyze_service, "_get_scan", lambda root, refresh=False: scan)
    monkeypatch.setattr(analyze_service, "cached_saved_at", lambda root: scan_saved_at)
    monkeypatch.setattr(analyze_service, "cached_commit", lambda root: scan_commit)
    monkeypatch.setattr(
        analyze_service.sql_cache_store,
        "load_cached",
        lambda database, schema, server="": cache_payload,
    )
    monkeypatch.setattr(
        analyze_service.sql_cache_store,
        "cached_saved_at",
        lambda database, schema="dbo", server="": sql_cache_saved_at,
    )


def _sp_request(sp_name: str = "dbo.usp_Alpha", *, refresh: bool = False) -> FindBySPRequest:
    return FindBySPRequest(
        source={"project": "orders", "repo": "orders"},
        sp_name=sp_name,
        database="OrdersDb",
        cache_only=False,
        refresh=refresh,
    )


def _table_request(table_name: str = "TableA", *, refresh: bool = False) -> FindByTableRequest:
    return FindByTableRequest(
        source={"project": "orders", "repo": "orders"},
        table_name=table_name,
        database="OrdersDb",
        cache_only=False,
        refresh=refresh,
    )


def _scope(tmp_path: Path) -> analyze_service.DerivedExecutionEvidenceScope:
    return analyze_service.DerivedExecutionEvidenceScope.of(_sp_request(), [tmp_path])


def _count_real_rating_derivations(monkeypatch) -> list:
    calls: list = []
    real = analyze_service._rated_execution_invocations

    def counting(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(analyze_service, "_rated_execution_invocations", counting)
    return calls


def _count_real_path_builds(monkeypatch) -> list:
    calls: list = []
    real = analyze_service.build_execution_paths

    def counting(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(analyze_service, "build_execution_paths", counting)
    return calls


def _simulate_restart() -> None:
    """Drop the in-memory retention only -- the disk store is untouched, as a
    real process restart would leave it."""
    analyze_service._rated_invocations_retention.clear()


# --------------------------------------------------------------------- restart


def test_a_scope_derived_in_one_process_is_served_from_disk_in_the_next(monkeypatch, tmp_path: Path) -> None:
    with RatedInvocationsRetention():
        scan = _scan(tmp_path)
        _wire(monkeypatch, scan, tmp_path, _graph("usp_Alpha"))
        calls = _count_real_rating_derivations(monkeypatch)

        before = analyze_service.find_by_sp(_sp_request())
        assert len(calls) == 1

        _simulate_restart()
        after = analyze_service.find_by_sp(_sp_request())

        assert len(calls) == 1  # no further derivation -- served from disk
        assert [(m.program, m.file) for m in before.matches] == [(m.program, m.file) for m in after.matches]


def test_execution_paths_survive_a_restart_too(monkeypatch, tmp_path: Path) -> None:
    """The costlier half of the evidence (path building, ticket 05's seam)
    must also come back from disk, not just the rated invocations."""
    with RatedInvocationsRetention():
        scan = _scan(tmp_path)
        _wire(monkeypatch, scan, tmp_path, _graph("usp_Alpha"))
        rating_calls = _count_real_rating_derivations(monkeypatch)
        path_calls = _count_real_path_builds(monkeypatch)

        before = analyze_service.find_by_table(_table_request())
        assert len(rating_calls) == 1
        assert len(path_calls) == 1

        _simulate_restart()
        after = analyze_service.find_by_table(_table_request())

        assert len(rating_calls) == 1
        assert len(path_calls) == 1  # no further path build -- served from disk
        assert [(m.program, m.file) for m in before.matches] == [(m.program, m.file) for m in after.matches]


# --------------------------------------------------------------------- eviction


def test_a_scope_evicted_from_memory_is_served_from_disk(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(analyze_service.settings, "DERIVED_EXECUTION_EVIDENCE_RETENTION_LIMIT", 1)
    with RatedInvocationsRetention():
        scan = _scan(tmp_path)
        _wire(monkeypatch, scan, tmp_path, _graph("usp_Alpha", "usp_Other"))
        calls = _count_real_rating_derivations(monkeypatch)

        first = analyze_service.find_by_sp(_sp_request("dbo.usp_Alpha"))
        assert len(calls) == 1

        # A second, distinct scope evicts the first from the bounded in-memory
        # retention (bound=1) without touching the disk store.
        other_request = FindBySPRequest(
            source={"project": "orders", "repo": "orders"},
            sp_name="dbo.usp_Alpha",
            database="OtherDb",
            cache_only=False,
            refresh=False,
        )
        monkeypatch.setattr(
            analyze_service.sql_cache_store,
            "load_cached",
            lambda database, schema, server="": {
                "database": database,
                "schema": "dbo",
                "sql_execution_graph": _graph("usp_Alpha", "usp_Other"),
            },
        )
        analyze_service.find_by_sp(other_request)
        first_scope = analyze_service.DerivedExecutionEvidenceScope.of(_sp_request(), [tmp_path])
        assert first_scope not in analyze_service._rated_invocations_retention

        again = analyze_service.find_by_sp(_sp_request("dbo.usp_Alpha"))

        assert len(calls) == 2  # first derivation + the other scope's -- not a third
        assert [(m.program, m.file) for m in first.matches] == [(m.program, m.file) for m in again.matches]


# ------------------------------------------------------------------------ files


def test_each_scope_occupies_one_file_replaced_in_place(monkeypatch, tmp_path: Path) -> None:
    with RatedInvocationsRetention() as _retention:
        scan = _scan(tmp_path)
        _wire(monkeypatch, scan, tmp_path, _graph("usp_Alpha", "usp_Beta"))
        root = Path(analyze_service.settings.DERIVED_EXECUTION_EVIDENCE_STORE_ROOT)

        analyze_service.find_by_sp(_sp_request(refresh=True))
        analyze_service.find_by_sp(_sp_request(refresh=True))
        analyze_service.find_by_sp(_sp_request(refresh=True))

        files = [p for p in root.iterdir() if p.is_file()]
        assert len(files) == 1


def test_the_write_is_atomic_no_temp_file_survives_a_successful_write(monkeypatch, tmp_path: Path) -> None:
    with RatedInvocationsRetention():
        scan = _scan(tmp_path)
        _wire(monkeypatch, scan, tmp_path, _graph("usp_Alpha"))
        root = Path(analyze_service.settings.DERIVED_EXECUTION_EVIDENCE_STORE_ROOT)

        analyze_service.find_by_sp(_sp_request())

        entries = list(root.iterdir())
        assert len(entries) == 1
        assert not entries[0].name.endswith(".tmp") and "tmp-" not in entries[0].name


def test_a_failed_write_leaves_no_temp_file_and_a_previous_valid_file_intact(monkeypatch, tmp_path: Path) -> None:
    with RatedInvocationsRetention():
        scan = _scan(tmp_path)
        _wire(monkeypatch, scan, tmp_path, _graph("usp_Alpha"))
        root = Path(analyze_service.settings.DERIVED_EXECUTION_EVIDENCE_STORE_ROOT)

        first = analyze_service.find_by_sp(_sp_request())
        entries_after_first = {p.name for p in root.iterdir()}
        assert len(entries_after_first) == 1

        real_dump = store.pickle.dump

        def failing_dump(*args, **kwargs):
            raise OSError("simulated disk failure")

        monkeypatch.setattr(store.pickle, "dump", failing_dump)
        # Force a fresh derivation attempt (a changed recorded scan save time)
        # that tries, and fails, to persist -- a stamp mismatch is required
        # here, otherwise the still-valid stored file would just be reused
        # and no write would even be attempted.
        analyze_service._rated_invocations_retention.clear()
        monkeypatch.setattr(analyze_service, "cached_saved_at", lambda root: "scan-v2")
        monkeypatch.setattr(analyze_service, "_get_scan", lambda root, refresh=False: _scan(tmp_path, alpha_calls="usp_Gamma"))
        analyze_service.find_by_sp(_sp_request())
        monkeypatch.setattr(store.pickle, "dump", real_dump)

        entries_after_failure = {p.name for p in root.iterdir()}
        # No leftover temp file, and the previously-written valid file is untouched.
        assert entries_after_failure == entries_after_first


# ------------------------------------------------------------------ concurrency


def test_two_concurrent_derivations_of_one_new_scope_leave_one_valid_file(monkeypatch, tmp_path: Path) -> None:
    """Two 'concurrent' derivations (simulated by two sequential `store()`
    calls with equal results, since no lock is taken) must leave exactly one
    valid, loadable file -- never two files, never a corrupt one."""
    with RatedInvocationsRetention():
        scan = _scan(tmp_path)
        _wire(monkeypatch, scan, tmp_path, _graph("usp_Alpha"))
        root = Path(analyze_service.settings.DERIVED_EXECUTION_EVIDENCE_STORE_ROOT)

        scope = _scope(tmp_path)
        stamp = analyze_service._rated_invocations_validity_stamp(scope, [scan])
        rated_invocations, graph = analyze_service._rated_execution_invocations(
            scope, scan, list(scan.csharp_results), tmp_path
        )

        store.store(scope, stamp, rated_invocations, graph, execution_paths=None)
        store.store(scope, stamp, rated_invocations, graph, execution_paths=None)

        files = [p for p in root.iterdir() if p.is_file()]
        assert len(files) == 1
        loaded = store.load(scope)
        assert loaded is not None
        assert loaded.stamp == stamp


# --------------------------------------------------------------------- damage


def test_an_unreadable_stored_file_causes_a_derivation_instead_of_an_error(monkeypatch, tmp_path: Path) -> None:
    with RatedInvocationsRetention():
        scan = _scan(tmp_path)
        _wire(monkeypatch, scan, tmp_path, _graph("usp_Alpha"))
        calls = _count_real_rating_derivations(monkeypatch)

        analyze_service.find_by_sp(_sp_request())
        assert len(calls) == 1

        root = Path(analyze_service.settings.DERIVED_EXECUTION_EVIDENCE_STORE_ROOT)
        [only_file] = [p for p in root.iterdir() if p.is_file()]
        only_file.write_bytes(b"not a valid pickle stream at all")

        _simulate_restart()
        again = analyze_service.find_by_sp(_sp_request())

        assert len(calls) == 2  # the damaged file was treated as a miss, not an error
        assert [m.program for m in again.matches] == ["alphapage"]


def test_a_truncated_stored_file_causes_a_derivation_instead_of_an_error(monkeypatch, tmp_path: Path) -> None:
    with RatedInvocationsRetention():
        scan = _scan(tmp_path)
        _wire(monkeypatch, scan, tmp_path, _graph("usp_Alpha"))
        calls = _count_real_rating_derivations(monkeypatch)

        analyze_service.find_by_sp(_sp_request())
        assert len(calls) == 1

        root = Path(analyze_service.settings.DERIVED_EXECUTION_EVIDENCE_STORE_ROOT)
        [only_file] = [p for p in root.iterdir() if p.is_file()]
        truncated = only_file.read_bytes()[:5]
        only_file.write_bytes(truncated)

        _simulate_restart()
        again = analyze_service.find_by_sp(_sp_request())

        assert len(calls) == 2
        assert [m.program for m in again.matches] == ["alphapage"]


# ---------------------------------------------------------------- invalidation


def test_a_changed_repository_scan_causes_a_derivation_and_replaces_the_file(monkeypatch, tmp_path: Path) -> None:
    with RatedInvocationsRetention():
        first_scan = _scan(tmp_path)
        second_scan = _scan(tmp_path, alpha_calls="usp_Gamma")
        scans = [first_scan, second_scan]
        scan_saved_ats = ["scan-v1", "scan-v2"]
        cache_payload = {
            "database": "OrdersDb",
            "schema": "dbo",
            "sql_execution_graph": _graph("usp_Alpha", "usp_Gamma"),
        }
        monkeypatch.setattr(analyze_service, "resolve_scan_roots", lambda source, refresh=False: [tmp_path])
        monkeypatch.setattr(analyze_service, "_get_scan", lambda root, refresh=False: scans.pop(0))
        monkeypatch.setattr(analyze_service, "cached_saved_at", lambda root: scan_saved_ats.pop(0))
        monkeypatch.setattr(analyze_service, "cached_commit", lambda root: "commit-v1")
        monkeypatch.setattr(analyze_service.sql_cache_store, "load_cached", lambda database, schema, server="": cache_payload)
        monkeypatch.setattr(
            analyze_service.sql_cache_store, "cached_saved_at", lambda database, schema="dbo", server="": "sql-cache-v1"
        )
        calls = _count_real_rating_derivations(monkeypatch)
        root = Path(analyze_service.settings.DERIVED_EXECUTION_EVIDENCE_STORE_ROOT)

        before = analyze_service.find_by_sp(_sp_request())
        [file_before] = [p for p in root.iterdir() if p.is_file()]
        mtime_before = file_before.stat().st_mtime_ns

        _simulate_restart()
        after = analyze_service.find_by_sp(_sp_request())

        assert len(calls) == 2  # the scan change forced a fresh derivation, not a disk hit
        [file_after] = [p for p in root.iterdir() if p.is_file()]
        assert file_after == file_before  # same one file, replaced in place
        assert file_after.stat().st_mtime_ns >= mtime_before
        assert [m.program for m in before.matches] == ["alphapage"]
        assert after.matches == []  # AlphaPage now calls usp_Gamma, not usp_Alpha


def test_a_changed_sql_cache_causes_a_derivation(monkeypatch, tmp_path: Path) -> None:
    with RatedInvocationsRetention():
        scan = _scan(tmp_path)
        payloads = [
            {"database": "OrdersDb", "schema": "dbo", "sql_execution_graph": _graph("usp_Alpha")},
            {"database": "OrdersDb", "schema": "dbo", "sql_execution_graph": _graph()},  # usp_Alpha drops out
        ]
        sql_cache_saved_ats = ["sql-cache-v1", "sql-cache-v2"]
        monkeypatch.setattr(analyze_service, "resolve_scan_roots", lambda source, refresh=False: [tmp_path])
        monkeypatch.setattr(analyze_service, "_get_scan", lambda root, refresh=False: scan)
        monkeypatch.setattr(analyze_service, "cached_saved_at", lambda root: "scan-v1")
        monkeypatch.setattr(analyze_service, "cached_commit", lambda root: "commit-v1")
        monkeypatch.setattr(analyze_service.sql_cache_store, "load_cached", lambda database, schema, server="": payloads[0])
        monkeypatch.setattr(
            analyze_service.sql_cache_store,
            "cached_saved_at",
            lambda database, schema="dbo", server="": sql_cache_saved_ats[0],
        )
        calls = _count_real_rating_derivations(monkeypatch)

        before = analyze_service.find_by_sp(_sp_request())
        payloads.pop(0)
        sql_cache_saved_ats.pop(0)
        _simulate_restart()
        after = analyze_service.find_by_sp(_sp_request())

        assert len(calls) == 2
        assert [m.program for m in before.matches] == ["alphapage"]
        assert after.matches == []


def test_a_changed_external_wrapper_contract_causes_a_derivation(monkeypatch, tmp_path: Path) -> None:
    with RatedInvocationsRetention():
        scan = _scan(tmp_path)
        _wire(monkeypatch, scan, tmp_path, _graph("usp_Alpha"))
        monkeypatch.setattr(analyze_service, "load_external_wrapper_contract", lambda name: None)
        calls = _count_real_rating_derivations(monkeypatch)

        analyze_service.find_by_sp(_sp_request())
        monkeypatch.setattr(analyze_service, "load_external_wrapper_contract", lambda name: {"name": "changed"})
        _simulate_restart()
        analyze_service.find_by_sp(_sp_request())

        assert len(calls) == 2


def test_a_changed_contract_registry_causes_a_derivation(monkeypatch, tmp_path: Path) -> None:
    with RatedInvocationsRetention():
        scan = _scan(tmp_path)
        _wire(monkeypatch, scan, tmp_path, _graph("usp_Alpha"))
        monkeypatch.setattr(analyze_service, "load_contract_registry", lambda: {"contracts": {"a": {}}})
        calls = _count_real_rating_derivations(monkeypatch)

        analyze_service.find_by_sp(_sp_request())
        monkeypatch.setattr(analyze_service, "load_contract_registry", lambda: {"contracts": {"a": {}, "b": {}}})
        _simulate_restart()
        analyze_service.find_by_sp(_sp_request())

        assert len(calls) == 2


def test_a_changed_wrapper_review_exclusions_causes_a_derivation(monkeypatch, tmp_path: Path) -> None:
    with RatedInvocationsRetention():
        scan = _scan(tmp_path)
        _wire(monkeypatch, scan, tmp_path, _graph("usp_Alpha"))
        monkeypatch.setattr(analyze_service, "load_wrapper_review_exclusions", lambda system: ())
        calls = _count_real_rating_derivations(monkeypatch)

        analyze_service.find_by_sp(_sp_request())
        monkeypatch.setattr(
            analyze_service,
            "load_wrapper_review_exclusions",
            lambda system: ({"receiver_type": "x", "method_name": "y", "reason": "reviewed_non_wrapper_method"},),
        )
        _simulate_restart()
        analyze_service.find_by_sp(_sp_request())

        assert len(calls) == 2


# ----------------------------------------------------------------------- refresh


def test_an_explicit_refresh_ignores_a_valid_stored_file(monkeypatch, tmp_path: Path) -> None:
    with RatedInvocationsRetention():
        scan = _scan(tmp_path)
        _wire(monkeypatch, scan, tmp_path, _graph("usp_Alpha"))
        calls = _count_real_rating_derivations(monkeypatch)

        analyze_service.find_by_sp(_sp_request())
        assert len(calls) == 1

        _simulate_restart()
        analyze_service.find_by_sp(_sp_request(refresh=True))

        assert len(calls) == 2  # refresh derived again despite a valid file on disk


# ------------------------------------------------------------------- equivalence


def test_records_served_from_disk_are_identical_to_those_derived_in_memory(monkeypatch, tmp_path: Path) -> None:
    with RatedInvocationsRetention():
        scan = _scan(tmp_path)
        _wire(monkeypatch, scan, tmp_path, _graph("usp_Alpha"))

        in_memory = analyze_service.find_by_sp(_sp_request())
        _simulate_restart()
        from_disk = analyze_service.find_by_sp(_sp_request())

        assert [m.model_dump() for m in in_memory.matches] == [m.model_dump() for m in from_disk.matches]
