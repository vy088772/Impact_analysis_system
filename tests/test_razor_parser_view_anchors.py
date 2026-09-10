"""A view declares which actions its screen calls, at two strengths that are
never merged (issue 12, `.scratch/aspnet-mvc-core-analysis/`).

A markup-layer declaration — an action attribute or a form action — is a
determined View Anchor. A controller-and-action shaped URL inside the view's
own `<script>` block is a candidate, rated `likely`, because it is only a
guess about what the client-side code calls at runtime.
"""

from __future__ import annotations

from pathlib import Path

from code_analyzer.razor_parser import RazorParser


def _parse(tmp_path: Path, content: str):
    path = tmp_path / "View.cshtml"
    path.write_text(content, encoding="utf-8")
    return RazorParser().parse_file(str(path))


def test_an_asp_action_attribute_is_recorded_as_a_determined_view_anchor(tmp_path: Path) -> None:
    result = _parse(tmp_path, '<a asp-action="Details">Details</a>')

    assert result.view_anchors_determined == [{"action": "Details"}]
    assert result.view_anchors_candidate == []


def test_an_asp_action_with_asp_controller_names_that_controller(tmp_path: Path) -> None:
    result = _parse(
        tmp_path,
        '<a asp-controller="Order" asp-action="Details">Details</a>',
    )

    assert result.view_anchors_determined == [
        {"action": "Details", "controller": "Order"}
    ]


def test_an_asp_page_attribute_is_recorded_as_a_determined_view_anchor(tmp_path: Path) -> None:
    result = _parse(tmp_path, '<a asp-page="/Order/Details">Details</a>')

    assert result.view_anchors_determined == [{"page": "/Order/Details"}]


def test_a_form_action_with_a_trailing_route_segment_still_names_controller_and_action(
    tmp_path: Path,
) -> None:
    """`Html.BeginForm("Edit", "Order", new { id = Model.Id })` renders
    `<form action="/Order/Edit/5">` — a real id segment after the action, not a
    guess the way a script-block string is. Unlike the candidate check, the
    form-action checklist item carries no "shape" qualifier, so a trailing
    segment must not swallow the anchor whole."""
    result = _parse(tmp_path, '<form action="/Order/Edit/5" method="post"></form>')

    assert result.view_anchors_determined == [
        {"action": "Edit", "controller": "Order"}
    ]


def test_a_script_block_url_with_a_query_string_is_still_a_candidate_anchor(
    tmp_path: Path,
) -> None:
    result = _parse(
        tmp_path,
        """
        <script>
            $.get('/Order/Detail?id=5', function (data) {});
        </script>
        """,
    )

    assert result.view_anchors_candidate == [
        {"action": "Detail", "controller": "Order"}
    ]


def test_a_form_action_is_recorded_as_a_determined_view_anchor(tmp_path: Path) -> None:
    result = _parse(tmp_path, '<form action="/Order/Save" method="post"></form>')

    assert result.view_anchors_determined == [
        {"action": "Save", "controller": "Order"}
    ]


def test_a_script_block_controller_and_action_url_is_a_candidate_anchor(tmp_path: Path) -> None:
    result = _parse(
        tmp_path,
        """
        <script>
            $.ajax({ url: '/Order/GetOrderDetail', success: function (data) {} });
        </script>
        """,
    )

    assert result.view_anchors_candidate == [
        {"action": "GetOrderDetail", "controller": "Order"}
    ]
    assert result.view_anchors_determined == []


def test_a_script_block_string_without_the_controller_and_action_shape_produces_no_anchor(
    tmp_path: Path,
) -> None:
    result = _parse(
        tmp_path,
        """
        <script>
            var cssHref = '/Content/css/site.css';
            var script = "/Scripts/site.js";
            var justOne = '/Order';
        </script>
        """,
    )

    assert result.view_anchors_candidate == []
    assert result.view_anchors_determined == []


def test_determined_and_candidate_anchors_are_never_merged(tmp_path: Path) -> None:
    result = _parse(
        tmp_path,
        """
        <form action="/Order/Save" method="post"></form>
        <script>
            $.ajax({ url: '/Order/GetOrderDetail' });
        </script>
        """,
    )

    assert result.view_anchors_determined == [
        {"action": "Save", "controller": "Order"}
    ]
    assert result.view_anchors_candidate == [
        {"action": "GetOrderDetail", "controller": "Order"}
    ]


def test_the_measured_repositorys_ajax_only_detail_endpoint_is_a_candidate_anchor(
    tmp_path: Path,
) -> None:
    """ETR reaches its detail query only through a script-block URL — no markup
    anchor names it anywhere in the view (spec.md, issue 12's "What to build")."""
    result = _parse(
        tmp_path,
        """
        <table><tr><th>Order No.</th></tr></table>
        <script>
            function loadDetail(id) {
                $.get('/OrderDetail/Fetch', { id: id }, function (data) {});
            }
        </script>
        """,
    )

    assert result.view_anchors_determined == []
    assert result.view_anchors_candidate == [
        {"action": "Fetch", "controller": "OrderDetail"}
    ]
