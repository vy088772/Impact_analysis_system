# service/udf_fetcher.py
"""
使用者定義函數（UDF）依程式篩選（cache-only，盡力而為）。

靜態程式碼分析目前沒有專門的「UDF 呼叫關聯」偵測（不像 database invocation 那樣
逐一比對呼叫樣式），但 C# 解析本來就會把程式裡內嵌的 SQL 查詢文字整段擷取出來
（FileAnalysisResult.sql_queries，見 csharp_parser.py）。這支模組改用「比對」而
非「解析」的方式：從本機 SQL 快取（sql_cache_store.py，由 refresh_sql_cli 落地）
取得整庫實際存在的 UDF 名稱清單，逐一比對是否以「函數呼叫」的形式
（FunctionName(...)）出現在該程式自己的 SQL 查詢文字裡，藉此在不新增靜態解析
規則、不遞增掃描快取版本的前提下做到「依程式篩選相關 UDF」。

只讀本機快取，不即時連線（原因同 view_fetcher.py：對每個候選名稱都連線判斷是否
存在太耗時）。
"""
from __future__ import annotations

import re
from typing import List, Optional

from .sql_cache_store import load_cached


def _normalize(name: str) -> str:
    core = (name or "").strip().replace("[", "").replace("]", "")
    if "." in core:
        core = core.rsplit(".", 1)[-1]
    return core.lower()


def fetch_udf_definitions(
    sql_texts: List[str],
    database_alias: Optional[str] = None,
    max_def_chars: int = 8000,
) -> List[dict]:
    """從程式自己的 SQL 查詢文字中，比對出實際有呼叫到的 UDF，回傳其完整定義。

    sql_texts：該程式（已比對到的檔案）內嵌的原始 SQL 查詢文字清單（來自
    FileAnalysisResult.sql_queries 的 query_text），用來判斷「這支程式的 SQL
    裡有沒有出現這個 UDF 名稱」。

    每筆：{name, exists, definition, parameters, return_type, truncated}。
    只回傳「確實在該程式 SQL 文字裡以函數呼叫形式出現」的 UDF（名稱後緊接左括號，
    避免欄位名稱恰好跟函數同名卻沒有實際呼叫的誤判）；無資料庫、無快取、或程式
    本身沒有 SQL 查詢文字時回傳空清單（不影響主流程）。
    """
    if not sql_texts or not database_alias:
        return []

    cached = load_cached(database_alias)
    if not cached:
        return []

    functions = cached.get("functions", [])
    if not functions:
        return []

    blob = "\n".join(t for t in sql_texts if t)
    if not blob:
        return []

    found: List[dict] = []
    for fn in functions:
        name = fn.get("name", "")
        if not _normalize(name):
            continue
        # 函數呼叫形式：（可能的 schema 前綴/中括號）名稱 + 左括號
        call_pattern = re.compile(
            r"(?:\[?\w+\]?\.)?\[?" + re.escape(name) + r"\]?\s*\(", re.IGNORECASE
        )
        if not call_pattern.search(blob):
            continue
        definition = fn.get("definition", "") or ""
        found.append({
            "name": name,
            "exists": bool(definition),
            "definition": definition[:max_def_chars],
            "parameters": fn.get("parameters", []),
            "return_type": fn.get("return_type", ""),
            "truncated": len(definition) > max_def_chars,
        })
    return found
