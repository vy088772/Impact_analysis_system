#!/usr/bin/env python3
"""比對兩份 SQL 快取的 sql_execution_graph，排除定義文字不同的 module。

用途：驗證圖建構器的改動（例如 sql-analyzer-batch）沒有改變 graph。
先比每個 module 的 definition 文字；定義相同的 module 才算同一個比對對象。
若有 module 的定義變了，列出它們，並從兩邊的 graph 移除它們的節點與關係，
再比對其餘部分的 nodes、relationships、parse_errors。

用法：
    python tools/compare_sql_cache_graphs.py OLD_CACHE.json NEW_CACHE.json

結束碼：0 表示相等，1 表示有差異。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_MODULE_COLLECTIONS = ("procedures", "views", "functions")
_GRAPH_FIELDS = ("nodes", "relationships", "parse_errors")


def _definitions(cache: dict[str, Any]) -> dict[tuple[str, str, str], str]:
    return {
        (collection, str(item.get("schema") or ""), str(item.get("name") or "")): str(item.get("definition") or "")
        for collection in _MODULE_COLLECTIONS
        for item in cache.get(collection, []) or []
    }


def _changed_modules(old: dict[str, Any], new: dict[str, Any]) -> list[tuple[str, str, str]]:
    old_definitions, new_definitions = _definitions(old), _definitions(new)
    return sorted(
        key
        for key in old_definitions.keys() | new_definitions.keys()
        if old_definitions.get(key) != new_definitions.get(key)
    )


def _touches(entry: Any, module_names: set[str]) -> bool:
    """True when a node, relationship, or parse error mentions a changed module by name."""
    if not module_names:
        return False
    text = json.dumps(entry, ensure_ascii=False)
    return any(json.dumps(name, ensure_ascii=False) in text for name in module_names)


def compare(old: dict[str, Any], new: dict[str, Any]) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Return the changed modules and the graph fields that differ after they are removed."""
    changed = _changed_modules(old, new)
    module_names = {name for _, _, name in changed}
    old_graph, new_graph = old["sql_execution_graph"], new["sql_execution_graph"]
    differing = []
    if old_graph.get("graph_version") != new_graph.get("graph_version"):
        differing.append("graph_version")
    for field in _GRAPH_FIELDS:
        old_kept = [entry for entry in old_graph.get(field, []) if not _touches(entry, module_names)]
        new_kept = [entry for entry in new_graph.get(field, []) if not _touches(entry, module_names)]
        if old_kept != new_kept:
            differing.append(field)
    return changed, differing


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("old_cache", type=Path)
    parser.add_argument("new_cache", type=Path)
    args = parser.parse_args()
    old = json.loads(args.old_cache.read_text(encoding="utf-8"))
    new = json.loads(args.new_cache.read_text(encoding="utf-8"))

    changed, differing = compare(old, new)
    total = len(_definitions(old))
    print(f"modules: {total}; definition changed: {len(changed)}")
    for collection, schema, name in changed:
        print(f"  changed: {collection} {schema}.{name}")
    for field in _GRAPH_FIELDS:
        print(f"{field}: old {len(old['sql_execution_graph'].get(field, []))}, new {len(new['sql_execution_graph'].get(field, []))}")
    if differing:
        print(f"DIFFERENT: {', '.join(differing)}")
        return 1
    print("EQUAL: graph_version, nodes, relationships, parse_errors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
