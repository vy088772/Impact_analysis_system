"""Program Screen resolution — one View plus the actions that serve it.

A specification names a program by a bare code, such as `AgentMtn`. In an MVC
or ASP.NET Core repository that code resolves to one Program Screen: one View
file together with the actions that serve it (ADR-0019). The controller is a
path used to reach those actions, never the unit of scope, so one controller
can hold several Program Screens and one Program Screen never spans two
controllers.

The code resolves through three entry points, tried in order:

1. A `Views/{code}` folder — every view in it becomes a Program Screen.
2. A view file whose base name is `{code}`, with an optional trailing `View`
   allowed on the file name.
3. A `{code}Controller.cs` file — the views its actions name become Program
   Screens, found the way MVC itself looks a view up: under `Views/{code}`,
   then under `Views/Shared`, inside the controller's own Area.

Every comparison is a whole-name comparison, so a shorter program code never
absorbs a longer name that merely contains it. A screen's actions are the ones
whose name equals the view name; the actions its View Anchors name join them in
ticket 13, which is where View Anchor extraction lands. WebForms program
resolution does not come through here; it keeps its existing base-name path in
`analyze_service`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Iterable, List, Mapping, Optional, Sequence, Tuple

_VIEW_SUFFIX = "view"
_CONTROLLER_SUFFIX = "controller"
_VIEW_EXTENSION = ".cshtml"
_VIEWS_SEGMENT = "views"
_AREAS_SEGMENT = "areas"
_SHARED_FOLDER = "shared"


@dataclass(frozen=True)
class ProgramScreen:
    """One resolved Program Screen: a view, its controller, and its actions."""

    program_code: str
    view_path: str
    view_name: str
    area: str
    controller_path: str
    action_names: Tuple[str, ...]


@dataclass(frozen=True)
class _ViewFile:
    path: str
    area: str
    folder: str
    name: str


@dataclass(frozen=True)
class _ControllerFile:
    path: str
    area: str
    name: str
    actions: Tuple[str, ...]


def resolve_program_screens(
    program_code: str,
    *,
    view_paths: Iterable[str],
    controller_actions: Mapping[str, Sequence[str]],
) -> List[ProgramScreen]:
    """Resolve one program code to the Program Screens it names.

    `controller_actions` maps each scanned C# file to the method names it
    declares; the files that are not controllers are ignored here.
    """
    area, code = _split_area(program_code)
    if not code:
        return []

    views = [parsed for parsed in map(_view_file, view_paths) if parsed is not None]
    controllers = [
        parsed
        for parsed in (
            _controller_file(path, actions)
            for path, actions in controller_actions.items()
        )
        if parsed is not None
    ]
    if area:
        views = [view for view in views if _same(view.area, area)]
        controllers = [item for item in controllers if _same(item.area, area)]

    matched = [view for view in views if _same(view.folder, code)]
    if not matched:
        matched = [view for view in views if _names_view_file(code, view.name)]
    if matched:
        return [
            _screen(program_code, view, _controller_of(view, controllers))
            for view in matched
        ]

    return _screens_through_controllers(program_code, code, views, controllers)


def _screens_through_controllers(
    program_code: str,
    code: str,
    views: Sequence[_ViewFile],
    controllers: Sequence[_ControllerFile],
) -> List[ProgramScreen]:
    screens: List[ProgramScreen] = []
    seen: set[str] = set()
    for controller in controllers:
        if not _same(controller.name, code):
            continue
        for view in views:
            if view.path in seen or not _looks_up(controller, view):
                continue
            screens.append(_screen(program_code, view, controller))
            seen.add(view.path)
    return screens


def _looks_up(controller: _ControllerFile, view: _ViewFile) -> bool:
    """Whether one controller reaches one view the way MVC looks a view up.

    MVC searches `Views/{controller}/{action}` and then `Views/Shared/{action}`
    inside the controller's own Area. Searching wider would make every
    `Index.cshtml` in the repository a screen of every controller declaring an
    `Index` action.
    """
    if not _same_area(controller.area, view.area):
        return False
    if not (_same(view.folder, controller.name) or _same(view.folder, _SHARED_FOLDER)):
        return False
    return any(_same(action, view.name) for action in controller.actions)


def _screen(
    program_code: str,
    view: _ViewFile,
    controller: Optional[_ControllerFile],
) -> ProgramScreen:
    actions: Tuple[str, ...] = ()
    if controller is not None:
        actions = tuple(
            action for action in controller.actions if _same(action, view.name)
        )
    return ProgramScreen(
        program_code=program_code,
        view_path=view.path,
        view_name=view.name,
        area=view.area,
        controller_path=controller.path if controller is not None else "",
        action_names=actions,
    )


def _controller_of(
    view: _ViewFile, controllers: Sequence[_ControllerFile]
) -> Optional[_ControllerFile]:
    """The controller that serves one view, inside the view's own Area.

    The view's folder names it in the ordinary case. The controller that serves
    a screen may carry an entirely different name, so a view whose folder names
    no controller falls back to the one controller of its Area that declares an
    action of the view's name. Several such controllers name no one of them, and
    the screen reports no action rather than guessing at one.
    """
    for controller in controllers:
        if _same_area(controller.area, view.area) and _same(
            controller.name, view.folder
        ):
            return controller
    declaring = [
        controller
        for controller in controllers
        if _same_area(controller.area, view.area)
        and any(_same(action, view.name) for action in controller.actions)
    ]
    return declaring[0] if len(declaring) == 1 else None


def _split_area(program_code: str) -> Tuple[str, str]:
    """Split an Area-qualified program code such as `Admin/Summary`."""
    text = (program_code or "").strip().replace("\\", "/").strip("/")
    if "/" not in text:
        return "", text
    area, _, code = text.rpartition("/")
    return area.strip(), code.strip()


def _view_file(path: str) -> Optional[_ViewFile]:
    parts = _parts(path)
    if len(parts) < 2 or not parts[-1].lower().endswith(_VIEW_EXTENSION):
        return None
    lowered = [part.lower() for part in parts]
    if _VIEWS_SEGMENT not in lowered:
        return None
    index = len(lowered) - 1 - lowered[::-1].index(_VIEWS_SEGMENT)
    area = ""
    if index >= 2 and lowered[index - 2] == _AREAS_SEGMENT:
        area = parts[index - 1]
    folder = parts[index + 1] if len(parts) - index > 2 else ""
    name = parts[-1][: -len(_VIEW_EXTENSION)]
    return _ViewFile(path=path, area=area, folder=folder, name=name)


def _controller_file(path: str, actions: Sequence[str]) -> Optional[_ControllerFile]:
    parts = _parts(path)
    if not parts:
        return None
    stem = parts[-1]
    if not stem.lower().endswith(".cs"):
        return None
    stem = stem[: -len(".cs")]
    if not stem.lower().endswith(_CONTROLLER_SUFFIX) or len(stem) == len(
        _CONTROLLER_SUFFIX
    ):
        return None
    lowered = [part.lower() for part in parts]
    area = ""
    if _AREAS_SEGMENT in lowered:
        index = len(lowered) - 1 - lowered[::-1].index(_AREAS_SEGMENT)
        if index + 1 < len(parts) - 1:
            area = parts[index + 1]
    return _ControllerFile(
        path=path,
        area=area,
        name=stem[: -len(_CONTROLLER_SUFFIX)],
        actions=tuple(actions),
    )


def _parts(path: str) -> Tuple[str, ...]:
    return PurePosixPath((path or "").replace("\\", "/")).parts


def _same(left: str, right: str) -> bool:
    """Whole-name comparison; a name never matches a longer one containing it."""
    return bool(left) and left.lower() == (right or "").lower()


def _same_area(left: str, right: str) -> bool:
    """Area comparison, where two files outside any Area share one Area."""
    return (left or "").lower() == (right or "").lower()


def _names_view_file(code: str, view_name: str) -> bool:
    """Whether a program code names a view file, trailing `View` allowed."""
    return _same(view_name, code) or _same(view_name, f"{code}{_VIEW_SUFFIX}")
