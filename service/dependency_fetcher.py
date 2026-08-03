# service/dependency_fetcher.py
"""Compatibility adapter for SQL Execution Graph dependencies.

Formal callers must query the typed SQL Execution Graph. The old
``sql_expression_dependencies`` and ``write_dependencies`` cache dictionaries
remain available only for migration comparison and are deliberately ignored
here; this module never turns those legacy indexes into formal lineage.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional


def _normalize(name: str) -> str:
    core = (name or "").strip().replace("[", "").replace("]", "")
    if "." in core:
        core = core.rsplit(".", 1)[-1]
    return core.lower()


def fetch_dependencies(
    object_names: List[str],
    database_alias: Optional[str] = None,
    *,
    graph: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Dict[str, List[str]]]:
    """Return graph-backed direct dependencies in the legacy result shape.

    ``database_alias`` is retained for source compatibility only. Without an
    explicit graph this function returns an empty result instead of silently
    loading a stale dependency dictionary.
    """
    if not object_names or not graph:
        return {}

    result: Dict[str, Dict[str, List[str]]] = {}
    nodes = {
        str(node.get("id")): node
        for node in graph.get("nodes", []) or []
        if node.get("id")
    }
    outgoing: Dict[str, List[str]] = {}
    incoming: Dict[str, List[str]] = {}
    for relationship in graph.get("relationships", []) or []:
        source = str(relationship.get("source") or "")
        target = str(relationship.get("target") or "")
        if not source or not target:
            continue
        if relationship.get("type") not in {"calls", "reads", "writes", "uses"}:
            continue
        outgoing.setdefault(source, []).append(target)
        incoming.setdefault(target, []).append(source)

    for raw in object_names:
        node_id = _find_node_id(nodes, raw)
        if not node_id:
            continue
        depends_on = _node_names(outgoing.get(node_id, []), nodes)
        depended_by = _node_names(incoming.get(node_id, []), nodes)
        if depends_on or depended_by:
            result[raw] = {
                "depends_on": depends_on,
                "depended_by": depended_by,
            }
    return result


def _find_node_id(nodes: Mapping[str, Mapping[str, Any]], name: str) -> str:
    target = _normalize(name)
    for node_id, node in nodes.items():
        if _normalize(str(node.get("name") or "")) == target:
            return node_id
    return ""


def _node_names(node_ids: Iterable[str], nodes: Mapping[str, Mapping[str, Any]]) -> List[str]:
    names: List[str] = []
    seen = set()
    for node_id in node_ids:
        node = nodes.get(node_id)
        name = str(node.get("name") or "") if node else ""
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return names
