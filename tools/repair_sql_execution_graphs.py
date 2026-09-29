#!/usr/bin/env python3
"""把磁碟上每一份 SQL 快取的 sql_execution_graph 重建成目前版本。

GRAPH_VERSION 每次提高都跑一次：讀取路徑只拒用舊版 Graph，不在查詢時重建。
v3 修正 offset（下段說明）；v5 讓每個 analyzer 參照保留 server、database、
schema、名稱四段（canonical-object-identity，Step 2a）；v7 讓沒寫 schema 的參照
保持空白、不再補 dbo（Step 2b）。重建之後接著跑
tools/backfill_object_location_indexes.py。

v3：01、02 兩張票只修好「以後怎麼寫」；這支工具修「已經寫壞的」——每份快取檔
早在修好之前就已經用會腐蝕 offset 的舊寫法建好了 sql_execution_graph，
不主動修就會一路帶著錯誤的 offset 留在磁碟上，直到被拒用（graph_version
不符）或更糟、offset 剛好還落在界內、悄悄切出錯的內容。

只重建 sql_execution_graph，不重新連線 SQL Server：每份快取檔裡
procedures/views/functions 的 definition 文字本來就是對的（腐蝕只發生在
餵給 ScriptDom 的暫存檔，不是寫進 JSON 的這份），把它們重新丟一次
build_sql_execution_graph() 就能算出正確的 offset，不需要資料庫連線與帳密。

用法：
    python tools/repair_sql_execution_graphs.py [--dry-run] [--cache-root data/sql_cache]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from code_analyzer.static_analyzer_host import StaticAnalyzerHost  # noqa: E402
from service import sql_cache_store  # noqa: E402
from service.sql_execution_graph import GRAPH_VERSION, build_sql_execution_graph  # noqa: E402


def _existing_graph_version(payload: object) -> Optional[int]:
    if not isinstance(payload, dict):
        return None
    graph = payload.get("sql_execution_graph")
    if not isinstance(graph, dict):
        return None
    version = graph.get("graph_version")
    return version if isinstance(version, int) else None


def repair_cache_file(
    data_path: Path,
    host: StaticAnalyzerHost,
    project_root: Path,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """修好單一快取檔：只換掉 sql_execution_graph 這個欄位，其餘原封不動。"""
    entry: Dict[str, Any] = {
        "path": str(data_path),
        "old_graph_version": None,
        "new_graph_version": GRAPH_VERSION,
    }

    try:
        raw = data_path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:  # 單一檔案讀不動不該讓整批搬移中斷
        entry["action"] = "unreadable"
        entry["error"] = str(exc)
        return entry

    if not isinstance(payload, dict):
        entry["action"] = "not_a_cache"
        return entry

    entry["old_graph_version"] = _existing_graph_version(payload)
    if entry["old_graph_version"] == GRAPH_VERSION:
        entry["action"] = "already_current"
        return entry

    entry["action"] = "would_repair" if dry_run else "repaired"
    if dry_run:
        return entry

    # 只用這份快取自己已經存好的 procedures/views/functions definition 文字
    # 重新跑一次 build_sql_execution_graph()——不連線 SQL Server、不改動
    # payload 裡除了 sql_execution_graph 以外的任何欄位。
    payload["sql_execution_graph"] = build_sql_execution_graph(
        payload, host=host, project_root=project_root
    )
    # 整份重新 json.dumps() 而不定點取代位元組：
    # 這裡換的是一個巢狀 JSON 物件（graph），不是單一純量值，定點取代等於要自己
    # 重寫一個 JSON 解析器去找對應的大括號，脆弱得不划算。之所以其餘欄位仍然
    # 「等同於原封不動」，是因為磁碟上每一份快取本來就只由 sql_cache_store._save()
    # 用同一組 json.dumps(data, ensure_ascii=False, indent=2) 參數寫出；用同一組
    # 參數對同一個（除了這個欄位）內容不變的 dict 重新序列化，得到的位元組必然相同。
    data_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return entry


def repair_all_caches(
    host: Optional[StaticAnalyzerHost] = None,
    project_root: Optional[Path] = None,
    dry_run: bool = False,
) -> List[Dict[str, Any]]:
    """修好目前快取根目錄底下每一份 SQL 快取；回傳每一筆的處理結果。

    哪些檔案是快取只問 sql_cache_store.list_cache_files()，這裡不留自己的副檔名
    清單——自己留一份時漏了 .index.json，索引檔排在資料檔前面又不是快取格式，
    第一個檔案就讓整批修復中斷。檔名認不得身分的檔案回報後略過；認得身分、
    重建卻失敗的檔案是缺陷，照樣讓整批中斷。
    """
    project_root = project_root or PROJECT_ROOT
    host = host or StaticAnalyzerHost.for_project(project_root)
    host.ensure_ready()

    results: List[Dict[str, Any]] = []
    for cache_file in sql_cache_store.list_cache_files():
        if cache_file.identity is None:
            results.append(
                {
                    "path": str(cache_file.data_path),
                    "action": "bad_identity",
                    "old_graph_version": None,
                    "new_graph_version": GRAPH_VERSION,
                }
            )
            continue
        results.append(repair_cache_file(cache_file.data_path, host, project_root, dry_run))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="把磁碟上每一份 SQL 快取的 sql_execution_graph 重建成目前版本"
    )
    parser.add_argument(
        "--cache-root",
        default=None,
        help="SQL 快取根目錄（預設讀 settings.SQL_CACHE_ROOT）",
    )
    parser.add_argument("--dry-run", action="store_true", help="只列出會做什麼，不改檔案")
    args = parser.parse_args()

    from config.settings import settings

    if args.cache_root:
        settings.SQL_CACHE_ROOT = args.cache_root

    results = repair_all_caches(dry_run=args.dry_run)
    labels = {
        "repaired": "✅ 已修好",
        "would_repair": "🔎 將修好",
        "already_current": "⏭️  已是目前版本，略過",
        "unreadable": "⚠️  讀取失敗",
        "not_a_cache": "⚠️  非快取格式，略過",
        "bad_identity": "⚠️  身分無法辨識，略過",
    }
    for entry in results:
        action = str(entry["action"])
        label = labels.get(action, f"⚠️  未知結果（{action}）")
        old_version = entry["old_graph_version"]
        print(
            f"{label}：{entry['path']}"
            f"（graph_version {old_version} → {entry['new_graph_version']}）"
        )
    if not results:
        print("找不到任何 SQL 快取檔。")


if __name__ == "__main__":
    main()
