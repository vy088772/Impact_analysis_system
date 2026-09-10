"""End-to-end: a Razor view's displayed field text resolves from all three
measured conventions (issue 11, `.scratch/aspnet-mvc-core-analysis/`) — plain
markup text, a display attribute's literal label, and a display attribute
resolved through a resource file — and the view-layer summary
(`service.analyze_service._view_layer_summary`) renders the result the same
way it renders an ASPX view, with no special-casing.
"""

from __future__ import annotations

from pathlib import Path

from code_analyzer.csharp_parser import CSharpParser
from code_analyzer.razor_display_field_resolver import resolve_razor_display_fields
from code_analyzer.razor_parser import RazorParser
from service.analyze_service import _view_layer_summary


_VIEW = """@model Orders.Models.OrderViewModel
<table>
<tr><th>訂單日期</th></tr>
</table>
<label asp-for="OrderNo">Order No.</label>
<label asp-for="CustomerName"></label>
<label asp-for="ShipDate"></label>
"""

_MODEL = """namespace Orders.Models
{
    public class OrderViewModel
    {
        public string OrderNo { get; set; }

        [Display(Name = "客戶名稱")]
        public string CustomerName { get; set; }

        [Display(Name = "ShipDate", ResourceType = typeof(Resources.SharedResource))]
        public string ShipDate { get; set; }
    }
}
"""

_RESX = """<root><data name="ShipDate"><value>出貨日期</value></data></root>"""


def test_a_razor_view_resolves_all_three_field_text_conventions(tmp_path: Path) -> None:
    view_path = tmp_path / "Views" / "Order" / "Edit.cshtml"
    view_path.parent.mkdir(parents=True, exist_ok=True)
    view_path.write_text(_VIEW, encoding="utf-8")

    model_path = tmp_path / "Models" / "OrderViewModel.cs"
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_text(_MODEL, encoding="utf-8")

    resx_path = tmp_path / "Resources" / "SharedResource.resx"
    resx_path.parent.mkdir(parents=True, exist_ok=True)
    resx_path.write_text(_RESX, encoding="utf-8")

    razor_result = RazorParser().parse_file(str(view_path))
    csharp_result = CSharpParser().parse_file(str(model_path))
    resolve_razor_display_fields([razor_result], [csharp_result], tmp_path)

    summary = _view_layer_summary(razor_result, tmp_path)

    assert summary["file"] == "Views/Order/Edit.cshtml"
    assert set(summary.keys()) == {"file", "type", "framework", "summary", "fields", "warnings"}
    assert summary["fields"] == [
        {"kind": "header", "text": "訂單日期"},
        {"kind": "label", "text": "Order No.", "data_field": "OrderNo"},
        {"kind": "label", "data_field": "CustomerName", "text": "客戶名稱"},
        {"kind": "label", "data_field": "ShipDate", "text": "出貨日期"},
    ]


def test_a_missing_resource_entry_never_falls_back_to_the_raw_key(tmp_path: Path) -> None:
    view_path = tmp_path / "Views" / "Order" / "Edit.cshtml"
    view_path.parent.mkdir(parents=True, exist_ok=True)
    view_path.write_text(
        '@model Orders.Models.OrderViewModel\n<label asp-for="ShipDate"></label>\n',
        encoding="utf-8",
    )

    model_path = tmp_path / "Models" / "OrderViewModel.cs"
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_text(_MODEL, encoding="utf-8")

    razor_result = RazorParser().parse_file(str(view_path))
    csharp_result = CSharpParser().parse_file(str(model_path))
    # No .resx file written under tmp_path at all.
    resolve_razor_display_fields([razor_result], [csharp_result], tmp_path)

    summary = _view_layer_summary(razor_result, tmp_path)

    entry = summary["fields"][0]
    assert "text" not in entry
    assert entry["unresolved_reason"] == "resource_file_not_found:SharedResource.resx"
