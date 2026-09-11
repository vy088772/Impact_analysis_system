# code_analyzer/project_connection_scope.py
"""Project Connection Scope：一張連線查找表涵蓋一個專案檔目錄（ADR-0018）。

一個連線查找鍵只在宣告它的那份設定檔裡是唯一的。同一個掃描根底下的兩個專
案，可以用同一個鍵名開兩個不同伺服器上的兩個不同資料庫——實測的
EnterpriseApi 儲存庫就有六個專案這樣做。合併成一張表會讓其中一邊任意勝出，
而輸的那一邊的呼叫會解析到它從來沒開過的資料庫。

所以：一個 `.cs` 檔屬於它上方最近的那個專案檔，兩個專案的表永遠不合併，也
永遠不擴大到掃描根。上方沒有專案檔的 `.cs` 檔沒有表，它的連線維持
unresolved 並說出理由——unresolved 是看得見的，錯的 {server, database} 不是。

這個索引只在掃描根底下真的有 appsettings.json 時才作用。沒有任何一份
appsettings.json 的掃描根（例如 WebForms 系統）拿到 None，整條 Web.config
解析路徑因此完全不動（ADR-0008）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Tuple, Union

from .appsettings_connection_resolver import (
    AppSettingsConnections,
    parse_appsettings_file,
)
from .composition_root_reader import parse_composition_root_contexts
from .connection_string_value import ResolvedConnection
from .source_text import decode_source_bytes

BASE_SETTINGS_FILE_NAME = "appsettings.json"
# 專案檔的副檔名。ADR-0018 的規則是「上方最近的專案檔」，所以巢狀在 C# 專案裡
# 的 VB／F# 專案必須被認出來，否則它會借用外層專案的查找表。
PROJECT_FILE_SUFFIXES = (".csproj", ".vbproj", ".fsproj")
COMPOSITION_ROOT_FILE_NAMES = ("program.cs", "startup.cs")
_IGNORED_DIRECTORY_NAMES = {
    "bin",
    "obj",
    "node_modules",
    "packages",
    ".vs",
    ".git",
    "__pycache__",
    "dist",
    "build",
}

# 解析不到連線時說出的理由。ratio 本身分不出「解析變好了」與「只是變得有自
# 信」，所以每一個解不出來的連線都必須指名它為什麼解不出來。
NO_PROJECT_CONNECTION_SCOPE = "no_project_connection_scope"
CONNECTION_KEY_NOT_IN_PROJECT_SCOPE = "connection_key_not_in_project_scope"
ROOT_CONFIGURATION_NAMESPACE = "root_configuration_namespace_not_connection_strings"
CONTEXT_TYPE_NOT_REGISTERED = "context_type_not_registered"
# 一個發生過 Database Invocation 的接收者，這份分析在它的檔案裡找不到任何
# 型別宣告可以讀——不是「型別沒註冊」（那個答案需要先讀到型別名稱），是連型
# 別名稱都讀不到。兩者是不同的缺口，不能共用同一個理由（ticket 17）。
RECEIVER_DECLARATION_UNRESOLVED = "receiver_declaration_unresolved"
# 一個 Field-Held Connection，它持有的值追不回任何一個連線查找鍵。追不到就維
# 持 unresolved：unresolved 看得見，錯的 {server, database} 不是。
FIELD_HELD_CONNECTION_NOT_TRACED = "field_held_connection_not_traced"


@dataclass(frozen=True)
class EnvironmentSettingsOverride:
    """一份環境專屬設定檔改寫掉的連線——只回報，永不套用。

    哪一個環境會跑起來是部署時才知道的事，靜態掃描無從得知。套用其中一個等
    於猜測；完全不提則讓「這個系統在正式環境開的是另一個資料庫」這件事消
    失。所以記成觀察事實，讓讀的人自己判斷。
    """

    settings_file: str
    lookup_key: str
    database: Optional[str] = None
    server: Optional[str] = None

    def to_dict(self) -> Dict[str, object]:
        return {
            "kind": "environment_settings_override",
            "settings_file": self.settings_file,
            "lookup_key": self.lookup_key,
            "database": self.database,
            "server": self.server,
            "applied": False,
        }


@dataclass(frozen=True)
class ProjectConnectionScope:
    """一個專案檔目錄的連線查找表。

    介面刻意與 WebConfigConnections 對齊（`app_settings` /
    `connection_strings` 兩張各自獨立的表），讓 DBConnectionTracker 兩種設定
    檔都能用同一段程式碼查找。`app_settings` 永遠是空的：appsettings.json 沒
    有 `<appSettings>` 的對應物，最外層其餘的鍵是 Configuration 根命名空間，
    而根命名空間不是連線查找表（見 `root_configuration_keys`）。

    一個表是空的 scope 仍然是真值。空表代表「這個專案的設定檔裡沒有這個
    鍵」，是一個明確的事實；讓它變成假值會讓呼叫端退回「把查找鍵當資料庫名
    稱」的舊猜測，正好是這張票要消滅的失敗模式。
    """

    project_file: Optional[str] = None
    settings_file: Optional[str] = None
    app_settings: Dict[str, ResolvedConnection] = field(default_factory=dict)
    connection_strings: Dict[str, ResolvedConnection] = field(default_factory=dict)
    context_connection_keys: Dict[str, str] = field(default_factory=dict)
    root_configuration_keys: FrozenSet[str] = frozenset()
    root_connection_keys: FrozenSet[str] = frozenset()
    environment_overrides: Tuple[EnvironmentSettingsOverride, ...] = ()
    unresolved_reason: str = ""

    def __bool__(self) -> bool:
        return True


def _find_settings_file(directory: Path, name: str) -> Optional[Path]:
    try:
        entries = list(directory.iterdir())
    except OSError:
        return None
    for entry in entries:
        if entry.is_file() and entry.name.casefold() == name.casefold():
            return entry
    return None


def _find_environment_settings_files(directory: Path) -> List[Path]:
    """回傳 `appsettings.<環境>.json` 形式的檔案，基礎設定檔本身不算。"""
    try:
        entries = list(directory.iterdir())
    except OSError:
        return []
    matches = [
        entry
        for entry in entries
        if entry.is_file()
        and entry.name.casefold().startswith("appsettings.")
        and entry.name.casefold().endswith(".json")
        and entry.name.casefold() != BASE_SETTINGS_FILE_NAME.casefold()
    ]
    return sorted(matches)


def _find_composition_root_files(directory: Path) -> List[Path]:
    matches: List[Path] = []
    for root, directory_names, file_names in os.walk(directory):
        directory_names[:] = [
            name
            for name in directory_names
            if name.casefold() not in _IGNORED_DIRECTORY_NAMES
        ]
        for file_name in file_names:
            if file_name.casefold() in COMPOSITION_ROOT_FILE_NAMES:
                matches.append(Path(root) / file_name)
    return sorted(matches)


def _environment_overrides(
    directory: Path, base: AppSettingsConnections
) -> Tuple[EnvironmentSettingsOverride, ...]:
    overrides: List[EnvironmentSettingsOverride] = []
    for settings_file in _find_environment_settings_files(directory):
        environment = parse_appsettings_file(settings_file)
        for lookup_key, resolved in environment.connection_strings.items():
            if base.connection_strings.get(lookup_key) == resolved:
                continue
            overrides.append(
                EnvironmentSettingsOverride(
                    settings_file=str(settings_file),
                    lookup_key=lookup_key,
                    database=resolved.database,
                    server=resolved.server,
                )
            )
    return tuple(overrides)


def build_project_connection_scope(project_file: Union[str, Path]) -> Optional[ProjectConnectionScope]:
    """為一個專案檔建立它的連線查找表，沒有基礎設定檔時回傳 None。"""
    project_path = Path(project_file).resolve()
    directory = project_path.parent
    settings_file = _find_settings_file(directory, BASE_SETTINGS_FILE_NAME)
    if settings_file is None:
        return None

    base = parse_appsettings_file(settings_file)

    context_connection_keys: Dict[str, str] = {}
    for composition_root in _find_composition_root_files(directory):
        try:
            source_bytes = composition_root.read_bytes()
        except OSError:
            continue
        # 組合根與其他 C# 原始檔用同一套解碼規則。實測的 ETR 儲存庫的
        # Program.cs 註解是 Big5，嚴格解碼會在這裡丟例外，而整個掃描根的連線
        # 解析會隨之安靜消失。
        content = decode_source_bytes(source_bytes)
        for context_type, lookup_key in parse_composition_root_contexts(content).items():
            context_connection_keys.setdefault(context_type, lookup_key)

    return ProjectConnectionScope(
        project_file=str(project_path),
        settings_file=str(settings_file),
        connection_strings=dict(base.connection_strings),
        context_connection_keys=context_connection_keys,
        root_configuration_keys=base.root_configuration_keys,
        root_connection_keys=base.root_connection_keys,
        environment_overrides=_environment_overrides(directory, base),
    )


class ProjectConnectionScopeIndex:
    """一個掃描根底下，每個專案檔目錄各自的連線查找表。

    只在掃描根底下真的存在 appsettings.json 時才作用；否則每一次查找都回傳
    None，呼叫端維持既有的 Web.config 解析路徑，一個位元組都不變。
    """

    def __init__(self, scan_root: Union[str, Path]):
        self._scan_root = Path(scan_root).resolve()
        self._scopes: Dict[Path, Optional[ProjectConnectionScope]] = {}
        self._project_files: Dict[Path, Optional[Path]] = {}
        self._enabled = self._contains_settings_file(self._scan_root)

    def _project_file_for(self, source_file: Union[str, Path]) -> Optional[Path]:
        """回傳一個原始檔上方最近的專案檔，每個目錄只走一次。

        一次掃描會對數千個原始檔問同一個問題，而它們大多共用同一串上層目錄。
        """
        path = Path(source_file).resolve()
        directory = path if path.is_dir() else path.parent
        unknown: List[Path] = []
        for candidate in [directory, *directory.parents]:
            if candidate in self._project_files:
                answer = self._project_files[candidate]
                break
            unknown.append(candidate)
            try:
                project_files = sorted(
                    path
                    for suffix in PROJECT_FILE_SUFFIXES
                    for path in candidate.glob(f"*{suffix}")
                )
            except OSError:
                continue
            if project_files:
                answer = project_files[0]
                break
        else:
            answer = None
        for candidate in unknown:
            self._project_files[candidate] = answer
        return answer

    @property
    def enabled(self) -> bool:
        return self._enabled

    @staticmethod
    def _contains_settings_file(root: Path) -> bool:
        for directory, directory_names, file_names in os.walk(root):
            directory_names[:] = [
                name
                for name in directory_names
                if name.casefold() not in _IGNORED_DIRECTORY_NAMES
            ]
            for file_name in file_names:
                if file_name.casefold() == BASE_SETTINGS_FILE_NAME.casefold():
                    return True
        return False

    def scope_for(self, source_file: Union[str, Path]) -> Optional[ProjectConnectionScope]:
        """回傳這個原始檔所屬的連線查找表。

        上方沒有專案檔時，回傳一個空表並帶著理由——它不會借用鄰居的表。這個
        專案沒有基礎設定檔時回傳 None，把它留給既有的 Web.config 解析路徑，
        所以一個同時放著 WebForms 與 Core 專案的儲存庫兩邊都不會掉。
        """
        if not self._enabled:
            return None

        project_file = self._project_file_for(source_file)
        if project_file is None:
            return ProjectConnectionScope(unresolved_reason=NO_PROJECT_CONNECTION_SCOPE)

        if project_file not in self._scopes:
            self._scopes[project_file] = build_project_connection_scope(project_file)
        return self._scopes[project_file]

    def environment_overrides(self) -> List[Dict[str, object]]:
        """回傳目前已建立的所有 scope 觀察到的環境改寫，去重後排序。"""
        seen: Dict[Tuple[str, str], Dict[str, object]] = {}
        for scope in self._scopes.values():
            if scope is None:
                continue
            for override in scope.environment_overrides:
                seen[(override.settings_file, override.lookup_key)] = override.to_dict()
        return [seen[key] for key in sorted(seen)]
