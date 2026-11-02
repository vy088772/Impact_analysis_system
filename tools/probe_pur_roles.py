# tools/probe_pur_roles.py
"""
手動檢查：在 PUR 資料庫裡，找出定義內含某個關鍵字的 SP（預設找 Roles）

用途：手動確認某個資料表被哪些 SP 用到。這支工具會連到真正的 PUR 資料庫，
所以不是自動測試，pytest 不會收集它。

需求：
  - data/repos/System_Dept_1/Y-DOCs/TTPUR 已 clone（從它的 web.config 讀連線字串）
  - 這台機器有 ODBC Driver 17 for SQL Server，並且連得到 PUR 資料庫

用法（於 Impact_analysis_system 專案根目錄執行，需啟用其 .venv）：
    python tools/probe_pur_roles.py
    python tools/probe_pur_roles.py --keyword Users --limit 10
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
# 讓本檔可從 Impact_analysis_system 專案根目錄以外的 cwd 執行時，仍能 import 到本專案模組
sys.path.insert(0, str(PROJECT_ROOT))

from code_analyzer.project_scanner import ProjectScanner  # noqa: E402

TTPUR_ROOT = PROJECT_ROOT / "data" / "repos" / "System_Dept_1" / "Y-DOCs" / "TTPUR"
DATABASE = "PUR"

_QUERY = """
SELECT
    OBJECT_NAME(object_id) as sp_name,
    LEFT(definition, 200) as preview
FROM sys.sql_modules
WHERE definition LIKE ?
AND OBJECTPROPERTY(object_id, 'IsProcedure') = 1
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--keyword", default="Roles", help="SP 定義裡要找的字（預設 Roles）")
    parser.add_argument("--limit", type=int, default=5, help="最多列出幾個 SP（預設 5）")
    args = parser.parse_args()

    scanner = ProjectScanner(str(TTPUR_ROOT))
    scanner.initialize_databases([DATABASE])
    try:
        analyzer = scanner.sql_analyzers.get(DATABASE)
        if analyzer is None:
            print(f"❌ 沒有連上 {DATABASE} 資料庫，請看上面的連線訊息。", file=sys.stderr)
            return 1

        cursor = analyzer.connection.cursor()
        cursor.execute(_QUERY, f"%{args.keyword}%")
        results = cursor.fetchall()

        print("\n" + "=" * 80)
        print(f"找到 {len(results)} 個 SP 包含 '{args.keyword}'")
        print("=" * 80)

        for i, r in enumerate(results[: args.limit], 1):
            print(f"\n{i}. {r.sp_name}")
            print(f"   預覽: {r.preview[:100]}...")
        return 0
    finally:
        scanner.close_databases()


if __name__ == "__main__":
    sys.exit(main())
