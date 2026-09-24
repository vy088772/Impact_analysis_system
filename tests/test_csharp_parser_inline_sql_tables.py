"""Seam 5: the C# parser reads the tables of inline SQL in a source file.

`.scratch/canonical-object-identity/` ticket 04 added this case with the old
output, `{"AVM", "ORDERS"}`. The parser converted the SQL text to upper case,
its patterns captured two name parts at most, and a filter then dropped `DBO` as
a schema name. Ticket 07 changes the expected values: each table keeps its
database, its schema, and its written case.
"""

from __future__ import annotations

from pathlib import Path

from canonical_object_identity import ObjectName
from code_analyzer.csharp_parser import CSharpParser


def test_inline_sql_tables_keep_every_stated_part_in_the_written_case(tmp_path: Path) -> None:
    source = '''
namespace Orders.Pages
{
    public class OrderPage
    {
        public void LoadData()
        {
            string sql = "SELECT u.Id FROM PUR.dbo.Users u JOIN [COMMON].[AVM] a ON a.Id = u.Id JOIN Orders o ON o.Id = u.Id";
        }
    }
}
'''
    path = tmp_path / "OrderPage.cs"
    path.write_text(source, encoding="utf-8")

    result = CSharpParser().parse_file(str(path))

    assert [query.tables for query in result.sql_queries] == [
        {
            ObjectName(server="", database="PUR", schema="dbo", name="Users"),
            ObjectName(server="", database="", schema="COMMON", name="AVM"),
            ObjectName(server="", database="", schema="", name="Orders"),
        }
    ]


def test_a_rowset_function_after_from_is_not_a_table(tmp_path: Path) -> None:
    source = '''
namespace Orders.Pages
{
    public class OrderPage
    {
        public void LoadData()
        {
            string sql = "SELECT q.Id FROM OPENQUERY(LNK, 'SELECT 1') q JOIN OPENJSON(@json) j ON j.Id = q.Id";
        }
    }
}
'''
    path = tmp_path / "OrderPage.cs"
    path.write_text(source, encoding="utf-8")

    result = CSharpParser().parse_file(str(path))

    assert [query.tables for query in result.sql_queries] == [set()]
