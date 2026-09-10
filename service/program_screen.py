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
absorbs a longer name that merely contains it. A screen's action set is the
actions whose name equals the view name plus the actions its View Anchors name,
and an action reached only through a candidate anchor keeps that anchor's
`likely` strength. WebForms program resolution does not come through here; it
keeps its existing base-name path in `analyze_service`.

A Razor Pages screen resolves separately, through `resolve_razor_page_screens`:
one view carrying a page directive, paired with the code-behind file beside
it, exactly as a WebForms page pairs with its own code-behind. Its actions are
the handlers the page model declares, not a controller's actions.
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

DETERMINED = "determined"
LIKELY = "likely"


@dataclass(frozen=True)
class ScreenAction:
    """One action a Program Screen holds, on the controller that declares it.

    `strength` is `determined` when the view's own name or a markup-layer View
    Anchor named the action, and `likely` when only a candidate anchor did.
    """

    name: str
    controller_path: str
    strength: str


@dataclass(frozen=True)
class ProgramScreen:
    """One resolved Program Screen: a view, its controller, and its actions."""

    program_code: str
    view_path: str
    view_name: str
    area: str
    controller_path: str
    actions: Tuple[ScreenAction, ...] = ()


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


@dataclass(frozen=True)
class _Anchors:
    """One view's View Anchors, held at their two strengths and never merged."""

    determined: Tuple[Mapping[str, str], ...] = ()
    candidate: Tuple[Mapping[str, str], ...] = ()


def resolve_program_screens(
    program_code: str,
    *,
    view_paths: Iterable[str],
    controller_actions: Mapping[str, Sequence[str]],
    determined_anchors: Optional[Mapping[str, Sequence[Mapping[str, str]]]] = None,
    candidate_anchors: Optional[Mapping[str, Sequence[Mapping[str, str]]]] = None,
) -> List[ProgramScreen]:
    """Resolve one program code to the Program Screens it names.

    `controller_actions` maps each scanned C# file to the method names it
    declares; the files that are not controllers are ignored here.

    The two anchor maps carry each view's View Anchors at their own strength,
    keyed by view path. They arrive as two arguments because the two strengths
    are never merged: a markup-layer anchor states the call, a script-block URL
    only looks like one.
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
        # Only the views narrow to the Area. Every controller stays in reach,
        # because a View Anchor can name one that sits outside every Area, and
        # both entry points below compare a controller's Area to its view's
        # anyway.
        views = [view for view in views if _same(view.area, area)]

    anchors = _anchors_by_view(determined_anchors, candidate_anchors)

    matched = [view for view in views if _same(view.folder, code)]
    if not matched:
        matched = [view for view in views if _names_view_file(code, view.name)]
    if matched:
        return [
            _screen(
                program_code,
                view,
                _controller_of(view, controllers),
                controllers,
                anchors.get(view.path, _Anchors()),
            )
            for view in matched
        ]

    return _screens_through_controllers(
        program_code, code, views, controllers, anchors
    )


def resolve_razor_page_screens(
    program_code: str,
    *,
    view_paths: Iterable[str],
    page_directives: Mapping[str, bool],
    page_model_handlers: Mapping[str, Sequence[str]],
) -> List[ProgramScreen]:
    """Resolve a program code to the Razor Pages screens it names.

    A Razor Pages screen anchors through its page model exactly the way a
    WebForms page anchors through its code-behind: a view and a code-behind
    file beside it, sharing a name. The page directive is the gate — a view
    naming no `@page` directive is MVC, however many editor-generated files
    sit beside it, and resolves no screen here. `page_model_handlers` is keyed
    by the view's own path; a page model declaring no handler resolves no
    screen either, so an empty editor-generated stub anchors nothing.
    """
    code = (program_code or "").strip()
    if not code:
        return []
    screens: List[ProgramScreen] = []
    for view_path in view_paths:
        if not page_directives.get(view_path):
            continue
        name = _razor_view_name(view_path)
        if name is None or not _same(name, code):
            continue
        handlers = page_model_handlers.get(view_path) or ()
        if not handlers:
            continue
        model_path = razor_page_model_path(view_path)
        screens.append(
            ProgramScreen(
                program_code=program_code,
                view_path=view_path,
                view_name=name,
                area="",
                controller_path=model_path,
                actions=tuple(
                    ScreenAction(handler, model_path, DETERMINED)
                    for handler in handlers
                ),
            )
        )
    return screens


def _razor_view_name(path: str) -> Optional[str]:
    parts = _parts(path)
    if not parts or not parts[-1].lower().endswith(_VIEW_EXTENSION):
        return None
    return parts[-1][: -len(_VIEW_EXTENSION)]


def razor_page_model_path(view_path: str) -> str:
    """A Razor Pages page model sits beside its view, sharing its whole file
    name plus `.cs` — `Foo.cshtml` pairs with `Foo.cshtml.cs`. The single place
    that states the pairing rule, so a caller building `page_model_handlers`
    and this resolution never drift apart on how the pair is named."""
    return f"{view_path}.cs"


def view_identity(view_path: str) -> Optional[Tuple[str, str, str]]:
    """A view's `(area, folder, name)` — the same identity `resolve_program_screens`
    matches views by, exposed so `service/shared_component.py` can locate a
    partial view the way MVC itself looks a view up, without duplicating this
    parse."""
    parsed = _view_file(view_path)
    if parsed is None:
        return None
    return parsed.area, parsed.folder, parsed.name


def _screens_through_controllers(
    program_code: str,
    code: str,
    views: Sequence[_ViewFile],
    controllers: Sequence[_ControllerFile],
    anchors: Mapping[str, _Anchors],
) -> List[ProgramScreen]:
    screens: List[ProgramScreen] = []
    seen: set[str] = set()
    for controller in controllers:
        if not _same(controller.name, code):
            continue
        for view in views:
            if view.path in seen or not _looks_up(controller, view):
                continue
            screens.append(
                _screen(
                    program_code,
                    view,
                    controller,
                    controllers,
                    anchors.get(view.path, _Anchors()),
                )
            )
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
    controllers: Sequence[_ControllerFile],
    anchors: _Anchors,
) -> ProgramScreen:
    named: List[ScreenAction] = []
    if controller is not None:
        named = [
            ScreenAction(action, controller.path, DETERMINED)
            for action in controller.actions
            if _same(action, view.name)
        ]
    actions = _without_repeats(
        named
        + _anchored(view, controller, controllers, anchors.determined, DETERMINED)
        + _anchored(view, controller, controllers, anchors.candidate, LIKELY)
    )
    return ProgramScreen(
        program_code=program_code,
        view_path=view.path,
        view_name=view.name,
        area=view.area,
        controller_path=controller.path if controller is not None else "",
        actions=actions,
    )


def _anchored(
    view: _ViewFile,
    controller: Optional[_ControllerFile],
    controllers: Sequence[_ControllerFile],
    anchors: Sequence[Mapping[str, str]],
    strength: str,
) -> List[ScreenAction]:
    """The actions one view's anchors name, at the strength those anchors carry.

    An anchor that names no controller action — a page anchor — contributes
    none, and so does one whose named action no controller declares: this
    resolution reports an action it can reach, never a name it cannot.
    """
    actions: List[ScreenAction] = []
    for anchor in anchors:
        name = str(anchor.get("action") or "").strip()
        if not name:
            continue
        target = _anchor_controller(
            view, controller, controllers, str(anchor.get("controller") or ""), name
        )
        if target is None:
            continue
        declared = next(
            (action for action in target.actions if _same(action, name)), ""
        )
        if declared:
            actions.append(ScreenAction(declared, target.path, strength))
    return actions


def _anchor_controller(
    view: _ViewFile,
    controller: Optional[_ControllerFile],
    controllers: Sequence[_ControllerFile],
    named: str,
    action: str,
) -> Optional[_ControllerFile]:
    """The controller one anchor reaches, by whole name.

    An anchor naming no controller reaches the screen's own, exactly as MVC
    routes a controller-less anchor. An anchor naming one reaches that
    controller inside the view's own Area, and reaches a controller outside
    every Area when the Area holds none of that name — which is the route a
    shared AJAX controller with no view folder of its own is reached by
    (ADR-0019). Two controllers of one name that both declare the action reach
    neither, because the screen reports no action rather than guessing at one.
    """
    if not named.strip():
        return controller
    reachable = [
        item
        for item in controllers
        if _same(item.name, named.strip())
        and any(_same(declared, action) for declared in item.actions)
    ]
    inside = [item for item in reachable if _same_area(item.area, view.area)]
    outside = [item for item in reachable if not item.area]
    found = inside or outside
    return found[0] if len(found) == 1 else None


def _without_repeats(actions: Sequence[ScreenAction]) -> Tuple[ScreenAction, ...]:
    """One action per controller, keeping the first — and so strongest — reach."""
    kept: List[ScreenAction] = []
    seen: set[Tuple[str, str]] = set()
    for action in actions:
        key = (action.controller_path.lower(), action.name.lower())
        if key in seen:
            continue
        seen.add(key)
        kept.append(action)
    return tuple(kept)


def _anchors_by_view(
    determined: Optional[Mapping[str, Sequence[Mapping[str, str]]]],
    candidate: Optional[Mapping[str, Sequence[Mapping[str, str]]]],
) -> Mapping[str, _Anchors]:
    paths = set(determined or {}) | set(candidate or {})
    return {
        path: _Anchors(
            determined=tuple((determined or {}).get(path) or ()),
            candidate=tuple((candidate or {}).get(path) or ()),
        )
        for path in paths
    }


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
