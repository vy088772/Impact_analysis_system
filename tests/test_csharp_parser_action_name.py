"""A controller method carries the action name MVC routes it by (ticket 13).

`[ActionName("X")]` renames the action. ASP.NET Core also removes the `Async`
suffix of a method name. The method name stays the call graph identity.
"""

from __future__ import annotations

from pathlib import Path

from code_analyzer.csharp_parser import CSharpParser


def _methods(tmp_path: Path, members: str):
    source = (
        "namespace Rt.Controllers\n{\n"
        "    public class SampleController : Controller\n    {\n"
        f"{members}\n"
        "    }\n}\n"
    )
    path = tmp_path / "SampleController.cs"
    path.write_text(source, encoding="utf-8")
    result = CSharpParser().parse_file(str(path))
    return {m.name: m for c in result.classes for m in c.methods}


def test_an_action_name_attribute_gives_the_routed_action_name(tmp_path: Path) -> None:
    methods = _methods(
        tmp_path,
        """
        [HttpPost]
        [ActionName("TechnicianSkillQry")]
        public async Task<IActionResult> TechnicianSkillQryPost([FromBody] Param p)
        {
            return Json(1);
        }
        """,
    )

    assert methods["TechnicianSkillQryPost"].action_name == "TechnicianSkillQry"


def test_an_async_suffix_is_removed_from_the_routed_action_name(tmp_path: Path) -> None:
    methods = _methods(
        tmp_path,
        """
        public async Task<IActionResult> UserGroupPermissionMtnAsync()
        {
            return View();
        }
        """,
    )

    assert methods["UserGroupPermissionMtnAsync"].action_name == "UserGroupPermissionMtn"


def test_a_method_with_no_rename_routes_by_its_own_name(tmp_path: Path) -> None:
    methods = _methods(
        tmp_path,
        """
        public IActionResult Index()
        {
            return View();
        }
        """,
    )

    assert methods["Index"].action_name == "Index"


def test_an_action_name_attribute_does_not_leak_to_the_next_method(tmp_path: Path) -> None:
    methods = _methods(
        tmp_path,
        """
        [ActionName("Renamed")]
        public IActionResult First()
        {
            return View();
        }

        public IActionResult Second()
        {
            return View();
        }
        """,
    )

    assert methods["First"].action_name == "Renamed"
    assert methods["Second"].action_name == "Second"
