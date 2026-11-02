# tools/probe_pur_sp_tables.py
"""
手動檢查：列出 PUR 資料庫裡某個 SP 用到的資料表（預設 dbo.usp_CheckProgramAuth）

用途：手動確認 SQL 分析器從 SP 定義讀出的資料表對不對。這支工具會連到真正的
PUR 資料庫，所以不是自動測試，pytest 不會收集它。

需求：
  - data/repos/System_Dept_1/Y-DOCs/TTPUR 已 clone（從它的 web.config 讀連線字串）
  - 這台機器有 ODBC Driver 17 for SQL Server，並且連得到 PUR 資料庫

用法（於 Impact_analysis_system 專案根目錄執行，需啟用其 .venv）：
    python tools/probe_pur_sp_tables.py
    python tools/probe_pur_sp_tables.py --sp usp_GetOrder --schema dbo
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sp", default="usp_CheckProgramAuth", help="SP 名稱（預設 usp_CheckProgramAuth）")
    parser.add_argument("--schema", default="dbo", help="SP 的 schema（預設 dbo）")
    args = parser.parse_args()

    print("=" * 80)
    print(f"檢查 {args.schema}.{args.sp} 的資料表")
    print("=" * 80)

    scanner = ProjectScanner(TTPUR_ROOT)
    scanner.initialize_databases([DATABASE])
    try:
        analyzer = scanner.sql_analyzers.get(DATABASE)
        if analyzer is None:
            print(f"❌ 沒有連上 {DATABASE} 資料庫，請看上面的連線訊息。", file=sys.stderr)
            return 1

        sp_info = analyzer.quick_analyze_sp(args.sp, args.schema)

        print(f"\nSP: {sp_info.procedure_name}")
        print(f"資料表: {sp_info.referenced_tables}")
        print(f"資料表數量: {len(sp_info.referenced_tables)}")

        for table in sp_info.referenced_tables:
            print(f"  - {table} (upper: {table.upper()})")
        return 0
    finally:
        scanner.close_databases()


if __name__ == "__main__":
    sys.exit(main())
