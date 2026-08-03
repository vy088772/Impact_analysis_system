# service/view_fetcher.py
"""
SQL View（檢視表）定義擷取（盡力而為）。

程式碼靜態分析目前不會區分「資料表」與「View」——兩者都以 SELECT/FROM 的方式
被存取，因此都落在 inline SQL facts（program 的 `tables` 清單）裡。這支模組
負責：給定一批表名，從本機 SQL 快取（sql_cache_store.py）比對出其中「其實是
View」的項目，回傳其完整定義（讓 AI 看得到 View 實際查詢邏輯，而不只是表名）。

快取沒有時才即時連線 SQL Server 補查（安全網，行為與 sp_fetcher.py 一致）。
"""
from __future__ import annotations

from typing import List, Optional

from .sql_cache_store import load_cached


def _normalize(name: str) -> str:
    core = (name or "").strip().replace("[", "").replace("]", "")
    if "." in core:
        core = core.rsplit(".", 1)[-1]
    return core.lower()


def _from_cache(table_names: List[str], database_alias: Optional[str], max_def_chars: int) -> tuple[List[dict], List[str]]:
    if not database_alias:
        return [], []  # 無資料庫可查，視為「無法判斷」，不當作快取缺漏去即時連線（避免誤連）

    cached = load_cached(database_alias)
    if not cached:
        return [], []

    view_names = {_normalize(v["name"]) for v in cached.get("views", [])}
    lookup = {_normalize(v["name"]): v for v in cached.get("views", [])}

    found: List[dict] = []
    for raw in table_names:
        key = _normalize(raw)
        if key not in view_names:
            continue  # 不是 View（是一般資料表或快取未涵蓋），跳過
        v = lookup[key]
        definition = v.get("definition", "") or ""
        found.append({
            "name": raw,
            "exists": bool(definition),
            "definition": definition[:max_def_chars],
            "truncated": len(definition) > max_def_chars,
        })
    return found, []


def fetch_view_definitions(
    table_names: List[str],
    database_alias: Optional[str] = None,
    max_def_chars: int = 8000,
) -> List[dict]:
    """從 table_names 中挑出「其實是 View」的項目，回傳其完整定義清單。

    每筆：{name, exists, definition, truncated}。不是 View 的名稱不會出現在結果
    裡（沒有「不存在」的空白項目，避免跟一般資料表混淆）。無資料庫或無快取時
    回傳空清單（純資料表分析仍可正常運作，不影響主流程）。
    """
    if not table_names:
        return []
    found, _ = _from_cache(table_names, database_alias, max_def_chars)
    return found
