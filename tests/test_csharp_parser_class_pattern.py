"""`CSharpParser.CLASS_PATTERN` starts a match at a keyword, not at whitespace.

It runs in linear time on a long run of whitespace, gives a class the line of
its declaration, and keeps its named groups.

`.scratch/rttalentdb-program-to-sql-chain/issues/16-...md`. Seam 1 is the
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


def _line(location: Optional[CodeLocation]) -> int:
    assert location is not None
    return location.line_number


def test_a_long_run_of_whitespace_takes_less_than_one_second() -> None:
    started = time.perf_counter()
    matches = list(re.finditer(CSharpParser.CLASS_PATTERN, " " * 20_000, re.MULTILINE))
    elapsed = time.perf_counter() - started

    assert matches == []
    assert elapsed < 1.0


def test_a_class_with_no_access_modifier_gets_the_line_of_its_declaration(
    tmp_path: Path,
) -> None:
    path = tmp_path / "Foo.cs"
    path.write_text(
        "namespace A {\n}\n\n\n    class Foo { }\n  static class Baz {}\n",
        encoding="utf-8",
    )

    result = CSharpParser().parse_file(str(path))

    lines = {cls.name: _line(cls.location) for cls in result.classes}
    assert lines == {"Foo": 5, "Baz": 6}


@pytest.mark.parametrize(
    "source, groups",
    [
        ("public class Foo {", ("public", None, "Foo", None)),
        ("public static class Foo {", ("public", "static", "Foo", None)),
        ("internal sealed class Foo {", ("internal", "sealed", "Foo", None)),
        ("class X : Base, IFoo\n{", (None, None, "X", "Base, IFoo\n")),
    ],
)
def test_a_declaration_gives_the_same_groups(
    source: str, groups: Tuple[Optional[str], Optional[str], str, Optional[str]]
) -> None:
    match = re.search(CSharpParser.CLASS_PATTERN, source, re.MULTILINE)

    assert match is not None
    assert match.group("access", "modifier", "name", "bases") == groups
