"""`CSharpParser.METHOD_PATTERN` takes a run of whitespace in one place.

It runs in linear time on a long run of whitespace, gives a method the line of
its declaration, and keeps its named groups.

`.scratch/rttalentdb-program-to-sql-chain/issues/17-...md`. Seam 1 is the
pattern with `re.finditer`. Seam 2 is `CSharpParser.parse_file`.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Optional, Tuple

import pytest

from code_analyzer.csharp_parser import CSharpParser
from code_analyzer.models import CodeLocation

_METHOD_GROUPS = ("access", "static", "virtual", "override", "abstract", "async", "ret", "name")


def _line(location: Optional[CodeLocation]) -> int:
    assert location is not None
    return location.line_number


def test_a_long_run_of_whitespace_takes_less_than_one_second() -> None:
    started = time.perf_counter()
    matches = list(re.finditer(CSharpParser.METHOD_PATTERN, " " * 20_000, re.MULTILINE))
    elapsed = time.perf_counter() - started

    assert matches == []
    assert elapsed < 1.0


def test_a_method_after_blank_lines_gets_the_line_of_its_declaration(
    tmp_path: Path,
) -> None:
    path = tmp_path / "A.cs"
    path.write_text(
        "class A {\n\n\n    void Foo() { }\n\n\n    static int Bar() { }\n"
        "    public void Baz() { }\n}",
        encoding="utf-8",
    )

    result = CSharpParser().parse_file(str(path))

    methods = {m.name: m for cls in result.classes for m in cls.methods}
    assert {name: _line(m.location) for name, m in methods.items()} == {
        "Foo": 4,
        "Bar": 7,
        "Baz": 8,
    }
    assert methods["Foo"].access_modifier == "private"
    assert methods["Bar"].is_static


@pytest.mark.parametrize(
    "source, groups",
    [
        (
            "    public void Save(int id)",
            ("public", None, None, None, None, None, "void", "Save"),
        ),
        (
            "  protected static virtual async Task Run()",
            ("protected", "static ", "virtual ", None, None, "async ", "Task", "Run"),
        ),
        (
            "public override string ToString()",
            ("public", None, None, "override ", None, None, "string", "ToString"),
        ),
        (
            "internal abstract int Count()",
            ("internal", None, None, None, "abstract ", None, "int", "Count"),
        ),
        (
            "public async Task<Dictionary<string, X>> LoadAsync()",
            (
                "public", None, None, None, None, "async ",
                "Task<Dictionary<string, X>>", "LoadAsync",
            ),
        ),
        (
            "private (bool Ok, string Msg) Check(int a)",
            ("private", None, None, None, None, None, "(bool Ok, string Msg)", "Check"),
        ),
        (
            "public T Get<T>(string key)",
            ("public", None, None, None, None, None, "T", "Get"),
        ),
        (
            "    int[]? Values()",
            (None, None, None, None, None, None, "int[]?", "Values"),
        ),
    ],
)
def test_a_declaration_gives_the_same_groups(
    source: str, groups: Tuple[Optional[str], ...]
) -> None:
    match = re.search(CSharpParser.METHOD_PATTERN, source, re.MULTILINE)

    assert match is not None
    assert match.group(*_METHOD_GROUPS) == groups
