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
這組三元組在模組內一律以 CacheIdentity 型別、一種參數順序傳遞。
「這個 Database 有沒有建檔」完全由對應的快取檔在不在磁碟上決定，沒有其他名單。
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

from code_analyzer.csharp_analysis_gateway import normalize_procedure_name
from config.settings import settings

# 資料表名稱正規化跟 /find_by_table 比對 SQL Execution Graph 節點時用的同一個函式
# （service/graph_queries.py 內部用來判斷一個 graph table 節點是否等於呼叫端要找的
# 表名），特意重用而不是自己另寫一份等價邏輯——否則索引跟真正的比對邏輯日後可能
# 悄悄長歪，讓索引誤刪一個 find_by_table 其實會找到的名字。
from .graph_queries import _normalize_table as normalize_table_name

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
# v10：fixed a bug where SP definitions longer than 4000 chars (ROUTINE_DEFINITION's
# NVARCHAR(4000) limit) were silently truncated mid-statement instead of falling
# back to OBJECT_DEFINITION; caches built before this fix may hold truncated SQL
# text that fails ScriptDom parsing, so they must be rebuilt via refresh_sql_cli.
_SQL_CACHE_VERSION = 10

# 同 process 內的記憶體快取
_mem_cache: Dict[str, Dict] = {}


# 內部 SQL Server 主機都在這個網域底下；短主機名補上這個尾綴即得完整位址。
# 這是一條演算法規則，不是對照表——新的主機（如未來的 vmsystest09）不需要改設定。
SERVER_DOMAIN_SUFFIX = ".topmost.com.tw"

# 快取檔名的形狀只在這裡定義一次：{server}__{database}__{schema}.json。
_KEY_SEPARATOR = "__"
_DATA_SUFFIX = ".json"
_META_SUFFIX = ".meta.json"
_INDEX_SUFFIX = ".index.json"


def _safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", text or "").strip("_") or "default"


def _key_of(*parts: str) -> str:
    return _KEY_SEPARATOR.join(_safe_name(part) for part in parts)


def _parse_key(stem: str) -> tuple[str, str, str]:
    """_key_of() 的反操作：把一個快取檔名（去掉副檔名後）拆回 (server, database, schema)。

    快取檔名的形狀只在 _key_of() 這一處定義；這裡是它唯一的反解出口，供
    list_caches() 在 meta 檔缺失/無法讀取、需要從檔名反推身分時使用，避免
    這條反解邏輯散落、各自重寫一份。server 一律在最前、schema 一律在最後，
    中間全部併回 database——database 本身含 `__` 時也能正確反解。
    """
    parts = stem.split(_KEY_SEPARATOR)
    if len(parts) >= 3:
        return parts[0], _KEY_SEPARATOR.join(parts[1:-1]), parts[-1]
    padded = (parts + ["", "", ""])[:3]
    return padded[0], padded[1], padded[2]


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


@dataclass(frozen=True)
class CacheIdentity:
    """一份 SQL 快取的身分：正規化過的 (server, database, schema) 三元組。

    模組內所有需要這組三元組的函式都收這一個值、用這一個順序；快取鍵與檔名
    都由它算出來，不再由呼叫端各自拼。用 of() 建立，不要直接呼叫建構式——
    of() 才會正規化 server、並檢查 server 與 database 都有值（schema 可省略，
    空字串等同 _safe_name() 的 "default"）。
    """

    server: str
    database: str
    schema: str

    @classmethod
    def of(cls, server: str, database: str, schema: str = "dbo") -> "CacheIdentity":
        normalized_server = normalize_server(server)
        database = str(database or "").strip()
        schema = str(schema or "").strip()
        if not normalized_server or not database:
            raise ValueError(
                f"SQL 快取鍵需要 server 與 database（server={server!r}, database={database!r}）"
            )
        return cls(normalized_server, database, schema)

    @property
    def key(self) -> str:
        return _key_of(self.server, self.database, self.schema)

    @property
    def filename(self) -> str:
        return f"{self.key}{_DATA_SUFFIX}"

    @property
    def meta_filename(self) -> str:
        return f"{self.key}{_META_SUFFIX}"

    @property
    def index_filename(self) -> str:
        return f"{self.key}{_INDEX_SUFFIX}"


def _cache_root() -> Path:
    root = Path(settings.SQL_CACHE_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _paths(identity: CacheIdentity) -> tuple[Path, Path]:
    root = _cache_root()
    return root / identity.filename, root / identity.meta_filename


def _index_path(identity: CacheIdentity) -> Path:
    return _cache_root() / identity.index_filename


def resolve_server(database: str, schema: str = "dbo") -> str:
    """呼叫端只知道 database 名稱時，從磁碟上唯一一份快取回推它的 server。

    找不到、或同名 database 在多台 server 上都有快取（無法判斷是哪一台）時回傳
    空字串——寧可查無快取，也不猜錯資料庫。

    結構上沒有 server 可帶的呼叫端有三個：/find_by_sp 與 /find_by_table
    （FindBySPRequest/FindByTableRequest 沒有 db_server 欄位），以及 refresh 流程的
    analyze_service.reconcile_refresh_wrappers()（含 tools/discover_external_wrappers.py）。
    /analyze、/path_evidence、/flow_chain 會把請求的 db_server 一路帶到這裡，
    指名讀哪一台；那些請求沒填 db_server 時同樣落到這條回推。
    """
    database = str(database or "").strip()
    if not database:
        return ""
    suffix = f"{_KEY_SEPARATOR}{_key_of(database, schema)}{_DATA_SUFFIX}"
    servers = sorted(
        {
            path.name[: -len(suffix)]
            for path in _cache_root().glob(f"*{suffix}")
            if not path.name.endswith(_META_SUFFIX) and len(path.name) > len(suffix)
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


@dataclass(frozen=True)
class ScanRecordListing:
    """list_caches() 的一列：一份 SQL 快取的身分與 Scan Record（掃描時間）。

    與 CacheIdentity 不同——這裡不正規化也不驗證，純粹反映磁碟上讀到的內容，
    連身分不完整的異常檔案都要能被列出（規格要求「never omitted from listing」）。
    scanned_at 為 None 代表 Scan Record 缺失或無法讀取，不是「從未掃描」與
    「讀不到」的混淆表達——呼叫端據此決定要不要顯示「never scanned」。
    """

    server: str
    database: str
    schema: str
    scanned_at: Optional[str]


def list_caches() -> List[ScanRecordListing]:
    """列出磁碟上每一份 SQL 快取的 (server, database, schema) 與 Scan Record。

    純目錄列舉，不連線 SQL Server、不觸發掃描、不修改任何快取檔案；供
    GET /scan_records 這個唯讀端點使用。判準與 has_cache() 完全一致：資料檔
    （.json，非 .meta.json）存在即列出。Database Registry 完全不參與判斷——
    一份用 --server/--database 直接掃描、Registry 裡沒登記的快取，一樣會出現
    在這份清單裡。

    每一列的 scan 時間來自同目錄下的 sibling meta 檔（.meta.json）；meta 檔
    缺失或無法解析時該列仍然列出，scanned_at 回 None，而不是整列被跳過。
    身分欄位優先採 meta 檔內容（較不受檔名安全化規則影響），meta 讀不到或某
    欄位缺漏時才退回從檔名反推。

    回傳依 (server, database, schema) 排序，讓同一份清單在多次呼叫間穩定
    （不受掃描先後影響）。
    """
    root = _cache_root()
    rows: List[ScanRecordListing] = []
    for data_path in root.glob(f"*{_DATA_SUFFIX}"):
        name = data_path.name
        # Both the Scan Record (.meta.json) and the Object Location Index
        # (.index.json) end in ".json" too, so the glob above matches them —
        # only the bare data file is a cache.
        if name.endswith(_META_SUFFIX) or name.endswith(_INDEX_SUFFIX):
            continue
        stem = name[: -len(_DATA_SUFFIX)]
        server, database, schema = _parse_key(stem)

        scanned_at: Optional[str] = None
        meta_path = data_path.with_name(f"{stem}{_META_SUFFIX}")
        try:
            info = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            info = None
        if isinstance(info, dict):
            server = str(info.get("server") or server)
            database = str(info.get("database") or database)
            schema = str(info.get("schema") or schema)
            saved_at = info.get("saved_at")
            if saved_at:
                scanned_at = str(saved_at)

        rows.append(
            ScanRecordListing(server=server, database=database, schema=schema, scanned_at=scanned_at)
        )
    rows.sort(key=lambda row: (row.server, row.database, row.schema))
    return rows


def _same_scope(actual: object, expected: str) -> bool:
    return str(actual or "").strip().casefold() == str(expected or "").strip().casefold()


def _is_valid_cache(data: object, identity: CacheIdentity) -> bool:
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
    if not _same_scope(data.get("database"), identity.database):
        return False
    if not _same_scope(data.get("schema"), identity.schema):
        return False
    return _same_scope(graph.get("database"), identity.database)


def _without_legacy_dependency_fields(data: Dict) -> Dict:
    sanitized = dict(data)
    sanitized.pop("dependencies", None)
    sanitized.pop("write_dependencies", None)
    return sanitized


def has_cache(database: str, schema: str = "dbo", server: str = "") -> bool:
    """這個 Database 有沒有建檔：完全由對應的快取檔在不在磁碟上決定。"""
    return load_cached(database, schema, server=server) is not None


def cached_saved_at(database: str, schema: str = "dbo", server: str = "") -> Optional[str]:
    """讀取這個 (server, database, schema) 目前磁碟上 SQL 快取記錄的 saved_at。

    與 load_cached() 收同一組參數、套用同一套 server 回推規則（server 省略時
    由 resolve_server() 從磁碟回推），但只讀 meta 檔的 saved_at 一個欄位，不驗
    證/載入完整快取內容、不連線、不觸發任何 dump。供只需要「這份快取自上次
    derive 後有沒有變」信號的呼叫端使用（見 analyze_service 的 validity
    stamp），取代原本比對 Python 物件身分的做法。
    """
    resolved_server = normalize_server(server) or resolve_server(database, schema)
    if not resolved_server:
        return None
    _, meta_path = _paths(CacheIdentity.of(resolved_server, database, schema))
    if not meta_path.exists():
        return None
    try:
        info = json.loads(meta_path.read_text(encoding="utf-8"))
        return info.get("saved_at")
    except Exception:
        return None


def _meta_payload(identity: CacheIdentity, saved_at: str) -> Dict[str, object]:
    return {
        "cache_version": _SQL_CACHE_VERSION,
        "server": identity.server,
        "database": identity.database,
        "schema": identity.schema,
        "saved_at": saved_at,
    }


def write_meta(meta_path: Path, identity: CacheIdentity, saved_at: str) -> None:
    """把 meta 檔寫到指定路徑。meta 格式只在這裡定義一次。

    _save() 與一次性搬移工具（tools/migrate_sql_cache_keys.py）共用這一個出口。
    saved_at 照傳照寫、不補值：搬移不是重新掃描，不該冒出一個沒發生過的掃描時間。
    """
    Path(meta_path).write_text(
        json.dumps(_meta_payload(identity, saved_at), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


@dataclass(frozen=True)
class ObjectLocationIndex:
    """一份 SQL 快取的 Object Location Index：這份快取能回答哪些物件名稱。

    分兩個桶，各自正規化：stored_procedures（procedures/views/functions，用
    normalize_procedure_name）與 tables（快取宣告的 tables ∪ SQL Execution
    Graph 裡的 table 節點，用 normalize_table_name，並且已經去掉 schema——
    dbo.Orders 與 sales.Orders 收斂成同一個 key，這是今天既有的比對行為）。
    寧可多報也不能少報：多報頂多多讀一次快取，少報會漏掉一個本該找到的答案。
    """

    server: str
    database: str
    schema: str
    cache_version: int
    stored_procedures: frozenset[str]
    tables: frozenset[str]


def build_object_location_index(identity: CacheIdentity, data: Dict) -> ObjectLocationIndex:
    """把一份已載入的 SQL 快取內容，轉成它的 Object Location Index。

    refresh 路徑（_save()）與 backfill 工具共用這一個函式，不會有第二份實作。
    """
    stored_procedures: set[str] = set()
    for collection in ("procedures", "views", "functions"):
        for item in data.get(collection, []) or []:
            name = str((item or {}).get("name") or "").strip()
            if name:
                stored_procedures.add(normalize_procedure_name(name))

    tables: set[str] = set()
    for item in data.get("tables", []) or []:
        name = str((item or {}).get("name") or "").strip()
        if name:
            tables.add(normalize_table_name(name))

    graph = data.get("sql_execution_graph")
    if isinstance(graph, dict):
        for node in graph.get("nodes", []) or []:
            if not isinstance(node, dict) or node.get("type") != "table":
                continue
            name = str(node.get("name") or "").strip()
            if name:
                tables.add(normalize_table_name(name))

    return ObjectLocationIndex(
        server=identity.server,
        database=identity.database,
        schema=identity.schema,
        cache_version=_SQL_CACHE_VERSION,
        stored_procedures=frozenset(stored_procedures),
        tables=frozenset(tables),
    )


def _index_payload(index: ObjectLocationIndex) -> Dict[str, object]:
    return {
        "server": index.server,
        "database": index.database,
        "schema": index.schema,
        "cache_version": index.cache_version,
        "stored_procedures": sorted(index.stored_procedures),
        "tables": sorted(index.tables),
    }


def write_object_location_index(identity: CacheIdentity, index: ObjectLocationIndex) -> None:
    """把索引寫到快取旁邊的獨立檔案——不併入 meta 檔，那是 Scan Record，意義不同。"""
    _index_path(identity).write_text(
        json.dumps(_index_payload(index), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_object_location_index(identity: CacheIdentity) -> Optional[ObjectLocationIndex]:
    """讀取一份索引；staleness 規則只定義在這一處。

    索引檔不存在、讀不了、修改時間早於它描述的快取資料檔、版本跟現在的
    _SQL_CACHE_VERSION 對不上、或身分跟呼叫端要的 identity 對不上，都算「沒有
    索引」——呼叫端接下來照舊打開整份快取，絕不會因為索引壞掉而少答一個答案。

    這裡只取快取資料檔的修改時間（stat），從不 parse 它的內容——105 MB 的檔案
    不該在這裡被打開，那正是索引想省下的成本。
    """
    data_path, _meta_path = _paths(identity)
    index_path = _index_path(identity)
    if not data_path.exists() or not index_path.exists():
        return None
    try:
        if index_path.stat().st_mtime < data_path.stat().st_mtime:
            return None
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("cache_version") != _SQL_CACHE_VERSION:
        return None
    if not _same_scope(payload.get("server"), identity.server):
        return None
    if not _same_scope(payload.get("database"), identity.database):
        return None
    if not _same_scope(payload.get("schema"), identity.schema):
        return None
    stored_procedures = payload.get("stored_procedures")
    tables = payload.get("tables")
    if not isinstance(stored_procedures, list) or not isinstance(tables, list):
        return None
    return ObjectLocationIndex(
        server=identity.server,
        database=identity.database,
        schema=identity.schema,
        cache_version=_SQL_CACHE_VERSION,
        stored_procedures=frozenset(str(name) for name in stored_procedures),
        tables=frozenset(str(name) for name in tables),
    )


def _load(identity: CacheIdentity) -> Optional[Dict]:
    data_path, meta_path = _paths(identity)
    if not data_path.exists():
        return None
    try:
        if not meta_path.exists():
            return None
        info = json.loads(meta_path.read_text(encoding="utf-8"))
        if info.get("cache_version") != _SQL_CACHE_VERSION:
            return None
        if not _same_scope(info.get("database"), identity.database):
            return None
        if not _same_scope(info.get("schema"), identity.schema):
            return None
        if info.get("server") and not _same_scope(info.get("server"), identity.server):
            return None
        data = json.loads(data_path.read_text(encoding="utf-8"))
        if not _is_valid_cache(data, identity):
            return None
        return data
    except Exception:
        return None


def _save(identity: CacheIdentity, data: Dict) -> None:
    data_path, meta_path = _paths(identity)
    try:
        data_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        write_meta(meta_path, identity, time.strftime("%Y-%m-%d %H:%M:%S"))
    except Exception as exc:  # 寫檔失敗不致命
        print(f"⚠️  SQL 快取寫出失敗（非致命）：{exc}")
        return
    # 索引一定寫在快取之後：中斷在這一步之前的 refresh，索引就是舊檔或缺席，
    # 而不是跟半成品快取一起看起來「完整但錯」。索引寫出失敗同樣不致命——
    # 索引缺席時呼叫端就照舊讀整份快取，不會少答任何一個答案。
    try:
        write_object_location_index(identity, build_object_location_index(identity, data))
    except Exception as exc:
        print(f"⚠️  Object Location Index 寫出失敗（非致命）：{exc}")


def load_cached(database: str, schema: str = "dbo", server: str = "") -> Optional[Dict]:
    """單純讀取本機快取（不連線、不 dump）；查詢時的快速路徑用這個。

    server 省略時由 resolve_server() 從磁碟回推；同名 database 分屬多台 server
    而無法判斷時視為查無快取。
    """
    server = normalize_server(server) or resolve_server(database, schema)
    if not server:
        return None
    identity = CacheIdentity.of(server, database, schema)
    if identity.key in _mem_cache:
        cached = _mem_cache[identity.key]
        if _is_valid_cache(cached, identity):
            return cached
        _mem_cache.pop(identity.key, None)
    cached = _load(identity)
    if cached is not None:
        _mem_cache[identity.key] = cached
    return cached


def get_or_dump(
    database: str,
    schema: str = "dbo",
    refresh: bool = False,
    server: str = "",
    db_name: str = "",
    user_id: str = "",
    password: str = "",
    progress_callback: Callable[[str, int, int, str], None] | None = None,
) -> Dict:
    """
    取得（或建立）SQL 物件快取：優先用記憶體/磁碟快取；refresh=True 則強制重新
    連線 SQL Server 撈取整庫定義並覆寫快取。

    server/db_name：實際連線目標，同時也是快取鍵的兩個組成（第三個是 schema），
    由呼叫端如 spec-rag 的 catalog 逐資料庫提供，兩者皆必填。db_name 為空即
    直接報錯，不猜資料庫名稱；缺 server 則由 SQLAnalyzer 報錯、不嘗試連線
    （見 config.settings.build_database_config）。

    database：顯示用簡稱；不參與快取鍵計算。

    user_id/password：這一台伺服器的掃描帳密覆寫，兩者都有值才生效；缺一即沿用
    .env 的全域 DB_AUTH_MODE 身分（見 docs/adr/0010-scan-identity-independent-of-app-credentials.md）。
    掃描用的連線身分永遠不從被掃應用程式的 Web.config 推導。
    """
    db = str(db_name or "").strip()
    if not db:
        raise ValueError(
            f"get_or_dump() 需要 db_name（實際資料庫名稱）；database={database!r} 只是顯示用簡稱。"
        )

    if not refresh:
        cached = load_cached(db, schema, server=server)
        if cached is not None:
            print(f"⚡ 使用 SQL 快取：{db}.{schema}")
            return cached

    print(f"🔍 連線 SQL Server 重新撈取物件定義：{db}.{schema}")
    _report_progress(progress_callback, "connecting", 0, 1, db)
    from code_analyzer.sql_analyzer import SQLAnalyzer

    analyzer = SQLAnalyzer(
        db, server=server, database_name=db, user_id=user_id, password=password
    )
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

    identity = CacheIdentity.of(server, db, schema)
    data = _without_legacy_dependency_fields(data)
    data["sql_execution_graph"] = build_sql_execution_graph(
        data,
        progress_callback=progress_callback,
    )
    if not _is_valid_cache(data, identity):
        raise ValueError(
            f"SQL cache payload database identity mismatch: {db}.{schema}"
        )
    _mem_cache[identity.key] = data
    _report_progress(progress_callback, "saving", 0, 1, "SQL cache")
    _save(identity, data)
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
