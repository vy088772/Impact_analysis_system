#!/usr/bin/env python3
"""一次性搬移：把舊的 system_id 式 SQL 快取檔名改成 (server, database, schema) 鍵。

舊鍵是 `{system_id}__{schema}`（例如 `Y-Docs_TTPUR__dbo`），新鍵是
`{正規化 server}__{database}__{schema}`（見 service/sql_cache_store.py 與
docs/adr/0009-sql-cache-identity-decoupled-from-system.md）。

只改名，不重掃：33MB 的 PUR 快取內容原封不動搬過去。唯一會改寫的是快取內部
記錄「自己是哪個資料庫」的兩個欄位（`database` 與 `sql_execution_graph.database`），
因為舊檔案存的是 system_id、不是真正的資料庫名稱，不改的話新讀取端會判定
身分不符而拒用這份快取。

用法：
    python tools/migrate_sql_cache_keys.py [--dry-run] [--cache-root data/sql_cache]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from service import sql_cache_store  # noqa: E402

# 現存的兩份快取：(舊快取鍵, server, 真正的資料庫名稱, schema)。
# 這是一次性搬移的完整清單——本專案只有這兩份快取，之後寫出的快取一律用新鍵。
LEGACY_CACHE_SCOPES: List[Tuple[str, str, str, str]] = [
    ("STC__dbo", "vmsystest07", "STC", "dbo"),
    ("Y-Docs_TTPUR__dbo", "vmsystest07", "PUR", "dbo"),
]

Scope = Tuple[str, str, str, str]


def _identity_aliases(payload: object, database: str) -> List[str]:
    """快取內部目前自稱的資料庫身分，扣掉已經正確的那些。"""
    if not isinstance(payload, dict):
        return []
    claimed = {str(payload.get("database") or "")}
    graph = payload.get("sql_execution_graph")
    if isinstance(graph, dict):
        claimed.add(str(graph.get("database") or ""))
    return sorted(alias for alias in claimed if alias and alias != database)


def _retag_identity(raw: bytes, database: str) -> Tuple[bytes, bool]:
    """只改寫身分欄位的那幾個位元組，其餘（含換行符號）原封不動。

    整份重新 json.dumps() 會順手改掉換行符號、把 33MB 的檔案整個重寫一遍；
    這裡改成定點取代，讓「不重掃」也真的等於「內容不動」。
    """
    payload = json.loads(raw.decode("utf-8"))
    aliases = _identity_aliases(payload, database)
    if not aliases:
        return raw, False
    for alias in aliases:
        needle = f'"database": "{alias}"'.encode("utf-8")
        if needle not in raw:
            raise ValueError(
                f"找不到可改寫的身分欄位 {alias!r}；此檔案格式與預期不符，請人工確認。"
            )
        raw = raw.replace(needle, f'"database": "{database}"'.encode("utf-8"))
    if _identity_aliases(json.loads(raw.decode("utf-8")), database):
        raise ValueError(f"身分改寫後仍不是 {database!r}；請人工確認。")
    return raw, True


def _migrate_one(cache_root: Path, scope: Scope, dry_run: bool) -> Dict[str, object]:
    legacy_key, server, database, schema = scope
    new_key = sql_cache_store.cache_key(server, database, schema)
    legacy_data = cache_root / f"{legacy_key}.json"
    legacy_meta = cache_root / f"{legacy_key}.meta.json"
    new_data = cache_root / f"{new_key}.json"
    new_meta = cache_root / f"{new_key}.meta.json"

    entry: Dict[str, object] = {
        "legacy_key": legacy_key,
        "new_key": new_key,
        "action": "missing",
        "retagged": False,
    }
    if not legacy_data.exists():
        return entry
    if new_data.exists():
        entry["action"] = "already_migrated"
        return entry
    entry["action"] = "migrated"
    if dry_run:
        entry["action"] = "would_migrate"
        return entry

    legacy_data.rename(new_data)
    if legacy_meta.exists():
        legacy_meta.rename(new_meta)

    raw, changed = _retag_identity(new_data.read_bytes(), database)
    if changed:
        new_data.write_bytes(raw)
    entry["retagged"] = changed

    meta = {}
    if new_meta.exists():
        try:
            meta = json.loads(new_meta.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
    meta.update(
        {
            "cache_version": sql_cache_store._SQL_CACHE_VERSION,
            "server": sql_cache_store.normalize_server(server),
            "database": database,
            "schema": schema,
        }
    )
    new_meta.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return entry


def migrate_cache_keys(
    cache_root: Path,
    scopes: Sequence[Scope] = tuple(LEGACY_CACHE_SCOPES),
    dry_run: bool = False,
) -> List[Dict[str, object]]:
    """把 scopes 列出的舊快取檔改名成新鍵；回傳每一筆的處理結果。"""
    cache_root = Path(cache_root)
    return [_migrate_one(cache_root, scope, dry_run) for scope in scopes]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="把舊的 system_id 式 SQL 快取檔名搬移成 (server, database, schema) 鍵"
    )
    parser.add_argument(
        "--cache-root",
        default=None,
        help="SQL 快取根目錄（預設讀 settings.SQL_CACHE_ROOT）",
    )
    parser.add_argument("--dry-run", action="store_true", help="只列出會做什麼，不改檔案")
    args = parser.parse_args()

    from config.settings import settings

    cache_root = Path(args.cache_root or settings.SQL_CACHE_ROOT)
    results = migrate_cache_keys(cache_root, LEGACY_CACHE_SCOPES, dry_run=args.dry_run)
    for entry in results:
        label = {
            "migrated": "✅ 已搬移",
            "would_migrate": "🔎 將搬移",
            "already_migrated": "⏭️  已是新鍵，略過",
            "missing": "⏭️  找不到舊檔，略過",
        }[str(entry["action"])]
        suffix = "（已更正快取內的資料庫身分）" if entry["retagged"] else ""
        print(f"{label}：{entry['legacy_key']} → {entry['new_key']}{suffix}")


if __name__ == "__main__":
    main()
