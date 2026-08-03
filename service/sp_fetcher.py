# service/sp_fetcher.py
"""
預存程序（SP）定義擷取（盡力而為）。

給定程式呼叫到的 SP 名稱，優先從本機 SQL 快取（sql_cache_store.py，由
「更新 SQL 快取」指令 /refresh_sql 落地）取得每個 SP 的完整定義（T-SQL 內文）、
參數與引用資料表；快取沒有時才即時連線 SQL Server 補查（安全網，避免使用者
忘記先跑 /refresh_sql 就整個沒資料）。

設計為「盡力而為」：無資料庫設定、無快取、連線失敗時回傳空清單，不丟例外。
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


def _from_cache(sp_names: List[str], database_alias: Optional[str], max_def_chars: int) -> tuple[List[dict], List[str]]:
    """從本機 SQL 快取查找；回傳 (已找到的定義清單, 快取中找不到的名稱清單)。
    快取本身不存在（從未 /refresh_sql 過）時，全部視為「找不到」交給即時查詢補上。
    """
    if not database_alias:
        return [], sp_names

    cached = load_cached(database_alias)
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


def _from_live_query(
    sp_names: List[str],
    database_alias: Optional[str],
    max_def_chars: int,
    db_server: Optional[str] = None,
    db_name: Optional[str] = None,
) -> List[dict]:
    """即時連線 SQL Server 查詢（快取沒有時的補查路徑）。

    優先用明確提供的 db_server/db_name（由 catalog 逐系統提供）建立連線；
    兩者都未提供時才退回舊行為（查 .env 的 DB_DATABASES/database_alias）。
    """
    if not sp_names:
        return []

    try:
        from code_analyzer.sql_analyzer import SQLAnalyzer
        analyzer = SQLAnalyzer(database_alias, server=db_server, database_name=db_name)
    except Exception:
        return []

    if not analyzer.connect():
        return []

    out: List[dict] = []
    seen: set[str] = set()
    try:
        for raw in sp_names:
            key = _normalize(raw)
            if not key or key in seen:
                continue
            seen.add(key)
            try:
                info = analyzer.quick_analyze_sp(raw)
            except Exception:
                continue
            if not getattr(info, "exists", False):
                out.append({
                    "name": raw, "exists": False, "parameters": [],
                    "tables": [], "complexity": "", "definition": "", "truncated": False,
                })
                continue
            definition = info.definition or ""
            truncated = len(definition) > max_def_chars
            out.append({
                "name": raw,
                "exists": True,
                "parameters": list(info.parameters),
                "tables": [],
                "dependency_source": "unavailable_without_execution_graph",
                "complexity": info.estimated_complexity,
                "definition": definition[:max_def_chars],
                "truncated": truncated,
            })
    finally:
        try:
            analyzer.disconnect()
        except Exception:
            pass
    return out


def fetch_sp_definitions(
    sp_names: List[str],
    database_alias: Optional[str] = None,
    max_def_chars: int = 8000,
    db_server: Optional[str] = None,
    db_name: Optional[str] = None,
) -> List[dict]:
    """回傳每個 SP 的定義摘要清單。

    每筆：{name, exists, parameters, tables, complexity, definition, truncated}
    優先讀本機 SQL 快取；快取版的 tables 來自 SQL Execution Graph。快取沒有的
    名稱才即時連線補查（需 db_server/db_name，由 catalog 提供），即時補查只提供
    SQL object definition，不宣稱 table lineage。無資料庫或全部失敗時回傳空清單。
    """
    if not sp_names:
        return []

    found, missing = _from_cache(sp_names, database_alias, max_def_chars)
    if missing:
        found.extend(_from_live_query(missing, database_alias, max_def_chars, db_server, db_name))
    return found

