"""
專案類型偵測器
根據專案結構和檔案特徵判斷專案類型
"""

import os
from pathlib import Path
from typing import Tuple, Dict, List
from collections import Counter
from .models import FrameworkType, FileType


class ProjectTypeDetector:
    """專案類型偵測器"""
    
    def __init__(self, project_root: str):
        """
        初始化偵測器
        
        Args:
            project_root: 專案根目錄
        """
        self.project_root = Path(project_root)
        self.file_stats: Dict[FileType, int] = {}
        self.config_files: List[str] = []
        
    def detect(self) -> FrameworkType:
        """
        偵測專案類型
        
        Returns:
            FrameworkType: 偵測到的專案類型
        """
        print(f"\n🔍 正在偵測專案類型...")
        
        # 1. 掃描檔案統計
        self._scan_files()
        
        # 2. 檢查設定檔
        self._check_config_files()
        
        # 3. 分析判斷
        framework = self._analyze_framework()
        
        print(f"   偵測結果: {framework.value}")
        return framework
    
    def _scan_files(self):
        """掃描並統計檔案類型"""
        file_counter = Counter()
        
        for root, dirs, files in os.walk(self.project_root):
            # 排除常見的忽略目錄
            dirs[:] = [d for d in dirs if d not in [
                'node_modules', 'bin', 'obj', 'packages', 
                '.vs', '.git', '__pycache__', 'dist', 'build'
            ]]
            
            for file in files:
                ext = Path(file).suffix.lower()
                
                # 統計各類型檔案
                if ext == '.cs':
                    file_counter[FileType.CSHARP] += 1
                elif ext == '.aspx':
                    file_counter[FileType.ASPX] += 1
                elif ext == '.ascx':
                    file_counter[FileType.ASCX] += 1
                elif ext == '.cshtml':
                    file_counter[FileType.RAZOR] += 1
                elif ext == '.vue':
                    file_counter[FileType.VUE] += 1
                elif ext == '.js':
                    file_counter[FileType.JAVASCRIPT] += 1
        
        self.file_stats = dict(file_counter)
        
        # 輸出統計
        print(f"   檔案統計:")
        for file_type, count in self.file_stats.items():
            print(f"      {file_type.value}: {count}")
    
    def _check_config_files(self):
        """檢查設定檔（檔名比對不分大小寫，例如 Web.config / web.config）"""
        # key 統一使用小寫，比對時也將實際檔名轉小寫
        config_patterns = {
            'web.config': 'ASP.NET Framework (WebForms/MVC)',
            'appsettings.json': 'ASP.NET Core',
            'package.json': 'Node.js/Vue/React',
            'vue.config.js': 'Vue',
            'global.asax': 'ASP.NET Framework',
            'startup.cs': 'ASP.NET Core',
            'program.cs': '.NET Core/5+',
        }

        found_configs = []
        root_path = str(self.project_root)

        for root, dirs, files in os.walk(self.project_root):
            # 只檢查根目錄（第一層），其餘子目錄不再往下遞迴
            if root != root_path:
                dirs[:] = []
                continue

            for file in files:
                match = config_patterns.get(file.lower())
                if match:
                    found_configs.append(file)
                    print(f"      ✓ {file} ({match})")

        self.config_files = found_configs
    
    def _analyze_framework(self) -> FrameworkType:
        """
        分析框架類型
        
        判斷邏輯優先順序：
        1. Vue + C# API (有 .vue 檔案 + C# 檔案)
        2. ASP.NET WebForms (有 .aspx/.ascx + web.config)
        3. ASP.NET MVC (有 .cshtml + C# 檔案)
        4. ASP.NET Core (有 appsettings.json + Startup.cs/Program.cs)
        5. Web API (只有 C# Controller 無前端)
        6. Blazor (有 .razor 檔案)
        """
        
        # 統計數量
        vue_count = self.file_stats.get(FileType.VUE, 0)
        aspx_count = self.file_stats.get(FileType.ASPX, 0)
        ascx_count = self.file_stats.get(FileType.ASCX, 0)
        razor_count = self.file_stats.get(FileType.RAZOR, 0)
        csharp_count = self.file_stats.get(FileType.CSHARP, 0)
        
        config_files_lower = {f.lower() for f in self.config_files}
        has_web_config = 'web.config' in config_files_lower
        has_appsettings = 'appsettings.json' in config_files_lower
        has_package_json = 'package.json' in config_files_lower
        has_vue_config = 'vue.config.js' in config_files_lower
        has_startup = 'startup.cs' in config_files_lower
        has_program = 'program.cs' in config_files_lower
        
        # 判斷 1: Vue + Web API
        if vue_count > 0 and csharp_count > 0:
            print(f"   判斷依據: Vue 檔案 ({vue_count}) + C# 檔案 ({csharp_count})")
            return FrameworkType.VUE_WEBAPI
        
        # 判斷 2: ASP.NET WebForms (傳統)
        if (aspx_count > 0 or ascx_count > 0) and has_web_config:
            print(f"   判斷依據: ASPX 檔案 ({aspx_count + ascx_count}) + web.config")
            return FrameworkType.WEBFORMS
        
        # 判斷 3: ASP.NET MVC (Razor)
        if razor_count > 0 and csharp_count > 0:
            if has_web_config:
                print(f"   判斷依據: Razor 檔案 ({razor_count}) + web.config")
                return FrameworkType.MVC
            elif has_appsettings:
                print(f"   判斷依據: Razor 檔案 ({razor_count}) + appsettings.json")
                return FrameworkType.DOTNET_CORE
        
        # 判斷 4: ASP.NET Core
        if has_appsettings and (has_startup or has_program):
            print(f"   判斷依據: appsettings.json + Startup/Program.cs")
            if has_program:
                return FrameworkType.DOTNET_5_PLUS
            return FrameworkType.DOTNET_CORE
        
        # 判斷 5: Web API (只有 C#)
        if csharp_count > 0:
            if has_web_config:
                print(f"   判斷依據: 只有 C# 檔案 ({csharp_count}) + web.config")
                return FrameworkType.WEBAPI
            elif has_appsettings:
                print(f"   判斷依據: 只有 C# 檔案 ({csharp_count}) + appsettings.json")
                return FrameworkType.DOTNET_CORE
        
        # 判斷 6: .NET Framework (有 web.config)
        if has_web_config:
            return FrameworkType.DOTNET_FRAMEWORK
        
        print(f"   無法明確判斷，使用預設")
        return FrameworkType.UNKNOWN
    
    def get_required_parsers(self, framework: FrameworkType) -> List[str]:
        """
        根據框架類型取得需要的解析器清單
        
        Args:
            framework: 框架類型
        
        Returns:
            解析器名稱清單
        """
        parser_mapping = {
            FrameworkType.VUE_WEBAPI: ['vue_parser', 'csharp_parser'],
            FrameworkType.WEBFORMS: ['aspx_parser', 'csharp_parser'],
            FrameworkType.MVC: ['razor_parser', 'csharp_parser'],
            FrameworkType.DOTNET_CORE: ['razor_parser', 'csharp_parser'],
            FrameworkType.DOTNET_5_PLUS: ['razor_parser', 'csharp_parser'],
            FrameworkType.WEBAPI: ['csharp_parser'],
            FrameworkType.DOTNET_FRAMEWORK: ['csharp_parser'],
        }
        
        return parser_mapping.get(framework, ['csharp_parser'])
    
    def get_file_extensions_to_scan(self, framework: FrameworkType) -> List[str]:
        """
        根據框架類型取得需要掃描的檔案副檔名
        
        Args:
            framework: 框架類型
        
        Returns:
            副檔名清單（不含點）
        """
        extension_mapping = {
            FrameworkType.VUE_WEBAPI: ['cs', 'vue', 'js'],
            FrameworkType.WEBFORMS: ['cs', 'aspx', 'ascx'],
            FrameworkType.MVC: ['cs', 'cshtml'],
            FrameworkType.DOTNET_CORE: ['cs', 'cshtml'],
            FrameworkType.DOTNET_5_PLUS: ['cs', 'cshtml'],
            FrameworkType.WEBAPI: ['cs'],
            FrameworkType.DOTNET_FRAMEWORK: ['cs'],
        }
        
        return extension_mapping.get(framework, ['cs'])


# ============================================
# 測試程式碼
# ============================================

def main():
    """測試專案類型偵測"""
    import sys
    
    if len(sys.argv) > 1:
        project_path = sys.argv[1]
    else:
        project_path = input("請輸入專案路徑: ").strip()
    
    if not Path(project_path).exists():
        print(f"❌ 路徑不存在: {project_path}")
        return
    
    print("=" * 80)
    print("專案類型偵測測試")
    print("=" * 80)
    
    detector = ProjectTypeDetector(project_path)
    framework = detector.detect()
    
    print(f"\n✅ 偵測完成")
    print(f"\n專案類型: {framework.value}")
    
    parsers = detector.get_required_parsers(framework)
    print(f"\n需要的解析器:")
    for parser in parsers:
        print(f"   - {parser}")
    
    extensions = detector.get_file_extensions_to_scan(framework)
    print(f"\n需要掃描的檔案類型:")
    for ext in extensions:
        print(f"   - *.{ext}")
    
    print("\n" + "=" * 80)


if __name__ == "__main__":
    main()
