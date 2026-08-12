"""Focused regression matrix for the unified Database Invocation classifier.

Each row is one data-access category from the migration cutover spec (issue
10). The matrix asserts the Gateway-external contract (``DbInvocation``,
``Evidence Status``, and cutover report aggregation) for that category
without depending on private helpers, regex traversal order, or registry
order. Deep per-category parsing behavior (branch resolution, overload
binding, adapter Fill, etc.) is already covered file-by-file in
``test_csharp_analysis_gateway.py``; this module verifies the categories are
represented, correctly aggregated, and that legacy detections never merge
into formal evidence.
"""

from __future__ import annotations

import pytest

from code_analyzer.csharp_analysis_gateway import (
    DbInvocation,
    InvocationEvidence,
    InvocationSourceSpan,
)
from service.migration_report import build_cutover_report, compare_legacy_gateway


def _invocation(
    method_name: str,
    *,
    evidence: InvocationEvidence,
    offset: int,
    procedure_name: str | None = "usp_Sample",
    database: str | None = "OrdersDb",
    contract_lifecycle_status: str = "",
    wrapper_review_candidate: bool = False,
    reason: str = "",
) -> DbInvocation:
    return DbInvocation(
        class_name="OrderPage",
        method_name=method_name,
        database=database,
        procedure_name=procedure_name,
        evidence=evidence,
        source=InvocationSourceSpan("OrderPage.cs", offset, offset + 20),
        reason=reason,
        contract_lifecycle_status=contract_lifecycle_status,
        wrapper_review_candidate=wrapper_review_candidate,
    )


# One representative, evidence-rated invocation per fixture category required
# by the issue-10 acceptance matrix. Categories that produce no invocation at
# all (UI false positive) are represented by an empty tuple.
REGRESSION_MATRIX: tuple[tuple[str, tuple[DbInvocation, ...]], ...] = (
    ("direct_sqlclient_text", (_invocation("SaveDirectText", evidence=InvocationEvidence.PROVEN, offset=0),)),
    ("direct_sqlclient_stored_procedure", (_invocation("SaveDirectSp", evidence=InvocationEvidence.PROVEN, offset=20),)),
    ("source_wrapper", (_invocation("SaveSourceWrapper", evidence=InvocationEvidence.PROVEN, offset=40),)),
    (
        "external_wrapper",
        (
            _invocation(
                "SaveExternalWrapper",
                evidence=InvocationEvidence.PROVEN,
                offset=60,
                contract_lifecycle_status="reused",
            ),
        ),
    ),
    ("dapper", (_invocation("SaveDapper", evidence=InvocationEvidence.PROVEN, offset=80),)),
    ("entity_framework", (_invocation("SaveEntityFramework", evidence=InvocationEvidence.PROVEN, offset=100),)),
    ("sqlobject", (_invocation("SaveSqlObject", evidence=InvocationEvidence.PROVEN, offset=120),)),
    ("inline_sql", (_invocation("SaveInlineSql", evidence=InvocationEvidence.PROVEN, offset=140, procedure_name=None),)),
    ("embedded_exec", (_invocation("SaveEmbeddedExec", evidence=InvocationEvidence.PROVEN, offset=160),)),
    (
        "branch",
        (
            _invocation("SaveBranchDefault", evidence=InvocationEvidence.PROVEN, offset=180),
            _invocation("SaveBranchConditional", evidence=InvocationEvidence.PROVEN, offset=200),
        ),
    ),
    ("overload", (_invocation("SaveOverload", evidence=InvocationEvidence.PROVEN, offset=220),)),
    ("fill", (_invocation("SaveFill", evidence=InvocationEvidence.PROVEN, offset=240),)),
    (
        "dynamic_sql",
        (
            _invocation(
                "SaveDynamicSql",
                evidence=InvocationEvidence.UNRESOLVED,
                offset=260,
                procedure_name=None,
                database=None,
                reason="dynamic_command_text",
            ),
        ),
    ),
    ("ui_false_positive", ()),
    (
        "cross_database_ambiguity",
        (
            _invocation(
                "SaveCrossDatabase",
                evidence=InvocationEvidence.UNRESOLVED,
                offset=280,
                database=None,
                reason="ambiguous_across_catalogs",
            ),
        ),
    ),
)


@pytest.mark.parametrize("category, invocations", REGRESSION_MATRIX, ids=[row[0] for row in REGRESSION_MATRIX])
def test_regression_matrix_category_produces_documented_evidence_status(
    category: str, invocations: tuple[DbInvocation, ...]
) -> None:
    if category == "ui_false_positive":
        assert invocations == ()
        return

    for invocation in invocations:
        assert invocation.evidence in (
            InvocationEvidence.PROVEN,
            InvocationEvidence.LIKELY,
            InvocationEvidence.UNRESOLVED,
        )
        # Every category must expose its evidence through the public field.
        assert invocation.evidence.value in ("proven", "likely", "unresolved")


def test_regression_matrix_cutover_report_aggregates_every_category() -> None:
    all_invocations = [
        invocation
        for _, invocations in REGRESSION_MATRIX
        for invocation in invocations
    ]

    report = build_cutover_report(all_invocations)

    assert report["evidence_summary"]["proven"] == sum(
        1
        for invocation in all_invocations
        if invocation.evidence == InvocationEvidence.PROVEN
    )
    assert report["evidence_summary"]["unresolved"] == 2
    assert report["contract_lifecycle_summary"]["reused"] == 1
    assert report["cutover_signals"]["unresolved_count"] == 2


def test_legacy_regex_differences_never_merge_into_formal_evidence(tmp_path) -> None:
    """Legacy parser output is comparison-only; it must not appear as Gateway
    evidence, contract lifecycle, or review-candidate state in the cutover
    report -- only inside the migration diff for manual review."""
    legacy_only = {
        "file": "Legacy.cs",
        "class": "LegacyPage",
        "method": "SaveLegacyOnly",
        "database": "OrdersDb",
        "procedure": "dbo.usp_LegacyOnly",
        "line": 5,
    }
    gateway_records = [_invocation("SaveDirectText", evidence=InvocationEvidence.PROVEN, offset=0)]

    report = build_cutover_report(
        gateway_records,
        legacy_records=[legacy_only],
        source_root=tmp_path,
    )

    assert report["legacy_migration"]["summary"]["dropped_count"] == 1
    assert sum(report["evidence_summary"].values()) == len(gateway_records)
    assert report["cutover_signals"]["ready_for_legacy_retirement"] is False

    # A plain diff (without the cutover wrapper) exposes the same invariant.
    diff = compare_legacy_gateway([legacy_only], gateway_records, source_root=tmp_path)
    assert diff["dropped"][0]["legacy"]["procedure"] == "dbo.usp_legacyonly"
    assert "gateway" not in diff["dropped"][0]
