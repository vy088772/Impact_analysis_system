# service/dependency_fetcher.py
"""
物件依賴關係（上下游，原生 sys.sql_expression_dependencies）擷取（盡力而為）。

原生依賴關係已在 refresh_sql_cli 時透過 sql_analyzer.SQLAnalyzer.get_all_dependencies()
一次查整個 schema、落地進 sql_cache_store.py 的 "dependencies" 欄位
（{name: {"depends_on":[...], "depended_by":[...]}}，涵蓋 SP/View/Function/Table）。

這支模組負責：給定這支程式關心的物件名稱（sp_names + table_names + udf 名稱），
從快取裡只挑出這些名稱對應的依賴紀錄回傳，避免把整個資料庫的依賴圖塞進單一
程式的分析結果。快取沒有時（尚未 refresh_sql_cli 過）回傳空 dict —— 這裡沒有
即時連線 fallback（原生依賴查詢設計上就是「整個 schema 一次查」，不像 SP 定義
那樣有單物件即時查詢的安全網），純快取讀取，跟 view_fetcher.py 的 cache-only
設計理念一致。
"""
from __future__ import annotations

from typing import Dict, List, Optional

from .sql_cache_store import load_cached


def _normalize(name: str) -> str:
    core = (name or "").strip().replace("[", "").replace("]", "")
    if "." in core:
        core = core.rsplit(".", 1)[-1]
    return core.lower()


def fetch_dependencies(
    object_names: List[str],
    database_alias: Optional[str] = None,
) -> Dict[str, Dict[str, List[str]]]:
    """從 object_names 中挑出快取裡有依賴紀錄的物件，回傳
    {name: {"depends_on": [...], "depended_by": [...]}}。

    - name 使用呼叫端傳入的原始寫法當 key（方便直接對照原始 sp_names/table_names
      清單），比對時忽略大小寫/schema 前綴/方括號。
    - 只回傳「這支程式關心的物件」，不是整個資料庫的依賴圖。
    - 無資料庫或無快取時回傳空 dict（純靜態分析仍可正常運作，不影響主流程）。
    """
    if not object_names or not database_alias:
        return {}

    cached = load_cached(database_alias)
    if not cached:
        return {}

    deps = cached.get("dependencies", {}) or {}
    lookup = {_normalize(k): v for k, v in deps.items()}

    result: Dict[str, Dict[str, List[str]]] = {}
    for raw in object_names:
        key = _normalize(raw)
        entry = lookup.get(key)
        if entry and (entry.get("depends_on") or entry.get("depended_by")):
            result[raw] = entry
    return result
