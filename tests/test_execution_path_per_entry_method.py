"""One Execution Path for each entry method that reaches a database invocation (Impact #11).

A same-file caller chain goes from a root method (no other method of the file
calls it) to the sink method of a database invocation. Each root method gives
its own Execution Path. These tests call `evidence_for_scope`, the one entry
point of the Derived Execution Evidence, and read its Execution Paths.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List, Sequence, Tuple

import pytest

from code_analyzer.models import (
    CallSite,
    ClassInfo,
    FileAnalysisResult,
    FileType,
    FrameworkType,
    MethodInfo,
    MethodSourceSpan,
    SourceSnapshot,
)
from code_analyzer.project_scanner import ProjectScanResult
from service import derived_execution_evidence
from service.derived_execution_evidence import (
    DerivedExecutionEvidence,
    DerivedExecutionEvidenceScope,
    evidence_for_scope,
)
from service.execution_path_builder import build_compact_execution_path_payload
from tests.derived_execution_evidence_fixtures import RatedInvocationsRetention
from tests.sql_cache_fixtures import cache_payload, execution_graph, one_server_holds_every_database

_SINK_CALL = "ExecuteSave();"

# A method is (name, the names of the methods it calls). The sink method holds the call.
Methods = Sequence[Tuple[str, Sequence[str]]]


@pytest.fixture(autouse=True)
def _stores(monkeypatch):
    graph = execution_graph(
        "OrdersDb",
        nodes=[{"id": "stored_procedure:dbo.usp_SaveOrder", "type": "stored_procedure",
                "schema": "dbo", "name": "usp_SaveOrder"}],
    )
    module = derived_execution_evidence
    monkeypatch.setattr(module, "cached_saved_at", lambda root: "scan-v1")
    monkeypatch.setattr(module, "cached_commit", lambda root: "commit-v1")
    monkeypatch.setattr(module.sql_cache_store, "load_cached", lambda identity: cache_payload("OrdersDb", graph=graph))
    monkeypatch.setattr(module.sql_cache_store, "cached_saved_at", lambda identity: "sql-cache-v1")
    monkeypatch.setattr(module, "load_external_wrapper_contract", lambda name: None)
    monkeypatch.setattr(module, "load_contract_registry", lambda: {"contracts": {}})
    monkeypatch.setattr(module, "load_wrapper_review_exclusions", lambda database: ())
    with RatedInvocationsRetention():
        yield


def _content(methods: Methods, sink: str) -> str:
    bodies = []
    for name, calls in methods:
        lines = [f"        {call}();" for call in calls]
        if name == sink:
            lines.append(f"        {_SINK_CALL}")
        bodies.append(f"    public void {name}()\n    {{\n" + "\n".join(lines) + "\n    }")
    return "class OrderPage\n{\n" + "\n\n".join(bodies) + "\n}\n"


def _scan(root: Path, methods: Methods, sink: str, *, overload: str = "") -> ProjectScanResult:
    """One `OrderPage.cs` file. `overload` adds a second, unused method with that name.

    The snapshot gives each method a call graph node and each call its Bound Call
    Target, so a file with an overload follows the Bound Call Targets (ADR-0044).
    """
    content = _content(methods, sink)
    source_file = root / "OrderPage.cs"
    source_file.write_text(content, encoding="utf-8")
    node = {name: f"OrderPage.{name}()" for name, _ in methods}
    spans: List[MethodSourceSpan] = []
    for name, calls in methods:
        start = content.index(f"    public void {name}()")
        end = content.index("\n    }", start) + len("\n    }")
        sites = []
        for call in calls:
            call_start = content.index(f"{call}();", start)
            sites.append(CallSite(
                call_text=f"{call}()", start_offset=call_start, end_offset=call_start + len(call) + 2,
                target_class="OrderPage", target_method=call, target_node=node[call],
            ))
        spans.append(MethodSourceSpan(
            class_name="OrderPage", method_name=name, start_offset=start, end_offset=end,
            calls=sites, node=node[name],
        ))
    infos = [
        MethodInfo(name=name, access_modifier="public", return_type="void", calls=list(calls))
        for name, calls in methods
    ]
    if overload:
        infos.append(MethodInfo(name=overload, access_modifier="public", return_type="void"))
        spans.append(MethodSourceSpan(
            class_name="OrderPage", method_name=overload, start_offset=len(content), end_offset=len(content),
            node=f"OrderPage.{overload}(int)",
        ))
    call_start = content.index(_SINK_CALL)
    return ProjectScanResult(
        project_root=str(root),
        project_name="orders",
        scan_time=datetime.now(),
        csharp_results=[FileAnalysisResult(
            file_path=str(source_file), file_type=FileType.CSHARP, framework=FrameworkType.WEBFORMS,
            classes=[ClassInfo(name="OrderPage", namespace="", file_path=str(source_file), methods=infos)],
        )],
        source_snapshots={"OrderPage.cs": SourceSnapshot(
            relative_path="OrderPage.cs", content_hash="snapshot-hash", content=content, method_spans=spans,
        )},
        db_invocations={str(source_file.resolve()): [{
            "class_name": "OrderPage",
            "method_name": sink,
            "command_text_kind": "literal",
            "command_text": "dbo.usp_SaveOrder",
            "command_type_stored_procedure": True,
            "terminal_sink": "ExecuteNonQuery",
            "connection_expression": "conn",
            "start_offset": call_start,
            "end_offset": call_start + len(_SINK_CALL),
        }]},
        connection_sources={str(source_file.resolve()): {"conn": "OrdersDb"}},
    )


def _evidence(root: Path, methods: Methods, sink: str, **options) -> DerivedExecutionEvidence:
    scan = _scan(root, methods, sink, **options)
    scope = DerivedExecutionEvidenceScope(
        repo_roots=(str(root),), database="OrdersDb",
        sql_cache_identity=one_server_holds_every_database("OrdersDb"), db_name="", wrapper_contract="",
    )
    return evidence_for_scope(scope, [scan], scan, root, refresh=True)


def _chains(evidence: DerivedExecutionEvidence) -> List[List[str]]:
    return sorted(list(path["method_chain"]) for path in evidence.execution_paths())


_DELETE_AND_INSERT: Methods = [
    ("OnDeleteRow", ["DeleteRow"]),
    ("DeleteRow", ["Save"]),
    ("OnInsert", ["Save"]),
    ("Save", []),
]


def test_two_root_callers_of_different_lengths_give_two_paths(tmp_path: Path) -> None:
    evidence = _evidence(tmp_path, _DELETE_AND_INSERT, "Save")

    paths = evidence.execution_paths()
    assert _chains(evidence) == [["OnDeleteRow", "DeleteRow", "Save"], ["OnInsert", "Save"]]
    assert sorted(path["entry_method"] for path in paths) == ["OrderPage.OnDeleteRow", "OrderPage.OnInsert"]
    assert len({path["path_id"] for path in paths}) == 2


def test_three_root_callers_of_one_length_give_three_paths(tmp_path: Path) -> None:
    methods: Methods = [("OnLoad", ["Read"]), ("OnSearch", ["Read"]), ("OnExport", ["Read"]), ("Read", [])]

    evidence = _evidence(tmp_path, methods, "Read")

    assert _chains(evidence) == [["OnExport", "Read"], ["OnLoad", "Read"], ["OnSearch", "Read"]]
    assert len({path["path_id"] for path in evidence.execution_paths()}) == 3


def test_a_part_of_a_longer_chain_gives_no_path_of_its_own(tmp_path: Path) -> None:
    evidence = _evidence(tmp_path, _DELETE_AND_INSERT, "Save")

    assert [chain for chain in _chains(evidence) if chain[0] == "DeleteRow"] == []


def test_a_file_with_overloads_gives_the_entry_methods_of_a_file_without_overloads(tmp_path: Path) -> None:
    plain_root = tmp_path / "plain"
    overload_root = tmp_path / "overload"
    plain_root.mkdir()
    overload_root.mkdir()

    plain = _evidence(plain_root, _DELETE_AND_INSERT, "Save")
    with_overload = _evidence(overload_root, _DELETE_AND_INSERT, "Save", overload="DeleteRow")

    assert _chains(with_overload) == _chains(plain)
    assert sorted(invocation.method_node_chain for invocation in with_overload.rated_invocations) == [
        ("OrderPage.OnDeleteRow()", "OrderPage.DeleteRow()", "OrderPage.Save()"),
        ("OrderPage.OnInsert()", "OrderPage.Save()"),
    ]


def test_the_compact_counts_include_the_extra_paths(tmp_path: Path) -> None:
    methods: Methods = [("OnLoad", ["Read"]), ("OnSearch", ["Read"]), ("OnExport", ["Read"]), ("Read", [])]
    evidence = _evidence(tmp_path, methods, "Read")

    payload = build_compact_execution_path_payload(evidence.execution_paths(), max_paths=2)

    assert (payload["total_paths"], payload["returned_paths"], payload["omitted_paths"]) == (3, 2, 1)
    assert len(payload["paths"]) == 2


def test_a_new_entry_method_keeps_the_path_id_of_the_existing_path(tmp_path: Path) -> None:
    """`OnInsert` comes after the sink method, so the call keeps its offsets in both files."""
    before_root = tmp_path / "before"
    after_root = tmp_path / "after"
    before_root.mkdir()
    after_root.mkdir()
    before_methods: Methods = [("OnDeleteRow", ["DeleteRow"]), ("DeleteRow", ["Save"]), ("Save", [])]

    before = _evidence(before_root, before_methods, "Save").execution_paths()
    after = _evidence(after_root, [*before_methods, ("OnInsert", ["Save"])], "Save").execution_paths()

    assert [path["entry_method"] for path in before] == ["OrderPage.OnDeleteRow"]
    after_by_entry = {path["entry_method"]: path["path_id"] for path in after}
    assert after_by_entry["OrderPage.OnDeleteRow"] == before[0]["path_id"]
    assert after_by_entry["OrderPage.OnInsert"] != before[0]["path_id"]
