# code_analyzer/appsettings_connection_resolver.py
"""appsettings.json 連線字串解析器

解析一份 ASP.NET Core 的 appsettings.json，把 `ConnectionStrings` 區段裡每一個
具名連線字串解析成它真正指向的 {server, database}。

這個解析器**坐在** webconfig_connection_resolver 旁邊，不取代它（ADR-0008）。
兩張表永遠不合併：一個 Core 專案的 `ConnectionStrings` 區段，與一個 WebForms
專案的 `<connectionStrings>` 節點，是兩份不同設定檔裡的兩個命名空間。

同一份 appsettings.json 裡也有兩個命名空間，同樣不合併：
`ConnectionStrings` 區段是連線查找表；最外層其餘的鍵是 Configuration 根命名
空間（`IConfiguration["Key"]` 讀得到的那些）。根命名空間的鍵永遠不解析成連
線，只記下鍵名——讓「這個鍵讀的是根命名空間，不是連線字串區段」這件事有話
可說，而不是靜默地解析不到。

解析採寬容態度：真實的設定檔會帶位元組順序記號（BOM），也會帶 `//` 與
`/* */` 註解與尾隨逗號，這些在 JSON 標準裡都不合法，但 .NET 的設定讀取器全部
接受。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, FrozenSet, Union

from .connection_string_value import (
    ResolvedConnection,
    resolve_connection_string_value,
)

CONNECTION_STRINGS_SECTION = "ConnectionStrings"


@dataclass(frozen=True)
class AppSettingsConnections:
    """一份 appsettings.json 解析後的連線查找表。

    connection_strings 是 `ConnectionStrings` 區段解析出來的查找表。
    root_configuration_keys 是最外層其餘的鍵名，只用來說明「這個鍵屬於根命名
    空間」，永遠不參與解析。
    """

    connection_strings: Dict[str, ResolvedConnection] = field(default_factory=dict)
    root_configuration_keys: FrozenSet[str] = frozenset()
    # 根命名空間裡「值看起來是連線字串」的那些鍵。讀根命名空間的程式碼絕大多數
    # 讀的是日誌層級、功能開關這類與資料庫無關的設定；只有這一小群鍵讀起來像
    # 是在讀連線，值得回報一句「這個鍵不在連線字串區段裡」。
    root_connection_keys: FrozenSet[str] = frozenset()

    def __bool__(self) -> bool:
        return bool(self.connection_strings)


# 註解剝除：`//` 到行尾、`/* */` 跨行，兩者都不能動到字串常值裡的同樣字元序列
# （Windows 連線字串常寫 `Data Source=.\\SQLEXPRESS`，斜線在字串裡很常見）。
# 因此用一個同時吃「字串常值」與「註解」的樣式掃過去，掃到字串就原樣留下，
# 掃到註解才丟掉。
_STRING_OR_COMMENT = re.compile(
    r'"(?:\\.|[^"\\])*"'      # JSON 字串常值（含逸出字元）
    r"|//[^\n\r]*"            # 單行註解
    r"|/\*.*?\*/",            # 跨行註解
    re.DOTALL,
)

# 尾隨逗號：`,` 後面只剩空白就接上 `}` 或 `]`。
_TRAILING_COMMA = re.compile(r",(\s*[}\]])")


def _strip_comments(text: str) -> str:
    def replace(match: re.Match) -> str:
        token = match.group(0)
        return token if token.startswith('"') else " "

    return _STRING_OR_COMMENT.sub(replace, text)


def parse_appsettings_connections(content: str) -> AppSettingsConnections:
    """解析一份 appsettings.json 內容，回傳它的連線查找表。

    內容帶 BOM、帶註解、帶尾隨逗號都能解析。整份檔案解析失敗（例如括號不
    對稱）時回傳空表，而不是拋出例外讓整個掃描失敗——一份讀不懂的設定檔讓
    它涵蓋的連線維持 unresolved，是可見的；讓掃描中斷則什麼都看不到。
    """
    text = (content or "").lstrip("﻿")
    if not text.strip():
        return AppSettingsConnections()

    cleaned = _TRAILING_COMMA.sub(r"\1", _strip_comments(text))
    try:
        document = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        return AppSettingsConnections()
    if not isinstance(document, dict):
        return AppSettingsConnections()

    section = document.get(CONNECTION_STRINGS_SECTION)
    connection_strings: Dict[str, ResolvedConnection] = {}
    if isinstance(section, dict):
        for name, value in section.items():
            if not isinstance(value, str):
                continue
            candidate = resolve_connection_string_value(value)
            if candidate.database:
                connection_strings[str(name)] = candidate

    root_keys = frozenset(
        str(key) for key in document if str(key) != CONNECTION_STRINGS_SECTION
    )
    root_connection_keys = frozenset(
        str(key)
        for key, value in document.items()
        if str(key) != CONNECTION_STRINGS_SECTION
        and isinstance(value, str)
        and resolve_connection_string_value(value).database
    )
    return AppSettingsConnections(
        connection_strings=connection_strings,
        root_configuration_keys=root_keys,
        root_connection_keys=root_connection_keys,
    )


def parse_appsettings_file(path: Union[str, Path]) -> AppSettingsConnections:
    """方便函式：讀取一個 appsettings.json 檔案並解析其連線設定。"""
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except OSError:
        return AppSettingsConnections()
    return parse_appsettings_connections(text)
