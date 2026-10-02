"""The Derived Execution Evidence module, tested at its one entry point.

These tests call `derived_execution_evidence.evidence_for_scope` with the real
in-memory retention and an isolated disk folder (`RatedInvocationsRetention`).
They do not patch the rating step and do not read the retention.

A test sees which copy served a request by its content. The first request
rates scan A, where AlphaPage calls usp_Alpha. A later request gives scan B,
where AlphaPage calls usp_Gamma, with the same recorded scan state. Retained
evidence still names usp_Alpha; a new derivation names usp_Gamma.

Before this module existed, these tests drove `find_by_sp()` and
`find_by_table()` and counted calls to a patched rating step
(derived-execution-evidence-reuse tickets 03 to 05, table-reverse-lookup-cost
tickets 05 to 07).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List, Optional

import pytest

from code_analyzer.models import ClassInfo, FileAnalysisResult, FileType, FrameworkType, MethodInfo
from code_analyzer.project_scanner import ProjectScanResult
from service import derived_execution_evidence
from service import derived_execution_evidence_store as store
from service.derived_execution_evidence import (
    DerivedExecutionEvidence,
    DerivedExecutionEvidenceScope,
    evidence_for_scope,
)
from service.execution_path_builder import build_execution_paths
from service.sql_execution_graph import GRAPH_VERSION
from tests.derived_execution_evidence_fixtures import RatedInvocationsRetention
from tests.sql_cache_fixtures import cache_payload, execution_graph, one_server_holds_every_database


def _graph(*procedure_names: str) -> dict:
    return execution_graph(
        "OrdersDb",
        nodes=[
            {"id": f"stored_procedure:dbo.{name}", "type": "stored_procedure", "schema": "dbo", "name": name}
            for name in procedure_names
        ],
    )


_ALL_PROCEDURES = ("usp_Alpha", "usp_Beta", "usp_Gamma")


def _file(root: Path, program: str = "Alpha") -> FileAnalysisResult:
    path = root / f"{program}Page.cs"
    return FileAnalysisResult(
        file_path=str(path),
        file_type=FileType.CSHARP,
        framework=FrameworkType.WEBFORMS,
        classes=[
            ClassInfo(
                name=f"{program}Page",
                namespace="",
                file_path=str(path),
                methods=[MethodInfo(name=f"Save{program}", access_modifier="private", return_type="void")],
            )
        ],
    )


def _raw_call(program: str, procedure: str) -> dict:
    return {
        "class_name": f"{program}Page",
        "method_name": f"Save{program}",
        "command_text_kind": "literal",
        "command_text": f"dbo.{procedure}",
        "command_type_stored_procedure": True,
        "terminal_sink": "ExecuteNonQuery",
        "connection_expression": "conn",
        "start_offset": 10,
        "end_offset": 90,
    }


def _scan(root: Path, alpha_calls: str = "usp_Alpha", *, beta_calls: str = "") -> ProjectScanResult:
    """One repository scan with one program that calls one stored procedure.

    With `beta_calls`, a second program BetaPage calls that stored procedure.
    """
    calls = {"Alpha": alpha_calls, **({"Beta": beta_calls} if beta_calls else {})}
    files = {program: str((root / f"{program}Page.cs").resolve()) for program in calls}
    return ProjectScanResult(
        project_root=str(root),
        project_name="orders",
        scan_time=datetime.now(),
        csharp_results=[_file(root, program) for program in calls],
        db_invocations={files[program]: [_raw_call(program, procedure)] for program, procedure in calls.items()},
        connection_sources={file: {"conn": "OrdersDb"} for file in files.values()},
    )


class _Inputs:
    """The recorded state of every stamp input. A test changes it in place.

    Production reads the recorded save time of the scan and of the SQL cache
    from disk (table-reverse-lookup-cost ticket 05), apart from the in-memory
    objects. A fixed stub value keeps the stamp equal across requests until a
    test changes it.
    """

    def __init__(self, monkeypatch) -> None:
        self.scan_saved_at = "scan-v1"
        self.scan_commit: Optional[str] = "commit-v1"
        self.sql_cache_saved_at = "sql-cache-v1"
        self.payload = cache_payload("OrdersDb", graph=_graph(*_ALL_PROCEDURES))
        self.external_wrapper_contract: Optional[dict] = None
        self.contract_registry: dict = {"contracts": {}}
        self.wrapper_review_exclusions: tuple = ()
        module = derived_execution_evidence
        monkeypatch.setattr(module, "cached_saved_at", lambda root: self.scan_saved_at)
        monkeypatch.setattr(module, "cached_commit", lambda root: self.scan_commit)
        monkeypatch.setattr(module.sql_cache_store, "load_cached", lambda identity: self.payload)
        monkeypatch.setattr(module.sql_cache_store, "cached_saved_at", lambda identity: self.sql_cache_saved_at)
        monkeypatch.setattr(module, "load_external_wrapper_contract", lambda name: self.external_wrapper_contract)
        monkeypatch.setattr(module, "load_contract_registry", lambda: self.contract_registry)
        monkeypatch.setattr(module, "load_wrapper_review_exclusions", lambda database: self.wrapper_review_exclusions)


def _scope(root: Path, database: str = "OrdersDb") -> DerivedExecutionEvidenceScope:
    return DerivedExecutionEvidenceScope(
        repo_roots=(str(root),),
        database=database,
        sql_cache_identity=one_server_holds_every_database(database),
        db_name="",
        wrapper_contract="",
    )


def _evidence(
    root: Path,
    alpha_calls: str = "usp_Alpha",
    *,
    beta_calls: str = "",
    needed: Optional[List[str]] = None,
    database: str = "OrdersDb",
    refresh: bool = False,
) -> DerivedExecutionEvidence:
    """The evidence of one request. `needed` names the programs whose files the request needs."""
    scan = _scan(root, alpha_calls, beta_calls=beta_calls)
    needed_files = (
        None
        if needed is None
        else [result for result in scan.csharp_results if Path(result.file_path).stem in needed]
    )
    return evidence_for_scope(
        _scope(root, database), [scan], scan, root, needed_files=needed_files, refresh=refresh
    )


def _procedures(evidence: DerivedExecutionEvidence) -> List[str]:
    return [invocation.executed_procedure_name for invocation in evidence.rated_invocations]


def _path_procedures(evidence: DerivedExecutionEvidence) -> List[str]:
    return [str(path["procedure_name"]).rsplit(".", 1)[-1] for path in evidence.execution_paths()]


@pytest.fixture
def retention():
    with RatedInvocationsRetention() as isolated:
        yield isolated


@pytest.fixture
def inputs(monkeypatch, retention) -> _Inputs:
    return _Inputs(monkeypatch)


def _forbid_path_builds(monkeypatch) -> None:
    def fail(*args, **kwargs):
        raise AssertionError("the Execution Paths were built again")

    monkeypatch.setattr(derived_execution_evidence, "build_execution_paths_by_invocation", fail)


# ----------------------------------------------------------------------- reuse


def test_a_second_request_in_one_scope_gets_the_retained_evidence(inputs, tmp_path: Path) -> None:
    first = _evidence(tmp_path, "usp_Alpha")
    second = _evidence(tmp_path, "usp_Gamma")  # a new scan object, the same recorded state

    assert _procedures(first) == ["usp_alpha"]
    assert _procedures(second) == ["usp_alpha"]


def test_a_second_request_in_one_scope_does_not_build_the_paths_again(
    monkeypatch, inputs, tmp_path: Path
) -> None:
    first_paths = _path_procedures(_evidence(tmp_path))
    _forbid_path_builds(monkeypatch)

    assert _path_procedures(_evidence(tmp_path)) == first_paths == ["usp_alpha"]


def test_a_new_sql_cache_object_with_the_same_recorded_state_gets_the_retained_evidence(
    inputs, tmp_path: Path
) -> None:
    _evidence(tmp_path)
    inputs.payload = cache_payload("OrdersDb", graph=_graph())  # a new dict, the same save time

    assert _procedures(_evidence(tmp_path, "usp_Gamma")) == ["usp_alpha"]


# ---------------------------------------------------------------- invalidation


def _change_scan_save_time(inputs: _Inputs) -> None:
    inputs.scan_saved_at = "scan-v2"


def _change_scan_commit(inputs: _Inputs) -> None:
    inputs.scan_commit = "commit-v2"


def _change_sql_cache_save_time(inputs: _Inputs) -> None:
    inputs.sql_cache_saved_at = "sql-cache-v2"


def _rebuild_the_graph(inputs: _Inputs) -> None:
    # The repair tool rewrites the graph and leaves the save time alone.
    inputs.payload = cache_payload(
        "OrdersDb", graph=dict(_graph(*_ALL_PROCEDURES), graph_version=GRAPH_VERSION + 1)
    )


def _change_external_wrapper_contract(inputs: _Inputs) -> None:
    inputs.external_wrapper_contract = {"name": "changed"}


def _change_contract_registry(inputs: _Inputs) -> None:
    inputs.contract_registry = {"contracts": {"b": {}}}


def _change_wrapper_review_exclusions(inputs: _Inputs) -> None:
    inputs.wrapper_review_exclusions = (
        {"receiver_type": "x", "method_name": "y", "reason": "reviewed_non_wrapper_method"},
    )


_INPUT_CHANGES = [
    _change_scan_save_time,
    _change_scan_commit,
    _change_sql_cache_save_time,
    _rebuild_the_graph,
    _change_external_wrapper_contract,
    _change_contract_registry,
    _change_wrapper_review_exclusions,
]


@pytest.mark.parametrize("change", _INPUT_CHANGES, ids=lambda change: change.__name__.lstrip("_"))
@pytest.mark.parametrize("restart", [False, True], ids=["in_memory", "after_restart"])
def test_a_changed_input_causes_a_new_derivation(
    change, restart: bool, inputs, retention, tmp_path: Path
) -> None:
    _evidence(tmp_path, "usp_Alpha")
    change(inputs)
    if restart:
        retention.simulate_restart()

    assert _procedures(_evidence(tmp_path, "usp_Gamma")) == ["usp_gamma"]


def test_a_new_derivation_builds_new_paths(inputs, tmp_path: Path) -> None:
    assert _path_procedures(_evidence(tmp_path, "usp_Alpha")) == ["usp_alpha"]
    _change_scan_save_time(inputs)

    assert _path_procedures(_evidence(tmp_path, "usp_Gamma")) == ["usp_gamma"]


# --------------------------------------------------------------------- refresh


def test_refresh_skips_the_memory_copy(inputs, tmp_path: Path) -> None:
    _evidence(tmp_path, "usp_Alpha")

    assert _procedures(_evidence(tmp_path, "usp_Gamma", refresh=True)) == ["usp_gamma"]


def test_refresh_builds_the_paths_again(inputs, tmp_path: Path) -> None:
    assert _path_procedures(_evidence(tmp_path, "usp_Alpha")) == ["usp_alpha"]

    assert _path_procedures(_evidence(tmp_path, "usp_Gamma", refresh=True)) == ["usp_gamma"]


def test_refresh_skips_the_disk_copy(inputs, retention, tmp_path: Path) -> None:
    _evidence(tmp_path, "usp_Alpha")
    retention.simulate_restart()

    assert _procedures(_evidence(tmp_path, "usp_Gamma", refresh=True)) == ["usp_gamma"]


def test_refresh_replaces_the_retained_evidence(inputs, tmp_path: Path) -> None:
    _evidence(tmp_path, "usp_Alpha")
    _evidence(tmp_path, "usp_Gamma", refresh=True)

    assert _procedures(_evidence(tmp_path, "usp_Alpha")) == ["usp_gamma"]


# ------------------------------------------------------------------------ disk


def test_a_scope_derived_in_one_process_is_served_from_disk_in_the_next(
    inputs, retention, tmp_path: Path
) -> None:
    in_memory = _evidence(tmp_path, "usp_Alpha")
    retention.simulate_restart()
    from_disk = _evidence(tmp_path, "usp_Gamma")

    assert _procedures(from_disk) == ["usp_alpha"]
    assert from_disk.rated_invocations == in_memory.rated_invocations


def test_execution_paths_survive_a_restart(monkeypatch, inputs, retention, tmp_path: Path) -> None:
    built = _path_procedures(_evidence(tmp_path))
    retention.simulate_restart()
    _forbid_path_builds(monkeypatch)

    assert _path_procedures(_evidence(tmp_path)) == built


def test_paths_built_after_a_disk_hit_are_written_to_disk(monkeypatch, inputs, retention, tmp_path: Path) -> None:
    """A scope that answered only rating questions gets its paths on disk later."""
    _evidence(tmp_path)
    retention.simulate_restart()
    built = _path_procedures(_evidence(tmp_path))  # a disk hit with no paths yet
    retention.simulate_restart()
    _forbid_path_builds(monkeypatch)

    assert _path_procedures(_evidence(tmp_path)) == built


def test_each_scope_occupies_one_file_replaced_in_place(inputs, retention, tmp_path: Path) -> None:
    for _ in range(3):
        _evidence(tmp_path, refresh=True)

    assert len([p for p in retention.store_root.iterdir() if p.is_file()]) == 1


def test_no_temp_file_survives_a_successful_write(inputs, retention, tmp_path: Path) -> None:
    _evidence(tmp_path)

    entries = list(retention.store_root.iterdir())
    assert len(entries) == 1
    assert "tmp-" not in entries[0].name


def test_a_failed_write_leaves_no_temp_file_and_the_previous_file_intact(
    monkeypatch, inputs, retention, tmp_path: Path
) -> None:
    _evidence(tmp_path, "usp_Alpha")
    before = {p.name: p.read_bytes() for p in retention.store_root.iterdir()}

    def failing_dump(*args, **kwargs):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(store.pickle, "dump", failing_dump)
    _change_scan_save_time(inputs)
    answered = _evidence(tmp_path, "usp_Gamma")

    assert _procedures(answered) == ["usp_gamma"]  # the request still gets its answer
    assert {p.name: p.read_bytes() for p in retention.store_root.iterdir()} == before


def test_two_equal_writes_of_one_scope_leave_one_valid_file(inputs, retention, tmp_path: Path) -> None:
    """No lock is taken: two derivations of one new scope both write, and the
    second `os.replace` overwrites the first with an equal result."""
    evidence = _evidence(tmp_path)
    scope = _scope(tmp_path)
    stamp = store.load(scope).stamp

    store.store(scope, stamp, evidence.rated_invocations, evidence.graph, paths_by_invocation=None)
    store.store(scope, stamp, evidence.rated_invocations, evidence.graph, paths_by_invocation=None)

    assert len([p for p in retention.store_root.iterdir() if p.is_file()]) == 1
    assert store.load(scope).stamp == stamp


@pytest.mark.parametrize(
    "damage",
    [lambda data: b"not a valid pickle stream at all", lambda data: data[:5]],
    ids=["unreadable", "truncated"],
)
def test_a_damaged_file_counts_as_a_miss(damage, inputs, retention, tmp_path: Path) -> None:
    _evidence(tmp_path, "usp_Alpha")
    [only_file] = [p for p in retention.store_root.iterdir() if p.is_file()]
    only_file.write_bytes(damage(only_file.read_bytes()))
    retention.simulate_restart()

    assert _procedures(_evidence(tmp_path, "usp_Gamma")) == ["usp_gamma"]


def test_a_file_of_the_previous_format_version_counts_as_a_miss(inputs, retention, tmp_path: Path) -> None:
    """Version 5 keeps the paths per invocation. A version 4 file holds one flat list."""
    _evidence(tmp_path, "usp_Alpha")
    [only_file] = [p for p in retention.store_root.iterdir() if p.is_file()]
    stored = store.pickle.loads(only_file.read_bytes())
    stored.store_version = 4
    only_file.write_bytes(store.pickle.dumps(stored))
    retention.simulate_restart()

    assert _procedures(_evidence(tmp_path, "usp_Gamma")) == ["usp_gamma"]


# ---------------------------------------------------------------- needed files


def test_a_miss_with_needed_files_rates_those_files_only(inputs, tmp_path: Path) -> None:
    evidence = _evidence(tmp_path, "usp_Alpha", beta_calls="usp_Beta", needed=["BetaPage"])

    assert _procedures(evidence) == ["usp_beta"]


def test_a_partial_miss_leaves_the_retention_and_the_disk_folder_empty(
    inputs, retention, tmp_path: Path
) -> None:
    partial = _evidence(tmp_path, "usp_Alpha", beta_calls="usp_Beta", needed=["AlphaPage"])
    partial.execution_paths()  # building paths must not write either

    assert list(retention.store_root.iterdir()) == []
    # Nothing in memory: a full request with new content derives again.
    assert _procedures(_evidence(tmp_path, "usp_Gamma", beta_calls="usp_Beta")) == [
        "usp_gamma",
        "usp_beta",
    ]


def test_a_hit_with_needed_files_gets_the_retained_evidence_of_the_whole_scope(
    inputs, tmp_path: Path
) -> None:
    _evidence(tmp_path, "usp_Alpha", beta_calls="usp_Beta")

    hit = _evidence(tmp_path, "usp_Gamma", beta_calls="usp_Beta", needed=["BetaPage"])

    assert _procedures(hit) == ["usp_alpha", "usp_beta"]


def test_a_disk_hit_with_needed_files_gets_the_evidence_of_the_whole_scope(
    inputs, retention, tmp_path: Path
) -> None:
    _evidence(tmp_path, "usp_Alpha", beta_calls="usp_Beta")
    retention.simulate_restart()

    hit = _evidence(tmp_path, "usp_Gamma", beta_calls="usp_Beta", needed=["BetaPage"])

    assert _procedures(hit) == ["usp_alpha", "usp_beta"]


# ------------------------------------------------------- paths per invocation


def _procedure_of(path: dict) -> str:
    return str(path["procedure_name"]).rsplit(".", 1)[-1]


def test_the_paths_of_given_invocations_are_the_paths_of_those_invocations_only(
    inputs, tmp_path: Path
) -> None:
    evidence = _evidence(tmp_path, "usp_Alpha", beta_calls="usp_Beta")
    beta = [i for i in evidence.rated_invocations if i.executed_procedure_name == "usp_beta"]

    assert [_procedure_of(path) for path in evidence.paths_of(beta)] == ["usp_beta"]


def test_the_paths_of_the_scope_equal_one_build_over_every_invocation(inputs, tmp_path: Path) -> None:
    evidence = _evidence(tmp_path, "usp_Alpha", beta_calls="usp_Beta")
    evidence.paths_of(evidence.rated_invocations[1:])  # one invocation built first

    assert evidence.execution_paths() == build_execution_paths(evidence.rated_invocations, evidence.graph)


def test_the_paths_of_an_invocation_are_built_one_time(monkeypatch, inputs, tmp_path: Path) -> None:
    evidence = _evidence(tmp_path, "usp_Alpha", beta_calls="usp_Beta")
    first = evidence.paths_of(evidence.rated_invocations)
    _forbid_path_builds(monkeypatch)

    assert evidence.paths_of(evidence.rated_invocations) == first


def test_a_path_id_gives_its_path_and_the_invocation_that_produced_it(inputs, tmp_path: Path) -> None:
    evidence = _evidence(tmp_path, "usp_Alpha", beta_calls="usp_Beta")
    beta = [i for i in evidence.rated_invocations if i.executed_procedure_name == "usp_beta"]
    [beta_path] = build_execution_paths(beta, evidence.graph)

    found = evidence.path_by_id(str(beta_path["path_id"]))

    assert found == (beta_path, beta[0])


def test_a_path_id_gives_nothing_when_its_invocation_is_not_selected(inputs, tmp_path: Path) -> None:
    evidence = _evidence(tmp_path, "usp_Alpha")
    [path] = evidence.execution_paths()

    assert evidence.path_by_id(str(path["path_id"]), produced_by=lambda invocation: False) is None


def test_an_unknown_path_id_gives_nothing(inputs, tmp_path: Path) -> None:
    evidence = _evidence(tmp_path, "usp_Alpha")

    assert evidence.path_by_id("no-such-path") is None


def test_the_paths_found_by_path_id_survive_a_restart(monkeypatch, inputs, retention, tmp_path: Path) -> None:
    built = _evidence(tmp_path, "usp_Alpha", beta_calls="usp_Beta").execution_paths()
    retention.simulate_restart()
    _forbid_path_builds(monkeypatch)

    found = _evidence(tmp_path, "usp_Alpha", beta_calls="usp_Beta").path_by_id(str(built[0]["path_id"]))

    assert found is not None
    assert found[0] == built[0]


# -------------------------------------------------------------------- eviction


def _evicted(printed: str) -> List[str]:
    """The databases that the eviction messages name as evicted, in order."""
    return [
        line.split("evicted database=", 1)[1].split(" ", 1)[0].strip("'")
        for line in printed.splitlines()
        if "已達上限" in line
    ]


def test_exceeding_the_bound_evicts_the_oldest_scope_and_prints_it(
    monkeypatch, inputs, tmp_path: Path, capsys
) -> None:
    monkeypatch.setattr(derived_execution_evidence.settings, "DERIVED_EXECUTION_EVIDENCE_RETENTION_LIMIT", 2)
    capsys.readouterr()
    for database in ("Db1", "Db2", "Db3"):
        _evidence(tmp_path, database=database)

    assert _evicted(capsys.readouterr().out) == ["Db1"]


def test_a_served_scope_is_evicted_last(monkeypatch, inputs, tmp_path: Path, capsys) -> None:
    """Least-recently-used, not first-in-first-out (table-reverse-lookup-cost ticket 07)."""
    monkeypatch.setattr(derived_execution_evidence.settings, "DERIVED_EXECUTION_EVIDENCE_RETENTION_LIMIT", 2)
    capsys.readouterr()
    for database in ("Db1", "Db2", "Db1", "Db3", "Db1", "Db4"):
        _evidence(tmp_path, database=database)

    assert _evicted(capsys.readouterr().out) == ["Db2", "Db3"]


def test_a_scope_evicted_from_memory_is_served_from_disk(monkeypatch, inputs, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(derived_execution_evidence.settings, "DERIVED_EXECUTION_EVIDENCE_RETENTION_LIMIT", 1)
    _evidence(tmp_path, "usp_Alpha", database="Db1")
    _evidence(tmp_path, "usp_Alpha", database="Db2")
    assert _evicted(capsys.readouterr().out) == ["Db1"]

    assert _procedures(_evidence(tmp_path, "usp_Gamma", database="Db1")) == ["usp_alpha"]


# ----------------------------------------------------------- fixture isolation


def test_the_retention_fixture_isolates_memory_and_disk(inputs, tmp_path: Path) -> None:
    """A test's retained evidence does not leak into the next test, and an
    entry from outside the test does not leak into it."""
    _evidence(tmp_path, "usp_Alpha")  # the entry from outside the inner fixture

    with RatedInvocationsRetention():
        assert _procedures(_evidence(tmp_path, "usp_Gamma")) == ["usp_gamma"]

    # The inner fixture restores the entry from outside it.
    assert _procedures(_evidence(tmp_path, "usp_Gamma")) == ["usp_alpha"]
