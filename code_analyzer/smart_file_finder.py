# code_analyzer/smart_file_finder.py
"""
智慧檔案搜尋器
支援根據名稱自動搜尋相關檔案
"""

import os
from pathlib import Path
from typing import List, Dict, Set, Optional
from dataclasses import dataclass, field
import fnmatch


@dataclass
class FileSearchResult:
    """檔案搜尋結果"""
    search_name: str
    project_root: str
    
    # 找到的檔案（按類型分類）
    aspx_files: List[str] = field(default_factory=list)      # .aspx
    aspx_cs_files: List[str] = field(default_factory=list)   # .aspx.cs
    ascx_files: List[str] = field(default_factory=list)      # .ascx (用戶控制項)
    cs_files: List[str] = field(default_factory=list)        # .cs
    
    # MVC 相關
    controllers: List[str] = field(default_factory=list)     # Controllers/*.cs
    services: List[str] = field(default_factory=list)        # Services/*.cs
    interfaces: List[str] = field(default_factory=list)      # Interfaces/*.cs
    views: List[str] = field(default_factory=list)           # Views/*/*.cshtml
    
    # 其他
    razor_files: List[str] = field(default_factory=list)     # .cshtml
    vue_files: List[str] = field(default_factory=list)       # .vue
    
    @property
    def all_files(self) -> List[str]:
        """所有找到的檔案"""
        return (
            self.aspx_files + self.aspx_cs_files + self.ascx_files + 
            self.cs_files + self.controllers + self.services + 
            self.interfaces + self.views + self.razor_files + self.vue_files
        )
    
    @property
    def total_count(self) -> int:
        """總檔案數"""
        return len(self.all_files)
    
    def print_summary(self):
        """輸出摘要"""
        print(f"\n搜尋結果: '{self.search_name}'")
        print("=" * 60)
        
        if not self.all_files:
            print("❌ 未找到任何檔案")
            return
        
        print(f"✅ 共找到 {self.total_count} 個檔案\n")
        
        # WebForms
        if self.aspx_files or self.aspx_cs_files or self.ascx_files:
            print("📄 WebForms:")
            for file in self.aspx_files:
                print(f"   - {Path(file).name} (ASPX)")
            for file in self.aspx_cs_files:
                print(f"   - {Path(file).name} (ASPX.CS)")
            for file in self.ascx_files:
                print(f"   - {Path(file).name} (ASCX)")
            print()
        
        # MVC
        if self.controllers or self.services or self.interfaces or self.views:
            print("🎯 MVC:")
            for file in self.controllers:
                print(f"   - {Path(file).name} (Controller)")
            for file in self.services:
                print(f"   - {Path(file).name} (Service)")
            for file in self.interfaces:
                print(f"   - {Path(file).name} (Interface)")
            for file in self.views:
                print(f"   - {Path(file).relative_to(self.project_root)} (View)")
            print()
        
        # 其他
        if self.cs_files:
            print("📝 其他 C# 檔案:")
            for file in self.cs_files:
                print(f"   - {Path(file).name}")
            print()
        
        if self.razor_files:
            print("🔷 Razor 檔案:")
            for file in self.razor_files:
                print(f"   - {Path(file).name}")
            print()
        
        if self.vue_files:
            print("💚 Vue 檔案:")
            for file in self.vue_files:
                print(f"   - {Path(file).name}")


class SmartFileFinder:
    """智慧檔案搜尋器"""
    
    def __init__(self, project_root: str):
        """
        初始化搜尋器
        
        Args:
            project_root: 專案根目錄
        """
        self.project_root = Path(project_root)
        
        if not self.project_root.exists():
            raise ValueError(f"專案路徑不存在: {project_root}")
        
        # 排除的資料夾
        self.exclude_folders = {
            'bin', 'obj', 'packages', 'node_modules', 
            '.git', '.vs', '.vscode', 'dist', 'build'
        }
    
    def search(
        self, 
        name: str, 
        case_sensitive: bool = False,
        exact_match: bool = False
    ) -> FileSearchResult:
        """
        智慧搜尋檔案
        
        Args:
            name: 搜尋名稱（例如: "User", "Customer"）
            case_sensitive: 是否區分大小寫
            exact_match: 是否精確匹配（False 則模糊搜尋）
        
        Returns:
            FileSearchResult: 搜尋結果
        """
        result = FileSearchResult(
            search_name=name,
            project_root=str(self.project_root)
        )
        
        print(f"🔍 搜尋檔案: {name}")
        print(f"   專案: {self.project_root}")
        print(f"   模式: {'精確' if exact_match else '模糊'}匹配")
        
        # 準備搜尋模式
        if exact_match:
            patterns = self._get_exact_patterns(name)
        else:
            patterns = self._get_fuzzy_patterns(name)
        
        # 遍歷專案
        for root, dirs, files in os.walk(self.project_root):
            # 排除特定資料夾
            dirs[:] = [d for d in dirs if d not in self.exclude_folders]
            
            root_path = Path(root)
            
            for file in files:
                file_path = root_path / file
                
                # 檢查是否符合搜尋模式
                if self._match_patterns(file, patterns, case_sensitive):
                    self._classify_file(file_path, result)
        
        return result
    
    def _get_exact_patterns(self, name: str) -> Dict[str, List[str]]:
        """取得精確匹配模式"""
        return {
            'aspx': [f"{name}.aspx"],
            'aspx_cs': [f"{name}.aspx.cs"],
            'ascx': [f"{name}.ascx"],
            'controller': [f"{name}Controller.cs"],
            'service': [f"{name}Service.cs"],
            'interface': [f"I{name}.cs", f"I{name}Service.cs", f"I{name}Repository.cs"],
            'view': [f"{name}.cshtml"],
            'cs': [f"{name}.cs"],
            'vue': [f"{name}.vue"]
        }
    
    def _get_fuzzy_patterns(self, name: str) -> Dict[str, List[str]]:
        """取得模糊匹配模式"""
        return {
            'aspx': [f"*{name}*.aspx"],
            'aspx_cs': [f"*{name}*.aspx.cs"],
            'ascx': [f"*{name}*.ascx"],
            'controller': [f"*{name}*Controller.cs"],
            'service': [f"*{name}*Service.cs"],
            'interface': [f"I*{name}*.cs"],
            'view': [f"*{name}*.cshtml"],
            'cs': [f"*{name}*.cs"],
            'vue': [f"*{name}*.vue"]
        }
    
    def _match_patterns(
        self, 
        filename: str, 
        patterns: Dict[str, List[str]], 
        case_sensitive: bool
    ) -> bool:
        """檢查檔案是否符合任一模式"""
        if not case_sensitive:
            filename = filename.lower()
        
        for category, pattern_list in patterns.items():
            for pattern in pattern_list:
                if not case_sensitive:
                    pattern = pattern.lower()
                
                if fnmatch.fnmatch(filename, pattern):
                    return True
        
        return False
    
    def _classify_file(self, file_path: Path, result: FileSearchResult):
        """分類檔案"""
        file_str = str(file_path)
        filename = file_path.name
        parent = file_path.parent.name
        
        # 判斷檔案類型
        if filename.endswith('.aspx.cs'):
            result.aspx_cs_files.append(file_str)
        elif filename.endswith('.aspx'):
            result.aspx_files.append(file_str)
        elif filename.endswith('.ascx'):
            result.ascx_files.append(file_str)
        elif filename.endswith('.vue'):
            result.vue_files.append(file_str)
        elif filename.endswith('.cshtml'):
            # 判斷是否在 Views 資料夾
            if 'Views' in file_path.parts:
                result.views.append(file_str)
            else:
                result.razor_files.append(file_str)
        elif filename.endswith('.cs'):
            # 根據資料夾和命名判斷
            if parent == 'Controllers' or 'Controller' in filename:
                result.controllers.append(file_str)
            elif parent == 'Services' or 'Service' in filename:
                result.services.append(file_str)
            elif parent == 'Interfaces' or filename.startswith('I'):
                result.interfaces.append(file_str)
            else:
                result.cs_files.append(file_str)
    
    def search_multiple(
        self, 
        names: List[str], 
        case_sensitive: bool = False
    ) -> Dict[str, FileSearchResult]:
        """
        批次搜尋多個名稱
        
        Args:
            names: 名稱清單
            case_sensitive: 是否區分大小寫
        
        Returns:
            Dict[名稱, FileSearchResult]
        """
        results = {}
        
        for name in names:
            results[name] = self.search(name, case_sensitive)
        
        return results
    
    def quick_search(self, name: str) -> List[str]:
        """
        快速搜尋（只返回檔案路徑清單）
        
        Args:
            name: 搜尋名稱
        
        Returns:
            List[str]: 檔案路徑清單
        """
        result = self.search(name, case_sensitive=False, exact_match=False)
        return result.all_files

        
        def __init__(self, project_root: str = None, project_name: str = None):
            # ... 原有初始化 ...
            
            # 🆕 加入智慧搜尋器
            self.file_finder = SmartFileFinder(self.project_root)
        
        def search_files(
            self, 
            name: str, 
            case_sensitive: bool = False,
            exact_match: bool = False
        ) -> FileSearchResult:
            """
            搜尋相關檔案
            
            Args:
                name: 搜尋名稱
                case_sensitive: 是否區分大小寫
                exact_match: 是否精確匹配
            """
            return self.file_finder.search(name, case_sensitive, exact_match)
        
        def analyze_related_files(self, name: str) -> Dict:
            """
            分析相關檔案的 SP 使用情況
            
            Args:
                name: 搜尋名稱（例如: "User"）
            
            Returns:
                分析結果字典
            """
            print(f"\n{'='*80}")
            print(f"分析相關檔案: {name}")
            print(f"{'='*80}")
            
            # 1. 搜尋檔案
            search_result = self.search_files(name)
            search_result.print_summary()
            
            if not search_result.all_files:
                return {'files': [], 'sp_calls': [], 'sql_queries': []}
            
            # 2. 解析找到的檔案
            print(f"\n📝 解析檔案...")
            
            all_sp_calls = []
            all_sql_queries = []
            file_analyses = []
            
            from tqdm import tqdm
            
            for file_path in tqdm(search_result.all_files, desc="解析進度"):
                if file_path.endswith('.cs'):
                    try:
                        result = self.csharp_parser.parse_file(file_path)
                        file_analyses.append(result)
                        all_sp_calls.extend(result.stored_procedure_calls)
                        all_sql_queries.extend(result.sql_queries)
                    except Exception as e:
                        print(f"\n   ⚠️  解析失敗 ({Path(file_path).name}): {e}")
            
            # 3. 統計
            print(f"\n📊 統計:")
            print(f"   找到檔案: {len(search_result.all_files)}")
            print(f"   解析成功: {len(file_analyses)}")
            print(f"   SP 呼叫: {len(all_sp_calls)}")
            print(f"   SQL 查詢: {len(all_sql_queries)}")
            
            # 4. 顯示 SP 清單
            if all_sp_calls:
                unique_sps = {}
                for sp_call in all_sp_calls:
                    key = (sp_call.database_source or 'unknown', sp_call.procedure_name)
                    if key not in unique_sps:
                        unique_sps[key] = []
                    unique_sps[key].append(sp_call)
                
                print(f"\n📞 使用的預存程序 ({len(unique_sps)}):")
                for (db, sp_name), calls in sorted(unique_sps.items()):
                    print(f"   - {db}.{sp_name} (呼叫 {len(calls)} 次)")
            
            # 5. 顯示資料表清單
            if all_sql_queries:
                unique_tables = set()
                for sql_query in all_sql_queries:
                    unique_tables.update(sql_query.tables)
                
                if unique_tables:
                    print(f"\n📊 涉及的資料表 ({len(unique_tables)}):")
                    for table in sorted(unique_tables):
                        print(f"   - {table}")
            
            return {
                'search_result': search_result,
                'file_analyses': file_analyses,
                'sp_calls': all_sp_calls,
                'sql_queries': all_sql_queries
            }


# ============================================
# 測試與使用
# ============================================

def test_smart_finder():
    """測試智慧搜尋"""
    from config.settings import settings
    
    project_root = input("請輸入專案根目錄: ").strip()
    
    if not project_root:
        print("❌ 未指定專案路徑")
        return
    
    # 建立搜尋器
    finder = SmartFileFinder(project_root)
    
    print("\n" + "=" * 80)
    print("智慧檔案搜尋測試")
    print("=" * 80)
    
    while True:
        search_name = input("\n請輸入搜尋名稱（Enter 結束）: ").strip()
        
        if not search_name:
            break
        
        # 選擇模式
        mode = input("搜尋模式 (1=精確, 2=模糊, Enter=模糊): ").strip()
        exact = mode == '1'
        
        # 搜尋
        result = finder.search(search_name, exact_match=exact)
        result.print_summary()
        
        # 顯示完整路徑
        if result.all_files:
            show_paths = input("\n是否顯示完整路徑？(y/n): ").strip().lower()
            if show_paths == 'y':
                print("\n完整路徑:")
                for file in result.all_files:
                    rel_path = Path(file).relative_to(project_root)
                    print(f"   {rel_path}")
    
    print("\n✅ 測試完成")


if __name__ == "__main__":
    test_smart_finder()