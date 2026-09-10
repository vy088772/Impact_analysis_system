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
from typing import Dict, Union

from .connection_string_value import (
    ResolvedConnection,
    resolve_connection_string_value,
)

# ResolvedConnection 過去宣告在這個模組裡，現在住在 connection_string_value，
# 因為 appsettings.json 解析器用的是同一個值語法。這裡重新匯出，讓既有的
# `from .webconfig_connection_resolver import ResolvedConnection` 呼叫端不動。
__all__ = [
    "ResolvedConnection",
    "WebConfigConnections",
    "parse_web_config_connections",
    "parse_web_config_file",
]


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
        candidate = resolve_connection_string_value(value)
        if candidate.database:
            app_settings[key] = candidate

    connection_strings: Dict[str, ResolvedConnection] = {}
    for add in root.findall("./connectionStrings/add"):
        name = add.get("name")
        conn_str = add.get("connectionString")
        if not name or not conn_str:
            continue
        candidate = resolve_connection_string_value(conn_str)
        if candidate.database:
            connection_strings[name] = candidate

    return WebConfigConnections(app_settings=app_settings, connection_strings=connection_strings)


def parse_web_config_file(path: Union[str, Path]) -> WebConfigConnections:
    """方便函式：讀取一個 Web.config 檔案並解析其連線設定。"""
    text = Path(path).read_text(encoding="utf-8-sig")
    return parse_web_config_connections(text)
