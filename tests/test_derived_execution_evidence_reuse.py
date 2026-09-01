"""Ticket 04: find_by_sp() rates the repository's C# facts once per scope, not
once per request.

Prior art for the seam and the counting style: tests/test_graph_reverse_lookup.py
drives find_by_sp() directly with fixture scans/graphs; tests/test_locate_object.py
proves work did *not* happen by making the expensive step fail if it runs again.
Here the expensive step (`analyze_service._rated_execution_invocations`, the
rating step named in ADR-0013) is wrapped with a counter instead of made to
fail outright, because some of these tests need it to run exactly twice.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from code_analyzer.csharp_analysis_gateway import DbInvocation, InvocationEvidence, InvocationSourceSpan
from code_analyzer.models import ClassInfo, FileAnalysisResult, FileType, FrameworkType, MethodInfo
from code_analyzer.project_scanner import ProjectScanResult
from service import analyze_service
from service.schemas import FindBySPRequest
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


def _file(root: Path, name: str, class_name: str, method_name: str) -> FileAnalysisResult:
    path = root / name
    return FileAnalysisResult(
        file_path=str(path),
        file_type=FileType.CSHARP,
        framework=FrameworkType.WEBFORMS,
        classes=[
            ClassInfo(
                name=class_name,
                namespace="",
                file_path=str(path),
                methods=[MethodInfo(name=method_name, access_modifier="private", return_type="void")],
            )
        ],
    )


def _scan(root: Path, *, alpha_calls: str = "usp_Alpha", beta_calls: str = "usp_Beta") -> ProjectScanResult:
    """One repository scan with two programs, each calling one stored procedure."""
    alpha = _file(root, "AlphaPage.cs", "AlphaPage", "SaveAlpha")
    beta = _file(root, "BetaPage.cs", "BetaPage", "SaveBeta")
    raw = {
        str((root / name).resolve()): [
            {
                "class_name": class_name,
                "method_name": method_name,
                "command_text_kind": "literal",
                "command_text": procedure,
                "command_type_stored_procedure": True,
                "terminal_sink": "ExecuteNonQuery",
                "connection_expression": "conn",
                "start_offset": 10,
                "end_offset": 90,
            }
        ]
        for name, class_name, method_name, procedure in (
            ("AlphaPage.cs", "AlphaPage", "SaveAlpha", f"dbo.{alpha_calls}"),
            ("BetaPage.cs", "BetaPage", "SaveBeta", f"dbo.{beta_calls}"),
        )
    }
    return ProjectScanResult(
        project_root=str(root),
        project_name="orders",
        scan_time=datetime.now(),
        csharp_results=[alpha, beta],
        db_invocations=raw,
        connection_sources={
            str((root / name).resolve()): {"conn": "OrdersDb"} for name in ("AlphaPage.cs", "BetaPage.cs")
        },
    )


def _wire(monkeypatch, scan: ProjectScanResult, tmp_path: Path, graph: dict) -> None:
    """Wire scan/cache lookups so repeated calls see the *same* objects.

    `sql_cache_store.load_cached()` hands back one stable object from its
    in-memory cache in production until a refresh replaces it; a stub that
    built a fresh dict on every call would make the SQL cache side of the
    validity stamp look changed on every single request, defeating reuse for
    a reason unrelated to whatever a test is isolating. The payload is built
    once, outside the lambda, so its identity stays fixed across calls.
    """
    cache_payload = {"database": "OrdersDb", "schema": "dbo", "sql_execution_graph": graph}
    monkeypatch.setattr(analyze_service, "resolve_scan_roots", lambda source, refresh=False: [tmp_path])
    monkeypatch.setattr(analyze_service, "_get_scan", lambda root, refresh=False: scan)
    monkeypatch.setattr(
        analyze_service.sql_cache_store,
        "load_cached",
        lambda database, schema, server="": cache_payload,
    )


def _request(sp_name: str, *, refresh: bool = False) -> FindBySPRequest:
    return FindBySPRequest(
        source={"project": "orders", "repo": "orders"},
        sp_name=sp_name,
        database="OrdersDb",
        cache_only=False,
        refresh=refresh,
    )


def _count_real_derivations(monkeypatch) -> list:
    """Wrap the real rating step with a counter, still calling through to it."""
    calls: list = []
    real = analyze_service._rated_execution_invocations

    def counting(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(analyze_service, "_rated_execution_invocations", counting)
    return calls


def _install_config_dependent_fake_rating(monkeypatch, config_reader) -> list:
    """Replace the rating step with one whose single PROVEN match's procedure
    name is read live from `config_reader()` at call time.

    This stands in for CSharpAnalysisGateway's own configuration-dependent
    rating rules (covered by that module's own tests, not this one): what
    this ticket's retention/freshness layer must get right is noticing that
    one of the three configuration reads moved and re-deriving -- and having
    the *response* actually change is how a reviewer can tell the freshness
    check ran for real, rather than merely counting internal calls.
    """
    calls: list = []

    def fake(scope, scan, matched_files, root):
        calls.append(1)
        invocation = DbInvocation(
            class_name="AlphaPage",
            method_name="SaveAlpha",
            database="OrdersDb",
            procedure_name=config_reader(),
            evidence=InvocationEvidence.PROVEN,
            source=InvocationSourceSpan(relative_path="AlphaPage.cs", start_offset=10, end_offset=90),
            command_text_literal="",
        )
        return [invocation], {}

    monkeypatch.setattr(analyze_service, "_rated_execution_invocations", fake)
    return calls


# --------------------------------------------------------------- reuse itself


def test_two_consecutive_lookups_in_one_scope_rate_the_facts_once(monkeypatch, tmp_path: Path) -> None:
    with RatedInvocationsRetention():
        scan = _scan(tmp_path)
        _wire(monkeypatch, scan, tmp_path, _graph("usp_Alpha", "usp_Beta"))
        calls = _count_real_derivations(monkeypatch)

        first = analyze_service.find_by_sp(_request("dbo.usp_Alpha"))
        second = analyze_service.find_by_sp(_request("dbo.usp_Alpha"))

        assert len(calls) == 1
        assert [(m.program, m.file) for m in first.matches] == [(m.program, m.file) for m in second.matches]


def test_two_different_sp_names_in_one_scope_still_rate_the_facts_once(monkeypatch, tmp_path: Path) -> None:
    """The rating step does not depend on which SP was asked about (ADR-0013)."""
    with RatedInvocationsRetention():
        scan = _scan(tmp_path)
        _wire(monkeypatch, scan, tmp_path, _graph("usp_Alpha", "usp_Beta"))
        calls = _count_real_derivations(monkeypatch)

        alpha_response = analyze_service.find_by_sp(_request("dbo.usp_Alpha"))
        beta_response = analyze_service.find_by_sp(_request("dbo.usp_Beta"))

        assert len(calls) == 1
        assert [m.program for m in alpha_response.matches] == ["alphapage"]
        assert [m.program for m in beta_response.matches] == ["betapage"]


# ------------------------------------------------------------------- equivalence


def test_answer_identical_with_reuse_active_and_defeated_for_a_match(monkeypatch, tmp_path: Path) -> None:
    with RatedInvocationsRetention():
        scan = _scan(tmp_path)
        _wire(monkeypatch, scan, tmp_path, _graph("usp_Alpha", "usp_Beta"))

        analyze_service.find_by_sp(_request("dbo.usp_Alpha"))
        reused = analyze_service.find_by_sp(_request("dbo.usp_Alpha"))

        analyze_service._rated_invocations_retention.clear()  # defeat reuse
        analyze_service.find_by_sp(_request("dbo.usp_Alpha"))
        fresh = analyze_service.find_by_sp(_request("dbo.usp_Alpha"))

        assert [(m.program, m.file) for m in reused.matches] == [(m.program, m.file) for m in fresh.matches]


def test_answer_identical_with_reuse_active_and_defeated_for_no_match(monkeypatch, tmp_path: Path) -> None:
    with RatedInvocationsRetention():
        scan = _scan(tmp_path)
        _wire(monkeypatch, scan, tmp_path, _graph("usp_Alpha", "usp_Beta"))

        analyze_service.find_by_sp(_request("dbo.usp_Missing"))
        reused = analyze_service.find_by_sp(_request("dbo.usp_Missing"))

        analyze_service._rated_invocations_retention.clear()  # defeat reuse
        analyze_service.find_by_sp(_request("dbo.usp_Missing"))
        fresh = analyze_service.find_by_sp(_request("dbo.usp_Missing"))

        assert reused.matches == [] == fresh.matches


# --------------------------------------------------------------- invalidation


def test_a_changed_repository_scan_causes_a_fresh_derivation(monkeypatch, tmp_path: Path) -> None:
    with RatedInvocationsRetention():
        first_scan = _scan(tmp_path)
        second_scan = _scan(tmp_path, alpha_calls="usp_Gamma")
        scans = [first_scan, second_scan]
        cache_payload = {
            "database": "OrdersDb",
            "schema": "dbo",
            "sql_execution_graph": _graph("usp_Alpha", "usp_Beta", "usp_Gamma"),
        }
        monkeypatch.setattr(analyze_service, "resolve_scan_roots", lambda source, refresh=False: [tmp_path])
        monkeypatch.setattr(analyze_service, "_get_scan", lambda root, refresh=False: scans.pop(0))
        monkeypatch.setattr(analyze_service.sql_cache_store, "load_cached", lambda database, schema, server="": cache_payload)
        calls = _count_real_derivations(monkeypatch)

        before = analyze_service.find_by_sp(_request("dbo.usp_Alpha"))
        after = analyze_service.find_by_sp(_request("dbo.usp_Alpha"))

        assert len(calls) == 2
        assert [m.program for m in before.matches] == ["alphapage"]
        assert after.matches == []  # AlphaPage now calls usp_Gamma, not usp_Alpha


def test_a_changed_sql_cache_causes_a_fresh_derivation(monkeypatch, tmp_path: Path) -> None:
    with RatedInvocationsRetention():
        scan = _scan(tmp_path)
        payloads = [
            {"database": "OrdersDb", "schema": "dbo", "sql_execution_graph": _graph("usp_Alpha", "usp_Beta")},
            {"database": "OrdersDb", "schema": "dbo", "sql_execution_graph": _graph("usp_Beta")},  # usp_Alpha drops out
        ]
        monkeypatch.setattr(analyze_service, "resolve_scan_roots", lambda source, refresh=False: [tmp_path])
        monkeypatch.setattr(analyze_service, "_get_scan", lambda root, refresh=False: scan)
        monkeypatch.setattr(analyze_service.sql_cache_store, "load_cached", lambda database, schema, server="": payloads[0])
        calls = _count_real_derivations(monkeypatch)

        before = analyze_service.find_by_sp(_request("dbo.usp_Alpha"))
        payloads.pop(0)
        after = analyze_service.find_by_sp(_request("dbo.usp_Alpha"))

        assert len(calls) == 2
        assert [m.program for m in before.matches] == ["alphapage"]
        assert after.matches == []


def test_a_changed_external_wrapper_contract_causes_a_fresh_derivation(monkeypatch, tmp_path: Path) -> None:
    with RatedInvocationsRetention():
        scan = _scan(tmp_path)
        _wire(monkeypatch, scan, tmp_path, _graph("usp_Alpha", "usp_Beta"))
        monkeypatch.setattr(analyze_service, "load_external_wrapper_contract", lambda name: None)
        calls = _install_config_dependent_fake_rating(
            monkeypatch,
            config_reader=lambda: (
                "dbo.usp_Alpha"
                if analyze_service.load_external_wrapper_contract("x") is None
                else "dbo.usp_Beta"
            ),
        )

        before = analyze_service.find_by_sp(_request("dbo.usp_Alpha"))
        monkeypatch.setattr(analyze_service, "load_external_wrapper_contract", lambda name: {"name": "changed"})
        after = analyze_service.find_by_sp(_request("dbo.usp_Alpha"))

        assert len(calls) == 2
        assert [m.program for m in before.matches] == ["alphapage"]
        assert after.matches == []  # the fake's rating now reports usp_Beta instead


def test_a_changed_contract_registry_causes_a_fresh_derivation(monkeypatch, tmp_path: Path) -> None:
    with RatedInvocationsRetention():
        scan = _scan(tmp_path)
        _wire(monkeypatch, scan, tmp_path, _graph("usp_Alpha", "usp_Beta"))
        monkeypatch.setattr(analyze_service, "load_contract_registry", lambda: {"contracts": {"a": {}}})
        calls = _install_config_dependent_fake_rating(
            monkeypatch,
            config_reader=lambda: (
                "dbo.usp_Alpha"
                if "b" not in analyze_service.load_contract_registry().get("contracts", {})
                else "dbo.usp_Beta"
            ),
        )

        before = analyze_service.find_by_sp(_request("dbo.usp_Alpha"))
        monkeypatch.setattr(analyze_service, "load_contract_registry", lambda: {"contracts": {"a": {}, "b": {}}})
        after = analyze_service.find_by_sp(_request("dbo.usp_Alpha"))

        assert len(calls) == 2
        assert [m.program for m in before.matches] == ["alphapage"]
        assert after.matches == []


def test_a_changed_wrapper_review_exclusions_causes_a_fresh_derivation(monkeypatch, tmp_path: Path) -> None:
    with RatedInvocationsRetention():
        scan = _scan(tmp_path)
        _wire(monkeypatch, scan, tmp_path, _graph("usp_Alpha", "usp_Beta"))
        monkeypatch.setattr(analyze_service, "load_wrapper_review_exclusions", lambda system: ())
        calls = _install_config_dependent_fake_rating(
            monkeypatch,
            config_reader=lambda: (
                "dbo.usp_Alpha"
                if not analyze_service.load_wrapper_review_exclusions("OrdersDb")
                else "dbo.usp_Beta"
            ),
        )

        before = analyze_service.find_by_sp(_request("dbo.usp_Alpha"))
        monkeypatch.setattr(
            analyze_service,
            "load_wrapper_review_exclusions",
            lambda system: ({"receiver_type": "x", "method_name": "y", "reason": "reviewed_non_wrapper_method"},),
        )
        after = analyze_service.find_by_sp(_request("dbo.usp_Alpha"))

        assert len(calls) == 2
        assert [m.program for m in before.matches] == ["alphapage"]
        assert after.matches == []


def test_an_explicit_refresh_always_derives_again(monkeypatch, tmp_path: Path) -> None:
    with RatedInvocationsRetention():
        scan = _scan(tmp_path)
        _wire(monkeypatch, scan, tmp_path, _graph("usp_Alpha", "usp_Beta"))
        calls = _count_real_derivations(monkeypatch)

        analyze_service.find_by_sp(_request("dbo.usp_Alpha"))
        analyze_service.find_by_sp(_request("dbo.usp_Alpha", refresh=True))
        analyze_service.find_by_sp(_request("dbo.usp_Alpha", refresh=True))

        assert len(calls) == 3


# ------------------------------------------------------------ retained-state isolation


def test_retention_fixture_snapshots_and_restores_around_a_test() -> None:
    """Mirrors sql_cache_fixtures.CacheRoot: a test's retained entries must not
    leak into the next test, and a pre-existing entry from outside the test
    must not leak into it either."""
    scope = analyze_service.DerivedExecutionEvidenceScope(
        repo_roots=("preexisting",), database="Db", db_server="", db_name="", wrapper_contract=""
    )
    stamp = analyze_service._RatedInvocationsValidityStamp(
        scan_identity=(1,),
        sql_cache_identity=None,
        external_wrapper_contract=None,
        contract_registry={},
        wrapper_review_exclusions=(),
    )
    analyze_service._rated_invocations_retention[scope] = analyze_service._RetainedRatedInvocations(stamp, [], {})

    with RatedInvocationsRetention() as retention:
        assert scope not in retention  # cleared on entry, not visible inside the test
        other_scope = analyze_service.DerivedExecutionEvidenceScope(
            repo_roots=("during-test",), database="Db", db_server="", db_name="", wrapper_contract=""
        )
        retention[other_scope] = analyze_service._RetainedRatedInvocations(stamp, [], {})

    # restored: the pre-existing entry is back, the test's own entry is gone
    assert list(analyze_service._rated_invocations_retention.keys()) == [scope]
    del analyze_service._rated_invocations_retention[scope]
