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


def test_display_name_for_with_a_direct_binding_produces_a_label_entry(
    tmp_path: Path,
) -> None:
    result = _parse(tmp_path, "@Html.DisplayNameFor(m => m.OrderNo)")

    assert result.ui_fields == [{"kind": "label", "data_field": "OrderNo"}]


def test_label_for_with_a_direct_binding_produces_a_label_entry(
    tmp_path: Path,
) -> None:
    result = _parse(tmp_path, "@Html.LabelFor(m => m.OrderNo)")

    assert result.ui_fields == [{"kind": "label", "data_field": "OrderNo"}]


def test_display_for_with_a_direct_binding_produces_a_value_entry(
    tmp_path: Path,
) -> None:
    result = _parse(tmp_path, "@Html.DisplayFor(m => m.OrderNo)")

    assert result.ui_fields == [{"kind": "value", "data_field": "OrderNo"}]


def test_text_box_for_with_a_direct_binding_produces_an_input_entry(
    tmp_path: Path,
) -> None:
    result = _parse(
        tmp_path, '@Html.TextBoxFor(m => m.OrderNo, new { @class = "form-control" })'
    )

    assert result.ui_fields == [{"kind": "input", "data_field": "OrderNo"}]


def test_text_area_for_with_a_direct_binding_produces_an_input_entry(
    tmp_path: Path,
) -> None:
    result = _parse(tmp_path, "@Html.TextAreaFor(m => m.Memo)")

    assert result.ui_fields == [{"kind": "input", "data_field": "Memo"}]


def test_hidden_for_produces_no_ui_fields_entry(tmp_path: Path) -> None:
    result = _parse(tmp_path, "@Html.HiddenFor(m => m.OrderNo)")

    assert result.ui_fields == []


def test_a_collection_indexed_binding_produces_raw_text_with_no_data_field(
    tmp_path: Path,
) -> None:
    result = _parse(tmp_path, "@Html.DisplayFor(m => m.Items[i].Property)")

    assert result.ui_fields == [{"kind": "value", "text": "m.Items[i].Property"}]


def test_a_direct_binding_through_a_consistently_named_non_m_parameter_produces_a_data_field(
    tmp_path: Path,
) -> None:
    # `item` here is both the lambda's own declared parameter and the
    # body's leading identifier, so this is a direct binding — the same
    # shape `m.Property` is — and now earns a `data_field`. Previously this
    # test asserted raw `text`, back when the direct-binding check compared
    # only against the hardcoded literal `m`/`Model` instead of the
    # lambda's actual declared parameter.
    result = _parse(tmp_path, "@Html.DisplayFor(item => item.UserName)")

    assert result.ui_fields == [{"kind": "value", "data_field": "UserName"}]


def test_a_direct_binding_through_a_non_m_declared_parameter_produces_a_data_field(
    tmp_path: Path,
) -> None:
    result = _parse(tmp_path, "@Html.DisplayFor(model => model.Property)")

    assert result.ui_fields == [{"kind": "value", "data_field": "Property"}]


def test_the_literal_model_still_resolves_when_the_declared_parameter_is_named_differently(
    tmp_path: Path,
) -> None:
    result = _parse(tmp_path, "@Html.DisplayFor(model => Model.Property)")

    assert result.ui_fields == [{"kind": "value", "data_field": "Property"}]


def test_a_multi_level_binding_through_a_non_m_declared_parameter_produces_raw_text(
    tmp_path: Path,
) -> None:
    result = _parse(tmp_path, "@Html.DisplayFor(model => model.Query.JobTypeID)")

    assert result.ui_fields == [
        {"kind": "value", "text": "model.Query.JobTypeID"}
    ]


def test_a_collection_indexed_binding_through_a_non_m_declared_parameter_produces_raw_text(
    tmp_path: Path,
) -> None:
    result = _parse(tmp_path, "@Html.DisplayFor(model => model.ResultList[0].UserID)")

    assert result.ui_fields == [
        {"kind": "value", "text": "model.ResultList[0].UserID"}
    ]


def test_a_binding_through_an_identifier_that_is_neither_the_declared_parameter_nor_model_falls_back_to_text(
    tmp_path: Path,
) -> None:
    result = _parse(tmp_path, "@Html.DisplayFor(modelItem => item.UserName)")

    assert result.ui_fields == [{"kind": "value", "text": "item.UserName"}]
