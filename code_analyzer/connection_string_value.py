# code_analyzer/connection_string_value.py
"""ADO.NET 連線字串「值」的解析（ADR-0008）。

一個連線查找鍵（Web.config 的 key/name、appsettings.json 的
ConnectionStrings 名稱）永遠不是資料庫名稱；真正的 {server, database} 只能
從連線字串的*值*解析出來。Web.config 與 appsettings.json 兩個設定檔格式不同，
但值的語法完全相同，所以這個語法住在這裡一份，兩個解析器各自引用。

這個模組只認識值，不認識設定檔——它不知道 XML，也不知道 JSON，因此新增一種
設定檔格式不會改到它。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class ResolvedConnection:
    """一個連線查找鍵解析後的真實目標。"""

    server: Optional[str] = None
    database: Optional[str] = None


# 連線字串欄位同義字表：
# server / Data Source / Address / Addr -> server
# database / Initial Catalog -> database
#
# 刻意不解析 uid/pwd：ADR-0010 的掃描工具憑證永遠只能來自 SQLServerData.json
# 的 per-server credential override 或全域 DB_AUTH_MODE，絕不能讀取或衍生自
# 被掃描應用程式自己的設定檔。這裡連解析都不做，讓「掃描身分與應用程式憑證
# 無關」這件事在程式碼層級就不可能被繞過，而不是解析出來又靠呼叫方自律不去
# 讀它。
_FIELD_SYNONYMS: Dict[str, str] = {
    "server": "server",
    "data source": "server",
    "address": "server",
    "addr": "server",
    "database": "database",
    "initial catalog": "database",
}


def _parse_connection_string_fields(value: str) -> Dict[str, str]:
    """把 `key1=val1;key2=val2` 形式的連線字串值，解析成同義字表歸一化後的欄位。"""
    fields: Dict[str, str] = {}
    for part in (value or "").split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        raw_key, _, raw_value = part.partition("=")
        canonical = _FIELD_SYNONYMS.get(raw_key.strip().casefold())
        if canonical and canonical not in fields:
            fields[canonical] = raw_value.strip()
    return fields


def resolve_connection_string_value(value: str) -> ResolvedConnection:
    """把一個連線字串值解析成它真正指向的 {server, database}。"""
    fields = _parse_connection_string_fields(value)
    return ResolvedConnection(server=fields.get("server"), database=fields.get("database"))
