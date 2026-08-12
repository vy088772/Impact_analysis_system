# 測試 SP 資料表資訊
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from code_analyzer.project_scanner import ProjectScanner

print("=" * 80)
print("檢查 usp_CheckProgramAuth 的資料表")
print("=" * 80)

project_root = PROJECT_ROOT / "data" / "repos" / "System_Dept_1" / "Y-DOCs" / "TTPUR"
scanner = ProjectScanner(project_root)

# 初始化資料庫
scanner.initialize_databases(['PUR'])

# 尋找並分析 SP
analyzer = scanner.sql_analyzers['PUR']
sp_info = analyzer.quick_analyze_sp('usp_CheckProgramAuth')

print(f"\nSP: {sp_info.procedure_name}")
print(f"資料表: {sp_info.referenced_tables}")
print(f"資料表數量: {len(sp_info.referenced_tables)}")

for table in sp_info.referenced_tables:
    print(f"  - {table} (upper: {table.upper()})")

scanner.close_databases()
