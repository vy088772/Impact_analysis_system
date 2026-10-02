"""Seam 2: a parsed inline table relation takes its Database from its rated Database Invocation.

Each case builds a C# Scan Result with one table relation, gives `find_by_table` the rated
Database Invocations that the rating step would return, and reads the match record.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Optional, Sequence

from canonical_object_identity import ObjectName
from code_analyzer.csharp_analysis_gateway import (
    DbInvocation,
    InvocationEvidence,
    InvocationSourceSpan,
)
from code_analyzer.project_scanner import (
    INLINE_SQL_PARSED,
    INLINE_SQL_REGEX,
    UNRESOLVED_CONNECTION_DATABASE,
)
from service import analyze_service
from service.derived_execution_evidence import DerivedExecutionEvidence
from service.schemas import FindByTableRequest
from service.request_context_adapters import InMemoryCacheStore
from tests.request_context_fixtures import RequestStores
from tests.test_table_match import _inline_scan

SPAN = (154, 310)


def _invocation(
    database: Optional[str],
    candidates: Sequence[str] = (),
    *,
    span: tuple[int, int] = SPAN,
    path: str = "InlinePage.cs",
) -> DbInvocation:
    return DbInvocation(
        class_name="InlinePage",
        method_name="Load",
        database=database,
        procedure_name=None,
        evidence=InvocationEvidence.PROVEN if database else InvocationEvidence.UNRESOLVED,
        source=InvocationSourceSpan(path, span[0], span[1]),
        database_candidates=tuple(candidates),
    )


def _parsed_scan(tmp_path, *, stored_database: str = "Response", access_type: str = "SELECT"):
    scan = _inline_scan(tmp_path, ObjectName("", "", "dbo", "Orders"), stored_database)
    scan.table_relations[:] = [
        replace(
            scan.table_relations[0],
            access_type=access_type,
            reason=INLINE_SQL_PARSED,
            invocation_span=SPAN,
        )
    ]
    return scan


def _ask(
    monkeypatch,
    tmp_path,
    scan,
    invocations: Sequence[DbInvocation],
    *,
    database: str = "",
    write_only: bool = False,
):
    rated_for: list[str] = []

    def rated(scope, scans, merged, root, *, refresh=False):
        rated_for.append(scope.database)
        return DerivedExecutionEvidence(list(invocations), {}, paths_by_invocation=[[] for _ in invocations])

    stores = RequestStores.of(tmp_path, scan)
    monkeypatch.setattr(analyze_service, "_require_sql_execution_graph", lambda name, server="", **_: (None, {}))
    monkeypatch.setattr(analyze_service, "filter_table_accesses", lambda *args, **kwargs: [])
    response = analyze_service.find_by_table(
        FindByTableRequest(
            source={"project": "orders", "repo": "orders"},
            table_name="dbo.Orders",
            database=database,
            cache_only=False,
            write_only=write_only,
        ),
        evidence_source=rated,
        scan_store=stores.scan_store, cache_store=InMemoryCacheStore(),
    )
    return response, rated_for


def test_a_parsed_relation_takes_the_database_its_invocation_resolves_to(monkeypatch, tmp_path) -> None:
    scan = _parsed_scan(tmp_path)

    response, _ = _ask(monkeypatch, tmp_path, scan, [_invocation("PUR")], database="PUR")

    (match,) = response.matches
    assert (match.database, match.database_attribution) == ("PUR", "resolved")


def test_a_parsed_relation_with_candidates_matches_a_question_on_any_database(monkeypatch, tmp_path) -> None:
    scan = _parsed_scan(tmp_path)

    response, _ = _ask(monkeypatch, tmp_path, scan, [_invocation(None, ("PUR", "STC"))], database="ETON")

    (match,) = response.matches
    assert match.database_attribution == "candidate"
    assert list(match.database_candidates) == ["PUR", "STC"]


def test_a_parsed_relation_with_an_unresolved_invocation_matches_a_question_on_any_database(
    monkeypatch, tmp_path
) -> None:
    scan = _parsed_scan(tmp_path)

    response, _ = _ask(monkeypatch, tmp_path, scan, [_invocation(None)], database="ETON")

    (match,) = response.matches
    assert match.database_attribution == "unresolved"
    assert list(match.database_candidates) == []


def test_a_parsed_write_stays_a_not_applicable_write_when_its_database_is_not_resolved(
    monkeypatch, tmp_path
) -> None:
    scan = _parsed_scan(tmp_path, access_type="UPDATE")

    response, _ = _ask(
        monkeypatch, tmp_path, scan, [_invocation(None, ("PUR", "STC"))], database="ETON", write_only=True
    )

    (match,) = response.matches
    assert (match.access_type, match.evidence_status) == ("UPDATE", "not_applicable")
    assert response.excluded_count == 0


def test_a_parsed_relation_with_no_database_in_the_request_takes_the_stored_database(
    monkeypatch, tmp_path
) -> None:
    resolved = _parsed_scan(tmp_path, stored_database="Response")
    unresolved = _parsed_scan(tmp_path, stored_database=UNRESOLVED_CONNECTION_DATABASE)

    answer_resolved, rated_resolved = _ask(monkeypatch, tmp_path, resolved, [_invocation("PUR")])
    answer_unresolved, _ = _ask(monkeypatch, tmp_path, unresolved, [_invocation("PUR")])

    assert [(m.database, m.database_attribution) for m in answer_resolved.matches] == [("Response", "resolved")]
    assert [(m.database, m.database_attribution) for m in answer_unresolved.matches] == [("", "unresolved")]
    assert rated_resolved == []


def test_a_parsed_relation_whose_span_no_invocation_has_takes_the_stored_database(monkeypatch, tmp_path) -> None:
    scan = _parsed_scan(tmp_path, stored_database="Response")
    other_span = _invocation("PUR", span=(1, 2))
    other_file = _invocation("PUR", path="Other.cs")

    response, _ = _ask(monkeypatch, tmp_path, scan, [other_span, other_file], database="Response")

    assert [(m.database, m.database_attribution) for m in response.matches] == [("Response", "resolved")]


def test_a_fallback_relation_keeps_the_database_the_parser_finds(monkeypatch, tmp_path) -> None:
    scan = _parsed_scan(tmp_path, stored_database="Response")
    scan.table_relations[:] = [
        replace(scan.table_relations[0], reason=INLINE_SQL_REGEX, access_type="UNRESOLVED", invocation_span=())
    ]

    response, _ = _ask(monkeypatch, tmp_path, scan, [_invocation("PUR")], database="Response")

    assert [(m.database, m.database_attribution) for m in response.matches] == [("Response", "resolved")]


def test_a_parsed_relation_whose_invocation_resolves_to_another_database_does_not_match(
    monkeypatch, tmp_path
) -> None:
    scan = _parsed_scan(tmp_path)

    response, _ = _ask(monkeypatch, tmp_path, scan, [_invocation("PUR")], database="ETON")

    assert response.matches == []


def test_a_parsed_relation_whose_span_no_invocation_has_is_unresolved_when_the_stored_database_is(
    monkeypatch, tmp_path
) -> None:
    scan = _parsed_scan(tmp_path, stored_database=UNRESOLVED_CONNECTION_DATABASE)

    response, _ = _ask(monkeypatch, tmp_path, scan, [_invocation("PUR", span=(1, 2))], database="ETON")

    assert [(m.database, m.database_attribution) for m in response.matches] == [("", "unresolved")]
