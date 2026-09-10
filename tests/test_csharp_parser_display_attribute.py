"""A model property's [Display] attribute is captured for Razor label resolution
(issue 11, `.scratch/aspnet-mvc-core-analysis/`).

A Razor view whose `<label asp-for="X">` carries no readable text names the model
property `X`. The property's own `[Display]` attribute is where the real label
text lives, either as a literal or as a key into a resource file. This parser is
the only place that attribute is visible, so it must survive into `PropertyInfo`.
"""

from __future__ import annotations

from pathlib import Path

from code_analyzer.csharp_parser import CSharpParser


def _properties(tmp_path: Path, class_body: str):
    source = f"""
namespace Orders.Models
{{
    public class OrderViewModel
    {{
{class_body}
    }}
}}
"""
    path = tmp_path / "OrderViewModel.cs"
    path.write_text(source, encoding="utf-8")
    result = CSharpParser().parse_file(str(path))
    assert len(result.classes) == 1
    return {prop.name: prop for prop in result.classes[0].properties}


def test_a_display_attribute_with_a_literal_name_is_captured_with_no_resource_lookup(
    tmp_path: Path,
) -> None:
    properties = _properties(
        tmp_path,
        '        [Display(Name = "訂單編號")]\n'
        "        public string OrderNo { get; set; }\n",
    )

    prop = properties["OrderNo"]
    assert prop.display_literal_label == "訂單編號"
    assert prop.display_resource_type is None
    assert prop.display_resource_key is None


def test_a_display_attribute_naming_a_resource_type_is_captured_as_a_resource_key(
    tmp_path: Path,
) -> None:
    properties = _properties(
        tmp_path,
        "        [Display(Name = \"OrderNo\", ResourceType = typeof(Resources.SharedResource))]\n"
        "        public string OrderNo { get; set; }\n",
    )

    prop = properties["OrderNo"]
    assert prop.display_literal_label is None
    assert prop.display_resource_type == "SharedResource"
    assert prop.display_resource_key == "OrderNo"


def test_a_property_with_no_display_attribute_carries_neither(tmp_path: Path) -> None:
    properties = _properties(tmp_path, "        public string OrderNo { get; set; }\n")

    prop = properties["OrderNo"]
    assert prop.display_literal_label is None
    assert prop.display_resource_type is None
    assert prop.display_resource_key is None


def test_a_display_attribute_belonging_to_an_earlier_property_is_not_reused(
    tmp_path: Path,
) -> None:
    properties = _properties(
        tmp_path,
        '        [Display(Name = "訂單編號")]\n'
        "        public string OrderNo { get; set; }\n"
        "        public string CustomerName { get; set; }\n",
    )

    assert properties["OrderNo"].display_literal_label == "訂單編號"
    assert properties["CustomerName"].display_literal_label is None
