"""
測試專案類型偵測和多解析器系統
"""
from code_analyzer.project_type_detector import ProjectTypeDetector
from code_analyzer.project_scanner import ProjectScanner

def test_project_detection():
    """測試專案類型偵測"""
    
    projects = [
        (r"d:\TOPCSCY\Andy\TOPCSCY", "MVC 專案"),
        # 您可以新增其他專案路徑進行測試
    ]
    
    print("=" * 80)
    print("專案類型偵測測試")
    print("=" * 80)
    
    for project_path, description in projects:
        print(f"\n{'='*80}")
        print(f"測試: {description}")
        print(f"路徑: {project_path}")
        print(f"{'='*80}")
        
        try:
            # 使用偵測器
            detector = ProjectTypeDetector(project_path)
            framework = detector.detect()
            
            parsers = detector.get_required_parsers(framework)
            extensions = detector.get_file_extensions_to_scan(framework)
            
            print(f"\n✅ 偵測完成")
            print(f"   專案類型: {framework.value}")
            print(f"   需要的解析器: {', '.join(parsers)}")
            print(f"   掃描檔案類型: {', '.join([f'*.{ext}' for ext in extensions])}")
            
        except Exception as e:
            print(f"❌ 錯誤: {e}")


def test_scanner_with_detection():
    """測試帶自動偵測的掃描器"""
    
    project_path = r"d:\TOPCSCY\Andy\TOPCSCY\Services"
    
    print("\n" + "=" * 80)
    print("測試掃描器（含自動偵測）")
    print("=" * 80)
    
    try:
        # 建立掃描器（會自動偵測專案類型）
        scanner = ProjectScanner(
            project_root=project_path,
            project_name="TOPCSCY_Services_Test"
        )
        
        print(f"\n掃描器已初始化")
        print(f"   偵測到的專案類型: {scanner.framework_type.value}")
        print(f"   啟用的解析器: {list(scanner.parsers.keys())}")
        
        # 尋找檔案
        files = scanner.find_project_files()
        
        print(f"\n✅ 找到 {len(files)} 個檔案")
        
        # 顯示前5個檔案
        if files:
            print("\n前 5 個檔案:")
            from pathlib import Path
            for i, file in enumerate(files[:5], 1):
                print(f"   {i}. {Path(file).name} ({Path(file).suffix})")
        
    except Exception as e:
        print(f"❌ 錯誤: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    # 測試 1: 專案類型偵測
    test_project_detection()
    
    # 測試 2: 掃描器整合
    test_scanner_with_detection()
    
    print("\n" + "=" * 80)
    print("✅ 所有測試完成")
    print("=" * 80)
