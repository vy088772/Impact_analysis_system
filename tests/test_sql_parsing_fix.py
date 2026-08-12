# 測試 SQL 解析修復
import sys
sys.path.insert(0, 'D:\\pratice\\Python\\Impact_analysis_system')

from code_analyzer.csharp_parser import CSharpParser

# 測試案例
test_sql = """
Select M.Url From dbo.Roles as R 
inner join dbo.ModuleList as M 
on R.DefaultPageID = M.ItemID 
Where R.ID = 1
"""

parser = CSharpParser()

# 測試提取資料表
tables = parser._extract_tables_from_sql(test_sql)

print("=" * 80)
print("測試 SQL 解析修復")
print("=" * 80)
print(f"\nSQL 語句:")
print(test_sql)
print(f"\n提取的資料表:")
for table in sorted(tables):
    print(f"  - {table}")

print("\n預期結果:")
print("  - ROLES")
print("  - MODULELIST")

print("\n" + "=" * 80)
if tables == {'ROLES', 'MODULELIST'}:
    print("✅ 測試通過！DBO 已被正確過濾")
else:
    print(f"❌ 測試失敗！")
    print(f"   預期: {{'ROLES', 'MODULELIST'}}")
    print(f"   實際: {tables}")
print("=" * 80)
