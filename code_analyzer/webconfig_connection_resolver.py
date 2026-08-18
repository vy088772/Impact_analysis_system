# code_analyzer/webconfig_connection_resolver.py
"""Web.config 連線字串解析器

解析 Web.config 的 <appSettings> 與 <connectionStrings>，把每一個連線查找鍵
(AppSettings 的 key，或 ConnectionStrings 的 name) 解析成它真正指向的
{server, database}。

與 db_connection_tracker.py 舊有「模式4」的關鍵差異：模式4把程式碼裡查找連線
時使用的 key 本身（例如 "error"）當成資料庫名稱；這個模組永遠解析連線字串的
*值*（例如 "server=vmsystest07;...;DataBase=SysErrorRecord"），因為 key 與
真正的資料庫名稱經常不同。

使用真正的 XML 解析器（xml.etree.ElementTree），所以被註解掉的
<!-- <add .../> --> 節點在解析樹裡根本不存在，永遠不會被誤判為有效連線。

ADR-0008：<appSettings> 的 key 與 <connectionStrings> 的 name 是兩個獨立的
XML 命名空間——即使字面上撞名，也可能指向不同的連線。解析結果因此保持成兩張
分開的表，各自配對到產生查找鍵的 C# 存取式
（ConfigurationManager.AppSettings["x"] 對應 app_settings；
ConfigurationManager.ConnectionStrings["x"].ConnectionString 對應
connection_strings），絕不合併成一張平面表格。
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Union


@dataclass(frozen=True)
class ResolvedConnection:
    """一個連線查找鍵解析後的真實目標。"""

    server: Optional[str] = None
    database: Optional[str] = None


@dataclass(frozen=True)
class WebConfigConnections:
    """一份 Web.config 解析後的連線查找表，依 XML 命名空間分成兩張獨立的表。

    app_settings 對應 <appSettings><add key="..." value="..."/></appSettings>，
    connection_strings 對應
    <connectionStrings><add name="..." connectionString="..."/></connectionStrings>。
    """

    app_settings: Dict[str, ResolvedConnection] = field(default_factory=dict)
    connection_strings: Dict[str, ResolvedConnection] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.app_settings or self.connection_strings)


# 連線字串欄位同義字表：
# server / Data Source / Address / Addr -> server
# database / Initial Catalog -> database
# uid / User ID -> uid
# pwd / Password -> pwd
#
# uid/pwd 目前只被解析出來、歸一化，尚未有任何呼叫方讀取——ADR-0010 的掃描工具
# 憑證覆寫（per (server, database) 的 credential override）之後會用到，這裡先
# 把同義字規則做完整，留給那張票直接使用，而不是這裡先丟棄再讓那張票重新解析
# 一次連線字串。
_FIELD_SYNONYMS: Dict[str, str] = {
    "server": "server",
    "data source": "server",
    "address": "server",
    "addr": "server",
    "database": "database",
    "initial catalog": "database",
    "uid": "uid",
    "user id": "uid",
    "pwd": "pwd",
    "password": "pwd",
}


def _parse_fields(value: str) -> Dict[str, str]:
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


def _resolve_value(value: str) -> ResolvedConnection:
    fields = _parse_fields(value)
    return ResolvedConnection(server=fields.get("server"), database=fields.get("database"))


def parse_web_config_connections(content: str) -> WebConfigConnections:
    """解析一份 Web.config 內容，回傳 app_settings/connection_strings 兩張表。

    被註解掉的 <add .../> 節點在 ElementTree 解析樹裡不是 element，findall
    找不到它們，所以永遠不會解析出結果。一個值裡解不出資料庫名稱的項目
    （例如純路徑或郵件伺服器設定）也不會出現在回傳結果中。
    """
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return WebConfigConnections()

    app_settings: Dict[str, ResolvedConnection] = {}
    for add in root.findall("./appSettings/add"):
        key = add.get("key")
        value = add.get("value")
        if not key or not value:
            continue
        candidate = _resolve_value(value)
        if candidate.database:
            app_settings[key] = candidate

    connection_strings: Dict[str, ResolvedConnection] = {}
    for add in root.findall("./connectionStrings/add"):
        name = add.get("name")
        conn_str = add.get("connectionString")
        if not name or not conn_str:
            continue
        candidate = _resolve_value(conn_str)
        if candidate.database:
            connection_strings[name] = candidate

    return WebConfigConnections(app_settings=app_settings, connection_strings=connection_strings)


def parse_web_config_file(path: Union[str, Path]) -> WebConfigConnections:
    """方便函式：讀取一個 Web.config 檔案並解析其連線設定。"""
    text = Path(path).read_text(encoding="utf-8-sig")
    return parse_web_config_connections(text)
