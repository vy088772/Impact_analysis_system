# code_analyzer/project_scanner.py
"""
專案掃描器
整合 C# 解析、SQL 分析、資料庫連線追蹤
"""


import os
from pathlib import Path
from typing import List, Dict, Set, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from tqdm import tqdm
import json

from .csharp_parser import CSharpParser
from .aspx_parser import ASPXParser
from .razor_parser import RazorParser
from .vue_parser import VueParser
from .project_type_detector import ProjectTypeDetector
from .sql_analyzer import SQLAnalyzer, SimplifiedSPInfo
from .db_connection_tracker import DBConnectionTracker
from .models import FileAnalysisResult, StoredProcedureCall, SQLQuery, FrameworkType
from .smart_file_finder import SmartFileFinder, FileSearchResult
from .config_parser import WebConfigParser
from config.settings import settings, DatabaseConfig


# ============================================
# 資料模型
# ============================================

@dataclass
class CSharpSPRelation:
    """C# 檔案與 SP 的關聯"""
    # C# 端資訊
    csharp_file: str
    class_name: str
    method_name: str
    line_number: int
    
    # SP 端資訊
    sp_name: str
    sp_database: str
    sp_info: Optional[SimplifiedSPInfo] = None
    
    # 呼叫資訊
    call_method: str = ""  # ExeProcRead, CreateReader, SqlCommand
    connection_variable: str = ""
    
    def to_dict(self) -> Dict:
        return {
            'csharp': {
                'file': self.csharp_file,
                'class': self.class_name,
                'method': self.method_name,
                'line': self.line_number
            },
            'stored_procedure': self.sp_info.to_dict() if self.sp_info else {
                'name': self.sp_name,
                'database': self.sp_database,
                'exists': False
            },
            'call_info': {
                'method': self.call_method,
                'connection': self.connection_variable
            }
        }
    
    def __str__(self):
        exists = "✅" if (self.sp_info and self.sp_info.exists) else "❌"
        return f"{self.csharp_file} -> {exists} {self.sp_database}.{self.sp_name}"


@dataclass
class CSharpTableRelation:
    """C# 檔案與資料表的關聯（透過 SQL 查詢）"""
    # C# 端資訊
    csharp_file: str
    class_name: str
    method_name: str
    line_number: int
    
    # 資料表資訊
    table_name: str
    database: str
    access_type: str  # READ, INSERT, UPDATE, DELETE
    
    # SQL 資訊
    sql_preview: str = ""
    
    def to_dict(self) -> Dict:
        return {
            'csharp': {
                'file': self.csharp_file,
                'class': self.class_name,
                'method': self.method_name,
                'line': self.line_number
            },
            'table': {
                'name': self.table_name,
                'database': self.database,
                'access_type': self.access_type
            },
            'sql_preview': self.sql_preview
        }


@dataclass
class ProjectScanResult:
    """專案掃描結果"""
    project_root: str
    project_name: str
    scan_time: datetime
    
    # 掃描統計
    total_files: int = 0
    scanned_files: int = 0
    failed_files: int = 0
    
    # C# 分析結果
    csharp_results: List[FileAnalysisResult] = field(default_factory=list)
    
    # 關聯資訊
    sp_relations: List[CSharpSPRelation] = field(default_factory=list)
    table_relations: List[CSharpTableRelation] = field(default_factory=list)
    
    # 資料庫統計
    databases_used: Set[str] = field(default_factory=set)
    total_sp_calls: int = 0
    total_sql_queries: int = 0
    unique_sps: Set[str] = field(default_factory=set)
    unique_tables: Set[str] = field(default_factory=set)
    
    def calculate_statistics(self):
        """計算統計資訊"""
        self.databases_used = set(rel.sp_database for rel in self.sp_relations)
        self.total_sp_calls = len(self.sp_relations)
        self.total_sql_queries = sum(len(r.sql_queries) for r in self.csharp_results)
        self.unique_sps = set(rel.sp_name for rel in self.sp_relations)
        self.unique_tables = set(rel.table_name for rel in self.table_relations)
    
    def to_dict(self) -> Dict:
        self.calculate_statistics()
        
        return {
            'project_info': {
                'name': self.project_name,
                'root': self.project_root,
                'scan_time': self.scan_time.isoformat()
            },
            'statistics': {
                'files': {
                    'total': self.total_files,
                    'scanned': self.scanned_files,
                    'failed': self.failed_files,
                    'success_rate': f"{(self.scanned_files/self.total_files*100):.1f}%" if self.total_files > 0 else "0%"
                },
                'databases': list(self.databases_used),
                'stored_procedures': {
                    'total_calls': self.total_sp_calls,
                    'unique': len(self.unique_sps)
                },
                'sql_queries': {
                    'total': self.total_sql_queries
                },
                'tables': {
                    'unique': len(self.unique_tables)
                }
            },
            'sp_relations': [rel.to_dict() for rel in self.sp_relations],
            'table_relations': [rel.to_dict() for rel in self.table_relations]
        }


# ============================================
# 專案掃描器
# ============================================

class ProjectScanner:
    """專案掃描器"""
    
    def __init__(self, project_root: str = None, project_name: str = None):
        """
        初始化專案掃描器
        
        Args:
            project_root: 專案根目錄
            project_name: 專案名稱
        """
        self.project_root = project_root or settings.PROJECT_ROOT
        self.project_name = project_name or Path(self.project_root).name
        
        if not self.project_root or not Path(self.project_root).exists():
            raise ValueError(f"專案路徑不存在: {self.project_root}")
        
        # 🆕 偵測專案類型
        detector = ProjectTypeDetector(self.project_root)
        self.framework_type = detector.detect()
        self.required_parsers = detector.get_required_parsers(self.framework_type)
        self.scan_extensions = detector.get_file_extensions_to_scan(self.framework_type)
        
        # 初始化解析器（根據專案類型）
        self.parsers = {}
        if 'csharp_parser' in self.required_parsers:
            self.parsers['csharp'] = CSharpParser()
        if 'aspx_parser' in self.required_parsers:
            self.parsers['aspx'] = ASPXParser()
        if 'razor_parser' in self.required_parsers:
            self.parsers['razor'] = RazorParser()
        if 'vue_parser' in self.required_parsers:
            self.parsers['vue'] = VueParser()
        
        # 保留向下相容
        self.csharp_parser = self.parsers.get('csharp')
        
        # 初始化 SQL 分析器（多資料庫）
        self.sql_analyzers: Dict[str, SQLAnalyzer] = {}

        # 初始化智慧檔案搜尋器
        self.file_finder = SmartFileFinder(self.project_root)
        
        # 掃描結果
        self.scan_result: Optional[ProjectScanResult] = None
        
        print(f"✅ 專案掃描器已初始化")
        print(f"   專案: {self.project_name}")
        print(f"   路徑: {self.project_root}")
        print(f"   類型: {self.framework_type.value}")
        print(f"   解析器: {', '.join(self.required_parsers)}")
        print(f"   掃描檔案: {', '.join([f'*.{ext}' for ext in self.scan_extensions])}")
    
    # ========================================
    # 自動偵測資料庫
    # ========================================
    def detect_databases_from_config(self):
        """從 web.config 自動偵測資料庫設定"""
        print(f"\n🔍 正在尋找並解析 web.config...")
        parser = WebConfigParser(self.project_root)
        connection_strings = parser.parse()
        
        if not connection_strings:
            return

        print(f"   從 web.config 發現 {len(connection_strings)} 個連線字串")
        
        # 取得預設參數 (從 .env 載入的)
        default_config = settings.get_default_database()
        
        for alias, conn_str in connection_strings.items():
            # 解析連線字串詳細資訊
            conn_info = parser.get_connection_info(conn_str)
            db_name = conn_info['database']
            server_name = conn_info['server']
            
            if db_name:
                display_server = f" @ {server_name}" if server_name else ""
                print(f"   👉 發現設定: {alias} -> {db_name}{display_server}")
                
                # 將發現的設定注入到全域 settings 中
                # 即使設定已存在，如果 web.config 有更詳細的資訊 (如 Server)，我們也可能會想更新它
                # 但目前的策略是：如果 settings 裡沒有，就加入。
                if alias not in settings.get_all_databases():
                    # 判斷驗證模式
                    user_id = conn_info['user_id']
                    password = conn_info['password']
                    auth_mode = 'sql' if (user_id and password) else (default_config.auth_mode if default_config else 'windows')
                    
                    # 建立設定物件
                    new_config = DatabaseConfig(
                        alias=alias,
                        database_name=db_name,
                        # 優先使用從 web.config 解析到的 Server，否則使用預設值
                        server=server_name if server_name else (default_config.server if default_config else settings.DB_SERVER),
                        user_id=user_id if user_id else (default_config.user_id if default_config else settings.DB_USER_ID),
                        password=password if password else (default_config.password if default_config else settings.DB_PASSWORD),
                        auth_mode=auth_mode
                    )
                    
                    # 注入
                    settings._databases[alias] = new_config
                    print(f"      ✅ 已加入可連線清單: {alias} -> {new_config.server}")
                else:
                    print(f"      ℹ️  設定已存在，保留現有設定")

    # ========================================
    # 初始化資料庫連線
    # ========================================
    
    def initialize_databases(self, database_aliases: List[str] = None):
        """
        初始化資料庫連線
        
        Args:
            database_aliases: 要連線的資料庫列表，None 則連線全部
        """
        # 先嘗試自動偵測
        self.detect_databases_from_config()

        print("\n🔌 初始化資料庫連線...")
        
        all_dbs = settings.get_all_databases()
        
        if database_aliases:
            # 只連線指定的資料庫
            target_dbs = {k: v for k, v in all_dbs.items() if k in database_aliases}
        else:
            # 連線所有資料庫
            target_dbs = all_dbs
        
        for alias, db_config in target_dbs.items():
            try:
                analyzer = SQLAnalyzer(alias)
                if analyzer.connect():
                    self.sql_analyzers[alias] = analyzer
                    print(f"   ✅ {alias} ({db_config.database_name})")
            except Exception as e:
                print(f"   ❌ {alias}: {e}")
        
        if not self.sql_analyzers:
            print("   ⚠️ 未連接任何資料庫")
        else:
            print(f"\n   共連接 {len(self.sql_analyzers)} 個資料庫")
    
    def close_databases(self):
        """關閉所有資料庫連線"""
        for analyzer in self.sql_analyzers.values():
            analyzer.disconnect()
        self.sql_analyzers.clear()
    
    # ========================================
    # 檔案掃描
    # ========================================
    # 檔案掃描
    # ========================================
    
    def find_project_files(self) -> List[str]:
        """尋找所有需要掃描的檔案（根據專案類型）"""
        print(f"\n🔍 搜尋專案檔案...")
        
        project_files = []
        exclude_folders = set(settings.EXCLUDE_FOLDERS)
        
        for root, dirs, files in os.walk(self.project_root):
            # 排除特定資料夾
            dirs[:] = [d for d in dirs if d not in exclude_folders]
            
            for file in files:
                file_ext = Path(file).suffix[1:]  # 移除點
                
                # 檢查是否為需要掃描的檔案類型
                if file_ext in self.scan_extensions:
                    file_path = os.path.join(root, file)
                    project_files.append(file_path)
        
        print(f"   找到 {len(project_files)} 個檔案")
        for ext in set(Path(f).suffix for f in project_files):
            count = sum(1 for f in project_files if Path(f).suffix == ext)
            print(f"      {ext}: {count}")
        
        return project_files
    
    def find_csharp_files(self) -> List[str]:
        """尋找所有 C# 檔案"""
        print(f"\n🔍 搜尋 C# 檔案...")
        
        csharp_files = []
        exclude_folders = set(settings.EXCLUDE_FOLDERS)
        exclude_patterns = settings.EXCLUDE_PATTERNS
        
        for root, dirs, files in os.walk(self.project_root):
            # 排除特定資料夾
            dirs[:] = [d for d in dirs if d not in exclude_folders]
            
            for file in files:
                if file.endswith('.cs'):
                    # 檢查排���模式
                    should_exclude = False
                    for pattern in exclude_patterns:
                        import fnmatch
                        if fnmatch.fnmatch(file, pattern):
                            should_exclude = True
                            break
                    
                    if not should_exclude:
                        full_path = os.path.join(root, file)
                        csharp_files.append(full_path)
        
        print(f"   找到 {len(csharp_files)} 個 C# 檔案")
        return csharp_files
    
    # ========================================
    # 主掃描流程
    # ========================================
    
    def scan_project(
        self, 
        database_aliases: List[str] = None,
        analyze_sp: bool = True,
        max_files: Optional[int] = None
    ) -> ProjectScanResult:
        """
        掃描專案
        
        Args:
            database_aliases: 要連線的資料庫列表
            analyze_sp: 是否分析 SP（需要資料庫連線）
            max_files: 限制掃描檔案數量（測試用）
        """
        print("=" * 80)
        print(f"開始掃描專案: {self.project_name}")
        print("=" * 80)
        
        # 初始化結果
        self.scan_result = ProjectScanResult(
            project_root=self.project_root,
            project_name=self.project_name,
            scan_time=datetime.now()
        )
        
        # 1. 初始化資料庫連線資料庫如果需要）
        if analyze_sp:
            self.initialize_databases(database_aliases)
        
        # 2. 尋找 C# 檔案
        csharp_files = self.find_csharp_files()
        
        if max_files:
            csharp_files = csharp_files[:max_files]
        
        self.scan_result.total_files = len(csharp_files)
        
        # 3. 解析 C# 檔案
        print(f"\n📝 解析 C# 檔案...")
        
        for file_path in tqdm(csharp_files, desc="解析進度"):
            try:
                result = self.csharp_parser.parse_file(file_path)
                self.scan_result.csharp_results.append(result)
                self.scan_result.scanned_files += 1
            except Exception as e:
                self.scan_result.failed_files += 1
                print(f"\n   ⚠️  解析失敗 ({Path(file_path).name}): {e}")
        
        print(f"\n   ✅ 完成: {self.scan_result.scanned_files}/{self.scan_result.total_files}")
        
        # 4. 建立關聯
        print(f"\n🔗 建立關聯...")
        self._build_relations(analyze_sp)
        
        # 🆕 4.5 智慧推斷 unknown 資料庫
        if analyze_sp and self.sql_analyzers:
            self._infer_unknown_databases()
        
        # 5. 計算統計
        self.scan_result.calculate_statistics()
        
        # 6. 關閉資料庫連線
        if analyze_sp:
            self.close_databases()
        
        print(f"\n✅ 掃描完成")
        return self.scan_result
    
    def _build_relations(self, analyze_sp: bool):
        """建立 C# 與資料庫的關聯"""
        
        # 統計所有 SP 呼叫和 SQL 查詢
        all_sp_calls: List[StoredProcedureCall] = []
        all_sql_queries: List[SQLQuery] = []
        
        for result in self.scan_result.csharp_results:
            all_sp_calls.extend(result.stored_procedure_calls)
            all_sql_queries.extend(result.sql_queries)
        
        print(f"   找到 {len(all_sp_calls)} 個 SP 呼叫")
        print(f"   找到 {len(all_sql_queries)} 個 SQL 查詢")
        
        # 建立 SP 關聯
        if all_sp_calls:
            self._build_sp_relations(all_sp_calls, analyze_sp)
        
        # 建立資料表關聯
        if all_sql_queries:
            self._build_table_relations(all_sql_queries)
    
    def _build_sp_relations(self, sp_calls: List[StoredProcedureCall], analyze_sp: bool):
        """建立 SP 關聯"""
        print(f"\n   建立 SP 關聯...")
        
        for sp_call in tqdm(sp_calls, desc="   SP 分析"):
            # 找出對應的 C# ���案資訊
            csharp_file = sp_call.location.file_path
            
            # 找出類別和方法
            class_name, method_name = self._find_class_and_method(
                csharp_file, 
                sp_call.location.line_number
            )
            
            # 建立關聯
            relation = CSharpSPRelation(
                csharp_file=csharp_file,
                class_name=class_name,
                method_name=method_name,
                line_number=sp_call.location.line_number,
                sp_name=sp_call.procedure_name,
                sp_database=sp_call.database_source or 'unknown',
                connection_variable=sp_call.connection_variable or ""
            )
            
            # 分析 SP（如果有資料庫連線）
            if analyze_sp:
                # 情況 1: 已經知道資料庫，且已連線
                if relation.sp_database in self.sql_analyzers:
                    try:
                        analyzer = self.sql_analyzers[relation.sp_database]
                        sp_info = analyzer.quick_analyze_sp(sp_call.procedure_name)
                        relation.sp_info = sp_info
                    except Exception as e:
                        pass  # 靜默失敗
                
                # 情況 2: 資料庫未知 (unknown) 或未連接該特定資料庫，嘗試在所有已連接的資料庫中搜尋
                elif self.sql_analyzers:
                    for alias, analyzer in self.sql_analyzers.items():
                        try:
                            # 快速檢測
                            sp_info = analyzer.quick_analyze_sp(sp_call.procedure_name)
                            if sp_info.exists:
                                relation.sp_info = sp_info
                                relation.sp_database = alias  # 更新正確的資料庫名稱
                                break  # 找到就停止
                        except Exception:
                            continue
            
            self.scan_result.sp_relations.append(relation)
    
    def _build_table_relations(self, sql_queries: List[SQLQuery]):
        """建立資料表關聯"""
        print(f"\n   建立資料表關聯...")
        
        for sql_query in sql_queries:
            # 找出對應的 C# 檔案資訊
            csharp_file = sql_query.location.file_path
            
            # 找出類別和方法
            class_name, method_name = self._find_class_and_method(
                csharp_file,
                sql_query.location.line_number
            )
            
            # 對每個涉及的資料表建立關聯
            for table in sql_query.tables:
                relation = CSharpTableRelation(
                    csharp_file=csharp_file,
                    class_name=class_name,
                    method_name=method_name,
                    line_number=sql_query.location.line_number,
                    table_name=table,
                    database=sql_query.database_source or 'unknown',
                    access_type=sql_query.query_type.value,
                    sql_preview=sql_query.query_text[:100]
                )
                
                self.scan_result.table_relations.append(relation)
    
    def _infer_unknown_databases(self):
        """
        智慧推斷 unknown 資料庫
        基於已知的 SP 資料表資訊來推斷
        """
        print(f"\n   🔍 智慧推斷 unknown 資料庫...")
        
        # 建立資料表 → 資料庫的映射（從 SP 資訊中）
        table_to_db_map = {}
        
        for sp_rel in self.scan_result.sp_relations:
            if sp_rel.sp_info and sp_rel.sp_info.referenced_tables:
                for table in sp_rel.sp_info.referenced_tables:
                    table_upper = table.upper()
                    # 如果這個資料表還沒有記錄，或者記錄的是 unknown，就更新
                    if table_upper not in table_to_db_map or table_to_db_map[table_upper] == 'unknown':
                        table_to_db_map[table_upper] = sp_rel.sp_database
        
        # 使用映射來更新 unknown 的資料表關聯
        updated_count = 0
        for relation in self.scan_result.table_relations:
            if relation.database == 'unknown':
                table_upper = relation.table_name.upper()
                if table_upper in table_to_db_map and table_to_db_map[table_upper] != 'unknown':
                    old_db = relation.database
                    relation.database = table_to_db_map[table_upper]
                    updated_count += 1
                    print(f"      ✓ {relation.table_name:20s} : unknown → {relation.database}")
        
        if updated_count > 0:
            print(f"   ✅ 已更新 {updated_count} 個資料表的資料庫來源")
        else:
            print(f"   ℹ️  沒有可推斷的 unknown 資料庫")
    
    def _find_class_and_method(
        self, 
        file_path: str, 
        line_number: int
    ) -> Tuple[str, str]:
        """找出特定行號所屬的類別和方法"""
        # 從已解析的結果中查找
        for result in self.scan_result.csharp_results:
            if result.file_path == file_path:
                for cls in result.classes:
                    # 找出包含該行號的方法
                    for method in cls.methods:
                        if method.location and method.location.line_number <= line_number:
                            # 簡單判斷：如果方法在該行之前，可能是該方法
                            return cls.name, method.name
                    
                    # 如果沒找到方法，至少返回類別
                    return cls.name, "unknown"
        
        return "unknown", "unknown"
    
    # ========================================
    # 🆕 智慧搜尋相關方法
    # ========================================
    
    def search_files(
        self, 
        name: str, 
        case_sensitive: bool = False,
        exact_match: bool = False
    ) -> FileSearchResult:
        """
        搜尋相關檔案
        
        Args:
            name: 搜尋名稱（例如: "User", "Customer"）
            case_sensitive: 是否區分大小寫
            exact_match: 是否精確匹配
        
        Returns:
            FileSearchResult: 搜尋結果
        """
        return self.file_finder.search(name, case_sensitive, exact_match)
    
    def analyze_related_files(
        self, 
        name: str,
        connect_databases: bool = True,
        database_aliases: List[str] = None
    ) -> Dict:
        """
        分析相關檔案的 SP 使用情況
        
        Args:
            name: 搜尋名稱（例如: "User"）
            connect_databases: 是否連接資料庫分析 SP
            database_aliases: 要連接的資料庫列表
        
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
            return {
                'search_result': search_result,
                'files': [],
                'sp_calls': [],
                'sql_queries': []
            }
        
        # 2. 初始化資料庫（如果需要）
        if connect_databases:
            if not self.sql_analyzers:
                self.initialize_databases(database_aliases)
        
        # 3. 解析找到的檔案
        print(f"\n📝 解析檔案...")
        
        all_sp_calls = []
        all_sql_queries = []
        file_analyses = []
        
        for file_path in tqdm(search_result.all_files, desc="解析進度"):
            if file_path.endswith('.cs'):
                try:
                    result = self.csharp_parser.parse_file(file_path)
                    file_analyses.append(result)
                    all_sp_calls.extend(result.stored_procedure_calls)
                    all_sql_queries.extend(result.sql_queries)
                except Exception as e:
                    print(f"\n   ⚠️  解析失敗 ({Path(file_path).name}): {e}")
        
        # 4. 分析 SP（如果有資料庫連線）
        sp_details = {}
        if connect_databases and self.sql_analyzers:
            print(f"\n🔍 分析預存程序...")
            
            for sp_call in tqdm(all_sp_calls, desc="SP 分析"):
                key = (sp_call.database_source or 'unknown', sp_call.procedure_name)
                
                if key not in sp_details:
                    db_source = sp_call.database_source or 'unknown'
                    
                    if db_source in self.sql_analyzers:
                        try:
                            analyzer = self.sql_analyzers[db_source]
                            sp_info = analyzer.quick_analyze_sp(sp_call.procedure_name)
                            sp_details[key] = sp_info
                        except:
                            sp_details[key] = None
        
        # 5. 統計
        print(f"\n📊 統計:")
        print(f"   找到檔案: {len(search_result.all_files)}")
        print(f"   解析成功: {len(file_analyses)}")
        print(f"   SP 呼叫: {len(all_sp_calls)}")
        print(f"   SQL 查詢: {len(all_sql_queries)}")
        
        # 6. 顯示 SP 清單
        if all_sp_calls:
            unique_sps = {}
            for sp_call in all_sp_calls:
                key = (sp_call.database_source or 'unknown', sp_call.procedure_name)
                if key not in unique_sps:
                    unique_sps[key] = []
                unique_sps[key].append(sp_call)
            
            print(f"\n📞 使用的預存程序 ({len(unique_sps)}):")
            for (db, sp_name), calls in sorted(unique_sps.items()):
                sp_info = sp_details.get((db, sp_name))
                complexity = f" [{sp_info.estimated_complexity}]" if sp_info else ""
                exists = "✅" if (sp_info and sp_info.exists) else "❌" if sp_info else "❓"
                print(f"   {exists} {db}.{sp_name}{complexity} (呼叫 {len(calls)} 次)")
                
                if sp_info and sp_info.referenced_tables:
                    tables = ", ".join(list(sp_info.referenced_tables)[:3])
                    if len(sp_info.referenced_tables) > 3:
                        tables += f" ... (共 {len(sp_info.referenced_tables)} 個)"
                    print(f"      涉及資料表: {tables}")
        
        # 7. 顯示資料表清單
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
            'sql_queries': all_sql_queries,
            'sp_details': sp_details
        }

    def quick_search(self, name: str) -> List[str]:
        """
        快速搜尋（只返回檔案路徑）
        
        Args:
            name: 搜尋名稱
        
        Returns:
            List[str]: 檔案路徑清單
        """
        return self.file_finder.quick_search(name)
    
    # ========================================
    # 報告輸出
    # ========================================
    
    def print_summary(self):
        """輸出摘要"""
        if not self.scan_result:
            print("❌ 尚未執行掃描")
            return
        
        result = self.scan_result
        
        print("\n" + "=" * 80)
        print(f"專案掃描摘要: {result.project_name}")
        print("=" * 80)
        
        # 檔案統計
        print(f"\n📁 檔案統計:")
        print(f"   總檔案數: {result.total_files}")
        print(f"   成功掃描: {result.scanned_files}")
        print(f"   失敗: {result.failed_files}")
        success_rate = (result.scanned_files / result.total_files * 100) if result.total_files > 0 else 0
        print(f"   成功率: {success_rate:.1f}%")
        
        # 資料庫統計
        print(f"\n🗄️  資料庫統計:")
        print(f"   使用的資料庫: {len(result.databases_used)}")
        if result.databases_used:
            for db in sorted(result.databases_used):
                sp_count = sum(1 for r in result.sp_relations if r.sp_database == db)
                print(f"      - {db}: {sp_count} 個 SP 呼叫")
        
        # SP 統計
        print(f"\n📞 預存程序統計:")
        print(f"   總呼叫次數: {result.total_sp_calls}")
        print(f"   不重複 SP: {len(result.unique_sps)}")
        
        # 檢查不存在的 SP
        if any(rel.sp_info for rel in result.sp_relations):
            missing_sps = [rel for rel in result.sp_relations if rel.sp_info and not rel.sp_info.exists]
            if missing_sps:
                print(f"   ⚠️  不存在的 SP: {len(missing_sps)}")
        
        # SQL 統計
        print(f"\n📊 SQL 查詢統計:")
        print(f"   總查詢數: {result.total_sql_queries}")
        print(f"   涉及資料表: {len(result.unique_tables)}")
        
        # 複雜度分析（如果有 SP 資訊）
        sp_with_info = [rel for rel in result.sp_relations if rel.sp_info]
        if sp_with_info:
            print(f"\n⚙️  SP 複雜度分布:")
            complexity_count = {}
            for rel in sp_with_info:
                comp = rel.sp_info.estimated_complexity
                complexity_count[comp] = complexity_count.get(comp, 0) + 1
            
            for comp, count in sorted(complexity_count.items()):
                print(f"   {comp}: {count}")
        
        print("\n" + "=" * 80)
    
    def print_sp_relations(self, limit: int = 20):
        """輸出 SP 關聯清單"""
        if not self.scan_result:
            print("❌ 尚未執行掃描")
            return
        
        print("\n" + "=" * 80)
        print("C# 與 SP 關聯")
        print("=" * 80)
        
        for i, rel in enumerate(self.scan_result.sp_relations[:limit], 1):
            print(f"\n{i}. {rel}")
            print(f"   檔案: {Path(rel.csharp_file).name}")
            print(f"   類別.方法: {rel.class_name}.{rel.method_name}")
            print(f"   行號: {rel.line_number}")
            
            if rel.sp_info:
                print(f"   SP 複雜度: {rel.sp_info.estimated_complexity}")
                if rel.sp_info.referenced_tables:
                    tables = ", ".join(list(rel.sp_info.referenced_tables)[:3])
                    print(f"   涉及資料表: {tables}")
        
        if len(self.scan_result.sp_relations) > limit:
            print(f"\n... 還有 {len(self.scan_result.sp_relations) - limit} 個關聯")
    
    def export_to_json(self, output_path: str = None) -> str:
        """匯出為 JSON"""
        if not self.scan_result:
            raise ValueError("尚未執行掃描")
        
        if output_path is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_path = f"output/project_scan/{self.project_name}_{timestamp}.json"
        
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(self.scan_result.to_dict(), f, indent=2, ensure_ascii=False)
        
        print(f"✅ 已匯出 JSON: {output_path}")
        return output_path
    
    def export_to_excel(self, output_path: str = None) -> str:
        """匯出為 Excel"""
        if not self.scan_result:
            raise ValueError("尚未執行掃描")
        
        import pandas as pd
        
        if output_path is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_path = f"output/project_scan/{self.project_name}_{timestamp}.xlsx"
        
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        
        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            # 1. 專案摘要
            summary_data = [{
                '專案名稱': self.scan_result.project_name,
                '專案路徑': self.scan_result.project_root,
                '掃描時間': self.scan_result.scan_time.strftime('%Y-%m-%d %H:%M:%S'),
                '總檔案數': self.scan_result.total_files,
                '成功掃描': self.scan_result.scanned_files,
                '失敗': self.scan_result.failed_files,
                '使用資料庫數': len(self.scan_result.databases_used),
                'SP 呼叫數': self.scan_result.total_sp_calls,
                '不重複 SP': len(self.scan_result.unique_sps),
                'SQL 查詢數': self.scan_result.total_sql_queries,
                '涉及資料表數': len(self.scan_result.unique_tables)
            }]
            
            pd.DataFrame(summary_data).to_excel(writer, sheet_name='專案摘要', index=False)
            
            # 2. SP 關聯
            if self.scan_result.sp_relations:
                sp_data = []
                for rel in self.scan_result.sp_relations:
                    row = {
                        'C# 檔案': Path(rel.csharp_file).name,
                        '完整路徑': rel.csharp_file,
                        '類別': rel.class_name,
                        '方法': rel.method_name,
                        '行號': rel.line_number,
                        'SP 名稱': rel.sp_name,
                        '資料庫': rel.sp_database,
                        '是否存在': '是' if (rel.sp_info and rel.sp_info.exists) else '否',
                        '複雜度': rel.sp_info.estimated_complexity if rel.sp_info else '',
                        '涉及資料表數': len(rel.sp_info.referenced_tables) if rel.sp_info else 0,
                        '連線變數': rel.connection_variable
                    }
                    
                    if rel.sp_info and rel.sp_info.referenced_tables:
                        row['涉及資料表'] = ', '.join(sorted(rel.sp_info.referenced_tables))
                    
                    sp_data.append(row)
                
                pd.DataFrame(sp_data).to_excel(writer, sheet_name='SP關聯', index=False)
            
            # 3. 資料表關聯
            if self.scan_result.table_relations:
                table_data = []
                for rel in self.scan_result.table_relations:
                    table_data.append({
                        'C# 檔案': Path(rel.csharp_file).name,
                        '類別': rel.class_name,
                        '方法': rel.method_name,
                        '行號': rel.line_number,
                        '資料表': rel.table_name,
                        '資料庫': rel.database,
                        '操作類型': rel.access_type,
                        'SQL預覽': rel.sql_preview
                    })
                
                pd.DataFrame(table_data).to_excel(writer, sheet_name='資料表關聯', index=False)
        
        print(f"✅ 已匯出 Excel: {output_path}")
        return output_path


# ============================================
# 測試與使用
# ============================================

def main():
    """測試主程式"""
    print("=" * 80)
    print("專案掃描器測試（含智慧搜尋）")
    print("=" * 80)
    
    project_root = settings.PROJECT_ROOT
    
    if not project_root or not Path(project_root).exists():
        project_root = input("\n請輸入專案根目錄: ").strip()
    
    if not project_root or not Path(project_root).exists():
        print("❌ 專案路徑無效")
        return
    
    try:
        scanner = ProjectScanner(project_root)
        
        print("\n請選擇功能:")
        print("  1. 完整專案掃描")
        print("  2. 智慧搜尋特定檔案")
        print("  3. 分析特定模組")
        
        choice = input("\n請輸入選項 (1-3): ").strip()
        if choice == '1':
            # 完整專案掃描
            test_mode = input("\n是否啟用測試模式（限制10個檔案）？(y/n): ").strip().lower()
            max_files = 10 if test_mode == 'y' else None

            selected_dbs = settings.get_all_databases()
            result = scanner.scan_project(
                database_aliases=selected_dbs,
                analyze_sp=True,
                max_files=max_files
            )
            
            scanner.print_summary()
            scanner.print_sp_relations(limit=10)
            
            export_choice = input("\n是否匯出結果？(json/excel/both/n): ").strip().lower()
            
            if export_choice in ['json', 'both']:
                scanner.export_to_json()
            
            if export_choice in ['excel', 'both']:
                scanner.export_to_excel()
        
        elif choice == '2':
            # 智慧搜尋
            search_name = input("\n請輸入搜尋名稱: ").strip()
            
            if search_name:
                result = scanner.search_files(search_name)
                result.print_summary()
                
                # 自動連接選擇的資料庫，用於分析 SP
                analyzer_dict = {}
                selected_dbs = settings.get_all_databases()
                dbs_to_connect = selected_dbs if selected_dbs else list(selected_dbs.keys())
                
                print(f"\n🔌 連接資料庫中... ({len(dbs_to_connect)} 個)")
                for db_alias in dbs_to_connect:
                    try:
                        sql_analyzer = SQLAnalyzer(db_alias)
                        if sql_analyzer.connect():
                            analyzer_dict[db_alias] = sql_analyzer
                    except Exception as e:
                        print(f"   ⚠️  連接 {db_alias} 失敗: {e}")
                
                # 掃描所有找到的 C# 檔案 (.cs)
                # search_result 裡可能包含 aspx_cs_files, cs_files 等
                target_files = []
                if result.aspx_cs_files: target_files.extend(result.aspx_cs_files)
                if result.cs_files: target_files.extend(result.cs_files)
                
                # 去重
                target_files = list(set(target_files))
                
                if target_files:
                    print(f"\n📝 開始解析 {len(target_files)} 個 C# 檔案...")
                    parser = CSharpParser()
                    
                    for file_path in target_files:
                        print(f"\n{'-'*60}")
                        print(f"📄 檔案: {Path(file_path).name}")
                        print(f"{'-'*60}")
                        
                        try:
                            file_result = parser.parse_file(file_path)
                            
                            total_sps = len(file_result.stored_procedure_calls)
                            if total_sps == 0:
                                print("   ℹ️  未發現 SP 呼叫")
                                continue

                            print(f"   🔍 發現 {total_sps} 個 SP 呼叫，開始分析...\n")
                            
                            for i, sp in enumerate(file_result.stored_procedure_calls, 1):
                                sp_name = sp.procedure_name
                                db_source = sp.database_source
                                
                                print(f"   {i}. {sp_name}")
                                print(f"      📍 位置: 行 {sp.location.line_number}")
                                if sp.connection_variable:
                                    print(f"      🔌 連線變數: {sp.connection_variable}")
                                
                                # 嘗試使用正確的資料庫分析，若無指定則嘗試所有已連接的資料庫
                                sp_info = None
                                used_analyzer = None
                                
                                # 1. 有指定資料庫來源
                                if db_source and db_source in analyzer_dict:
                                    used_analyzer = analyzer_dict[db_source]
                                    sp_info = used_analyzer.quick_analyze_sp(sp_name)
                                    print(f"      🗄️  資料庫: {db_source} (自動偵測)")
                                
                                # 2. 無指定或來源不明，嘗試所有連接的資料庫
                                elif analyzer_dict:
                                    for alias, analyzer in analyzer_dict.items():
                                        temp_info = analyzer.quick_analyze_sp(sp_name)
                                        if temp_info.exists:
                                            sp_info = temp_info
                                            used_analyzer = analyzer
                                            print(f"      🗄️  資料庫: {alias} (搜尋匹配)")
                                            break
                                
                                # 顯示 SP 分析結果
                                if sp_info and sp_info.exists:
                                    print(f"      ✅ 複雜度: {sp_info.estimated_complexity}")
                                    
                                    if sp_info.referenced_tables:
                                        tables_display = ", ".join(list(sp_info.referenced_tables)[:3])
                                        if len(sp_info.referenced_tables) > 3:
                                            tables_display += f" ... 等 {len(sp_info.referenced_tables)} 個"
                                        print(f"      📊 關聯表: {tables_display}")
                                        
                                    # 如果想要更詳細，可以像之前一樣使用 analyzer.print_sp_info(sp_info, detailed=True)
                                    # 這裡我們印出簡介就好
                                else:
                                    print(f"      ⚠️  無法在連接的資料庫中找到此 SP 定義")

                        except Exception as e:
                            print(f"   ❌ 解析檔案失敗: {e}")
                
                # 任務結束，關閉連線
                for analyzer in analyzer_dict.values():
                    analyzer.disconnect()


        elif choice == '3':
            # 分析特定模組
            module_name = input("\n請輸入模組名稱: ").strip()
            
            if module_name:
                result = scanner.analyze_related_files(module_name)
        
    except Exception as e:
        print(f"\n❌ 錯誤: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 80)
    print("✅ 測試完成")
    print("=" * 80)


if __name__ == "__main__":
    main()