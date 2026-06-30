"""
資料模型定義
定義程式碼分析過程中使用的所有資料結構
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Set
from enum import Enum
from pathlib import Path
from datetime import datetime

# ============================================
# 列舉類型定義
# ============================================
class FileType(Enum):
    """檔案類型"""
    CSHARP = "cs"           # C# 程式碼
    ASPX = "aspx"           # ASP.NET WebForms 頁面
    ASCX = "ascx"           # ASP.NET 使用者控制項
    RAZOR = "cshtml"        # Razor 視圖
    VUE = "vue"             # Vue 元件
    JAVASCRIPT = "js"       # JavaScript
    HTML = "html"           # HTML
    CSS = "css"             # CSS
    SQL = "sql"             # SQL 腳本
    CONFIG = "config"       # 設定檔
    XML = "xml"             # XML
    JSON = "json"           # JSON
    UNKNOWN = "unknown"     # 未知類型


class FrameworkType(Enum):
    """框架類型"""
    DOTNET_FRAMEWORK = ".NET Framework"
    DOTNET_CORE = ".NET Core"
    DOTNET_5_PLUS = ".NET 5+"
    MVC = "ASP.NET MVC"
    WEBFORMS = "ASP.NET WebForms"
    WEBAPI = "ASP.NET Web API"
    VUE_WEBAPI = "Vue + C# Web API"
    BLAZOR = "Blazor"
    UNKNOWN = "Unknown"


class SQLQueryType(Enum):
    """SQL 查詢類型"""
    SELECT = "SELECT"
    INSERT = "INSERT"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    PROCEDURE = "PROCEDURE"
    FUNCTION = "FUNCTION"
    CREATE = "CREATE"
    ALTER = "ALTER"
    DROP = "DROP"
    UNKNOWN = "UNKNOWN"


class HTTPMethod(Enum):
    """HTTP 方法"""
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"
    OPTIONS = "OPTIONS"
    HEAD = "HEAD"

class TableAccessType(Enum):
    """資料表存取類型"""
    READ = "READ"           # SELECT
    INSERT = "INSERT"       # INSERT
    UPDATE = "UPDATE"       # UPDATE
    DELETE = "DELETE"       # DELETE
    MERGE = "MERGE"         # MERGE


# ============================================
# 基礎資料類別
# ============================================

@dataclass
class CodeLocation:
    """
    程式碼位置
    記錄程式碼在檔案中的位置
    """
    file_path: str          # 檔案路徑
    line_number: int        # 行號
    column_number: int = 0  # 列號（可選）
    
    def __str__(self):
        if self.column_number > 0:
            return f"{self.file_path}:{self.line_number}:{self.column_number}"
        return f"{self.file_path}:{self.line_number}"
    
    def __hash__(self):
        return hash((self.file_path, self.line_number, self.column_number))


# ============================================
# C# 相關資料結構
# ============================================

@dataclass
class ParameterInfo:
    """參數資訊"""
    name: str               # 參數名稱
    type: str               # 參數型別
    default_value: Optional[str] = None  # 預設值
    is_optional: bool = False            # 是否可選
    is_params: bool = False              # 是否為 params 參數
    
    def __str__(self):
        result = f"{self.type} {self.name}"
        if self.default_value:
            result += f" = {self.default_value}"
        return result


@dataclass
class PropertyInfo:
    """屬性資訊"""
    name: str               # 屬性名稱
    type: str               # 屬性型別
    access_modifier: str    # 存取修飾詞
    has_getter: bool = True
    has_setter: bool = True
    is_auto_property: bool = True
    location: Optional[CodeLocation] = None
    
    def __str__(self):
        access = "{ "
        if self.has_getter:
            access += "get; "
        if self.has_setter:
            access += "set; "
        access += "}"
        return f"{self.access_modifier} {self.type} {self.name} {access}"


@dataclass
class MethodInfo:
    """
    方法資訊
    記錄類別中的方法定義
    """
    name: str                                   # 方法名稱
    access_modifier: str                        # 存取修飾詞 (public, private, protected, internal)
    return_type: str                            # 回傳型別
    parameters: List[ParameterInfo] = field(default_factory=list)
    location: Optional[CodeLocation] = None
    
    # 方法特性
    is_async: bool = False                      # 是否為非同步方法
    is_static: bool = False                     # 是否為靜態方法
    is_virtual: bool = False                    # 是否為虛擬方法
    is_override: bool = False                   # 是否為覆寫方法
    is_abstract: bool = False                   # 是否為抽象方法
    
    # 方法內容分析
    calls: List[str] = field(default_factory=list)           # 呼叫的方法
    sql_queries: List[str] = field(default_factory=list)     # 包含的 SQL 查詢
    line_count: int = 0                                      # 方法行數
    
    def __str__(self):
        modifiers = [self.access_modifier]
        if self.is_static:
            modifiers.append("static")
        if self.is_async:
            modifiers.append("async")
        if self.is_virtual:
            modifiers.append("virtual")
        if self.is_override:
            modifiers.append("override")
        if self.is_abstract:
            modifiers.append("abstract")
        
        params = ", ".join([str(p) for p in self.parameters])
        return f"{' '.join(modifiers)} {self.return_type} {self.name}({params})"
    
    def __hash__(self):
        return hash(f"{self.name}_{self.location}")


@dataclass
class ClassInfo:
    """
    類別資訊
    記錄 C# 類別的完整定義
    """
    name: str                   # 類別名稱
    namespace: str              # 命名空間
    file_path: str              # 檔案路徑
    
    # 繼承與實作
    base_class: Optional[str] = None                    # 基底類別
    interfaces: List[str] = field(default_factory=list) # 實作的介面
    
    # 類別成員
    methods: List[MethodInfo] = field(default_factory=list)
    properties: List[PropertyInfo] = field(default_factory=list)
    fields: List[Dict] = field(default_factory=list)
    
    # 類別特性
    access_modifier: str = "internal"
    is_static: bool = False
    is_abstract: bool = False
    is_sealed: bool = False
    is_partial: bool = False
    
    # 類別類型判斷
    is_controller: bool = False
    is_model: bool = False
    is_service: bool = False
    is_repository: bool = False
    
    location: Optional[CodeLocation] = None
    
    @property
    def full_name(self) -> str:
        """取得完整類別名稱（包含命名空間）"""
        return f"{self.namespace}.{self.name}" if self.namespace else self.name
    
    def __str__(self):
        return f"{self.full_name} ({len(self.methods)} methods)"
    
    def __hash__(self):
        return hash(self.full_name)


# ============================================
# SQL 相關資料結構
# ============================================

@dataclass
class SQLQuery:
    """
    SQL 查詢
    記錄程式碼中的 SQL 語句
    """
    query_text: str                             # SQL 文字
    query_type: SQLQueryType                    # 查詢類型
    tables: Set[str] = field(default_factory=set)      # 涉及的資料表
    columns: List[str] = field(default_factory=list)   # 涉及的欄位
    parameters: List[str] = field(default_factory=list) # 參數
    location: Optional[CodeLocation] = None
    
    # 分析結果
    is_parameterized: bool = False              # 是否使用參數化查詢
    has_join: bool = False                      # 是否包含 JOIN
    has_subquery: bool = False                  # 是否包含子查詢
    
    # 🆕 資料庫來源追蹤
    database_source: Optional[str] = None       # 資料庫來源 (例如: "PUR", "STC", "DmsDB")
    connection_variable: Optional[str] = None   # 連線變數名稱 (例如: "objPUR", "_connetStrRead")

    def __str__(self):
        return f"{self.query_type.value}: {self.query_text[:50]}..."
    
    def __hash__(self):
        return hash((self.query_text, str(self.location)))


@dataclass
class StoredProcedureCall:
    """預存程序呼叫"""
    procedure_name: str
    parameters: List[str] = field(default_factory=list)
    location: Optional[CodeLocation] = None

    # 🆕 資料庫來源追蹤
    database_source: Optional[str] = None       # 資料庫來源
    connection_variable: Optional[str] = None   # 連線變數名稱
    
    def __str__(self):
        source_info = f" [{self.database_source}]" if self.database_source else ""
        params = ", ".join(self.parameters) if self.parameters else ""
        return f"EXEC {self.procedure_name}({params}){source_info}"

@dataclass
class TableAccess:
    """資料表存取資訊"""
    table_name: str
    access_type: TableAccessType
    columns: List[str] = field(default_factory=list)  # 存取的欄位
    where_columns: List[str] = field(default_factory=list)  # WHERE 條件欄位
    
    def __str__(self):
        cols_str = ", ".join(self.columns) if self.columns else "所有欄位"
        return f"{self.table_name} ({self.access_type.value}, 欄位: {cols_str})"

@dataclass
class JoinRelation:
    """JOIN 關係"""
    left_table: str
    right_table: str
    join_type: str  # INNER, LEFT, RIGHT, FULL
    join_condition: str  # 例如: CustomerID
    
    def __str__(self):
        return f"{self.left_table} ←[{self.join_type}]→ {self.right_table} (ON {self.join_condition})"

@dataclass
class SPParameter:
    """預存程序參數"""
    name: str
    data_type: str
    direction: str  # IN, OUT, INOUT
    default_value: Optional[str] = None
    
    def __str__(self):
        default = f" = {self.default_value}" if self.default_value else ""
        return f"{self.name} {self.data_type} ({self.direction}){default}"

@dataclass
class StoredProcedureAnalysis:
    """預存程序分析結果"""
    procedure_name: str
    database: str
    schema: str = "dbo"
    
    # 基本資訊
    parameters: List[SPParameter] = field(default_factory=list)
    definition: str = ""
    created_date: Optional[str] = None
    modified_date: Optional[str] = None
    
    # 資料表存取
    table_accesses: List[TableAccess] = field(default_factory=list)
    
    # JOIN 關係
    join_relations: List[JoinRelation] = field(default_factory=list)
    
    # WHERE 條件
    where_conditions: List[str] = field(default_factory=list)
    
    # 業務邏輯
    description: str = ""
    comments: List[str] = field(default_factory=list)
    
    # 依賴關係
    called_procedures: List[str] = field(default_factory=list)  # 呼叫的其他 SP
    called_functions: List[str] = field(default_factory=list)   # 呼叫的函數
    
    # 統計
    total_reads: int = 0
    total_writes: int = 0
    complexity_score: int = 0  # 複雜度評分
    
    def get_all_affected_tables(self) -> Set[str]:
        """取得所有受影響的資料表"""
        return set(access.table_name for access in self.table_accesses)
    
    def get_read_tables(self) -> List[TableAccess]:
        """取得讀取的資料表"""
        return [acc for acc in self.table_accesses if acc.access_type == TableAccessType.READ]
    
    def get_write_tables(self) -> List[TableAccess]:
        """取得寫入的資料表"""
        return [acc for acc in self.table_accesses if acc.access_type in [
            TableAccessType.INSERT, 
            TableAccessType.UPDATE, 
            TableAccessType.DELETE,
            TableAccessType.MERGE
        ]]
    
    def calculate_complexity(self):
        """計算複雜度評分"""
        score = 0
        score += len(self.table_accesses) * 2
        score += len(self.join_relations) * 3
        score += len(self.where_conditions)
        score += len(self.called_procedures) * 5
        self.complexity_score = score
    
    def __str__(self):
        return f"SP: {self.procedure_name} (讀: {self.total_reads}, 寫: {self.total_writes}, 複雜度: {self.complexity_score})"

# ============================================
# API 相關資料結構
# ============================================

@dataclass
class APIEndpoint:
    """
    API 端點
    記錄 Web API 的路由資訊
    """
    route: str                  # 路由路徑
    http_method: HTTPMethod     # HTTP 方法
    controller: str             # 控制器名稱
    action: str                 # 動作方法名稱
    parameters: List[ParameterInfo] = field(default_factory=list)
    location: Optional[CodeLocation] = None
    
    # 認證與授權
    requires_auth: bool = False
    roles: List[str] = field(default_factory=list)
    
    # 回應資訊
    return_type: Optional[str] = None
    
    def __str__(self):
        return f"{self.http_method.value} {self.route} -> {self.controller}.{self.action}"
    
    @property
    def full_route(self) -> str:
        """取得完整路由"""
        return f"{self.http_method.value} {self.route}"


# ============================================
# 檔案分析結果
# ============================================

@dataclass
class FileAnalysisResult:
    """
    檔案分析結果
    記錄單一檔案的分析結果
    """
    file_path: str              # 檔案路徑
    file_type: FileType         # 檔案類型
    framework: FrameworkType    # 偵測到的框架
    
    # C# 相關
    namespaces: List[str] = field(default_factory=list)
    using_statements: List[str] = field(default_factory=list)
    classes: List[ClassInfo] = field(default_factory=list)
    
    # SQL 相關
    sql_queries: List[SQLQuery] = field(default_factory=list)
    stored_procedure_calls: List[StoredProcedureCall] = field(default_factory=list)
    
    # API 相關
    api_endpoints: List[APIEndpoint] = field(default_factory=list)
    
    # 依賴關係
    dependencies: Set[str] = field(default_factory=set)
    referenced_files: Set[str] = field(default_factory=set)
    
    # 統計資訊
    line_count: int = 0
    code_line_count: int = 0
    comment_line_count: int = 0
    blank_line_count: int = 0
    
    # 分析狀態
    analysis_time: Optional[datetime] = None
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    
    @property
    def total_classes(self) -> int:
        return len(self.classes)
    
    @property
    def total_methods(self) -> int:
        return sum(len(cls.methods) for cls in self.classes)
    
    @property
    def total_sql_queries(self) -> int:
        return len(self.sql_queries)
    
    def __str__(self):
        return f"{self.file_path} ({self.file_type.value}): {self.total_classes} classes, {self.total_methods} methods"


# ============================================
# 專案分析結果
# ============================================

@dataclass
class ProjectAnalysisResult:
    """
    專案分析結果
    記錄整個專案的分析結果
    """
    project_root: str           # 專案根目錄
    project_name: str = ""      # 專案名稱
    
    # 檔案分析結果
    file_results: List[FileAnalysisResult] = field(default_factory=list)
    
    # 統計資訊
    total_files: int = 0
    analyzed_files: int = 0
    failed_files: int = 0
    
    total_lines: int = 0
    total_code_lines: int = 0
    total_classes: int = 0
    total_methods: int = 0
    total_sql_queries: int = 0
    total_api_endpoints: int = 0
    
    # 框架偵測
    detected_frameworks: Set[FrameworkType] = field(default_factory=set)
    
    # 資料庫相關
    referenced_tables: Set[str] = field(default_factory=set)
    referenced_stored_procedures: Set[str] = field(default_factory=set)
    
    # 分析時間
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    
    # 依賴圖（稍後建立）
    dependency_graph: Optional[object] = None
    
    @property
    def analysis_duration(self) -> Optional[float]:
        """分析耗時（秒）"""
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return None
    
    @property
    def success_rate(self) -> float:
        """成功率"""
        if self.total_files == 0:
            return 0.0
        return (self.analyzed_files / self.total_files) * 100
    
    def add_file_result(self, result: FileAnalysisResult):
        """新增檔案分析結果"""
        self.file_results.append(result)
        self.analyzed_files += 1
        
        # 更新統計
        self.total_lines += result.line_count
        self.total_code_lines += result.code_line_count
        self.total_classes += result.total_classes
        self.total_methods += result.total_methods
        self.total_sql_queries += result.total_sql_queries
        self.total_api_endpoints += len(result.api_endpoints)
        
        # 更新框架
        if result.framework != FrameworkType.UNKNOWN:
            self.detected_frameworks.add(result.framework)
        
        # 更新資料庫資訊
        for sql in result.sql_queries:
            self.referenced_tables.update(sql.tables)
        
        for sp in result.stored_procedure_calls:
            self.referenced_stored_procedures.add(sp.procedure_name)
    
    def get_summary(self) -> Dict:
        """取得摘要資訊"""
        return {
            "project_name": self.project_name,
            "project_root": self.project_root,
            "total_files": self.total_files,
            "analyzed_files": self.analyzed_files,
            "success_rate": f"{self.success_rate:.1f}%",
            "total_lines": self.total_lines,
            "total_code_lines": self.total_code_lines,
            "total_classes": self.total_classes,
            "total_methods": self.total_methods,
            "total_sql_queries": self.total_sql_queries,
            "total_api_endpoints": self.total_api_endpoints,
            "frameworks": [f.value for f in self.detected_frameworks],
            "referenced_tables": len(self.referenced_tables),
            "analysis_duration": self.analysis_duration
        }
    
    def __str__(self):
        return f"Project: {self.project_name} ({self.analyzed_files}/{self.total_files} files)"


# ============================================
# 測試程式碼
# ============================================

if __name__ == "__main__":
    print("=" * 60)
    print("資料模型測試")
    print("=" * 60)
    
    # 測試 CodeLocation
    location = CodeLocation("MyFile.cs", 42, 10)
    print(f"\n位置: {location}")
    
    # 測試 ParameterInfo
    param = ParameterInfo("userId", "int")
    print(f"參數: {param}")
    
    # 測試 MethodInfo
    method = MethodInfo(
        name="GetUser",
        access_modifier="public",
        return_type="User",
        parameters=[param],
        is_async=True
    )
    print(f"方法: {method}")
    
    # 測試 ClassInfo
    cls = ClassInfo(
        name="UserController",
        namespace="MyApp.Controllers",
        file_path="Controllers/UserController.cs",
        methods=[method],
        is_controller=True
    )
    print(f"類別: {cls}")
    print(f"完整名稱: {cls.full_name}")
    
    # 測試 SQLQuery
    sql = SQLQuery(
        query_text="SELECT * FROM Users WHERE UserId = @id",
        query_type=SQLQueryType.SELECT,
        tables={"Users"},
        is_parameterized=True
    )
    print(f"SQL: {sql}")
    
    # 測試 APIEndpoint
    api = APIEndpoint(
        route="/api/users/{id}",
        http_method=HTTPMethod.GET,
        controller="UserController",
        action="GetUser"
    )
    print(f"API: {api}")
    
    # 測試 FileAnalysisResult
    file_result = FileAnalysisResult(
        file_path="Controllers/UserController.cs",
        file_type=FileType.CSHARP,
        framework=FrameworkType.MVC,
        classes=[cls],
        sql_queries=[sql],
        api_endpoints=[api],
        line_count=150,
        code_line_count=120,
        comment_line_count=20
    )
    print(f"\n檔案分析: {file_result}")
    print(f"  總類別數: {file_result.total_classes}")
    print(f"  總方法數: {file_result.total_methods}")
    print(f"  總 SQL 數: {file_result.total_sql_queries}")
    
    # 測試 ProjectAnalysisResult
    project = ProjectAnalysisResult(
        project_root="C:/Projects/MyApp",
        project_name="MyApp"
    )
    project.total_files = 1
    project.add_file_result(file_result)
    
    print(f"\n專案分析: {project}")
    print(f"成功率: {project.success_rate:.1f}%")
    
    print("\n摘要:")
    import json
    print(json.dumps(project.get_summary(), indent=2, ensure_ascii=False))
    
    print("\n✅ 所有資料模型測試完成")