# service/fk_resolver.py
"""
外鍵（FK）關聯資料表解析（S3，無 AI，盡力而為）。

給定程式碼中參照到的資料表，查詢 SQL Server 的 sys.foreign_keys，
找出透過外鍵相連的相關資料表（雙向，可指定層數）。

設計為「盡力而為」：若無資料庫設定或連線失敗，回傳空結果且不丟例外，
讓無資料庫的純靜態分析仍可正常運作。
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Set


def _normalize_table(name: str) -> str:
    """去除 schema 與中括號，回傳小寫基底表名。"""
    base = (name or "").strip().strip("[]")
    # 取最後一段（去掉 schema，如 dbo.Table → Table）
    base = re.sub(r"^\[?[A-Za-z0-9_]+\]?\.", "", base)
    base = base.strip("[]")
    return base.lower()


def _fetch_fk_pairs(database_alias: Optional[str]) -> Optional[List[tuple]]:
    """查詢所有 FK（child_table, parent_table）配對。失敗回傳 None。"""
    try:
        from code_analyzer.sql_analyzer import SQLAnalyzer
        analyzer = SQLAnalyzer(database_alias)
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


def resolve_fk_related(
    base_tables: List[str],
    database_alias: Optional[str] = None,
    depth: int = 1,
    max_related: int = 50,
) -> List[str]:
    """
    回傳與 base_tables 經由外鍵相連的相關資料表（不含 base_tables 本身）。

    無資料庫或查詢失敗時回傳空清單（不丟例外）。
    """
    if depth < 1 or not base_tables:
        return []

    pairs = _fetch_fk_pairs(database_alias)
    if not pairs:
        return []

    # 建無向鄰接表（正規化名稱）
    adj: Dict[str, Set[str]] = {}
    display: Dict[str, str] = {}  # 正規化名 → 原始顯示名
    for child, parent in pairs:
        if not child or not parent:
            continue
        c, p = _normalize_table(child), _normalize_table(parent)
        display.setdefault(c, child)
        display.setdefault(p, parent)
        adj.setdefault(c, set()).add(p)
        adj.setdefault(p, set()).add(c)

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
