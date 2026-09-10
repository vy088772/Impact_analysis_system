"""A model property's [Display(ResourceType=..., Name=...)] names an entry in a
.resx resource file rather than carrying its own label text (issue 11,
`.scratch/aspnet-mvc-core-analysis/`). This module resolves that entry.

A missing file, an unreadable file, or a missing key are all real, disclosable
outcomes here — never silently substituted with the raw key, which would read
as a proven label when it is really a broken reference.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple
from xml.etree import ElementTree


def resolve_resource_entry(
    project_root: Path, resource_type: str, key: str
) -> Tuple[Optional[str], Optional[str]]:
    """Look up `key` inside the .resx file matching `resource_type`.

    Returns (text, reason) — exactly one is ever populated. `resource_type` is
    matched against the .resx file's base name (its generated designer class
    name), searched anywhere under `project_root`; the first match on a sorted
    walk wins so the result stays deterministic if more than one exists.
    """
    simple_name = resource_type.rsplit(".", 1)[-1]
    matches = sorted(project_root.rglob(f"{simple_name}.resx"))
    if not matches:
        return None, f"resource_file_not_found:{simple_name}.resx"

    try:
        tree = ElementTree.parse(matches[0])
    except ElementTree.ParseError:
        return None, f"resource_file_unreadable:{matches[0].name}"

    for data_element in tree.getroot().findall("data"):
        if data_element.get("name") != key:
            continue
        value_element = data_element.find("value")
        text = value_element.text.strip() if value_element is not None and value_element.text else ""
        if text:
            return text, None
        return None, f"resource_entry_empty:{key}"

    return None, f"resource_entry_missing:{key}"
