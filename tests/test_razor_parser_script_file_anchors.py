"""A view loads a `.js` file with `<script src>`; a URL in that file is a
`likely` View Anchor of the view (ticket 15,
`.scratch/rttalentdb-program-to-sql-chain/`).
"""

from __future__ import annotations

from pathlib import Path

from code_analyzer.razor_parser import RazorParser


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "Web"
    (project / "wwwroot" / "js").mkdir(parents=True)
    (project / "Views" / "Order").mkdir(parents=True)
    (project / "Web.csproj").write_text("<Project/>", encoding="utf-8")
    return project


def _parse(project: Path, src: str, js: str | None, js_name: str = "js/app.js", view: str = "Views/Order/Index.cshtml"):
    if js is not None:
        (project / "wwwroot" / js_name).write_text(js, encoding="utf-8")
    view_path = project / view
    view_path.write_text(f'<script src="{src}"></script>', encoding="utf-8")
    return RazorParser().parse_file(str(view_path))


JS = "$.post('/TraditionalAssessment/GetApproveComment', data);"
ANCHOR = [{"action": "GetApproveComment", "controller": "TraditionalAssessment"}]


def test_a_url_in_a_loaded_script_file_is_a_likely_anchor(tmp_path: Path) -> None:
    result = _parse(_project(tmp_path), "~/js/app.js", JS)

    assert result.view_anchors_candidate == ANCHOR
    assert result.view_anchors_determined == []


def test_a_root_and_a_relative_src_reach_the_same_file(tmp_path: Path) -> None:
    project = _project(tmp_path)

    assert _parse(project, "/js/app.js", JS).view_anchors_candidate == ANCHOR
    assert _parse(project, "js/app.js", JS).view_anchors_candidate == ANCHOR


def test_the_file_name_ignores_case_and_the_query_string(tmp_path: Path) -> None:
    result = _parse(_project(tmp_path), "~/js/APP.js?v=1", JS)

    assert result.view_anchors_candidate == ANCHOR


def test_external_and_dynamic_src_give_no_anchor(tmp_path: Path) -> None:
    project = _project(tmp_path)
    for src in ("https://cdn.x/app.js", "http://cdn.x/app.js", "//cdn.x/app.js", "~/js/@Model.Name.js"):
        assert _parse(project, src, JS).view_anchors_candidate == []


def test_a_missing_file_gives_no_anchor_and_no_error(tmp_path: Path) -> None:
    result = _parse(_project(tmp_path), "~/js/none.js", None)

    assert result.view_anchors_candidate == []
    assert result.errors == []


def test_a_comment_line_and_a_view_url_follow_the_script_block_rules(tmp_path: Path) -> None:
    js = "// $.post('/Old/Gone');\n$.get(`Order/Detail/${id}`);\nlocation = '/Order/OrderMtn.js';\n"
    result = _parse(_project(tmp_path), "~/js/app.js", js)

    assert result.view_anchors_candidate == [{"action": "Detail", "controller": "Order"}]


def test_two_views_that_load_the_same_file_both_get_the_anchor(tmp_path: Path) -> None:
    project = _project(tmp_path)
    first = _parse(project, "~/js/app.js", JS)
    second = _parse(project, "~/js/app.js", JS, view="Views/Order/Edit.cshtml")

    assert first.view_anchors_candidate == ANCHOR
    assert second.view_anchors_candidate == ANCHOR


def test_a_script_file_that_only_a_layout_loads_gives_no_anchor_to_a_view(tmp_path: Path) -> None:
    project = _project(tmp_path)
    (project / "wwwroot" / "js" / "layout.js").write_text(JS, encoding="utf-8")
    (project / "Views" / "Shared").mkdir()
    (project / "Views" / "Shared" / "_Layout.cshtml").write_text(
        '<script src="~/js/layout.js"></script>@RenderBody()', encoding="utf-8"
    )
    view = project / "Views" / "Order" / "Index.cshtml"
    view.write_text("<h1>Order</h1>", encoding="utf-8")

    assert RazorParser().parse_file(str(view)).view_anchors_candidate == []


def test_a_project_less_view_gives_no_anchor(tmp_path: Path) -> None:
    (tmp_path / "wwwroot" / "js").mkdir(parents=True)
    (tmp_path / "wwwroot" / "js" / "app.js").write_text(JS, encoding="utf-8")
    view = tmp_path / "Index.cshtml"
    view.write_text('<script src="~/js/app.js"></script>', encoding="utf-8")

    assert RazorParser().parse_file(str(view)).view_anchors_candidate == []


def test_one_parser_reads_a_shared_script_file_once_and_sees_a_change(tmp_path: Path) -> None:
    project = _project(tmp_path)
    script = project / "wwwroot" / "js" / "app.js"
    script.write_text(JS, encoding="utf-8")
    parser = RazorParser()
    reads: list[Path] = []
    original = Path.read_bytes

    def counting(self: Path) -> bytes:
        if self.name == "app.js":
            reads.append(self)
        return original(self)

    Path.read_bytes = counting  # type: ignore[method-assign]
    try:
        for name in ("A.cshtml", "B.cshtml"):
            view = project / "Views" / "Order" / name
            view.write_text('<script src="~/js/app.js"></script>', encoding="utf-8")
            assert parser.parse_file(str(view)).view_anchors_candidate == ANCHOR
        assert len(reads) == 1

        script.write_text("$.post('/Other/Thing');", encoding="utf-8")
        view = project / "Views" / "Order" / "C.cshtml"
        view.write_text('<script src="~/js/app.js"></script>', encoding="utf-8")
        assert parser.parse_file(str(view)).view_anchors_candidate == [
            {"action": "Thing", "controller": "Other"}
        ]
    finally:
        Path.read_bytes = original  # type: ignore[method-assign]
