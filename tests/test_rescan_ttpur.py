# 測試報告生成（用測試模式掃描 TTPUR）
import sys
sys.path.insert(0, 'D:\\pratice\\Python\\Impact_analysis_system')

from code_analyzer.project_scanner import ProjectScanner
from code_analyzer.report_generator import HTMLReportGenerator
from pathlib import Path
import json

print("=" * 80)
print("重新掃描 TTPUR 專案（測試模式：10 個檔案）")
print("=" * 80)

# 設定專案路徑
project_root = r"D:\PUR\TTPUR"

try:
    # 初始化掃描器
    scanner = ProjectScanner(project_root)
    
    # 掃描專案
    result = scanner.scan_project(analyze_sp=True, max_files=10)
    
    # 顯示摘要
    scanner.print_summary()
    
    # 檢查資料表關聯
    print("\n" + "=" * 80)
    print("資料表關聯檢查")
    print("=" * 80)
    
    # 找出 default.aspx.cs 的資料表關聯
    default_tables = [
        rel for rel in result.table_relations 
        if 'default.aspx.cs' in rel.csharp_file.lower()
    ]
    
    print(f"\ndefault.aspx.cs 的資料表關聯 ({len(default_tables)} 個):")
    for rel in default_tables:
        print(f"  - {rel.table_name:20s} | 資料庫: {rel.database:10s} | {rel.access_type}")
    
    # 檢查是否還有 DBO 作為資料表
    dbo_tables = [
        rel for rel in result.table_relations 
        if rel.table_name.upper() == 'DBO'
    ]
    
    print(f"\n檢查 DBO 是否還被識別為資料表:")
    if dbo_tables:
        print(f"  ❌ 仍有 {len(dbo_tables)} 個 DBO 被識別為資料表")
        for rel in dbo_tables[:3]:
            print(f"     - 檔案: {Path(rel.csharp_file).name}")
    else:
        print(f"  ✅ DBO 已不再被識別為資料表")
    
    # 檢查 unknown 資料庫
    unknown_tables = [
        rel for rel in result.table_relations 
        if rel.database == 'unknown'
    ]
    
    print(f"\n資料庫來源為 'unknown' 的資料表 ({len(unknown_tables)} 個):")
    if unknown_tables:
        for rel in unknown_tables[:5]:
            print(f"  - {rel.table_name:20s} | 檔案: {Path(rel.csharp_file).name:25s} | SQL: {rel.sql_preview[:40]}...")
    else:
        print("  ✅ 所有資料表都已識別資料庫")
    
    # 生成報告
    print("\n" + "=" * 80)
    print("生成 HTML 報告")
    print("=" * 80)
    
    generator = HTMLReportGenerator(result)
    output_path = generator.generate_report()
    
    print(f"\n✅ 測試完成！")
    print(f"   報告位置: {output_path}")

except Exception as e:
    print(f"\n❌ 錯誤: {e}")
    import traceback
    traceback.print_exc()
