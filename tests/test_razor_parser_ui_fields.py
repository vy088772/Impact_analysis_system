"""A Razor view's displayed field text is extracted the same way the WebForms
view's is (issue 11, `.scratch/aspnet-mvc-core-analysis/`): plain markup text in
table headers and labels, and — when a label carries no readable text at all —
the model property a model-bound `asp-for` attribute names, left for a later
pass (`code_analyzer/razor_display_field_resolver.py`) to resolve through the
model class's own [Display] attribute.
"""

from __future__ import annotations

from pathlib import Path

from code_analyzer.razor_parser import RazorParser


def _parse(tmp_path: Path, content: str):
    path = tmp_path / "View.cshtml"
    path.write_text(content, encoding="utf-8")
    return RazorParser().parse_file(str(path))


def test_plain_table_header_text_is_extracted_as_displayed_field_text(tmp_path: Path) -> None:
    result = _parse(
        tmp_path,
        "<table><tr><th>訂單編號</th><th>客戶</th></tr></table>",
    )

    assert result.ui_fields == [
        {"kind": "header", "text": "訂單編號"},
        {"kind": "header", "text": "客戶"},
    ]


def test_a_plain_label_with_readable_text_is_extracted_directly(tmp_path: Path) -> None:
    result = _parse(tmp_path, '<label for="OrderNo">Order No.</label>')

    assert result.ui_fields == [{"kind": "label", "text": "Order No."}]


def test_a_model_bound_label_with_readable_text_keeps_both_the_text_and_the_property(
    tmp_path: Path,
) -> None:
    result = _parse(tmp_path, '<label asp-for="OrderNo">Order No.</label>')

    assert result.ui_fields == [
        {"kind": "label", "text": "Order No.", "data_field": "OrderNo"}
    ]


def test_a_model_bound_label_with_no_text_contributes_only_the_model_property(
    tmp_path: Path,
) -> None:
    result = _parse(tmp_path, '<label asp-for="OrderNo"></label>')

    assert result.ui_fields == [{"kind": "label", "data_field": "OrderNo"}]
