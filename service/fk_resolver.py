# service/fk_resolver.py
"""
資料表關聯解析（S3，無 AI，盡力而為）。

找出與程式碼參照到的資料表「相關」的其他資料表（雙向，可指定層數），支援兩種來源：

  1. PK 命名慣例推論（優先，純讀本機 SQL 快取，不連線）：
     資料庫未建立實際 FK 約束（只用 Primary Key）時，改用「某表的主鍵欄位名稱，
     剛好也出現在其他表當一般欄位」這種命名慣例推論關聯（例如 Customer 表主鍵
     CustomerCode，Order 表也有 CustomerCode 欄位 → 視為相關）。資料來自
     sql_cache_store.py（由 /refresh_sql 落地時，SQLAnalyzer.dump_all_sql_objects()
     已把每張表的 primary_keys 一併存入），純本機比對，不需要即時連線。
  2. 實際 FK 約束（sys.foreign_keys，安全網）：本機快取沒有資料時，才即時連線
     查詢資料庫實際的外鍵約束（適用真的有建 FK 的資料庫）。

設計為「盡力而為」：兩種來源都找不到資料時回傳空結果且不丟例外，
讓無資料庫的純靜態分析仍可正常運作。
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Set

from .sql_cache_store import load_cached


def _normalize_table(name: str) -> str:
    """去除 schema 與中括號，回傳小寫基底表名。"""
    base = (name or "").strip().strip("[]")
    # 取最後一段（去掉 schema，如 dbo.Table → Table）
    base = re.sub(r"^\[?[A-Za-z0-9_]+\]?\.", "", base)
    base = base.strip("[]")
    return base.lower()


def _build_pk_naming_adjacency(cached: Dict) -> tuple[Dict[str, Set[str]], Dict[str, str]]:
    """
    依本機快取的 tables[].primary_keys / columns，建立「PK 命名慣例」推論出的
    無向鄰接表：某表的主鍵欄位名稱，若剛好是另一張表的欄位名稱，視為兩表相關。

    只用「單一主鍵欄位」的表來推論（複合主鍵當關聯鍵容易誤判，跳過較保守）；
    欄位名稱比對忽略大小寫。常見審計欄位（如 CreatedBy 這類非鍵欄位不會出現在
    primary_keys，故不會被當成推論依據，不需要額外排除清單）。
    """
    tables = cached.get("tables", []) or []

    # 每張表的欄位名稱集合（小寫）
    table_columns: Dict[str, Set[str]] = {}
    # 單一主鍵欄位名稱 → 擁有此主鍵的表名清單（可能多表用同名單一主鍵，如都叫 "Id"，
    # 這種過於通用的鍵之後會被過濾）
    pk_owner: Dict[str, List[str]] = {}

    for t in tables:
        name = t.get("name", "")
        if not name:
            continue
        cols = {c.get("name", "").lower() for c in t.get("columns", []) if c.get("name")}
        table_columns[name] = cols
        pks = t.get("primary_keys", []) or []
        if len(pks) == 1:
            pk_owner.setdefault(pks[0].lower(), []).append(name)

    # 過於通用的主鍵名稱（多張表共用同名單一主鍵，如各表都叫 "Id"）不具鑑別性，
    # 會讓幾乎所有表互相「誤連」，故排除只保留恰好由一張表擁有的主鍵名稱。
    distinctive_pks = {pk: owners[0] for pk, owners in pk_owner.items() if len(owners) == 1}

    adj: Dict[str, Set[str]] = {}
    display: Dict[str, str] = {}
    for pk_col, owner_table in distinctive_pks.items():
        owner_norm = _normalize_table(owner_table)
        display.setdefault(owner_norm, owner_table)
        for other_table, cols in table_columns.items():
            if other_table == owner_table:
                continue
            if pk_col in cols:
                other_norm = _normalize_table(other_table)
                display.setdefault(other_norm, other_table)
                adj.setdefault(owner_norm, set()).add(other_norm)
                adj.setdefault(other_norm, set()).add(owner_norm)

    return adj, display


def _fetch_fk_pairs(
    database_alias: Optional[str],
    db_server: Optional[str] = None,
    db_name: Optional[str] = None,
) -> Optional[List[tuple]]:
    """查詢所有 FK（child_table, parent_table）配對。失敗回傳 None。"""
    try:
        from code_analyzer.sql_analyzer import SQLAnalyzer
        analyzer = SQLAnalyzer(database_alias, server=db_server, database_name=db_name)
    except Exception:
        return None

    if not analyzer.connect():
        return None
    try:
        analyzer.cursor.execute(
            "SELECT OBJECT_NAME(parent_object_id), "
            "OBJECT_NAME(referenced_object_id) FROM sys.foreign_keys"
        )
        return [(r[0], r[1]) for r in analyzer.cursor.fetchall()]
    except Exception:
        return None
    finally:
        try:
            analyzer.disconnect()
        except Exception:
            pass


def _bfs_related(
    adj: Dict[str, Set[str]],
    display: Dict[str, str],
    base_tables: List[str],
    depth: int,
    max_related: int,
) -> List[str]:
    """依無向鄰接表，從 base_tables 出發做 BFS，回傳 depth 層內的相關表（不含自己）。"""
    base_norm = {_normalize_table(t) for t in base_tables}
    visited: Set[str] = set(base_norm)
    frontier: Set[str] = set(base_norm)

    related: List[str] = []
    for _ in range(depth):
        next_frontier: Set[str] = set()
        for node in frontier:
            for neigh in adj.get(node, ()):
                if neigh not in visited:
                    visited.add(neigh)
                    next_frontier.add(neigh)
                    related.append(display.get(neigh, neigh))
                    if len(related) >= max_related:
                        return related
        if not next_frontier:
            break
        frontier = next_frontier

    return related


def resolve_fk_related(
    base_tables: List[str],
    database_alias: Optional[str] = None,
    depth: int = 1,
    max_related: int = 50,
    db_server: Optional[str] = None,
    db_name: Optional[str] = None,
) -> List[str]:
    """
    回傳與 base_tables 相關的其他資料表（不含 base_tables 本身）。

    優先讀本機 SQL 快取（sql_cache_store.py，由 /refresh_sql 落地），用 PK 命名慣例
    推論關聯，不需要連線——適合像本專案這樣只用 Primary Key、沒有建立實際 FK
    約束的資料庫。快取不存在時才退回即時連線查詢 sys.foreign_keys（安全網，
    行為與舊版相同，適用真的有建 FK 約束的資料庫）。

    無資料庫、無快取又連線失敗時回傳空清單（不丟例外）。db_server/db_name 由
    呼叫端（catalog）提供；未提供時退回舊行為（查 .env 的 DB_DATABASES/database_alias）。
    """
    if depth < 1 or not base_tables:
        return []

    if database_alias:
        cached = load_cached(database_alias)
        if cached:
            adj, display = _build_pk_naming_adjacency(cached)
            return _bfs_related(adj, display, base_tables, depth, max_related)

    pairs = _fetch_fk_pairs(database_alias, db_server, db_name)
    if not pairs:
        return []

    # 建無向鄰接表（正規化名稱）
    adj = {}
    display = {}  # 正規化名 → 原始顯示名
    for child, parent in pairs:
        if not child or not parent:
            continue
        c, p = _normalize_table(child), _normalize_table(parent)
        display.setdefault(c, child)
        display.setdefault(p, parent)
        adj.setdefault(c, set()).add(p)
        adj.setdefault(p, set()).add(c)

    return _bfs_related(adj, display, base_tables, depth, max_related)
