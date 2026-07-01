# service/sp_fetcher.py
"""
預存程序（SP）定義擷取（盡力而為）。

給定程式呼叫到的 SP 名稱，連線 SQL Server 取得每個 SP 的完整定義
（T-SQL 內文）、參數、引用資料表與複雜度，讓 AI 能看到 SP 實際邏輯。

設計為「盡力而為」：無資料庫設定或連線失敗時回傳空清單、不丟例外。
"""
from __future__ import annotations

from typing import List, Optional


def fetch_sp_definitions(
    sp_names: List[str],
    database_alias: Optional[str] = None,
    max_def_chars: int = 8000,
) -> List[dict]:
    """回傳每個 SP 的定義摘要清單。

    每筆：{name, exists, parameters, tables, complexity, definition, truncated}
    無資料庫或失敗時回傳空清單。
    """
    if not sp_names:
        return []

    try:
        from code_analyzer.sql_analyzer import SQLAnalyzer
        analyzer = SQLAnalyzer(database_alias)
    except Exception:
        return []

    if not analyzer.connect():
        return []

    out: List[dict] = []
    seen: set[str] = set()
    try:
        for raw in sp_names:
            key = (raw or "").strip().lower()
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
                "tables": list(info.referenced_tables),
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
