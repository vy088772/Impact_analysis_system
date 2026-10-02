"""Seam 2: `/find_by_table` reports the reason and the access type of an inline table relation.

Each case builds a C# Scan Result with table relations and asks `find_by_table`.
"""

from __future__ import annotations

from dataclasses import replace

from canonical_object_identity import ObjectName
from code_analyzer.project_scanner import INLINE_SQL_PARSED, INLINE_SQL_REGEX
from service import analyze_service
from service.schemas import FindByTableRequest
from service.request_context_adapters import InMemoryCacheStore
from tests.request_context_fixtures import RequestStores
from tests.test_table_match import _inline_scan


def _ask(monkeypatch, tmp_path, scan, table_name: str, write_only: bool = False):
    stores = RequestStores.of(tmp_path, scan)
    return analyze_service.find_by_table(
        FindByTableRequest(
            source={"project": "orders", "repo": "orders"},
            table_name=table_name,
            cache_only=False,
            write_only=write_only,
        ),
        scan_store=stores.scan_store, cache_store=InMemoryCacheStore(),
    )


def test_a_record_carries_the_reason_of_its_relation(monkeypatch, tmp_path) -> None:
    scan = _inline_scan(tmp_path, ObjectName("", "", "dbo", "Orders"), "Response")
    parsed = replace(scan.table_relations[0], access_type="UPDATE", reason=INLINE_SQL_PARSED)
    regex = replace(
        parsed,
        csharp_file=str(tmp_path / "RegexPage.cs"),
        access_type="UNRESOLVED",
        reason=INLINE_SQL_REGEX,
    )
    scan.table_relations[:] = [parsed, regex]

    answer = _ask(monkeypatch, tmp_path, scan, "dbo.Orders")

    assert [(match.file, match.reason, match.access_type) for match in answer.matches] == [
        ("InlinePage.cs", INLINE_SQL_PARSED, "UPDATE"),
        ("RegexPage.cs", INLINE_SQL_REGEX, "UNRESOLVED"),
    ]


def test_write_only_does_not_report_a_program_that_only_reads_the_table_in_an_update_from_join(
    monkeypatch, tmp_path
) -> None:
    """`UPDATE t ... FROM t JOIN u` writes `t` and reads `u`: each table has its own access type."""
    scan = _inline_scan(tmp_path, ObjectName("", "", "dbo", "T"), "Response")
    written = replace(scan.table_relations[0], access_type="UPDATE", reason=INLINE_SQL_PARSED)
    read = replace(written, table=ObjectName("", "", "dbo", "U"), access_type="SELECT")
    scan.table_relations[:] = [written, read]

    writers_of_t = _ask(monkeypatch, tmp_path, scan, "dbo.T", write_only=True)
    writers_of_u = _ask(monkeypatch, tmp_path, scan, "dbo.U", write_only=True)

    assert [(match.file, match.access_type) for match in writers_of_t.matches] == [("InlinePage.cs", "UPDATE")]
    assert writers_of_u.matches == []
    assert writers_of_u.excluded_count == 1
