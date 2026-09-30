#!/usr/bin/env python3
"""報告每一份 SQL 快取裡的 sql_execution_graph 目前記錄了什麼——不連線 SQL Server、
不改動任何快取檔。

`.scratch/unstated-schema-resolves-as-sql-server-does/` 的驗收工具：重建 graph
（graph_version 8）之前先跑一次留下 v7 基準，重建之後再跑一次比較。每份快取數：

- empty_schema_references：目標沒有 schema 的 reads / writes / calls 關係數；
- references_by_schema_source：上述關係按 schema 來源分組。關係尚未帶
  `schema_source` 欄位時（v7），目標有 schema 算 `written`，沒有算 `""`；
- cte_reads：把 CTE 名稱當成資料表的讀取數。同一個陳述式讀同一個名稱多次只算一次（數（operation, 目標）組合）；
- alias_writes：UPDATE / DELETE 的目標其實是同一個陳述式 FROM 子句別名的寫入數，計法同上；
- unproven_schema_targets：帶 Unproven Schema 標記的目標節點數（沒有 schema，每個節點算一次）。

CTE 與別名兩項都從關係的 source_location 切出陳述式原文來判斷；沒有 source_location
的關係不計入這兩項。這是計數用的近似，不是 SQL 解析器。

用法：
    python tools/rebuild_report.py [--cache-root data/sql_cache] [--json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from canonical_object_identity import parse  # noqa: E402
from service import sql_cache_store  # noqa: E402

_REFERENCE_TYPES = frozenset({"reads", "writes", "calls"})
_MODULE_LISTS = (
    ("stored_procedure", "procedures"),
    ("view", "views"),
    ("function", "functions"),
)
_OBJECT_TOKEN = r"(?:[\w#@\[\]\.]+|\))"


def _module_definitions(payload: Dict[str, Any]) -> Dict[str, str]:
    """module id（`stored_procedure:BSPL.sp_BSprocess`）到它的定義文字。"""
    definitions: Dict[str, str] = {}
    for node_type, key in _MODULE_LISTS:
        for item in payload.get(key) or []:
            definition = item.get("definition")
            if isinstance(definition, str):
                written = parse(str(item.get("name") or ""))
                schema = item.get("schema") or written.schema
                definitions[f"{node_type}:{schema}.{written.name}"] = definition
    return definitions


def _statement_text(relationship: Dict[str, Any], definitions: Dict[str, str]) -> Optional[str]:
    location = relationship.get("source_location") or {}
    definition = definitions.get(str(location.get("module_id") or ""))
    start, length = location.get("start_offset"), location.get("length")
    if definition is None or not isinstance(start, int) or not isinstance(length, int):
        return None
    return definition[start : start + length]


def _target_schema_and_name(target_id: str, nodes: Dict[str, Dict[str, Any]]) -> tuple[str, str]:
    node = nodes.get(target_id)
    if node is not None:
        return str(node.get("schema") or ""), str(node.get("name") or "")
    # 一個沒有節點的呼叫目標（未列出的程序）：id 形如 `stored_procedure:schema.name`。
    _, _, qualified = target_id.partition(":")
    schema, dot, name = qualified.partition(".")
    return (schema, name) if dot else ("", qualified)


def _is_cte_name(statement: str, name: str) -> bool:
    bare = r"\[?" + re.escape(name) + r"\]?"
    pattern = rf"(?:\bWITH|,)\s*{bare}\s*(?:\([^)]*\))?\s*AS\s*\("
    return re.search(pattern, statement, re.IGNORECASE) is not None


def _is_from_clause_alias(statement: str, name: str) -> bool:
    bare = r"\[?" + re.escape(name) + r"\]?"
    pattern = rf"(?:\bFROM|\bJOIN|,)\s*(?!{bare}\b){_OBJECT_TOKEN}\s+(?:AS\s+)?{bare}(?![\w.])"
    return re.search(pattern, statement, re.IGNORECASE) is not None


def report_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """數一份快取 payload 的 graph；payload 沒有 graph 時各項為 0。"""
    graph = payload.get("sql_execution_graph") or {}
    nodes = {str(node["id"]): node for node in graph.get("nodes") or [] if node.get("id")}
    definitions = _module_definitions(payload)

    empty_schema = 0
    by_source: Counter[str] = Counter()
    cte_reads: set[tuple[str, str]] = set()
    alias_writes: set[tuple[str, str]] = set()
    unproven_targets: set[str] = set()

    for relationship in graph.get("relationships") or []:
        relationship_type = relationship.get("type")
        if relationship_type not in _REFERENCE_TYPES:
            continue
        target_id = str(relationship.get("target") or "")
        schema, name = _target_schema_and_name(target_id, nodes)
        by_source[str(relationship.get("schema_source") or ("written" if schema else ""))] += 1
        if not schema:
            empty_schema += 1
            unproven_targets.add(target_id)

        statement = _statement_text(relationship, definitions)
        if statement is None or not name:
            continue
        operation_and_target = (str(relationship.get("source") or ""), target_id)
        if relationship_type == "reads" and _is_cte_name(statement, name):
            cte_reads.add(operation_and_target)
        if relationship_type == "writes" and _is_from_clause_alias_write(
            relationship, nodes, statement, name
        ):
            alias_writes.add(operation_and_target)

    return {
        "empty_schema_references": empty_schema,
        "references_by_schema_source": dict(by_source),
        "cte_reads": len(cte_reads),
        "alias_writes": len(alias_writes),
        "unproven_schema_targets": len(unproven_targets),
    }


def _is_from_clause_alias_write(
    relationship: Dict[str, Any], nodes: Dict[str, Dict[str, Any]], statement: str, name: str
) -> bool:
    operation = nodes.get(str(relationship.get("source") or "")) or {}
    if operation.get("operation_type") not in ("UPDATE", "DELETE"):
        return False
    return _is_from_clause_alias(statement, name)


def report_all_caches() -> List[Dict[str, Any]]:
    """數目前快取根目錄底下每一份快取；只走 list_caches() 的清單、只讀磁碟。

    讀取路徑不採信的快取（版本、Database 不符）回報 `invalid_cache` 並略過——
    這份報告要說的是查詢會看到的 graph。
    """
    reports: List[Dict[str, Any]] = []
    for row in sql_cache_store.list_caches():
        entry: Dict[str, Any] = {"server": row.server, "database": row.database}
        try:
            identity = sql_cache_store.CacheIdentity.of(row.server, row.database)
        except ValueError as exc:
            entry.update(action="bad_identity", error=str(exc))
            reports.append(entry)
            continue
        data = sql_cache_store.load_cached(identity)
        if data is None:
            entry["action"] = "invalid_cache"
        else:
            entry["action"] = "reported"
            entry["graph_version"] = (data.get("sql_execution_graph") or {}).get("graph_version")
            entry.update(report_payload(data))
        reports.append(entry)
    return reports


def _print_report(reports: List[Dict[str, Any]]) -> None:
    totals: Counter[str] = Counter()
    source_totals: Counter[str] = Counter()
    for entry in reports:
        identity_text = f"{entry['server']}/{entry['database']}"
        if entry["action"] != "reported":
            print(f"⚠️  {identity_text}：{entry['action']}{'（' + entry['error'] + '）' if entry.get('error') else ''}")
            continue
        sources = ", ".join(
            f"{source or '(empty)'}={count}"
            for source, count in sorted(entry["references_by_schema_source"].items())
        )
        print(
            f"{identity_text}（graph_version {entry['graph_version']}）："
            f"empty_schema={entry['empty_schema_references']} "
            f"cte_reads={entry['cte_reads']} alias_writes={entry['alias_writes']} "
            f"unproven_targets={entry['unproven_schema_targets']} by_source[{sources}]"
        )
        for key in ("empty_schema_references", "cte_reads", "alias_writes", "unproven_schema_targets"):
            totals[key] += entry[key]
        source_totals.update(entry["references_by_schema_source"])
    if not reports:
        print("找不到任何 SQL 快取檔。")
        return
    sources = ", ".join(f"{source or '(empty)'}={count}" for source, count in sorted(source_totals.items()))
    print(
        f"合計：empty_schema={totals['empty_schema_references']} cte_reads={totals['cte_reads']} "
        f"alias_writes={totals['alias_writes']} unproven_targets={totals['unproven_schema_targets']} "
        f"by_source[{sources}]"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="報告每一份 SQL 快取的 graph 目前記錄了什麼")
    parser.add_argument("--cache-root", default=None, help="SQL 快取根目錄（預設讀 settings.SQL_CACHE_ROOT）")
    parser.add_argument("--json", action="store_true", help="輸出 JSON")
    args = parser.parse_args()

    from config.settings import settings

    if args.cache_root:
        settings.SQL_CACHE_ROOT = args.cache_root

    reports = report_all_caches()
    if args.json:
        print(json.dumps(reports, ensure_ascii=False, indent=2))
    else:
        _print_report(reports)


if __name__ == "__main__":
    main()
