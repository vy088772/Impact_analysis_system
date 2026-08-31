#!/usr/bin/env python3
"""一次性搬移：幫磁碟上每一份已經存在、還沒有 Object Location Index 的 SQL 快取
補上索引——不重新連線 SQL Server、不改動快取內容，只在快取旁邊多寫一個索引檔。

01 號票只讓「以後」的 refresh 自動帶著索引一起寫；這支工具補「已經在磁碟上」的
存量——那些快取早在 01 號票之前就已經寫好，不主動補，`/locate_object` 就永遠
看不到它們，Reverse Lookup 也就享受不到「跳過用不到的快取」這個好處。PUR 一顆
快取就有 105 MB、又是兩個有申報 Database 的 System 都會查到的快取，補齊它的
索引是這支工具第一個要拿到的好處。

用法：
    python tools/backfill_object_location_indexes.py [--dry-run] [--cache-root data/sql_cache]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from service import sql_cache_store  # noqa: E402


def backfill_cache_row(
    row: sql_cache_store.ScanRecordListing, dry_run: bool = False
) -> Dict[str, Any]:
    """幫 list_caches() 列出的其中一列補索引；回傳這一列的處理結果。"""
    entry: Dict[str, Any] = {
        "server": row.server,
        "database": row.database,
        "schema": row.schema,
    }

    try:
        identity = sql_cache_store.CacheIdentity.of(row.server, row.database, row.schema)
    except ValueError as exc:
        entry["action"] = "bad_identity"
        entry["error"] = str(exc)
        return entry

    # load_cached() 套用跟 find_by_sp/find_by_table 完全相同的有效性判斷（meta
    # 版本、sql_execution_graph 版本、database/schema 是否相符）——backfill 出來的
    # 索引才會跟正式查詢路徑「看到同一份快取」，不會有索引說「有」但正式查詢其實
    # 連這份快取都不採信的落差。這個函式本身不連線 SQL Server、只讀磁碟。
    data = sql_cache_store.load_cached(identity.database, identity.schema, server=identity.server)
    if data is None:
        entry["action"] = "invalid_cache"
        return entry

    index = sql_cache_store.build_object_location_index(identity, data)
    entry["stored_procedures"] = len(index.stored_procedures)
    entry["tables"] = len(index.tables)
    entry["action"] = "would_index" if dry_run else "indexed"
    if not dry_run:
        sql_cache_store.write_object_location_index(identity, index)
    return entry


def backfill_all_caches(dry_run: bool = False) -> List[Dict[str, Any]]:
    """幫目前快取根目錄底下每一份快取補索引；回傳每一列的處理結果。

    只走 list_caches() 列出的清單、只用 load_cached() 讀內容——不自己另外
    glob 目錄、不打開 SQL Server 連線、不改動快取本身的任何欄位。重跑一次一律
    重新建索引並覆寫舊檔：索引沒有自己的版本號要追（cache_version 只用來偵測
    快取格式換版），所以每次重跑都安全、也都等冪。
    """
    return [backfill_cache_row(row, dry_run=dry_run) for row in sql_cache_store.list_caches()]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="幫磁碟上每一份已經存在的 SQL 快取補上 Object Location Index"
    )
    parser.add_argument(
        "--cache-root",
        default=None,
        help="SQL 快取根目錄（預設讀 settings.SQL_CACHE_ROOT）",
    )
    parser.add_argument("--dry-run", action="store_true", help="只列出會做什麼，不寫索引檔")
    args = parser.parse_args()

    from config.settings import settings

    if args.cache_root:
        settings.SQL_CACHE_ROOT = args.cache_root

    results = backfill_all_caches(dry_run=args.dry_run)
    labels = {
        "indexed": "✅ 已建立索引",
        "would_index": "🔎 將建立索引",
        "invalid_cache": "⚠️  快取無效（讀取路徑不會採信），略過",
        "bad_identity": "⚠️  身分無法辨識，略過",
    }
    for entry in results:
        action = str(entry["action"])
        label = labels.get(action, f"⚠️  未知結果（{action}）")
        identity_text = f"{entry.get('server')}/{entry.get('database')}/{entry.get('schema')}"
        detail = ""
        if action in ("indexed", "would_index"):
            detail = f"（SP/View/Function {entry['stored_procedures']} 個、資料表 {entry['tables']} 個）"
        elif entry.get("error"):
            detail = f"（{entry['error']}）"
        print(f"{label}：{identity_text}{detail}")
    if not results:
        print("找不到任何 SQL 快取檔。")


if __name__ == "__main__":
    main()
