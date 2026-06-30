# main.py
"""
Impact Analysis System - 主程式入口
"""

import sys
from pathlib import Path


def _resolve_project_root() -> str:
    """
    互動式選擇專案來源：
      1. 手動輸入本機路徑
      2. 使用 .env 中的 PROJECT_ROOT
      3. 從 Azure DevOps 自動 clone
    回傳本機路徑字串；若使用者取消則回傳空字串。
    """
    print("\n請選擇專案來源:")
    print("  1. 手動輸入本機路徑")
    print("  2. 使用設定檔中的 PROJECT_ROOT")
    print("  3. 從 Azure DevOps 自動取得")
    src = input("請選擇 (1-3): ").strip()

    if src == '1':
        path = input("請輸入專案路徑: ").strip()
        if not path:
            print("❌ 路徑不可為空")
            return ''
        return path

    elif src == '2':
        from config.settings import settings
        if not settings.PROJECT_ROOT:
            print("❌ .env 中未設定 PROJECT_ROOT")
            return ''
        print(f"✅ 使用 PROJECT_ROOT: {settings.PROJECT_ROOT}")
        return settings.PROJECT_ROOT

    elif src == '3':
        from code_analyzer.azure_fetcher import fetch_from_settings, AzureFetchError
        try:
            project_path = fetch_from_settings()
            return str(project_path)
        except AzureFetchError as e:
            print(f"❌ Azure DevOps 擷取失敗：{e}")
            return ''

    else:
        print("❌ 無效選項")
        return ''

def main():
    """主選單"""
    print("=" * 80)
    print("Impact Analysis System")
    print("=" * 80)
    
    print("\n請選擇功能:")
    print("  1. 測試設定")
    print("  2. 掃描專案")
    print("  3. 智慧搜尋")
    print("  4. 生成依賴關係圖")
    print("  5. 分析預存程序")
    print("  0. 離開")
    
    choice = input("\n請選擇 (0-5): ").strip()
    
    if choice == '1':
        from config.settings import settings
        settings.print_settings()
        errors = settings.validate()
        if errors:
            print("\n❌ 設定錯誤:")
            for error in errors:
                print(f"  {error}")
    
    elif choice == '2':
        from code_analyzer.project_scanner import ProjectScanner
        project_root = _resolve_project_root()
        if project_root:
            scanner = ProjectScanner(project_root)
            result = scanner.scan_project(analyze_sp=True)
            scanner.print_summary()
    
    elif choice == '3':
        from code_analyzer.project_scanner import ProjectScanner
        
        project_root = _resolve_project_root()
        if project_root:
            scanner = ProjectScanner(project_root)
            name = input("請輸入搜尋名稱: ").strip()
            if name:
                result = scanner.analyze_related_files(name)
    
    elif choice == '4':
        from code_analyzer.dependency_graph import main as graph_main
        graph_main()
    
    elif choice == '5':
        from code_analyzer.sql_analyzer import main as sql_main
        sql_main()
    
    elif choice == '0':
        print("再見！")
        sys.exit(0)
    
    else:
        print("❌ 無效選項")


if __name__ == "__main__":
    main()