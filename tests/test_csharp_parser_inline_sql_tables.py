"""Seam 5: the C# parser reads the tables of inline SQL in a source file.

`.scratch/canonical-object-identity/` ticket 04 adds this case with today's
output. The parser converts the SQL text to upper case, its patterns capture two
name parts at most, and a filter then drops `DBO` as a schema name. So
`PUR.dbo.Users` disappears, `[COMMON].[AVM]` loses its schema, and `Orders`
reads as `ORDERS`. Step 2a's extraction commit changes the expected values, and
that change is the proof of the behaviour change.
"""

from __future__ import annotations

from pathlib import Path

from code_analyzer.csharp_parser import CSharpParser


def test_inline_sql_tables_keep_todays_bare_upper_case_names(tmp_path: Path) -> None:
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

    assert [query.tables for query in result.sql_queries] == [{"AVM", "ORDERS"}]
