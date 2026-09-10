# code_analyzer/composition_root_reader.py
"""組合根（Program.cs / Startup.cs）裡的 DbContext 連線註冊。

一個 ASP.NET Core 的資料庫內容型別，不在使用它的類別裡說出自己開哪個資料
庫——它在組合根被註冊到一個具名連線字串上：

    builder.Services.AddDbContext<PayrollContext>(options =>
        options.UseSqlServer(builder.Configuration.GetConnectionString("Payroll")));

這個模組只回答一件事：這份組合根把哪個內容型別註冊到哪個連線查找鍵。它不
解析連線字串的值，也不知道 appsettings.json 長什麼樣——把鍵解析成
{server, database} 是 appsettings_connection_resolver 的工作。

從型別名稱猜資料庫（`PayrollContext` -> `Payroll`）是明確被取代的舊捷徑：一
個內容型別的名稱與它真正開的資料庫經常不同，就像連線查找鍵與資料庫名稱經常
不同一樣（ADR-0008）。
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

# services.AddDbContext<T>( / AddDbContextPool<T>( / AddDbContextFactory<T>(
_ADD_DB_CONTEXT = re.compile(
    r"\.\s*AddDbContext(?:Pool|Factory)?\s*<(?P<type_arguments>[^<>]*(?:<[^<>]*>[^<>]*)*)>\s*\(",
)

# GetConnectionString("Key")
_GET_CONNECTION_STRING = re.compile(
    r"GetConnectionString\s*\(\s*[\"'](?P<key>[^\"']+)[\"']\s*\)"
)

# Configuration["ConnectionStrings:Key"] —— 讀的是同一張連線查找表，只是走
# 索引器語法；`ConnectionStrings:` 這個前綴正是它與根命名空間讀取的分界。
_CONFIGURATION_SECTION_INDEXER = re.compile(
    r"[\"']ConnectionStrings:(?P<key>[^\"']+)[\"']"
)


def _argument_text(content: str, open_paren_index: int) -> str:
    """回傳 `(` 之後到對應 `)` 之間的引數文字。找不到對稱括號時回傳到結尾。"""
    depth = 0
    for index in range(open_paren_index, len(content)):
        character = content[index]
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                return content[open_paren_index + 1 : index]
    return content[open_paren_index + 1 :]


def _split_type_arguments(text: str) -> List[str]:
    """把 `IFoo, FooContext` 這種型別引數清單拆開，巢狀泛型裡的逗號不算分隔。"""
    arguments: List[str] = []
    depth = 0
    current: List[str] = []
    for character in text:
        if character == "<":
            depth += 1
        elif character == ">":
            depth -= 1
        if character == "," and depth == 0:
            arguments.append("".join(current))
            current = []
            continue
        current.append(character)
    arguments.append("".join(current))
    return [argument.strip() for argument in arguments if argument.strip()]


def _simple_type_name(type_argument: str) -> str:
    """把 `MyApp.Data.PayrollContext` 縮成 `PayrollContext`。

    使用端寫的是 using 之後的簡短名稱，所以查找鍵也用簡短名稱。
    """
    return type_argument.split("<", 1)[0].strip().rsplit(".", 1)[-1]


def _connection_key_in(text: str) -> Optional[str]:
    match = _GET_CONNECTION_STRING.search(text)
    if match:
        return match.group("key")
    match = _CONFIGURATION_SECTION_INDEXER.search(text)
    if match:
        return match.group("key")
    return None


def parse_composition_root_contexts(content: str) -> Dict[str, str]:
    """回傳 {資料庫內容型別的簡短名稱: 連線查找鍵}。

    一個註冊沒有說出連線查找鍵時（例如連線字串直接寫死在程式碼裡，或從環境
    變數取得），這個型別不會出現在回傳結果中——它維持 unresolved，而不是被
    猜一個鍵名。
    """
    registrations: Dict[str, str] = {}
    for match in _ADD_DB_CONTEXT.finditer(content or ""):
        arguments = _argument_text(content, match.end() - 1)
        key = _connection_key_in(arguments)
        if not key:
            continue
        for type_argument in _split_type_arguments(match.group("type_arguments")):
            name = _simple_type_name(type_argument)
            if name:
                registrations.setdefault(name, key)
    return registrations
