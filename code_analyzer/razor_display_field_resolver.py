"""Resolve a Razor view's model-bound `ui_fields` entries through the model
class's own [Display] attribute (issue 11, `.scratch/aspnet-mvc-core-analysis/`).

The Razor parser sees one .cshtml file at a time and cannot see the model
class's attributes; the C# parser sees one .cs file at a time and cannot see
which view binds to it. This module runs once both sides of a scan exist,
matching a view's `@model` type to a parsed class by name and filling in each
`ui_fields` entry's displayed text from that class's properties.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from code_analyzer.models import FileAnalysisResult, PropertyInfo
from code_analyzer.resource_file_resolver import resolve_resource_entry

_MODEL_DEPENDENCY_PREFIX = "Model: "


def resolve_razor_display_fields(
    razor_results: List[FileAnalysisResult],
    csharp_results: List[FileAnalysisResult],
    project_root: Path,
) -> None:
    """Mutate each Razor result's `ui_fields` in place, filling in resolvable text."""
    if not razor_results:
        return

    # Keyed by qualified name (namespace.ClassName) first, so two model classes
    # sharing a bare name in different namespaces never bind to the wrong one;
    # the bare-name map is only a fallback for an `@model` value with no namespace.
    properties_by_qualified_name: Dict[str, Dict[str, PropertyInfo]] = {}
    properties_by_class_name: Dict[str, Dict[str, PropertyInfo]] = {}
    for csharp_result in csharp_results:
        for class_info in csharp_result.classes:
            properties = {prop.name: prop for prop in class_info.properties}
            qualified_name = (
                f"{class_info.namespace}.{class_info.name}"
                if class_info.namespace
                else class_info.name
            )
            properties_by_qualified_name.setdefault(qualified_name, properties)
            properties_by_class_name.setdefault(class_info.name, properties)

    for view_result in razor_results:
        model_type = _model_type_of(view_result)
        if not model_type:
            continue
        class_name = model_type.rsplit(".", 1)[-1]
        properties = properties_by_qualified_name.get(model_type) or properties_by_class_name.get(class_name)
        if not properties:
            continue
        for entry in view_result.ui_fields:
            _resolve_entry(entry, properties, project_root)


def _model_type_of(view_result: FileAnalysisResult) -> str:
    for dependency in view_result.dependencies:
        if dependency.startswith(_MODEL_DEPENDENCY_PREFIX):
            return dependency[len(_MODEL_DEPENDENCY_PREFIX):]
    return ""


def _resolve_entry(
    entry: Dict, properties: Dict[str, PropertyInfo], project_root: Path
) -> None:
    if entry.get("text") or entry.get("unresolved_reason"):
        return
    data_field = entry.get("data_field")
    if not data_field:
        return
    prop = properties.get(data_field)
    if prop is None:
        entry["unresolved_reason"] = f"model_property_not_found:{data_field}"
        return

    if prop.display_literal_label:
        entry["text"] = prop.display_literal_label
        return

    if prop.display_resource_type and prop.display_resource_key:
        text, reason = resolve_resource_entry(
            project_root, prop.display_resource_type, prop.display_resource_key
        )
        if text:
            entry["text"] = text
        else:
            entry["unresolved_reason"] = reason
