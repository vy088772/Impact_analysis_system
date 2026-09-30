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
import dataclasses
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from canonical_object_identity import bare_key, parse, part_key  # noqa: E402
from service import sql_cache_store  # noqa: E402

_REFERENCE_TYPES = frozenset({"reads", "writes", "calls"})
_MODULE_LISTS = (
    ("stored_procedure", "procedures"),
    ("view", "views"),
    ("function", "functions"),
)
# 一個 FROM / JOIN 項目的物件寫法：名稱（可含括號、#、@、點），或子查詢的右括號。
_FROM_ITEM_OBJECT = r"(?:[\w#@\[\]\.]+|\))"


@dataclasses.dataclass(frozen=True)
class GraphReport:
    """一份快取的 graph 計數；欄位名就是報告與 JSON 的鍵。"""

    empty_schema_references: int
    references_by_schema_source: Dict[str, int]
    cte_reads: int
    alias_writes: int
    unproven_schema_targets: int


_TOTALED_COUNTS = ("empty_schema_references", "cte_reads", "alias_writes", "unproven_schema_targets")


@dataclasses.dataclass(frozen=True)
class _Reference:
    """一條 reads / writes / calls 關係，連同它的目標 schema 與名稱。"""

    relationship: Dict[str, Any]
    target_id: str
    schema: str
    name: str

    @property
    def schema_source(self) -> str:
        # 關係尚未帶 `schema_source` 欄位時（v7），目標有 schema 算 written。
        return str(self.relationship.get("schema_source") or ("written" if self.schema else ""))


def _module_definitions(payload: Dict[str, Any], nodes: Dict[str, Dict[str, Any]]) -> Dict[str, str]:
    """module node id 到它的定義文字。

    id 從 graph 自己的 module 節點取，不在這裡重組 id 的格式。
    """
    ids: Dict[tuple[str, str, str], str] = {}
    for node_id, node in nodes.items():
        ids[(str(node.get("type")), part_key(node.get("schema")), part_key(node.get("name")))] = node_id
    definitions: Dict[str, str] = {}
    for node_type, key in _MODULE_LISTS:
        for item in payload.get(key) or []:
            written = parse(str(item.get("name") or ""))
            definition = item.get("definition")
            module_id = ids.get((node_type, part_key(item.get("schema") or written.schema), bare_key(written)))
            if module_id is not None and isinstance(definition, str):
                definitions[module_id] = definition
    return definitions


def _references(graph: Dict[str, Any], nodes: Dict[str, Dict[str, Any]]) -> Iterable[_Reference]:
    for relationship in graph.get("relationships") or []:
        if relationship.get("type") not in _REFERENCE_TYPES:
            continue
        target_id = str(relationship.get("target") or "")
        node = nodes.get(target_id)
        if node is not None:
            schema, name = str(node.get("schema") or ""), str(node.get("name") or "")
        else:
            # 一個沒有節點的呼叫目標（未列出的程序）：id 形如 `stored_procedure:schema.name`。
            written = parse(target_id.partition(":")[2])
            schema, name = written.schema, written.name
        yield _Reference(relationship, target_id, schema, name)


def _statement_text(relationship: Dict[str, Any], definitions: Dict[str, str]) -> Optional[str]:
    location = relationship.get("source_location") or {}
    definition = definitions.get(str(location.get("module_id") or ""))
    start, length = location.get("start_offset"), location.get("length")
    if definition is None or not isinstance(start, int) or not isinstance(length, int):
        return None
    return definition[start : start + length]


def _written_as_sql(name: str) -> str:
    """名稱的 regex 寫法，容許 SQL 的方括號。"""
    return r"\[?" + re.escape(name) + r"\]?"


def _is_cte_name(statement: str, name: str) -> bool:
    pattern = rf"(?:\bWITH|,)\s*{_written_as_sql(name)}\s*(?:\([^)]*\))?\s*AS\s*\("
    return re.search(pattern, statement, re.IGNORECASE) is not None


def _is_from_clause_alias(statement: str, name: str) -> bool:
    written = _written_as_sql(name)
    pattern = rf"(?:\bFROM|\bJOIN|,)\s*(?!{written}\b){_FROM_ITEM_OBJECT}\s+(?:AS\s+)?{written}(?![\w.])"
    return re.search(pattern, statement, re.IGNORECASE) is not None


def _schema_counts(references: List[_Reference]) -> tuple[int, Dict[str, int], int]:
    """空 schema 的參照數、按 schema 來源的分組，以及帶 Unproven Schema 標記的目標節點數。"""
    empty = [reference for reference in references if not reference.schema]
    by_source = Counter(reference.schema_source for reference in references)
    return len(empty), dict(by_source), len({reference.target_id for reference in empty})


def _statement_findings(
    references: List[_Reference], nodes: Dict[str, Dict[str, Any]], definitions: Dict[str, str]
) -> tuple[int, int]:
    """CTE 讀取數與別名寫入數，都數相異的（operation, 目標）組合。"""
    cte_reads: set[tuple[str, str]] = set()
    alias_writes: set[tuple[str, str]] = set()
    for reference in references:
        relationship = reference.relationship
        statement = _statement_text(relationship, definitions)
        if statement is None or not reference.name:
            continue
        operation_id = str(relationship.get("source") or "")
        operation_and_target = (operation_id, reference.target_id)
        if relationship["type"] == "reads" and _is_cte_name(statement, reference.name):
            cte_reads.add(operation_and_target)
        operation_type = (nodes.get(operation_id) or {}).get("operation_type")
        if (
            relationship["type"] == "writes"
            and operation_type in ("UPDATE", "DELETE")
            and _is_from_clause_alias(statement, reference.name)
        ):
            alias_writes.add(operation_and_target)
    return len(cte_reads), len(alias_writes)


def report_payload(payload: Dict[str, Any]) -> GraphReport:
    """數一份快取 payload 的 graph；payload 沒有 graph 時各項為 0。"""
    graph = payload.get("sql_execution_graph") or {}
    nodes = {str(node["id"]): node for node in graph.get("nodes") or [] if node.get("id")}
    references = list(_references(graph, nodes))
    empty, by_source, unproven = _schema_counts(references)
    cte_reads, alias_writes = _statement_findings(references, nodes, _module_definitions(payload, nodes))
    return GraphReport(empty, by_source, cte_reads, alias_writes, unproven)


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
            entry.update(dataclasses.asdict(report_payload(data)))
        reports.append(entry)
    return reports


def _counts_text(counts: Dict[str, Any], by_source: Dict[str, int]) -> str:
    sources = ", ".join(f"{source or '(empty)'}={count}" for source, count in sorted(by_source.items()))
    return (
        f"empty_schema={counts['empty_schema_references']} cte_reads={counts['cte_reads']} "
        f"alias_writes={counts['alias_writes']} unproven_targets={counts['unproven_schema_targets']} "
        f"by_source[{sources}]"
    )


def _print_report(reports: List[Dict[str, Any]]) -> None:
    labels = {
        "invalid_cache": "⚠️  快取無效（讀取路徑不會採信），略過",
        "bad_identity": "⚠️  身分無法辨識，略過",
    }
    totals: Counter[str] = Counter()
    source_totals: Counter[str] = Counter()
    for entry in reports:
        identity_text = f"{entry['server']}/{entry['database']}"
        if entry["action"] != "reported":
            label = labels.get(str(entry["action"]), f"⚠️  未知結果（{entry['action']}）")
            detail = f"（{entry['error']}）" if entry.get("error") else ""
            print(f"{label}：{identity_text}{detail}")
            continue
        print(
            f"{identity_text}（graph_version {entry['graph_version']}）："
            f"{_counts_text(entry, entry['references_by_schema_source'])}"
        )
        totals.update({key: entry[key] for key in _TOTALED_COUNTS})
        source_totals.update(entry["references_by_schema_source"])
    if not reports:
        print("找不到任何 SQL 快取檔。")
        return
    print(f"合計：{_counts_text(totals, source_totals)}")


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
