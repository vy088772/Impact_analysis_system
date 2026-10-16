"""Resolve a named System to the local scan roots that hold its source.

A System is named in `llamaindex-spec-rag`'s system catalog; its source lives
under this repository's clone root. Two commands need that mapping -- the
wrapper discovery audit and the Coverage Report -- and one rule, in one place,
keeps a System named the same way by both of them.

Nothing here clones, pulls, or scans. It reads the catalog file and resolves
paths that already exist.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from config.settings import settings

from . import repo_manager, scan_store


def scan_cache_state(root: Path) -> Tuple[bool, str]:
    """Whether one scan root has a usable cache, and why not when it has none.

    A command that measures a System must be able to say "not measured, cache is
    stale" instead of quietly reporting zero.
    """
    if scan_store.has_cache(root):
        return True, ""
    status = scan_store.cache_status(root)
    if status == "current":
        return True, ""
    if status == "stale":
        return False, "scan_cache_stale"
    if status == "invalid":
        return False, "scan_cache_invalid"
    return False, "scan_cache_missing"


def default_spec_rag_root() -> Path:
    """The sibling `llamaindex-spec-rag` checkout that holds the system catalog."""
    return Path(settings.AZURE_CLONE_ROOT).resolve().parent.parent.parent / "llamaindex-spec-rag"


def load_system_catalog(spec_rag_root: Path) -> List[dict]:
    """Every System the catalog declares, or an empty list when it cannot be read."""
    catalog_path = Path(spec_rag_root) / "catalog" / "system_catalog.json"
    if not catalog_path.exists():
        return []
    try:
        payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    systems = payload.get("systems", [])
    return [item for item in systems if isinstance(item, dict)] if isinstance(systems, list) else []


def resolve_system_targets(
    systems: Iterable[dict],
    requested_systems: Iterable[str],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """One target per (System, scan root), plus the requested names the catalog lacks.

    A System whose source root does not resolve still yields one target, carrying
    `source_root_unresolved`: a System that reported nothing and a System that
    resolved nothing must never read the same.
    """
    by_id = {
        str(item.get("system_id") or "").strip(): item
        for item in systems
        if str(item.get("system_id") or "").strip()
    }
    requested = [str(item).strip() for item in requested_systems if str(item).strip()]
    selected = requested or list(by_id)
    targets: List[Dict[str, Any]] = []
    not_found: List[str] = []
    for system_id in selected:
        item = by_id.get(system_id)
        if item is None:
            not_found.append(system_id)
            continue
        azure = item.get("azure") or {}
        if not isinstance(azure, dict):
            azure = {}
        roots = repo_manager.peek_scan_roots(azure)
        if not roots:
            targets.append(
                {
                    "system_id": system_id,
                    "root": None,
                    "configured_contract": str(item.get("wrapper_contract") or ""),
                    "reason": "source_root_unresolved",
                }
            )
            continue
        for root in roots:
            targets.append(
                {
                    "system_id": system_id,
                    "root": Path(root),
                    "configured_contract": str(item.get("wrapper_contract") or ""),
                }
            )
    return targets, not_found
