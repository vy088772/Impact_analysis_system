# tools/check_data_status.py
"""
資料完整性總覽：依 spec-rag 的 system_catalog.json 逐系統檢查

  1. 規格書資料   spec-rag/data/systems/<system_id>            （原始 .md 檔數）
  2. 向量索引     spec-rag/storage/<system_id>                 （已建索引的檔案數）
  3. 程式碼 clone data/repos/<project>/<repo>                  （是否已 clone）
  4. 靜態掃描快取 data/scan_cache/<hash>.pkl                   （是否已掃描過）
  5. SQL 快取     data/sql_cache/<system_id>__dbo.json         （是否已更新過）

用途：目前資料來源多（規格書、程式碼、SQL、各種 cache），容易漏掉某個系統忘記
clone / refresh，這支工具一次列出所有系統目前的狀態，方便盤點。

用法（於 Impact_analysis_system 專案根目錄執行，需啟用其 .venv）：
    python tools/check_data_status.py
    python tools/check_data_status.py --spec-rag-root "D:\\pratice\\Python\\llamaindex-spec-rag"
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 讓本檔可從 Impact_analysis_system 專案根目錄以外的 cwd 執行時，仍能 import 到本專案模組
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import settings  # noqa: E402
from service import repo_manager  # noqa: E402
from service import scan_store  # noqa: E402
from service import sql_cache_store  # noqa: E402

OK = "✅"
NO = "❌"
NA = "—"


def _count_files(d: Path, pattern: str = "*") -> int:
    if not d.exists():
        return 0
    return sum(1 for p in d.glob(pattern) if p.is_file())


def _spec_status(spec_rag_root: Path, system_id: str) -> tuple[str, str]:
    """回傳 (原始規格書狀態, 向量索引狀態)。"""
    raw_dir = spec_rag_root / "data" / "systems" / system_id
    raw_count = _count_files(raw_dir, "*.md")
    raw = f"{OK} {raw_count}份" if raw_count > 0 else f"{NO} 無檔案"

    store_dir = spec_rag_root / "storage" / system_id
    docstore = store_dir / "docstore.json"
    indexed = store_dir / "indexed_files.json"
    if docstore.exists() and docstore.stat().st_size > 2:
        idx_count = None
        if indexed.exists():
            try:
                idx_count = len(json.loads(indexed.read_text(encoding="utf-8")))
            except Exception:
                idx_count = None
        indexed_str = f"{idx_count}份" if idx_count is not None else "已建"
        vec = f"{OK} {indexed_str}"
    else:
        vec = f"{NO} 未建索引"
    return raw, vec


def _code_status(azure: dict) -> tuple[str, str]:
    project = (azure or {}).get("project", "")
    repo = (azure or {}).get("repo", "")
    if not repo:
        return f"{NA} 未設定repo", f"{NA} —"

    cloned = repo_manager.is_cloned(project, repo)
    if not cloned:
        return f"{NO} 未clone", f"{NO} 未clone"

    clone_str = f"{OK} 已clone"
    # 比照 repo_manager.peek_scan_roots 的子路徑判斷邏輯，但不觸發 clone；
    # path 可能是單一字串或多個子資料夾清單（同一套系統拆成多個 VS 專案），
    # 全部都要有掃描快取才算「已掃描」。
    scan_roots = repo_manager.peek_scan_roots(azure or {})
    has_cache = bool(scan_roots) and all(scan_store.has_cache(r) for r in scan_roots)
    if not has_cache:
        return clone_str, f"{NO} 未掃描"

    # 已有快取 → 再比對「掃描當下記錄的 commit」與「repo 目前本機 HEAD」是否一致，
    # 偵測 repo 已 git pull 到新版、但掃描快取還是舊版程式碼結果的情況。快取本身
    # 是否過期不影響快取是否可用（get_or_scan 仍會沿用），這裡只是額外提醒。
    stale = False
    for r in scan_roots:
        cached = scan_store.cached_commit(r)
        current = scan_store.current_commit(r)
        if cached is not None and current is not None and cached != current:
            stale = True
            break
    scan_str = f"⚠️ 已掃描(有新版未同步)" if stale else f"{OK} 已掃描"
    return clone_str, scan_str


def _sql_status(database: dict, system_id: str) -> str:
    server = (database or {}).get("server", "")
    name = (database or {}).get("name", "")
    if not server or not name:
        return f"{NA} 未設定DB"
    return f"{OK} 已更新" if sql_cache_store.has_cache(system_id, "dbo") else f"{NO} 未更新"


def main() -> None:
    parser = argparse.ArgumentParser(description="檢查各系統的規格書/程式碼/SQL 資料整理狀態")
    parser.add_argument(
        "--spec-rag-root",
        default=str(Path(settings.AZURE_CLONE_ROOT).resolve().parent.parent.parent
                    / "llamaindex-spec-rag"),
        help="spec-rag 專案根目錄（預設抓同層的 llamaindex-spec-rag）",
    )
    args = parser.parse_args()
    spec_rag_root = Path(args.spec_rag_root)

    catalog_path = spec_rag_root / "catalog" / "system_catalog.json"
    if not catalog_path.exists():
        print(f"{NO} 找不到 system_catalog.json：{catalog_path}")
        sys.exit(1)

    systems = json.loads(catalog_path.read_text(encoding="utf-8"))["systems"]

    rows = []
    need_code_refresh: list[str] = []   # 程式碼未clone 或 未掃描 → 都靠 refresh_cli 補齊
    need_sql_refresh: list[str] = []    # 有設定 DB 但 SQL 快取未更新 → refresh_sql_cli 補齊
    for sys_ in systems:
        system_id = sys_.get("system_id", "")
        azure = sys_.get("azure", {})
        database = sys_.get("database", {})
        raw, vec = _spec_status(spec_rag_root, system_id)
        code, scan = _code_status(azure)
        sql = _sql_status(database, system_id)
        rows.append((system_id, raw, vec, code, scan, sql))

        has_repo = bool((azure or {}).get("repo"))
        if has_repo and (NO in code or NO in scan or "⚠️" in scan):
            need_code_refresh.append(system_id)

        has_db = bool((database or {}).get("server")) and bool((database or {}).get("name"))
        if has_db and NO in sql:
            need_sql_refresh.append(system_id)

    headers = ["system_id", "規格書(原始)", "規格書(索引)", "程式碼(clone)", "程式碼(掃描)", "SQL快取"]
    widths = [max(len(h), *(len(r[i]) for r in rows)) if rows else len(h)
              for i, h in enumerate(headers)]

    def fmt_row(vals: list[str]) -> str:
        return " | ".join(v.ljust(widths[i]) for i, v in enumerate(vals))

    print(fmt_row(headers))
    print("-+-".join("-" * w for w in widths))
    for r in rows:
        print(fmt_row(list(r)))

    print(f"\n共 {len(rows)} 個系統。spec-rag 根目錄：{spec_rag_root}")

    print("\n--- 補齊資料要跑的指令（皆在 llamaindex-spec-rag 專案根目錄下執行，")
    print("    且需先在 Impact_analysis_system 專案啟動服務：")
    print("    cd d:\\pratice\\Python\\Impact_analysis_system")
    print("    .\\.venv\\Scripts\\python.exe -m uvicorn service.api:app --host 127.0.0.1 --port 8800")
    print("    ）---")

    if need_code_refresh:
        print("\n[程式碼 clone / 掃描未完成] → 執行 refresh_cli（git pull + 重新靜態解析，一次指令同時補齊 clone 與掃描）：")
        print("    cd d:\\pratice\\Python\\llamaindex-spec-rag")
        print(f"    .\\.venv\\Scripts\\python.exe -m impact_orch.refresh_cli {' '.join(need_code_refresh)}")
    else:
        print("\n[程式碼 clone / 掃描] 皆已完成（或該系統未設定 repo，略過）。")

    if need_sql_refresh:
        print("\n[SQL 快取未更新] → 執行 refresh_sql_cli（重新連線撈取整庫 SP/View/Function/資料表 Schema）：")
        print("    cd d:\\pratice\\Python\\llamaindex-spec-rag")
        print(f"    .\\.venv\\Scripts\\python.exe -m impact_orch.refresh_sql_cli {' '.join(need_sql_refresh)}")
    else:
        print("\n[SQL 快取] 皆已完成（或該系統未設定 database.server/name，略過）。")


if __name__ == "__main__":
    main()
