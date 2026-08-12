"""
測試 MVC 專案的完整掃描
"""
from code_analyzer.project_scanner import ProjectScanner

def test_mvc_project_scan():
    """測試 MVC 專案掃描"""
    
    # MVC 專案路徑 - 直接掃描 Services 目錄
    mvc_services_path = r"d:\TOPCSCY\Andy\TOPCSCY\Services"
    
    print("=" * 80)
    print("測試 MVC 專案 Services 層掃描")
    print("=" * 80)
    print(f"\n專案路徑: {mvc_services_path}")
    
    # 建立掃描器
    scanner = ProjectScanner(
        project_root=mvc_services_path,
        project_name="TOPCSCY_Services"
    )
    
    # 執行掃描
    result = scanner.scan_project(
        analyze_sp=False,  # 先不連資料庫，只看能否識別 SP
        max_files=20  # 掃描前 20 個檔案
    )
    
    # 顯示摘要
    scanner.print_summary()
    
    # 顯示 SP 關聯
    if result.sp_relations:
        print("\n" + "=" * 80)
        print("發現的 SP 呼叫詳細資訊:")
        print("=" * 80)
        
        for i, rel in enumerate(result.sp_relations[:20], 1):
            print(f"\n{i}. {rel.sp_name}")
            print(f"   檔案: {rel.csharp_file}")
            print(f"   類別: {rel.class_name}")
            print(f"   方法: {rel.method_name}")
            print(f"   行號: {rel.line_number}")
            print(f"   資料庫: {rel.sp_database}")
    
    print("\n" + "=" * 80)
    print("✅ 測試完成")
    print("=" * 80)

if __name__ == "__main__":
    test_mvc_project_scan()
