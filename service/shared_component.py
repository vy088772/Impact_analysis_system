"""Shared component contributions — a ViewComponent or partial view a screen
renders reaches that component's own stored procedures and tables, labelled
as coming from a shared component rather than the screen's own access
(spec.md stories 22-24).

A partial view holds no server code of its own; it only forwards markup, so
it never contributes a database fact directly. It can, in turn, render a
further ViewComponent or partial, so resolution walks the render chain from
the screen's own view and reports every ViewComponent it reaches, however
many partials sit in between. Only a ViewComponent's `Invoke`/`InvokeAsync`
method is reported, because that is the one method the framework calls to
render it — not the class's other members.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Mapping, Optional, Sequence, Set, Tuple

VIEW_COMPONENT = "view_component"

_VIEW_COMPONENT_SUFFIX = "viewcomponent"
_VIEW_COMPONENT_BASE_CLASS = "viewcomponent"
_INVOKE_METHOD_NAMES = ("invokeasync", "invoke")
_SHARED_FOLDER = "shared"


@dataclass(frozen=True)
class SharedComponentContribution:
    """One ViewComponent a screen reaches, directly or through a partial view."""

    name: str
    file_path: str
    class_name: str
    entry_method: str


@dataclass(frozen=True)
class _ViewIdentity:
    path: str
    area: str
    folder: str
    name: str


def resolve_shared_components(
    view_path: str,
    *,
    view_component_refs: Mapping[str, Sequence[str]],
    partial_view_refs: Mapping[str, Sequence[str]],
    view_component_classes: Sequence[Tuple[str, str, str, Sequence[str]]],
    view_identities: Mapping[str, Tuple[str, str, str]],
) -> List[SharedComponentContribution]:
    """The ViewComponents one screen's view reaches, each reported once.

    `view_component_classes` is `(file_path, class_name, base_class,
    method_names)` for every scanned C# class — a plain tuple sequence, not a
    `FileAnalysisResult`, so this module stays decoupled from
    `code_analyzer.models` the way `program_screen.py` already is.
    `view_identities` is every scanned view's `(area, folder, name)`
    (`program_screen.view_identity`), keyed by path, used to find a partial
    view the same way MVC looks one up.
    """
    identities = {
        path: _ViewIdentity(path, area, folder, name)
        for path, (area, folder, name) in view_identities.items()
    }
    resolved: List[SharedComponentContribution] = []
    seen_views: Set[str] = set()
    seen_components: Set[Tuple[str, str]] = set()

    def _walk(path: str) -> None:
        if path in seen_views:
            return
        seen_views.add(path)
        for name in view_component_refs.get(path, ()):
            contribution = _resolve_view_component(name, view_component_classes)
            if contribution is None:
                continue
            key = (contribution.file_path, contribution.class_name)
            if key in seen_components:
                continue
            seen_components.add(key)
            resolved.append(contribution)
        for name in partial_view_refs.get(path, ()):
            target = _resolve_partial_view(name, path, identities)
            if target is not None:
                _walk(target)

    _walk(view_path)
    return resolved


def _resolve_view_component(
    name: str,
    classes: Sequence[Tuple[str, str, str, Sequence[str]]],
) -> Optional[SharedComponentContribution]:
    target = _normalize_component_name(name)
    if not target:
        return None
    matches: List[SharedComponentContribution] = []
    for file_path, class_name, base_class, methods in classes:
        if not _is_view_component_class(class_name, base_class):
            continue
        candidates = {_normalize_component_name(class_name)}
        if class_name.lower().endswith(_VIEW_COMPONENT_SUFFIX) and len(
            class_name
        ) > len(_VIEW_COMPONENT_SUFFIX):
            candidates.add(
                _normalize_component_name(class_name[: -len(_VIEW_COMPONENT_SUFFIX)])
            )
        if target not in candidates:
            continue
        entry_method = _invoke_method(methods)
        if not entry_method:
            continue
        matches.append(
            SharedComponentContribution(
                name=name.strip(),
                file_path=file_path,
                class_name=class_name,
                entry_method=entry_method,
            )
        )
    return matches[0] if len(matches) == 1 else None


def _is_view_component_class(class_name: str, base_class: str) -> bool:
    if class_name.lower().endswith(_VIEW_COMPONENT_SUFFIX):
        return True
    return (base_class or "").strip().lower() == _VIEW_COMPONENT_BASE_CLASS


def _invoke_method(methods: Sequence[str]) -> str:
    lowered = {method.lower(): method for method in methods}
    for candidate in _INVOKE_METHOD_NAMES:
        if candidate in lowered:
            return lowered[candidate]
    return ""


def _normalize_component_name(name: str) -> str:
    return (name or "").strip().replace("-", "").replace("_", "").lower()


def _resolve_partial_view(
    name: str,
    caller_path: str,
    identities: Mapping[str, _ViewIdentity],
) -> Optional[str]:
    caller = identities.get(caller_path)
    if caller is None:
        return None
    target = (name or "").strip()
    if not target:
        return None
    candidates = [
        identity
        for identity in identities.values()
        if _matches_partial_name(target, identity.name)
    ]
    if not candidates:
        return None
    same_folder = [
        identity
        for identity in candidates
        if _same(identity.area, caller.area) and _same(identity.folder, caller.folder)
    ]
    if same_folder:
        return _one(same_folder)
    same_area_shared = [
        identity
        for identity in candidates
        if _same(identity.area, caller.area) and _same(identity.folder, _SHARED_FOLDER)
    ]
    if same_area_shared:
        return _one(same_area_shared)
    root_shared = [
        identity
        for identity in candidates
        if not identity.area and _same(identity.folder, _SHARED_FOLDER)
    ]
    return _one(root_shared)


def _matches_partial_name(reference: str, view_name: str) -> bool:
    return reference.strip("_").lower() == (view_name or "").strip("_").lower()


def _same(left: str, right: str) -> bool:
    return (left or "").lower() == (right or "").lower()


def _one(identities: Sequence[_ViewIdentity]) -> Optional[str]:
    return identities[0].path if len(identities) == 1 else None
