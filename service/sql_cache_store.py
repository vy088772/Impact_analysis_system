# service/sql_cache_store.py
"""
SQL 物件（預存程序/View/使用者定義函數/資料表 Schema）的本機落地快取。

跟 scan_store.py（C#/View 層程式碼的靜態掃描快取）是同一套設計理念：
第一次「更新 SQL 快取」後，把整個資料庫（含庫內每個 schema）的 SP/View/Function
完整定義與資料表欄位 Schema 以 JSON 寫入 data/sql_cache，之後直接讀取，
不必每次問問題都即時連線 SQL Server 查詢。只有明確執行更新指令
（refresh=True，見 /refresh_sql）時才重新連線撈取並覆寫。

純靜態資料，不含任何 AI 摘要（AI 注記交由 spec-rag 端的 code_retriever 按需、
依內容雜湊快取產生，符合本專案「全程無 AI」的分工原則）。

快取鍵是 (server, database) 這組正規化二元組，與 system_id 無關
（見 docs/adr/0009-sql-cache-identity-decoupled-from-system.md）：同一個
Database 被幾套 System 參照、或不屬於任何 System，都只掃描與快取一次。
模組的每個公開函式都收 CacheIdentity 這一個值，不收零散的 database/
server 參數；一份快取涵蓋一個 Database 的每個 schema，每個物件自帶它的 schema。
只知道 database 名稱的呼叫端先用 find_cache_identity() 從磁碟找。
CacheIdentity 擁有它的三個檔名（資料檔、Scan Record、Object Location Index），
「目錄裡哪些檔案是快取」只由 list_cache_files() 回答。
「這個 Database 有沒有建檔」完全由對應的快取檔在不在磁碟上決定，沒有其他名單。
"""
from __future__ import annotations

import json
import re
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Union

# 索引的兩個桶跟 /find_by_sp、/find_by_table 比對時用同一個 bare key
# （Canonical Object Identity module），特意重用而不是自己另寫一份等價邏輯——否則
# 索引跟真正的比對邏輯日後可能悄悄長歪，讓索引誤刪一個端點其實會找到的名字。
from canonical_object_identity import ObjectName, bare_key, full_key, parse
from config.settings import settings

# 快取格式版本：dump_all_sql_objects() 回傳結構若變動則遞增，讓舊快取自動失效
# v2：tables[].primary_keys（原供已移除的 fk_resolver.py 之 PK 命名慣例推論關聯使用）
# v3/v4：新增又退場的 dependencies/write_dependencies 欄位，見 ADR-0031。
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
# v11：one cache holds one Database. The cache identity and the filename lose the
# schema part, and the meta file and the Object Location Index lose their `schema`
# field. A cache written under a three-part filename never loads again.
_SQL_CACHE_VERSION = 11

# Object Location Index 自己的格式版本，跟上面的快取版本各管各的檔案：索引的形狀
# 換了、快取的形狀沒換時，只有這一個常數往上加。
# v1：每種物件兩個桶——bare key 桶與 full key（database.schema.name）桶。
# 沒有版本欄位的索引（Step 2b 之前寫的）與版本對不上的索引，一律算「沒有索引」。
_INDEX_VERSION = 1

# 同 process 內的記憶體快取。有界、LRU 淘汰（ticket 08，見
# settings.SQL_CACHE_MEMORY_RETENTION_LIMIT 上方註解的動機）：淘汰只影響這份
# 記憶體快取，磁碟落地檔（_save()/_load()）不受影響，被淘汰的 Database 下次
# 被問到時直接重新讀檔，不必重新連線 SQL Server，答案不會因此改變。
#
# 用 OrderedDict 讓「淘汰最久未使用」跟「淘汰最早載入」同一份資料結構就能兩者
# 兼得：每次命中或寫入都呼叫 move_to_end()，最久未使用的項目永遠留在最前面，
# _evict_for_new_mem_cache_key() 就從最前面 popitem(last=False)。與
# analyze_service._rated_invocations_retention 用的是同一套手法（ticket 07）。
#
# 型別標註不加引號：本檔已在最上方 `from __future__ import annotations`，
# 所有標註本來就延遲求值，手動加引號只是多餘。
_mem_cache: OrderedDict[CacheIdentity, Dict] = OrderedDict()


def _evict_for_new_mem_cache_key(identity: CacheIdentity) -> None:
    """為 identity 空出記憶體快取的位置：若加入它會超過上限，淘汰最久未使用的一筆。

    identity 已經在記憶體快取裡時不做事——覆寫既有項目的內容從不會讓快取變大，
    自然不需要淘汰誰。只透過 _retain_in_mem_cache() 呼叫。

    記憶體快取以 CacheIdentity 為鍵，淘汰訊息直接讀被淘汰那一筆的欄位，
    不必把快取鍵字串拆回去。
    """
    if identity in _mem_cache:
        return
    limit = max(1, int(settings.SQL_CACHE_MEMORY_RETENTION_LIMIT))
    if len(_mem_cache) < limit:
        return
    evicted, _ = _mem_cache.popitem(last=False)
    print(
        "⚠️  SQL 快取記憶體保留已達上限"
        f"（limit={limit}），淘汰最久未使用的資料庫："
        f"evicted server={evicted.server!r} database={evicted.database!r} / "
        f"new server={identity.server!r} database={identity.database!r}"
    )


def _retain_in_mem_cache(identity: CacheIdentity, data: Dict) -> None:
    """把 data 以 identity 為鍵寫入記憶體快取，並移到最新位置。

    先淘汰、後寫入：淘汰時看到的是「加入 identity 之前」的快取內容，identity
    本身若已在快取裡，_evict_for_new_mem_cache_key() 會判斷成不需要淘汰。跟
    analyze_service._evict_then_retain() 同一種先後順序。
    """
    _evict_for_new_mem_cache_key(identity)
    _mem_cache[identity] = data
    _mem_cache.move_to_end(identity)


# 內部 SQL Server 主機都在這個網域底下；短主機名補上這個尾綴即得完整位址。
# 這是一條演算法規則，不是對照表——新的主機（如未來的 vmsystest09）不需要改設定。
SERVER_DOMAIN_SUFFIX = ".topmost.com.tw"

# 快取檔名的形狀只在這裡定義一次：{server}__{database}.json。
_KEY_SEPARATOR = "__"
_DATA_SUFFIX = ".json"
_META_SUFFIX = ".meta.json"
_INDEX_SUFFIX = ".index.json"


def _safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", text or "").strip("_") or "default"


def _key_of(*parts: str) -> str:
    return _KEY_SEPARATOR.join(_safe_name(part) for part in parts)


def normalize_server(server: str) -> str:
    """把連線字串裡的主機位址正規化成快取鍵用的完整位址。

    規則有四條：`tcp:` 協定前綴丟掉；`,port` 埠號尾綴丟掉；具名執行個體尾綴
    （`host\\instance`）丟掉、只留主機；主機名不含 `.` 時補上
    SERVER_DOMAIN_SUFFIX。主機名不分大小寫，一律轉小寫。
    空字串進、空字串出（呼叫端自行決定要不要當成錯誤）。
    """
    host = str(server or "").strip()
    if host.lower().startswith("tcp:"):
        host = host[len("tcp:"):].strip()
    if "," in host:
        host = host.split(",", 1)[0].strip()
    if "\\" in host:
        host = host.split("\\", 1)[0].strip()
    if not host:
        return ""
    if "." not in host:
        host += SERVER_DOMAIN_SUFFIX
    return host.lower()


@dataclass(frozen=True)
class CacheIdentity:
    """一份 SQL 快取的身分：正規化過的 (server, database) 二元組。

    一份快取涵蓋一個 Database 與庫內每個 schema，所以身分沒有 schema 這一段。
    模組內所有需要這組二元組的函式都收這一個值、用這一個順序；快取鍵與它的
    三個檔名都由它算出來，from_key() 是檔名主幹的反操作，就放在 key 旁邊。
    用 of() 建立，不要直接呼叫建構式——of() 才會正規化 server、並檢查 server
    與 database 都有值。of() 是純函式，從不讀磁碟；只知道 database 的呼叫端改用
    find_cache_identity()。
    """

    server: str
    database: str

    @classmethod
    def of(cls, server: str, database: str) -> "CacheIdentity":
        normalized_server = normalize_server(server)
        database = str(database or "").strip()
        if not normalized_server or not database:
            raise ValueError(
                f"SQL 快取鍵需要 server 與 database（server={server!r}, database={database!r}）"
            )
        return cls(normalized_server, database)

    @classmethod
    def from_key(cls, stem: str) -> Optional["CacheIdentity"]:
        """key 的反操作：把一個快取檔名（去掉副檔名後）拆回它命名的身分。

        server 一律在最前，其後全部併回 database——database 本身含 `__` 時也能
        正確反解。拆不出兩段、或拆出來的 server/database 建不出身分時回傳 None：
        寧可說「這個檔名不是快取」，也不回報一個殘缺的身分。
        """
        parts = stem.split(_KEY_SEPARATOR)
        if len(parts) < 2:
            return None
        try:
            return cls.of(parts[0], _KEY_SEPARATOR.join(parts[1:]))
        except ValueError:
            return None

    @property
    def key(self) -> str:
        return _key_of(self.server, self.database)

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


@dataclass(frozen=True)
class CacheFile:
    """list_cache_files() 的一列：一個候選快取資料檔，以及命名它的身分。

    identity 為 None 代表檔名不是任何身分會寫出的名字（例如手動放進來的檔案、
    或舊格式的快取鍵）。要修檔的呼叫端與要列清單的呼叫端差別只在拿到這一列
    之後怎麼處理，判斷「哪些檔案是快取」這件事只在 list_cache_files() 做一次。
    """

    data_path: Path
    identity: Optional[CacheIdentity]


def list_cache_files() -> List[CacheFile]:
    """列出快取目錄裡每一個候選資料檔；本模組讀取快取目錄的唯一出口。

    Scan Record（.meta.json）與 Object Location Index（.index.json）也以 .json
    結尾，這裡排除它們，不產生任何一列。其餘每個 .json 檔都產生一列：身分用
    來回比對決定——從檔名拆出身分、由那個身分組回它自己的資料檔名，兩者相同
    才算這個身分命名的檔案。來回比對本身擋不掉 sibling 檔（索引檔的檔名會拆成
    database 以 `.index` 結尾的身分，而那個身分又剛好組回索引檔的檔名），所以
    副檔名排除必須留在這裡。依檔名排序回傳。
    """
    rows: List[CacheFile] = []
    for data_path in sorted(_cache_root().glob(f"*{_DATA_SUFFIX}")):
        name = data_path.name
        if name.endswith(_META_SUFFIX) or name.endswith(_INDEX_SUFFIX):
            continue
        identity = CacheIdentity.from_key(name[: -len(_DATA_SUFFIX)])
        if identity is not None and identity.filename != name:
            identity = None
        rows.append(CacheFile(data_path=data_path, identity=identity))
    return rows


def _same_file_part(actual: str, expected: str) -> bool:
    """快取檔名的一段是否等於呼叫端給的名字：比的是安全化後的檔名片段，不分大小寫。

    檔名反解出來的是 _safe_name() 之後的片段，所以呼叫端的名字也先安全化再比；
    不分大小寫則跟快取所在的 Windows 檔案系統、以及 _load() 的 _same_scope() 一致。
    """
    return _safe_name(actual).casefold() == _safe_name(expected).casefold()


@dataclass(frozen=True)
class AmbiguousServer:
    """find_cache_identity() 的一種結果：同名 database 在多台 server 上都有快取。

    無法判斷是哪一台，呼叫端應視為查無快取——寧可查無快取，也不猜錯資料庫。
    servers 依字母排序，列出每一台持有這個 database 的 server。
    """

    database: str
    servers: tuple[str, ...]


def find_cache_identity(database: str) -> Union[CacheIdentity, AmbiguousServer, None]:
    """呼叫端只知道 database 名稱時，從磁碟上唯一一份快取找出它的身分。

    會讀快取目錄，所以跟純函式 CacheIdentity.of() 分開命名。沒有任何快取以這個
    database 命名時回傳 None；同名 database 在多台 server 上都有快取時回傳
    AmbiguousServer。比對的是目錄列舉每一列身分的 Database 欄位，從不自己組
    檔名尾綴。檔名裡的 Database 是 _safe_name() 過的片段，所以只取它的 server，
    回傳的身分仍用呼叫端給的 database——跟快取內容記錄的名字一致。

    結構上沒有 server 可帶的呼叫端只有 refresh 流程的
    analyze_service.reconcile_refresh_wrappers()（含 tools/discover_external_wrappers.py）。
    /analyze、/path_evidence、/flow_chain、/find_by_sp、/find_by_table 會把請求的 db_server 一路帶到讀取端，
    指名讀哪一台；那些請求沒填 db_server 時同樣改走這裡。
    """
    database = str(database or "").strip()
    if not database:
        return None
    servers = tuple(
        sorted(
            {
                row.identity.server
                for row in list_cache_files()
                if row.identity is not None
                and _same_file_part(row.identity.database, database)
            }
        )
    )
    if not servers:
        return None
    if len(servers) > 1:
        print(
            f"⚠️  {database} 在多台 server 上都有 SQL 快取（{', '.join(servers)}）；"
            f"請指定 server。"
        )
        return AmbiguousServer(database=database, servers=servers)
    return CacheIdentity.of(servers[0], database)


@dataclass(frozen=True)
class ScanRecordListing:
    """list_caches() 的一列：一份 SQL 快取的身分與 Scan Record（掃描時間）。

    server/database 不正規化也不驗證，純粹反映磁碟上讀到的內容，連身分
    不完整的異常檔案都要能被列出（規格要求「never omitted from listing」）。
    檔名不是任何身分會寫出的名字時，database 帶著檔名主幹、server 為空，
    讓操作者看得到這個認不得的檔案。
    scanned_at 為 None 代表 Scan Record 缺失或無法讀取，不是「從未掃描」與
    「讀不到」的混淆表達——呼叫端據此決定要不要顯示「never scanned」。
    """

    server: str
    database: str
    scanned_at: Optional[str]


def _meta_names_file(info: Dict, data_filename: str) -> bool:
    """Scan Record 記錄的身分是否正好命名這個資料檔。

    舊的三段式快取（`server__PUR__dbo`）的 Scan Record 仍寫著 `database: PUR`；
    照收的話，一份永遠不會被載入的檔案會在清單上冒充 PUR 的掃描。
    """
    try:
        identity = CacheIdentity.of(str(info.get("server") or ""), str(info.get("database") or ""))
    except ValueError:
        return False
    return identity.filename == data_filename


def list_caches() -> List[ScanRecordListing]:
    """列出磁碟上每一份 SQL 快取的 (server, database) 與 Scan Record。

    純目錄列舉，不連線 SQL Server、不觸發掃描、不修改任何快取檔案；供
    GET /scan_records 這個唯讀端點使用。哪些檔案是快取由 list_cache_files()
    決定，這裡不另外過濾副檔名。Database Registry 完全不參與判斷——一份用
    --server/--database 直接掃描、Registry 裡沒登記的快取，一樣會出現在這份
    清單裡；檔名認不得身分的檔案也照樣列出，database 欄位放檔名主幹。

    每一列的 scan 時間來自同目錄下的 sibling meta 檔（.meta.json）；meta 檔
    缺失或無法解析時該列仍然列出，scanned_at 回 None，而不是整列被跳過。
    meta 檔記錄的身分正好命名這個資料檔時，身分欄位採 meta 檔內容（保留
    database 原本的寫法）；否則退回檔名——手動改壞的 Scan Record、或舊三段式
    快取的 Scan Record，只該讓這一列看起來怪，不該冒充另一份快取或讓端點失敗。

    回傳依 (server, database) 排序，讓同一份清單在多次呼叫間穩定
    （不受掃描先後影響）。
    """
    rows: List[ScanRecordListing] = []
    for cache_file in list_cache_files():
        identity = cache_file.identity
        stem = cache_file.data_path.name[: -len(_DATA_SUFFIX)]
        if identity is not None:
            server, database = identity.server, identity.database
        else:
            server, database = "", stem

        scanned_at: Optional[str] = None
        meta_path = cache_file.data_path.with_name(f"{stem}{_META_SUFFIX}")
        try:
            info = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            info = None
        if isinstance(info, dict):
            if _meta_names_file(info, cache_file.data_path.name):
                server = str(info.get("server") or server)
                database = str(info.get("database") or database)
            saved_at = info.get("saved_at")
            if saved_at:
                scanned_at = str(saved_at)

        rows.append(
            ScanRecordListing(server=server, database=database, scanned_at=scanned_at)
        )
    rows.sort(key=lambda row: (row.server, row.database))
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
    return _same_scope(graph.get("database"), identity.database)


def has_cache(identity: CacheIdentity) -> bool:
    """這個 Database 有沒有建檔：完全由對應的快取檔在不在磁碟上決定。"""
    return load_cached(identity) is not None


def cached_saved_at(identity: CacheIdentity) -> Optional[str]:
    """讀取這份 SQL 快取目前磁碟上 meta 檔記錄的 saved_at。

    與 load_cached() 收同一個身分，但只讀 meta 檔的 saved_at 一個欄位，不驗
    證/載入完整快取內容、不連線、不觸發任何 dump。供只需要「這份快取自上次
    derive 後有沒有變」信號的呼叫端使用（見 analyze_service 的 validity
    stamp），取代原本比對 Python 物件身分的做法。
    """
    _, meta_path = _paths(identity)
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
        "saved_at": saved_at,
    }


def write_meta(identity: CacheIdentity, saved_at: str) -> None:
    """把 identity 的 meta 檔寫到它自己的路徑。meta 格式只在這裡定義一次。

    路徑由 identity 決定，寫到哪裡跟記錄的身分不可能對不上。_save() 與測試的
    快取 fixture 共用這一個出口。saved_at 照傳照寫、不補值。
    """
    _, meta_path = _paths(identity)
    meta_path.write_text(
        json.dumps(_meta_payload(identity, saved_at), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


@dataclass(frozen=True)
class ObjectLocationIndex:
    """一份 SQL 快取的 Object Location Index：這份快取能回答哪些物件名稱。

    兩種物件（stored_procedures 含 procedures/views/functions；tables 含快取宣告的
    tables ∪ SQL Execution Graph 裡的 table 節點），每種兩個桶，都用 Canonical
    Object Identity 的 key 正規化：bare 桶只有 bare key，忽略 database 與 schema；
    full 桶是 `database.schema.name`。bare 桶保留今天持有的每一個名稱。
    快取列出的物件，database 取快取自己的 Database；graph 節點的 database 取 reference
    寫出的那個，沒寫就是快取自己的 Database。schema 沒人證明的節點，full key 的
    schema 段是空的，絕不補 dbo。
    寧可多報也不能少報：多報頂多多讀一次快取，少報會漏掉一個本該找到的答案。
    索引的版本是檔案的屬性，不是索引內容的一部分，所以值裡不帶版本。
    """

    server: str
    database: str
    stored_procedure_bare_keys: frozenset[str]
    stored_procedure_full_keys: frozenset[str]
    table_bare_keys: frozenset[str]
    table_full_keys: frozenset[str]

    def buckets(self, kind: str) -> tuple[frozenset[str], frozenset[str]]:
        """The (bare, full) buckets of one kind: "sp" or "table"."""
        if kind == "sp":
            return self.stored_procedure_bare_keys, self.stored_procedure_full_keys
        return self.table_bare_keys, self.table_full_keys


def _listed_full_key(identity: CacheIdentity, item: object) -> Optional[str]:
    """The full key of one listed object, or None for an entry with no name."""
    entry = item if isinstance(item, dict) else {}
    name = str(entry.get("name") or "").strip()
    if not name:
        return None
    written = parse(name)
    schema = str(entry.get("schema") or "").strip() or written.schema
    return full_key(ObjectName("", identity.database, schema, written.name))


def build_object_location_index(identity: CacheIdentity, data: Dict) -> ObjectLocationIndex:
    """把一份已載入的 SQL 快取內容，轉成它的 Object Location Index。

    refresh 路徑（_save()）與 backfill 工具共用這一個函式，不會有第二份實作。
    """
    stored_procedure_bare: set[str] = set()
    stored_procedure_full: set[str] = set()
    for collection in ("procedures", "views", "functions"):
        for item in data.get(collection, []) or []:
            key = _listed_full_key(identity, item)
            if key is not None:
                stored_procedure_bare.add(bare_key(str((item or {}).get("name") or "")))
                stored_procedure_full.add(key)

    table_bare: set[str] = set()
    table_full: set[str] = set()
    for item in data.get("tables", []) or []:
        key = _listed_full_key(identity, item)
        if key is not None:
            table_bare.add(bare_key(str((item or {}).get("name") or "")))
            table_full.add(key)

    graph = data.get("sql_execution_graph")
    if isinstance(graph, dict):
        # 一個節點被哪些 Database 的 reference 指到，就有哪幾把 full key；沒有
        # relationship 指到它的節點，只屬於快取自己的 Database。
        databases_of_target: Dict[str, set[str]] = {}
        for relationship in graph.get("relationships", []) or []:
            if not isinstance(relationship, dict):
                continue
            stated = str(relationship.get("database") or "").strip()
            databases_of_target.setdefault(str(relationship.get("target") or ""), set()).add(
                stated or identity.database
            )
        for node in graph.get("nodes", []) or []:
            if not isinstance(node, dict) or node.get("type") != "table":
                continue
            name = str(node.get("name") or "").strip()
            if not name:
                continue
            table_bare.add(bare_key(name))
            schema = str(node.get("schema") or "")
            for database in databases_of_target.get(str(node.get("id") or ""), {identity.database}):
                table_full.add(full_key(ObjectName("", database, schema, name)))

    return ObjectLocationIndex(
        server=identity.server,
        database=identity.database,
        stored_procedure_bare_keys=frozenset(stored_procedure_bare),
        stored_procedure_full_keys=frozenset(stored_procedure_full),
        table_bare_keys=frozenset(table_bare),
        table_full_keys=frozenset(table_full),
    )


def _index_payload(index: ObjectLocationIndex) -> Dict[str, object]:
    return {
        "index_version": _INDEX_VERSION,
        "server": index.server,
        "database": index.database,
        "stored_procedure_bare_keys": sorted(index.stored_procedure_bare_keys),
        "stored_procedure_full_keys": sorted(index.stored_procedure_full_keys),
        "table_bare_keys": sorted(index.table_bare_keys),
        "table_full_keys": sorted(index.table_full_keys),
    }


def write_object_location_index(identity: CacheIdentity, index: ObjectLocationIndex) -> None:
    """把索引寫到快取旁邊的獨立檔案——不併入 meta 檔，那是 Scan Record，意義不同。"""
    _index_path(identity).write_text(
        json.dumps(_index_payload(index), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_object_location_index(identity: CacheIdentity) -> Optional[ObjectLocationIndex]:
    """讀取一份索引；staleness 規則只定義在這一處。

    索引檔不存在、讀不了、修改時間早於它描述的快取資料檔、沒有 index_version 或
    版本跟現在的 _INDEX_VERSION 不相等（舊的、新的都算，新的可能來自被退版的部署）、
    缺任何一個桶（四個桶都要是 list）、或身分跟呼叫端要的 identity 對不上，都算
    「沒有索引」——呼叫端接下來照舊打開整份快取，絕不會因為索引壞掉而少答一個答案。

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
    version = payload.get("index_version")
    if isinstance(version, bool) or version != _INDEX_VERSION:
        return None
    if not _same_scope(payload.get("server"), identity.server):
        return None
    if not _same_scope(payload.get("database"), identity.database):
        return None
    buckets: list[frozenset[str]] = []
    for field in (
        "stored_procedure_bare_keys",
        "stored_procedure_full_keys",
        "table_bare_keys",
        "table_full_keys",
    ):
        bucket = payload.get(field)
        if not isinstance(bucket, list):
            return None
        buckets.append(frozenset(str(key) for key in bucket))
    stored_procedure_bare, stored_procedure_full, table_bare, table_full = buckets
    return ObjectLocationIndex(
        server=identity.server,
        database=identity.database,
        stored_procedure_bare_keys=stored_procedure_bare,
        stored_procedure_full_keys=stored_procedure_full,
        table_bare_keys=table_bare,
        table_full_keys=table_full,
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
        if info.get("server") and not _same_scope(info.get("server"), identity.server):
            return None
        data = json.loads(data_path.read_text(encoding="utf-8"))
        if not _is_valid_cache(data, identity):
            return None
        return data
    except Exception:
        return None


def _save(identity: CacheIdentity, data: Dict) -> None:
    data_path, _meta_path = _paths(identity)
    try:
        data_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        write_meta(identity, time.strftime("%Y-%m-%d %H:%M:%S"))
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


def load_cached(identity: CacheIdentity) -> Optional[Dict]:
    """單純讀取本機快取（不連線、不 dump）；查詢時的快速路徑用這個。"""
    retained = _mem_cache.get(identity)
    if retained is not None:
        if _is_valid_cache(retained, identity):
            _mem_cache.move_to_end(identity)
            return retained
        _mem_cache.pop(identity, None)
    cached = _load(identity)
    if cached is not None:
        _retain_in_mem_cache(identity, cached)
    return cached


def get_or_dump(
    identity: CacheIdentity,
    *,
    connection_server: str,
    refresh: bool = False,
    user_id: str = "",
    password: str = "",
    progress_callback: Callable[[str, int, int, str], None] | None = None,
) -> Dict:
    """
    取得（或建立）SQL 物件快取：優先用記憶體/磁碟快取；refresh=True 則強制重新
    連線 SQL Server 撈取 identity 指名的整庫定義並覆寫快取。

    identity：這份快取的身分，由呼叫端如 spec-rag 的 catalog 逐資料庫提供。

    connection_server：實際連線位址，照呼叫端給的原樣交給 SQLAnalyzer。它跟
    identity.server 不同——正規化會丟掉具名執行個體尾綴（`host\\instance`），
    快取鍵不分執行個體，連線卻一定要連到那個執行個體。缺值時由 SQLAnalyzer
    報錯、不嘗試連線（見 config.settings.build_database_config）。

    user_id/password：這一台伺服器的掃描帳密覆寫，兩者都有值才生效；缺一即沿用
    .env 的全域 DB_AUTH_MODE 身分（見 docs/adr/0010-scan-identity-independent-of-app-credentials.md）。
    掃描用的連線身分永遠不從被掃應用程式的 Web.config 推導。
    """
    db = identity.database
    if not refresh:
        cached = load_cached(identity)
        if cached is not None:
            print(f"⚡ 使用 SQL 快取：{db}")
            return cached

    print(f"🔍 連線 SQL Server 重新撈取物件定義：{db}")
    _report_progress(progress_callback, "connecting", 0, 1, db)
    from code_analyzer.sql_analyzer import SQLAnalyzer

    analyzer = SQLAnalyzer(
        db, server=connection_server, database_name=db, user_id=user_id, password=password
    )
    if not analyzer.connect():
        raise RuntimeError(f"無法連線資料庫：{db}")
    _report_progress(progress_callback, "connecting", 1, 1, db)
    try:
        if progress_callback is None:
            data = analyzer.dump_all_sql_objects()
        else:
            data = analyzer.dump_all_sql_objects(progress_callback=progress_callback)
    finally:
        try:
            analyzer.disconnect()
        except Exception:
            pass

    from .sql_execution_graph import build_sql_execution_graph

    data["sql_execution_graph"] = build_sql_execution_graph(
        data,
        progress_callback=progress_callback,
    )
    if not _is_valid_cache(data, identity):
        raise ValueError(
            f"SQL cache payload database identity mismatch: {db}"
        )
    _retain_in_mem_cache(identity, data)
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
