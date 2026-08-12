# 搜尋包含 Roles 資料表的 SP
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from code_analyzer.project_scanner import ProjectScanner

scanner = ProjectScanner(
    str(PROJECT_ROOT / 'data' / 'repos' / 'System_Dept_1' / 'Y-DOCs' / 'TTPUR')
)
scanner.initialize_databases(['PUR'])

analyzer = scanner.sql_analyzers['PUR']
cursor = analyzer.connection.cursor()

# 搜尋包含 Roles 的 SP
query = """
SELECT 
    OBJECT_NAME(object_id) as sp_name,
    LEFT(definition, 200) as preview
FROM sys.sql_modules 
WHERE definition LIKE '%Roles%' 
AND OBJECTPROPERTY(object_id, 'IsProcedure') = 1
"""

cursor.execute(query)
results = cursor.fetchall()

print("\n" + "=" * 80)
print(f"找到 {len(results)} 個 SP 包含 'Roles'")
print("=" * 80)

for i, r in enumerate(results[:5], 1):
    print(f"\n{i}. {r.sp_name}")
    print(f"   預覽: {r.preview[:100]}...")

scanner.close_databases()
