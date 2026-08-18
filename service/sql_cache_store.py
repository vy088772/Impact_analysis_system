# service/sql_cache_store.py
"""
SQL 物件（預存程序/View/使用者定義函數/資料表 Schema）的本機落地快取。

跟 scan_store.py（C#/View 層程式碼的靜態掃描快取）是同一套設計理念：
第一次「更新 SQL 快取」後，把整個資料庫（指定 schema）的 SP/View/Function
完整定義與資料表欄位 Schema 以 JSON 寫入 data/sql_cache，之後直接讀取，
不必每次問問題都即時連線 SQL Server 查詢。只有明確執行更新指令
（refresh=True，見 /refresh_sql）時才重新連線撈取並覆寫。

純靜態資料，不含任何 AI 摘要（AI 注記交由 spec-rag 端的 code_retriever 按需、
依內容雜湊快取產生，符合本專案「全程無 AI」的分工原則）。

快取鍵是 (server, database, schema) 這組正規化三元組，與 system_id 無關
（見 docs/adr/0009-sql-cache-identity-decoupled-from-system.md）：同一個
Database 被幾套 System 參照、或不屬於任何 System，都只掃描與快取一次。
「這個 Database 有沒有建檔」完全由對應的快取檔在不在磁碟上決定，沒有其他名單。
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Callable, Dict, Optional

from config.settings import settings

# 快取格式版本：dump_all_sql_objects() 回傳結構若變動則遞增，讓舊快取自動失效
# v2：tables[].primary_keys（供 fk_resolver.py 的 PK 命名慣例推論關聯使用）
# v3：新增 dependencies 欄位（sys.sql_expression_dependencies 原生依賴關係，
#     {name: {"depends_on":[...], "depended_by":[...]}}），取代 quick_analyze_sp
#     內原本純 regex 猜測資料表的做法（原生依賴優先，regex 僅作 fallback）
# v4：新增 write_dependencies 欄位（sys.dm_sql_referenced_entities 逐 SP 讀寫資訊，
#     {sp_name: {"writes_tables":[...], "reads_tables":[...], "writes_columns":{...}}}），
#     供 find_by_table() 分辨「這支 SP 到底是讀還是寫這張表」（原生依讀寫優先，
#     regex presence 比對僅作 fallback）
# v5：新增 sql_execution_graph（ScriptDom AST 產生的 typed operation nodes 與
#     reads/writes/contains relationships），舊 cache 必須重新 refresh。
# v6：sql_execution_graph 增加 database identity，供跨資料庫 Execution Path join 驗證。
# v7：sql_execution_graph v2 增加 nested CALL branches、dynamic unresolved nodes、
# typed View/UDF uses，以及 CTE/temp-table lineage。
# v8：formal consumers no longer read legacy dependencies/write_dependencies;
# rebuild the cache before using graph-backed reverse lookup and path selection.
# v9：legacy dependency dictionaries are no longer persisted in refreshed caches.
_SQL_CACHE_VERSION = 9

# 同 process 內的記憶體快取
_mem_cache: Dict[str, Dict] = {}


# 內部 SQL Server 主機都在這個網域底下；短主機名補上這個尾綴即得完整位址。
# 這是一條演算法規則，不是對照表——新的主機（如未來的 vmsystest09）不需要改設定。
SERVER_DOMAIN_SUFFIX = ".topmost.com.tw"


def _safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", text or "").strip("_") or "default"


def normalize_server(server: str) -> str:
    """把連線字串裡的主機位址正規化成快取鍵用的完整位址。

    規則只有兩條：具名執行個體尾綴（`host\\instance`）丟掉、只留主機；主機名
    不含 `.` 時補上 SERVER_DOMAIN_SUFFIX。主機名不分大小寫，一律轉小寫。
    空字串進、空字串出（呼叫端自行決定要不要當成錯誤）。
    """
    host = str(server or "").strip()
    if "\\" in host:
        host = host.split("\\", 1)[0].strip()
    if not host:
        return ""
    if "." not in host:
        host += SERVER_DOMAIN_SUFFIX
    return host.lower()


def cache_key(server: str, database: str, schema: str = "dbo") -> str:
    """(server, database, schema) 三元組的快取鍵；不吃 system_id。"""
    normalized_server = normalize_server(server)
    database = str(database or "").strip()
    if not normalized_server or not database:
        raise ValueError(
            f"SQL 快取鍵需要 server 與 database（server={server!r}, database={database!r}）"
        )
    return f"{_safe_name(normalized_server)}__{_safe_name(database)}__{_safe_name(schema)}"


def cache_filename(server: str, database: str, schema: str = "dbo") -> str:
    """該三元組的快取檔名（含 .json）。"""
    return f"{cache_key(server, database, schema)}.json"


def _cache_root() -> Path:
    root = Path(settings.SQL_CACHE_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _paths(server: str, database: str, schema: str) -> tuple[Path, Path]:
    k = cache_key(server, database, schema)
    return _cache_root() / f"{k}.json", _cache_root() / f"{k}.meta.json"


def resolve_server(database: str, schema: str = "dbo") -> str:
    """呼叫端只知道 database 名稱時，從磁碟上唯一一份快取回推它的 server。

    找不到、或同名 database 在多台 server 上都有快取（無法判斷是哪一台）時回傳
    空字串——寧可查無快取，也不猜錯資料庫。
    """
    database = str(database or "").strip()
    if not database:
        return ""
    suffix = f"__{_safe_name(database)}__{_safe_name(schema)}.json"
    servers = sorted(
        {
            path.name[: -len(suffix)]
            for path in _cache_root().glob(f"*{suffix}")
            if not path.name.endswith(".meta.json") and len(path.name) > len(suffix)
        }
    )
    if len(servers) != 1:
        if servers:
            print(
                f"⚠️  {database}.{schema} 在多台 server 上都有 SQL 快取（{', '.join(servers)}）；"
                f"請指定 server。"
            )
        return ""
    return servers[0]


def _same_scope(actual: object, expected: str) -> bool:
    return str(actual or "").strip().casefold() == str(expected or "").strip().casefold()


def _is_valid_cache(data: object, database: str, schema: str) -> bool:
    if not isinstance(data, dict):
        return False
    graph = data.get("sql_execution_graph")
    if not isinstance(graph, dict):
        return False
    from .sql_execution_graph import GRAPH_VERSION

    if graph.get("graph_version") != GRAPH_VERSION:
        return False
    if any(
        not isinstance(graph.get(field), list)
        for field in ("nodes", "relationships", "parse_errors")
    ):
        return False
    if not _same_scope(data.get("database"), database):
        return False
    if not _same_scope(data.get("schema"), schema):
        return False
    return _same_scope(graph.get("database"), database)


def _without_legacy_dependency_fields(data: Dict) -> Dict:
    sanitized = dict(data)
    sanitized.pop("dependencies", None)
    sanitized.pop("write_dependencies", None)
    return sanitized


def has_cache(database: str, schema: str = "dbo", server: str = "") -> bool:
    """這個 Database 有沒有建檔：完全由對應的快取檔在不在磁碟上決定。"""
    return load_cached(database, schema, server=server) is not None


def _load(server: str, database: str, schema: str) -> Optional[Dict]:
    data_path, meta_path = _paths(server, database, schema)
    if not data_path.exists():
        return None
    try:
        if not meta_path.exists():
            return None
        info = json.loads(meta_path.read_text(encoding="utf-8"))
        if info.get("cache_version") != _SQL_CACHE_VERSION:
            return None
        if not _same_scope(info.get("database"), database):
            return None
        if not _same_scope(info.get("schema"), schema):
            return None
        if info.get("server") and not _same_scope(info.get("server"), normalize_server(server)):
            return None
        data = json.loads(data_path.read_text(encoding="utf-8"))
        if not _is_valid_cache(data, database, schema):
            return None
        return data
    except Exception:
        return None


def _save(server: str, database: str, schema: str, data: Dict) -> None:
    data_path, meta_path = _paths(server, database, schema)
    try:
        data_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        meta_path.write_text(
            json.dumps(
                {
                    "cache_version": _SQL_CACHE_VERSION,
                    "server": normalize_server(server),
                    "database": database,
                    "schema": schema,
                    "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception as exc:  # 寫檔失敗不致命
        print(f"⚠️  SQL 快取寫出失敗（非致命）：{exc}")


def load_cached(database: str, schema: str = "dbo", server: str = "") -> Optional[Dict]:
    """單純讀取本機快取（不連線、不 dump）；查詢時的快速路徑用這個。

    server 省略時由 resolve_server() 從磁碟回推；同名 database 分屬多台 server
    而無法判斷時視為查無快取。
    """
    server = normalize_server(server) or resolve_server(database, schema)
    if not server:
        return None
    key = cache_key(server, database, schema)
    if key in _mem_cache:
        cached = _mem_cache[key]
        if _is_valid_cache(cached, database, schema):
            return cached
        _mem_cache.pop(key, None)
    cached = _load(server, database, schema)
    if cached is not None:
        _mem_cache[key] = cached
    return cached


def get_or_dump(
    database: str,
    schema: str = "dbo",
    refresh: bool = False,
    server: str = "",
    db_name: str = "",
    progress_callback: Callable[[str, int, int, str], None] | None = None,
) -> Dict:
    """
    取得（或建立）SQL 物件快取：優先用記憶體/磁碟快取；refresh=True 則強制重新
    連線 SQL Server 撈取整庫定義並覆寫快取。

    server/db_name：實際連線目標，同時也是快取鍵的兩個組成（第三個是 schema），
    由呼叫端如 spec-rag 的 catalog 逐資料庫提供。db_name 省略時退回用 database
    當資料庫名稱；缺 server 即由 SQLAnalyzer 直接報錯、不嘗試連線
    （見 config.settings.build_database_config）。

    database：顯示用簡稱；不參與快取鍵計算。
    """
    db = str(db_name or database or "").strip()

    if not refresh:
        cached = load_cached(db, schema, server=server)
        if cached is not None:
            print(f"⚡ 使用 SQL 快取：{db}.{schema}")
            return cached

    print(f"🔍 連線 SQL Server 重新撈取物件定義：{db}.{schema}")
    _report_progress(progress_callback, "connecting", 0, 1, db)
    from code_analyzer.sql_analyzer import SQLAnalyzer

    analyzer = SQLAnalyzer(db, server=server, database_name=db)
    if not analyzer.connect():
        raise RuntimeError(f"無法連線資料庫：{db}")
    _report_progress(progress_callback, "connecting", 1, 1, db)
    try:
        if progress_callback is None:
            data = analyzer.dump_all_sql_objects(schema)
        else:
            data = analyzer.dump_all_sql_objects(schema, progress_callback=progress_callback)
    finally:
        try:
            analyzer.disconnect()
        except Exception:
            pass

    from .sql_execution_graph import build_sql_execution_graph

    data = _without_legacy_dependency_fields(data)
    data["sql_execution_graph"] = build_sql_execution_graph(
        data,
        progress_callback=progress_callback,
    )
    if not _is_valid_cache(data, db, schema):
        raise ValueError(
            f"SQL cache payload database identity mismatch: {db}.{schema}"
        )
    _mem_cache[cache_key(server, db, schema)] = data
    _report_progress(progress_callback, "saving", 0, 1, "SQL cache")
    _save(server, db, schema, data)
    _report_progress(progress_callback, "saving", 1, 1, "SQL cache")
    return data


def _report_progress(
    callback: Callable[[str, int, int, str], None] | None,
    stage: str,
    current: int,
    total: int,
    item: str,
) -> None:
    if callback is None:
        return
    try:
        callback(stage, current, total, item)
    except Exception:
        pass
