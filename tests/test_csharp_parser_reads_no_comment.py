"""The C# parser reads no SQL from a C# comment.

`.scratch/inline-sql-tables-come-from-the-parser/` ticket 09. Seam 1 is
`CSharpParser.parse_file`. Seam 2 is `strip_csharp_comments` on its own.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pytest

from code_analyzer.csharp_parser import CSharpParser, strip_csharp_comments
from code_analyzer.models import CodeLocation


def _parse(tmp_path: Path, body: str):
    source = (
        "namespace Orders.Pages\n"
        "{\n"
        "    public class OrderPage\n"
        "    {\n"
        "        public void LoadData()\n"
        "        {\n"
        f"{body}"
        "        }\n"
        "    }\n"
        "}\n"
    )
    path = tmp_path / "OrderPage.cs"
    path.write_text(source, encoding="utf-8")
    return CSharpParser().parse_file(str(path))


def _line(location: Optional[CodeLocation]) -> int:
    assert location is not None
    return location.line_number


def _table_names(result) -> set:
    return {table.name for query in result.sql_queries for table in query.tables}


def test_a_line_comment_gives_no_sql_query(tmp_path: Path) -> None:
    result = _parse(
        tmp_path,
        '            // db.CreateReader("select a from T where x = 1");\n',
    )

    assert result.sql_queries == []


def test_a_slash_pair_inside_a_string_is_not_a_comment(tmp_path: Path) -> None:
    result = _parse(
        tmp_path,
        '            string url = "http://host/x"; var r = db.CreateReader("select a from Orders where y = 2");\n',
    )

    assert _table_names(result) == {"Orders"}
    assert [_line(query.location) for query in result.sql_queries] == [7]


def test_a_block_comment_over_several_lines_gives_no_sql_query(tmp_path: Path) -> None:
    result = _parse(
        tmp_path,
        '            /* objPUR.CreateReader("select a, b from Blocked where x = 1");\n'
        '               objPUR.CreateReader("select a from Hidden where x = 1"); */\n'
        '            var r = db.CreateReader("select a from Orders where y = 2");\n',
    )

    assert _table_names(result) == {"Orders"}
    assert [_line(query.location) for query in result.sql_queries] == [9]


def test_a_commented_out_stored_procedure_call_gives_no_call(tmp_path: Path) -> None:
    result = _parse(
        tmp_path,
        '            // new SqlCommand("usp_Commented_Out", cn);\n'
        '            // SqlCommand old = new SqlCommand("usp_Old_Call", cn);\n'
        '            SqlCommand cmd = new SqlCommand("usp_Live_Call", cn);\n'
        "            cmd.CommandType = CommandType.StoredProcedure;\n",
    )

    assert [call.procedure_name for call in result.stored_procedure_calls] == ["usp_Live_Call"]


def test_a_commented_out_class_is_not_a_class_of_the_result(tmp_path: Path) -> None:
    path = tmp_path / "Pages.cs"
    path.write_text(
        "namespace Orders.Pages\n"
        "{\n"
        "    // public class OldPage { public void Load() { } }\n"
        "    /*\n"
        "    public class RetiredPage\n"
        "    {\n"
        "        public void Load() { }\n"
        "    }\n"
        "    */\n"
        "    public class OrderPage\n"
        "    {\n"
        "        public void Load() { }\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )

    result = CSharpParser().parse_file(str(path))

    assert [cls.name for cls in result.classes] == ["OrderPage"]
    assert [_line(cls.location) for cls in result.classes] == [10]


_LITERALS = (
    "            char quote = '\"';\n"
    "            char tick = '\\'';\n"
    "            char slash = '/';\n"
    '            var a = db.CreateReader(@"select a -- note // not a comment\n'
    '                from Verbatim where ""x"" = 1");\n'
    '            var b = db.CreateReader($"select {x} from Interpolated where y = 2 // tail");\n'
    '            var c = db.CreateReader($@"select {x} from Both where y = 3 /* tail */");\n'
    '            var c2 = db.CreateReader(@$"select {{x}} from Swapped where y = {Fmt(\'"\')} // tail");\n'
    '            var d = db.CreateReader("""select a from Raw where z = \'//\' and q = "x" """);\n'
    '            var e = db.CreateReader("select a from Escaped where w = \\"/*\\"");\n'
)
_GHOST = '            // db.CreateReader("select a from Ghost where g = 1");\n'


def test_a_comment_mark_inside_a_literal_is_text() -> None:
    source = _LITERALS + _GHOST

    assert strip_csharp_comments(source) == _LITERALS + _blanked(_GHOST)


def test_a_comment_after_the_literals_gives_no_table_and_the_literals_keep_theirs(
    tmp_path: Path,
) -> None:
    result = _parse(tmp_path, _LITERALS + _GHOST)

    names = _table_names(result)
    assert "Ghost" not in names
    # The fallback misses `Interpolated` with or without the comment removal.
    assert {"Verbatim", "Both", "Raw", "Escaped"} <= names
    texts = [query.query_text for query in result.sql_queries]
    assert any("-- note // not a comment" in text for text in texts)
    assert any("/* tail */" in text for text in texts)


def _blanked(text: str) -> str:
    return "".join(ch if ch in "\r\n" else " " for ch in text)


_INPUTS = {
    "line": 'a = 1; // b = "x";\r\nc = 2;\r\n',
    "block": "a /* one\r\n two */ b\n",
    "doc": "/// <summary>Load the page.</summary>\nvoid Load() { }\n",
    "literals": _LITERALS + _GHOST,
    "directive": "#region Don't touch\nvar a = 1; // note\n#endregion\n",
    "unclosed block": "a = 1; /* never closed\nb = 2;\n",
    "unclosed string": 'a = "never closed\nb = 2; // note\n',
    "raw interpolated": 'var s = $$"""{{x}} // text"""; // note\n',
}


@pytest.mark.parametrize("name", sorted(_INPUTS))
def test_the_removal_keeps_the_length_and_each_line_break(name: str) -> None:
    source = _INPUTS[name]

    stripped = strip_csharp_comments(source)

    assert len(stripped) == len(source)
    assert [i for i, ch in enumerate(stripped) if ch in "\r\n"] == [
        i for i, ch in enumerate(source) if ch in "\r\n"
    ]


def test_each_comment_form_becomes_spaces() -> None:
    assert strip_csharp_comments(_INPUTS["line"]) == "a = 1;            \r\nc = 2;\r\n"
    assert strip_csharp_comments(_INPUTS["block"]) == "a       \r\n        b\n"
    assert strip_csharp_comments(_INPUTS["doc"]) == _blanked(
        "/// <summary>Load the page.</summary>"
    ) + "\nvoid Load() { }\n"
    assert strip_csharp_comments(_INPUTS["directive"]) == (
        "#region Don't touch\nvar a = 1;        \n#endregion\n"
    )
    assert strip_csharp_comments(_INPUTS["raw interpolated"]) == (
        'var s = $$"""{{x}} // text""";        \n'
    )


@pytest.mark.parametrize("name", ["unclosed block", "unclosed string"])
def test_a_construct_without_a_certain_end_keeps_the_rest_of_the_text(name: str) -> None:
    source = _INPUTS[name]

    assert strip_csharp_comments(source) == source


def test_the_comment_line_count_reads_the_original_lines(tmp_path: Path) -> None:
    result = _parse(
        tmp_path,
        "            // one\n"
        "            /* two\n"
        "               three */\n"
        "            var r = 1;\n",
    )

    assert (result.code_line_count, result.comment_line_count, result.blank_line_count) == (
        10,
        3,
        0,
    )


_ATV_PAGE = (
    Path(__file__).resolve().parent.parent
    / "data/repos/System_Dept_1/Y-DOCs/ATV/PO_ManifastUploadV3.aspx.cs"
)


@pytest.mark.skipif(not _ATV_PAGE.exists(), reason="the ATV checkout is local data")
def test_the_atv_upload_page_gives_no_commented_out_insert() -> None:
    result = CSharpParser().parse_file(str(_ATV_PAGE))

    assert "ManifestNew" not in _table_names(result)
    assert ("usp_PO_ManifaseUpload_AddData", 122) in {
        (call.procedure_name, _line(call.location))
        for call in result.stored_procedure_calls
    }
