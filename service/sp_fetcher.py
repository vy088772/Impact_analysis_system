# service/sp_fetcher.py
"""
預存程序（SP）定義擷取（盡力而為）。

給定程式呼叫到的 SP 名稱，從本機 SQL 快取（sql_cache_store.py，由
「更新 SQL 快取」指令 /refresh_sql 落地）取得每個 SP 的完整定義（T-SQL 內文）、
參數與引用資料表。快取沒有的名稱直接略過，不即時連線 SQL Server 補查——
一個缺口代表快取過期，需要重新 /refresh_sql，而不是默默用即時連線掩蓋它
（見 docs/adr/0011-remove-live-query-fallbacks.md）。

設計為「盡力而為」：無資料庫設定、無快取時回傳空清單，不丟例外。
"""
from __future__ import annotations

from typing import List, Optional

from .sql_cache_store import load_cached
from code_analyzer.sql_analyzer import estimate_complexity_from_definition


def _normalize(name: str) -> str:
    """正規化 SP 名稱以利比對：去除 schema 前綴與方括號、轉小寫。"""
    core = (name or "").strip().replace("[", "").replace("]", "")
    if "." in core:
        core = core.rsplit(".", 1)[-1]
    return core.lower()


def _qualified_node_name(node: dict) -> str:
    schema = str(node.get("schema") or "").strip()
    name = str(node.get("name") or "").strip()
    return f"{schema}.{name}" if schema and name else name


def _graph_tables_for_procedure(cached: dict, procedure_name: str) -> List[str]:
    graph = cached.get("sql_execution_graph") or {}
    nodes = {
        str(node.get("id")): node
        for node in graph.get("nodes", []) or []
        if node.get("id")
    }
    relationships = graph.get("relationships", []) or []
    roots = {
        node_id
        for node_id, node in nodes.items()
        if node.get("type") == "stored_procedure"
        and _normalize(_qualified_node_name(node)) == _normalize(procedure_name)
    }
    queue = list(roots)
    visited: set[str] = set()
    tables: set[str] = set()
    while queue:
        source_id = queue.pop(0)
        if source_id in visited:
            continue
        visited.add(source_id)
        source = nodes.get(source_id, {})
        for relationship in relationships:
            if relationship.get("source") != source_id:
                continue
            relationship_type = relationship.get("type")
            target_id = str(relationship.get("target") or "")
            target = nodes.get(target_id)
            if target is None:
                continue
            if relationship_type in {"contains", "calls"}:
                queue.append(target_id)
            elif relationship_type in {"reads", "writes"}:
                target_type = target.get("type")
                if target_type == "table":
                    tables.add(_qualified_node_name(target))
                elif target_type in {"view", "function", "dml_operation", "unresolved_dynamic_sql"}:
                    queue.append(target_id)
        if source.get("type") in {"view", "function"}:
            continue
    return sorted(table for table in tables if table)


def _from_cache(
    sp_names: List[str],
    database_alias: Optional[str],
    max_def_chars: int,
    db_server: Optional[str] = None,
) -> tuple[List[dict], List[str]]:
    """從本機 SQL 快取查找；回傳 (已找到的定義清單, 快取中找不到的名稱清單)。
    快取本身不存在（從未 /refresh_sql 過）時，全部視為「找不到」。
    db_server 指名要讀哪一台伺服器的快取；省略時由 sql_cache_store 從磁碟回推。
    """
    if not database_alias:
        return [], sp_names

    cached = load_cached(database_alias, server=db_server or "")
    if not cached:
        return [], sp_names

    lookup = {_normalize(p["name"]): p for p in cached.get("procedures", [])}
    found: List[dict] = []
    missing: List[str] = []
    for raw in sp_names:
        p = lookup.get(_normalize(raw))
        if p is None:
            missing.append(raw)
            continue
        definition = p.get("definition", "") or ""
        tables = _graph_tables_for_procedure(cached, raw)
        found.append({
            "name": raw,
            "exists": bool(definition),
            "parameters": p.get("parameters", []),
            "tables": tables,
            "dependency_source": "execution_graph",
            # 複雜度：純字串靜態分析（見 estimate_complexity_from_definition），
            # 不需要即時連線，可直接對快取的 definition 文字計算，故不再留空。
            "complexity": estimate_complexity_from_definition(definition) if definition else "",
            "definition": definition[:max_def_chars],
            "truncated": len(definition) > max_def_chars,
        })
    return found, missing


def fetch_sp_definitions(
    sp_names: List[str],
    database_alias: Optional[str] = None,
    max_def_chars: int = 8000,
    db_server: Optional[str] = None,
    db_name: Optional[str] = None,
) -> List[dict]:
    """回傳每個 SP 的定義摘要清單。

    每筆：{name, exists, parameters, tables, complexity, definition, truncated}
    只讀本機 SQL 快取；快取版的 tables 來自 SQL Execution Graph。快取沒有的
    名稱直接略過，不即時連線補查（見 docs/adr/0011-remove-live-query-fallbacks.md）。
    無資料庫或無快取時回傳空清單。db_name 參數保留供呼叫端相容，本函式不使用它。
    """
    if not sp_names:
        return []

    found, _missing = _from_cache(sp_names, database_alias, max_def_chars, db_server)
    return found

