"""A [Display(ResourceType=..., Name=...)] entry resolves through a .resx file
(issue 11, `.scratch/aspnet-mvc-core-analysis/`). A missing file, an unreadable
file, and a missing key are each disclosed by their own reason — never by
silently handing back the raw key.
"""

from __future__ import annotations

from pathlib import Path

from code_analyzer.resource_file_resolver import resolve_resource_entry


_RESX = """<?xml version="1.0" encoding="utf-8"?>
<root>
    <data name="OrderNo">
        <value>訂單編號</value>
    </data>
    <data name="Blank">
        <value></value>
    </data>
</root>
"""


def _write_resx(tmp_path: Path, relative: str = "Resources/SharedResource.resx") -> Path:
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_RESX, encoding="utf-8")
    return path


def test_an_existing_entry_resolves_its_text(tmp_path: Path) -> None:
    _write_resx(tmp_path)

    text, reason = resolve_resource_entry(tmp_path, "SharedResource", "OrderNo")

    assert text == "訂單編號"
    assert reason is None


def test_a_qualified_resource_type_is_matched_by_its_class_name(tmp_path: Path) -> None:
    _write_resx(tmp_path)

    text, reason = resolve_resource_entry(tmp_path, "Resources.SharedResource", "OrderNo")

    assert text == "訂單編號"
    assert reason is None


def test_a_missing_resource_file_contributes_nothing_and_says_why(tmp_path: Path) -> None:
    text, reason = resolve_resource_entry(tmp_path, "SharedResource", "OrderNo")

    assert text is None
    assert reason == "resource_file_not_found:SharedResource.resx"


def test_a_missing_key_contributes_nothing_and_says_why(tmp_path: Path) -> None:
    _write_resx(tmp_path)

    text, reason = resolve_resource_entry(tmp_path, "SharedResource", "NoSuchKey")

    assert text is None
    assert reason == "resource_entry_missing:NoSuchKey"


def test_an_empty_entry_contributes_nothing_and_says_why(tmp_path: Path) -> None:
    _write_resx(tmp_path)

    text, reason = resolve_resource_entry(tmp_path, "SharedResource", "Blank")

    assert text is None
    assert reason == "resource_entry_empty:Blank"
