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
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Dict, Optional

from config.settings import settings

# 快取格式版本：dump_all_sql_objects() 回傳結構若變動則遞增，讓舊快取自動失效
# v2：tables[].primary_keys（供 fk_resolver.py 的 PK 命名慣例推論關聯使用）
_SQL_CACHE_VERSION = 2

# 同 process 內的記憶體快取
_mem_cache: Dict[str, Dict] = {}


def _safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", text or "").strip("_") or "default"


def _cache_root() -> Path:
    root = Path(settings.SQL_CACHE_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _key(database_alias: str, schema: str) -> str:
    return f"{_safe_name(database_alias)}__{_safe_name(schema)}"


def _paths(database_alias: str, schema: str) -> tuple[Path, Path]:
    k = _key(database_alias, schema)
    return _cache_root() / f"{k}.json", _cache_root() / f"{k}.meta.json"


def has_cache(database_alias: str, schema: str = "dbo") -> bool:
    data_path, _ = _paths(database_alias, schema)
    return data_path.exists()


def _load(database_alias: str, schema: str) -> Optional[Dict]:
    data_path, meta_path = _paths(database_alias, schema)
    if not data_path.exists():
        return None
    try:
        if meta_path.exists():
            info = json.loads(meta_path.read_text(encoding="utf-8"))
            if info.get("cache_version") != _SQL_CACHE_VERSION:
                return None
        return json.loads(data_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _save(database_alias: str, schema: str, data: Dict) -> None:
    data_path, meta_path = _paths(database_alias, schema)
    try:
        data_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        meta_path.write_text(
            json.dumps(
                {
                    "cache_version": _SQL_CACHE_VERSION,
                    "database": database_alias,
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


def load_cached(database_alias: str, schema: str = "dbo") -> Optional[Dict]:
    """單純讀取本機快取（不連線、不 dump）；查詢時的快速路徑用這個。"""
    key = _key(database_alias, schema)
    if key in _mem_cache:
        return _mem_cache[key]
    cached = _load(database_alias, schema)
    if cached is not None:
        _mem_cache[key] = cached
    return cached


def get_or_dump(
    database_alias: str,
    schema: str = "dbo",
    refresh: bool = False,
    server: str = "",
    db_name: str = "",
) -> Dict:
    """
    取得（或建立）SQL 物件快取：優先用記憶體/磁碟快取；refresh=True 則強制重新
    連線 SQL Server 撈取整庫定義並覆寫快取。

    server/db_name：實際連線目標（由呼叫端如 spec-rag 的 catalog 逐系統提供），
    只在需要真的連線時（refresh=True 或無現成快取）才用得到；缺一即由
    SQLAnalyzer 直接報錯、不嘗試連線（見 config.settings.build_database_config）。
    """
    key = _key(database_alias, schema)

    if not refresh:
        if key in _mem_cache:
            return _mem_cache[key]
        cached = _load(database_alias, schema)
        if cached is not None:
            _mem_cache[key] = cached
            print(f"⚡ 使用 SQL 快取：{database_alias}.{schema}")
            return cached

    print(f"🔍 連線 SQL Server 重新撈取物件定義：{database_alias}.{schema}")
    from code_analyzer.sql_analyzer import SQLAnalyzer

    analyzer = SQLAnalyzer(database_alias, server=server, database_name=db_name)
    if not analyzer.connect():
        raise RuntimeError(f"無法連線資料庫：{database_alias}")
    try:
        data = analyzer.dump_all_sql_objects(schema)
    finally:
        try:
            analyzer.disconnect()
        except Exception:
            pass

    _mem_cache[key] = data
    _save(database_alias, schema, data)
    return data
