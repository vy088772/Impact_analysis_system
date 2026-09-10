"""A view's ViewComponent and partial view references (spec.md story 22-24).

`RazorParser` only extracts the raw names one .cshtml file references — it
never resolves them to a file, since a single view cannot see the other
scanned files that would answer that (see `service/shared_component.py`).
"""

from __future__ import annotations

from pathlib import Path

from code_analyzer.razor_parser import RazorParser


def _parse(tmp_path: Path, name: str, content: str):
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return RazorParser().parse_file(str(path))


def test_a_view_component_invoked_through_component_invokeasync_is_referenced(
    tmp_path: Path,
) -> None:
    result = _parse(
        tmp_path,
        "Index.cshtml",
        '@await Component.InvokeAsync("CustomerSelector")',
    )
    assert result.view_component_references == ["CustomerSelector"]


def test_a_view_component_invoked_synchronously_is_referenced(tmp_path: Path) -> None:
    result = _parse(tmp_path, "Index.cshtml", '@Component.Invoke("Menu")')
    assert result.view_component_references == ["Menu"]


def test_a_view_component_tag_helper_is_referenced_by_its_kebab_case_name(
    tmp_path: Path,
) -> None:
    result = _parse(tmp_path, "Index.cshtml", '<vc:customer-selector />')
    assert result.view_component_references == ["customer-selector"]


def test_a_partial_invoked_through_html_partial_is_referenced(tmp_path: Path) -> None:
    result = _parse(tmp_path, "Index.cshtml", '@Html.Partial("_CustomerList")')
    assert result.partial_view_references == ["_CustomerList"]


def test_a_partial_invoked_through_partial_async_is_referenced(tmp_path: Path) -> None:
    result = _parse(
        tmp_path, "Index.cshtml", '@await Html.PartialAsync("_CustomerList")'
    )
    assert result.partial_view_references == ["_CustomerList"]


def test_a_partial_tag_helper_is_referenced_by_its_name_attribute(
    tmp_path: Path,
) -> None:
    result = _parse(
        tmp_path, "Index.cshtml", '<partial name="_CustomerList" model="Model" />'
    )
    assert result.partial_view_references == ["_CustomerList"]


def test_a_view_naming_neither_reports_both_lists_empty(tmp_path: Path) -> None:
    result = _parse(tmp_path, "Index.cshtml", "<h1>Plain</h1>")
    assert result.view_component_references == []
    assert result.partial_view_references == []


def test_several_references_in_one_view_are_all_reported(tmp_path: Path) -> None:
    result = _parse(
        tmp_path,
        "Index.cshtml",
        (
            '@await Component.InvokeAsync("Menu")\n'
            '<partial name="_Header" />\n'
            '@await Html.PartialAsync("_Footer")\n'
            '<vc:cart-summary />\n'
        ),
    )
    assert sorted(result.view_component_references) == ["Menu", "cart-summary"]
    assert sorted(result.partial_view_references) == ["_Footer", "_Header"]
