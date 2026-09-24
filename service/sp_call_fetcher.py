# service/sp_call_fetcher.py
"""
SP 內部呼叫其他 SP（巢狀 EXEC）依定義文字比對（cache-only，盡力而為）。

靜態程式碼分析目前沒有「SP 呼叫 SP」的結構化關聯（sql_analyzer.py 只有
_quick_extract_tables 這種表名擷取，沒有解析 EXEC/EXECUTE 呼叫的其他 SP）。這支
模組比照 udf_fetcher.py 已驗證過的做法：從本機 SQL 快取（sql_cache_store.py，
由 refresh_sql_cli 落地）取得整庫已知的 SP 名稱清單，逐一比對是否以
EXEC/EXECUTE 呼叫形式出現在「給定的某支 SP 自己的定義文字」裡——藉此在不新增
即時資料庫查詢、不需要真正解析 T-SQL 語法樹的前提下，做到「這支 SP 內部呼叫了
哪些其他 SP」。

只讀本機快取，不即時連線（原因同 udf_fetcher.py：對每個候選 SP 逐一連線判斷
太耗時）；只回傳「確實存在於本機快取 SP 名單裡」的名稱，避免把 sp_executesql
這類系統預存程序、或動態 SQL 變數（EXEC @sql）誤判成真正的巢狀呼叫。
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


def _bare_name(name: str) -> str:
    """去除 schema 前綴與中括號，但保留原始大小寫（供組 regex 用；比對本身仍靠
    re.IGNORECASE，不需要靠這裡轉大小寫）。快取裡的 SP 名稱格式不一致——有些是
    純名稱（如 `sp_SO_Delete_Edit1`），有些整個是 `[dbo].[usp_Xxx]`——都要能正確
    比對，所以統一先取出「裸名稱」再組 pattern，而不是直接對整個原始字串跳脫。
    """
    core = (name or "").strip().replace("[", "").replace("]", "")
    if "." in core:
        core = core.rsplit(".", 1)[-1]
    return core


def fetch_called_sp_names(
    sp_definition: str,
    database_alias: Optional[str] = None,
    exclude_name: str = "",
    db_server: Optional[str] = None,
) -> List[str]:
    """從某支 SP 自己的定義文字中，比對出它實際以 EXEC/EXECUTE 呼叫到的其他已知
    SP 名稱清單（只回傳名稱本身，不含完整定義——呼叫端可再用這些名稱透過
    sp_fetcher/本機快取取得各自的完整定義，逐層組成巢狀呼叫鏈）。

    sp_definition：該支 SP 自己的完整 T-SQL 定義文字。
    database_alias：要讀哪一份 SQL 快取的資料庫名稱。
    db_server：那份快取所在的伺服器；省略時由 sql_cache_store 從磁碟回推。
    exclude_name：排除這個名稱本身（避免自我遞迴這種邊界情況誤判為呼叫自己）。

    只比對「EXEC/EXECUTE + （可能的 schema 前綴）+ 名稱」這種明確呼叫形式，且該
    名稱必須存在於本機 SQL 快取的整庫 SP 名單裡——避免誤把系統預存程序（如
    sp_executesql）、動態 SQL 變數（EXEC @sql）當成真正的巢狀呼叫；無資料庫、
    無快取、或本身無定義文字時回傳空清單，不影響主流程。
    """
    if not sp_definition or not database_alias:
        return []

    cached = load_cached(database_alias, server=db_server or "")
    if not cached:
        return []

    procedures = cached.get("procedures", [])
    if not procedures:
        return []

    exclude_core = _normalize(exclude_name)
    # 先移除註解，避免「EXEC 只出現在註解裡」被誤判為真的呼叫
    text = re.sub(r"--.*?$", "", sp_definition, flags=re.MULTILINE)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)

    found: List[str] = []
    seen: set[str] = set()
    for proc in procedures:
        name = proc.get("name", "")
        core = _normalize(name)
        if not core or core == exclude_core or core in seen:
            continue
        bare = _bare_name(name)
        if not bare:
            continue
        # 用「裸名稱」（已去除 schema 前綴與中括號）組 pattern，前面允許可選的
        # schema 前綴/中括號，結尾用「後面不是單字字元」取代 \b——因為裸名稱
        # 前後可能緊接中括號（如 `[usp_Xxx]`），而 `]` 不是單字字元，\b 在
        # 「非單字字元」與「非單字字元」之間不會成立，會導致帶中括號的名稱
        # 永遠比對不到。
        call_pattern = re.compile(
            r"\bEXEC(?:UTE)?\s+(?:\[?\w+\]?\.)?\[?" + re.escape(bare) + r"\]?(?!\w)",
            re.IGNORECASE,
        )
        if call_pattern.search(text):
            found.append(name)
            seen.add(core)
    return found
