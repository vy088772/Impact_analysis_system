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
from typing import Dict, FrozenSet, Set, Tuple, Union

from .connection_string_value import (
    ResolvedConnection,
    resolve_connection_string_value,
)

# ResolvedConnection 過去宣告在這個模組裡，現在住在 connection_string_value，
# 因為 appsettings.json 解析器用的是同一個值語法。這裡重新匯出，讓既有的
# `from .webconfig_connection_resolver import ResolvedConnection` 呼叫端不動。
__all__ = [
    "ResolvedConnection",
    "EntryBlocks",
    "WebConfigTables",
    "WebConfigConnections",
    "parse_web_config_connections",
    "parse_web_config_file",
]


@dataclass(frozen=True)
class EntryBlocks:
    """What one namespace of a Web.config stops from above (ticket 06).

    `cleared` is True after a `<clear/>`: nothing above this file reaches the
    application. `removed` holds the case-folded keys of each `<remove>` that
    no later `<add>` of the same file undid.
    """

    cleared: bool = False
    removed: FrozenSet[str] = frozenset()

    def stops(self, key: str) -> bool:
        return self.cleared or key.casefold() in self.removed

    def __bool__(self) -> bool:
        return self.cleared or bool(self.removed)


@dataclass(frozen=True)
class WebConfigTables:
    """一個應用程式從一份 Web.config 讀到的兩張連線查找表，以及它擋下的上層項目。

    app_settings 對應 <appSettings><add key="..." value="..."/></appSettings>，
    connection_strings 對應
    <connectionStrings><add name="..." connectionString="..."/></connectionStrings>。
    app_settings_blocks 與 connection_strings_blocks 記錄 <clear/> 與 <remove>
    對「這份檔案上方」的繼承所造成的阻擋。
    """

    app_settings: Dict[str, ResolvedConnection] = field(default_factory=dict)
    connection_strings: Dict[str, ResolvedConnection] = field(default_factory=dict)
    app_settings_blocks: EntryBlocks = EntryBlocks()
    connection_strings_blocks: EntryBlocks = EntryBlocks()

    def __bool__(self) -> bool:
        return bool(self.app_settings or self.connection_strings)

    @property
    def blocks_inheritance(self) -> bool:
        return bool(self.app_settings_blocks or self.connection_strings_blocks)


@dataclass(frozen=True)
class WebConfigConnections(WebConfigTables):
    """一份 Web.config 解析後的連線查找表，依 XML 命名空間分成兩張獨立的表。

    繼承來的欄位是這份 Web.config 自己的應用程式讀到的結果：根層的 section，
    加上 path 為空或 "." 的 <location> 內的 section。
    for_child_applications 是子應用程式繼承的結果。它不含
    <location inheritInChildApplications="false"> 內的 section，所以那些
    section 裡的 <add>、<clear/> 與 <remove> 都只作用在這份 Web.config 自己的
    應用程式。
    """

    for_child_applications: WebConfigTables = field(default_factory=WebConfigTables)


# 一個 namespace 的 section 名稱、<add> 的鍵屬性與值屬性。<remove> 用鍵屬性。
_APP_SETTINGS = ("appSettings", "key", "value")
_CONNECTION_STRINGS = ("connectionStrings", "name", "connectionString")


class _Section:
    """One <appSettings> or <connectionStrings> element, read in document order.

    IIS applies `<clear/>`, `<remove>`, and `<add>` in the order they appear, so
    a `<remove>` of a key that a later `<add>` declares keeps the later entry.
    """

    def __init__(self, key_attribute: str, value_attribute: str):
        self._key_attribute = key_attribute
        self._value_attribute = value_attribute
        self.entries: Dict[str, ResolvedConnection] = {}
        self.cleared = False
        self.removed: Set[str] = set()

    def read(self, element: ET.Element) -> None:
        for child in element:
            key = child.get(self._key_attribute)
            if child.tag == "clear":
                self.entries.clear()
                self.removed.clear()
                self.cleared = True
            elif child.tag == "remove" and key:
                folded = key.casefold()
                self.entries = {
                    name: value
                    for name, value in self.entries.items()
                    if name.casefold() != folded
                }
                self.removed.add(folded)
            elif child.tag == "add":
                value = child.get(self._value_attribute)
                if not key or not value:
                    continue
                candidate = resolve_connection_string_value(value)
                if candidate.database:
                    self.entries[key] = candidate
                    self.removed.discard(key.casefold())

    @property
    def blocks(self) -> EntryBlocks:
        return EntryBlocks(cleared=self.cleared, removed=frozenset(self.removed))


def _new_sections() -> Dict[tuple, _Section]:
    return {kind: _Section(*kind[1:]) for kind in (_APP_SETTINGS, _CONNECTION_STRINGS)}


def _own_location(location: ET.Element) -> bool:
    """True when a <location> element applies to the application of the file itself."""
    return (location.get("path") or ".").strip() in (".", "")


def _passes_to_children(location: ET.Element) -> bool:
    return (location.get("inheritInChildApplications") or "true").strip().lower() != "false"


def parse_web_config_connections(content: str) -> WebConfigConnections:
    """解析一份 Web.config 內容，回傳 app_settings/connection_strings 兩張表。

    被註解掉的 <add .../> 節點在 ElementTree 解析樹裡不是 element，findall
    找不到它們，所以永遠不會解析出結果。一個值裡解不出資料庫名稱的項目
    （例如純路徑或郵件伺服器設定）也不會出現在回傳結果中。

    <clear/> 與 <remove> 依文件順序套用。<location> 只讀 path 為空或 "." 的
    元素；它的 inheritInChildApplications="false" 讓其中的 section 不傳給
    子應用程式。
    """
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return WebConfigConnections()

    own_application = _new_sections()
    child_applications = _new_sections()

    sections_by_name = {kind[0]: kind for kind in (_APP_SETTINGS, _CONNECTION_STRINGS)}

    def read_section(element: ET.Element, readers: Tuple[Dict[tuple, _Section], ...]) -> None:
        kind = sections_by_name.get(element.tag)
        if kind is not None:
            for sections in readers:
                sections[kind].read(element)

    # Each application reads its sections in one document order. So a later
    # <clear/> at the root also clears an earlier <location> section, for each
    # application that reads that section.
    for child in root:
        if child.tag == "location":
            if _own_location(child):
                readers = (
                    (own_application, child_applications)
                    if _passes_to_children(child)
                    else (own_application,)
                )
                for element in child:
                    read_section(element, readers)
        else:
            read_section(child, (own_application, child_applications))

    own = _tables_of(own_application)
    return WebConfigConnections(
        app_settings=own.app_settings,
        connection_strings=own.connection_strings,
        app_settings_blocks=own.app_settings_blocks,
        connection_strings_blocks=own.connection_strings_blocks,
        for_child_applications=_tables_of(child_applications),
    )


def _tables_of(sections: Dict[tuple, _Section]) -> WebConfigTables:
    return WebConfigTables(
        app_settings=sections[_APP_SETTINGS].entries,
        connection_strings=sections[_CONNECTION_STRINGS].entries,
        app_settings_blocks=sections[_APP_SETTINGS].blocks,
        connection_strings_blocks=sections[_CONNECTION_STRINGS].blocks,
    )


def parse_web_config_file(path: Union[str, Path]) -> WebConfigConnections:
    """方便函式：讀取一個 Web.config 檔案並解析其連線設定。"""
    text = Path(path).read_text(encoding="utf-8-sig")
    return parse_web_config_connections(text)
