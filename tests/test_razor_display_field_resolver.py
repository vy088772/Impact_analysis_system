"""Once both a Razor view and its `@model` class have been parsed, a `ui_fields`
entry the Razor parser could only name by model property is resolved through
that class's own [Display] attribute (issue 11,
`.scratch/aspnet-mvc-core-analysis/`). The Razor parser sees one file at a
time and cannot see the model class's attributes on its own — this is where
the two are brought together.
"""

from __future__ import annotations

from pathlib import Path

from code_analyzer.models import ClassInfo, FileAnalysisResult, FileType, FrameworkType, PropertyInfo
from code_analyzer.razor_display_field_resolver import resolve_razor_display_fields


def _view(model_type: str, ui_fields):
    result = FileAnalysisResult(
        file_path="Views/Order/Edit.cshtml",
        file_type=FileType.RAZOR,
        framework=FrameworkType.MVC,
    )
    result.dependencies.add(f"Model: {model_type}")
    result.ui_fields = ui_fields
    return result


def _model_class(class_name: str, properties):
    return FileAnalysisResult(
        file_path="Models/OrderViewModel.cs",
        file_type=FileType.CSHARP,
        framework=FrameworkType.MVC,
        classes=[
            ClassInfo(
                name=class_name,
                namespace="Orders.Models",
                file_path="Models/OrderViewModel.cs",
                properties=properties,
            )
        ],
    )


def test_a_literal_display_label_resolves_the_field_text_with_no_resource_lookup(
    tmp_path: Path,
) -> None:
    razor_results = [_view("OrderViewModel", [{"kind": "label", "data_field": "OrderNo"}])]
    csharp_results = [
        _model_class(
            "OrderViewModel",
            [PropertyInfo(name="OrderNo", type="string", access_modifier="public",
                           display_literal_label="訂單編號")],
        )
    ]

    resolve_razor_display_fields(razor_results, csharp_results, tmp_path)

    assert razor_results[0].ui_fields == [
        {"kind": "label", "data_field": "OrderNo", "text": "訂單編號"}
    ]


def test_a_resource_backed_display_label_resolves_through_the_resx_file(
    tmp_path: Path,
) -> None:
    resx = tmp_path / "Resources" / "SharedResource.resx"
    resx.parent.mkdir(parents=True, exist_ok=True)
    resx.write_text(
        '<root><data name="OrderNo"><value>訂單編號</value></data></root>',
        encoding="utf-8",
    )
    razor_results = [_view("OrderViewModel", [{"kind": "label", "data_field": "OrderNo"}])]
    csharp_results = [
        _model_class(
            "OrderViewModel",
            [PropertyInfo(name="OrderNo", type="string", access_modifier="public",
                           display_resource_type="SharedResource",
                           display_resource_key="OrderNo")],
        )
    ]

    resolve_razor_display_fields(razor_results, csharp_results, tmp_path)

    assert razor_results[0].ui_fields == [
        {"kind": "label", "data_field": "OrderNo", "text": "訂單編號"}
    ]


def test_a_missing_resource_entry_contributes_nothing_and_says_why_not_the_key(
    tmp_path: Path,
) -> None:
    razor_results = [_view("OrderViewModel", [{"kind": "label", "data_field": "OrderNo"}])]
    csharp_results = [
        _model_class(
            "OrderViewModel",
            [PropertyInfo(name="OrderNo", type="string", access_modifier="public",
                           display_resource_type="SharedResource",
                           display_resource_key="OrderNo")],
        )
    ]

    resolve_razor_display_fields(razor_results, csharp_results, tmp_path)

    entry = razor_results[0].ui_fields[0]
    assert "text" not in entry
    assert entry["unresolved_reason"] == "resource_file_not_found:SharedResource.resx"


def test_a_property_with_no_display_attribute_leaves_only_the_model_property(
    tmp_path: Path,
) -> None:
    razor_results = [_view("OrderViewModel", [{"kind": "label", "data_field": "OrderNo"}])]
    csharp_results = [
        _model_class(
            "OrderViewModel",
            [PropertyInfo(name="OrderNo", type="string", access_modifier="public")],
        )
    ]

    resolve_razor_display_fields(razor_results, csharp_results, tmp_path)

    assert razor_results[0].ui_fields == [{"kind": "label", "data_field": "OrderNo"}]


def test_an_entry_that_already_has_readable_text_is_left_untouched(tmp_path: Path) -> None:
    razor_results = [
        _view("OrderViewModel", [{"kind": "label", "text": "Order No.", "data_field": "OrderNo"}])
    ]
    csharp_results = [
        _model_class(
            "OrderViewModel",
            [PropertyInfo(name="OrderNo", type="string", access_modifier="public",
                           display_literal_label="訂單編號")],
        )
    ]

    resolve_razor_display_fields(razor_results, csharp_results, tmp_path)

    assert razor_results[0].ui_fields == [
        {"kind": "label", "text": "Order No.", "data_field": "OrderNo"}
    ]


def test_a_view_with_no_resolvable_model_class_is_left_untouched(tmp_path: Path) -> None:
    razor_results = [_view("Unknown.Type", [{"kind": "label", "data_field": "OrderNo"}])]

    resolve_razor_display_fields(razor_results, [], tmp_path)

    assert razor_results[0].ui_fields == [{"kind": "label", "data_field": "OrderNo"}]


def test_a_qualified_model_type_binds_to_its_own_namespace_not_a_same_named_class(
    tmp_path: Path,
) -> None:
    razor_results = [_view("Orders.Models.OrderViewModel", [{"kind": "label", "data_field": "OrderNo"}])]
    wrong_namespace_class = FileAnalysisResult(
        file_path="Models/Billing/OrderViewModel.cs",
        file_type=FileType.CSHARP,
        framework=FrameworkType.MVC,
        classes=[
            ClassInfo(
                name="OrderViewModel",
                namespace="Billing.Models",
                file_path="Models/Billing/OrderViewModel.cs",
                properties=[
                    PropertyInfo(name="OrderNo", type="string", access_modifier="public",
                                 display_literal_label="錯誤的命名空間")
                ],
            )
        ],
    )
    right_namespace_class = _model_class(
        "OrderViewModel",
        [PropertyInfo(name="OrderNo", type="string", access_modifier="public",
                       display_literal_label="訂單編號")],
    )
    csharp_results = [wrong_namespace_class, right_namespace_class]

    resolve_razor_display_fields(razor_results, csharp_results, tmp_path)

    assert razor_results[0].ui_fields == [
        {"kind": "label", "data_field": "OrderNo", "text": "訂單編號"}
    ]


def test_a_model_bound_property_missing_from_the_resolved_model_class_says_why(
    tmp_path: Path,
) -> None:
    razor_results = [_view("OrderViewModel", [{"kind": "label", "data_field": "NoSuchProperty"}])]
    csharp_results = [
        _model_class(
            "OrderViewModel",
            [PropertyInfo(name="OrderNo", type="string", access_modifier="public")],
        )
    ]

    resolve_razor_display_fields(razor_results, csharp_results, tmp_path)

    entry = razor_results[0].ui_fields[0]
    assert "text" not in entry
    assert entry["unresolved_reason"] == "model_property_not_found:NoSuchProperty"
