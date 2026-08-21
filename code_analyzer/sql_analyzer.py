# code_analyzer/sql_analyzer.py
"""
SQL 分析器（精簡版）
策略：靜態分析建立基礎關聯，複雜分析交給 AI
"""

import re
import pyodbc
from typing import Callable, List, Dict, Set, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import json

from config.settings import settings, DatabaseConfig


# ============================================
# 資料模型
# ============================================

@dataclass
class SimplifiedSPInfo:
    """精簡版 SP 資訊（靜態分析）"""
    procedure_name: str
    database: str
    schema: str = "dbo"
    
    # 基本資訊（從資料庫查詢）
    exists: bool = False
    parameters: List[str] = field(default_factory=list)
    created_date: Optional[str] = None
    modified_date: Optional[str] = None
    definition: str = ""
    definition_length: int = 0
    
    # 簡單分析（原生依賴查詢優先，regex 為 fallback，見 quick_analyze_sp）
    referenced_tables: Set[str] = field(default_factory=set)
    dependency_source: str = "regex"  # "native"（sys.dm_sql_referenced_entities）或 "regex"（fallback）
    has_dynamic_sql: bool = False
    has_temp_tables: bool = False
    has_cursor: bool = False
    has_transaction: bool = False
    
    # 統計
    estimated_complexity: str = "簡單"  # 簡單/中等/複雜
    line_count: int = 0
    
    def to_dict(self) -> Dict:
        """轉為字典"""
        return {
            'name': self.procedure_name,
            'database': self.database,
            'schema': self.schema,
            'exists': self.exists,
            'parameters': self.parameters,
            'created_date': self.created_date,
            'modified_date': self.modified_date,
            'tables': list(self.referenced_tables),
            'dependency_source': self.dependency_source,
            'flags': {
                'dynamic_sql': self.has_dynamic_sql,
                'temp_tables': self.has_temp_tables,
                'cursor': self.has_cursor,
                'transaction': self.has_transaction
            },
            'complexity': self.estimated_complexity,
            'definition_length': self.definition_length,
            'line_count': self.line_count
        }
    
    def __str__(self):
        status = "✅" if self.exists else "❌"
        return f"{status} {self.database}.{self.schema}.{self.procedure_name} [{self.estimated_complexity}]"


@dataclass
class DatabaseSummary:
    """資料庫摘要"""
    database: str
    total_tables: int = 0
    total_views: int = 0
    total_procedures: int = 0
    total_functions: int = 0
    analyzed_procedures: int = 0
    
    procedures: List[SimplifiedSPInfo] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        return {
            'database': self.database,
            'statistics': {
                'tables': self.total_tables,
                'views': self.total_views,
                'procedures': self.total_procedures,
                'functions': self.total_functions,
                'analyzed': self.analyzed_procedures
            },
            'procedures': [sp.to_dict() for sp in self.procedures]
        }


# ============================================
# SQL 分析器（精簡版）
# ============================================

class SQLAnalyzer:
    """SQL 分析器（精簡實用版）"""
    
    def __init__(
        self,
        database_alias: str = None,
        server: str = None,
        database_name: str = None,
        user_id: str = "",
        password: str = "",
    ):
        """
        初始化 SQL 分析器

        Args:
            database_alias: 資料庫簡稱（例如: "STC", "PUR"）；同時提供 server/
                database_name 時僅作為顯示/快取鍵用途，不查 .env 的 DB_DATABASES。
            server: 明確指定的資料庫主機位址（由呼叫端如 spec-rag 的 catalog
                逐系統提供）。與 database_name 需同時提供才會現組設定，兩者只
                提供其一視為設定不完整，直接報錯不嘗試連線。
            database_name: 明確指定的實際資料庫名稱。
            user_id: 這一台伺服器的掃描帳密覆寫帳號，與 password 兩者都有值才
                生效；缺一即沿用 .env 的全域 DB_AUTH_MODE 身分（ADR-0010）。
                掃描身分永遠不從被掃應用程式的 Web.config 推導。
            password: 掃描帳密覆寫的密碼。

        每個系統的伺服器/資料庫可能不同，故優先使用明確提供的 server/
        database_name（見 settings.build_database_config()）；只有在完全沒
        提供時才退回舊行為（查 .env 的 DB_DATABASES/DB_DEFAULT_DATABASE，
        供尚未遷移到 catalog 標注方式的呼叫端相容使用）。
        """
        if server or database_name:
            self.db_config = settings.build_database_config(
                alias=database_alias or server,
                server=server,
                database_name=database_name,
                user_id=user_id,
                password=password,
            )
        elif database_alias:
            self.db_config = settings.get_database_config(database_alias)
            if not self.db_config:
                raise ValueError(f"找不到資料庫設定: {database_alias}")
        else:
            self.db_config = settings.get_default_database()
            if not self.db_config:
                raise ValueError("未設定預設資料庫")
        
        self.connection = None
        self.cursor = None
        
        print(f"✅ SQL 分析器已初始化: {self.db_config.alias} ({self.db_config.database_name})")
    
    # ========================================
    # 連線管理
    # ========================================
    
    def connect(self) -> bool:
        """建立資料庫連線"""
        try:
            print(f"🔌 連接資料庫: {self.db_config.alias}...")
            
            conn_str = self.db_config.get_connection_string()
            self.connection = pyodbc.connect(conn_str)
            self.cursor = self.connection.cursor()
            
            # 取得資料庫資訊
            self.cursor.execute("SELECT DB_NAME(), SUSER_SNAME()")
            db_name, user_name = self.cursor.fetchone()
            
            print(f"✅ 連線成功")
            print(f"   資料庫: {db_name}")
            print(f"   登入身分: {user_name}")
            
            return True
            
        except pyodbc.Error as e:
            print(f"❌ 連線失敗: {e}")
            return False
    
    def disconnect(self):
        """關閉資料庫連線"""
        if self.cursor:
            self.cursor.close()
        if self.connection:
            self.connection.close()
        print(f"✅ 已關閉資料庫連線: {self.db_config.alias}")
    
    def test_connection(self) -> Dict:
        """測試連線並返回資訊"""
        if not self.connection:
            return {'success': False, 'error': '未連線'}
        
        try:
            self.cursor.execute("SELECT @@VERSION")
            version = self.cursor.fetchone()[0]
            
            return {
                'success': True,
                'database': self.db_config.database_name,
                'version': version.split('\n')[0]
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    # ========================================
    # 資料庫概覽
    # ========================================
    
    def get_database_summary(self) -> DatabaseSummary:
        """取得資料庫摘要"""
        summary = DatabaseSummary(database=self.db_config.alias)
        
        # 資料表數量
        self.cursor.execute("""
            SELECT COUNT(*) 
            FROM INFORMATION_SCHEMA.TABLES 
            WHERE TABLE_TYPE = 'BASE TABLE'
        """)
        summary.total_tables = self.cursor.fetchone()[0]
        
        # View 數量
        self.cursor.execute("""
            SELECT COUNT(*) 
            FROM INFORMATION_SCHEMA.VIEWS
        """)
        summary.total_views = self.cursor.fetchone()[0]
        
        # 預存程序數量
        self.cursor.execute("""
            SELECT COUNT(*) 
            FROM INFORMATION_SCHEMA.ROUTINES 
            WHERE ROUTINE_TYPE = 'PROCEDURE'
        """)
        summary.total_procedures = self.cursor.fetchone()[0]
        
        # 函數數量
        self.cursor.execute("""
            SELECT COUNT(*) 
            FROM INFORMATION_SCHEMA.ROUTINES 
            WHERE ROUTINE_TYPE = 'FUNCTION'
        """)
        summary.total_functions = self.cursor.fetchone()[0]
        
        return summary
    
    def get_all_procedures(self, schema: str = 'dbo') -> List[str]:
        """取得所有預存程序名稱"""
        query = """
        SELECT ROUTINE_NAME
        FROM INFORMATION_SCHEMA.ROUTINES
        WHERE ROUTINE_TYPE = 'PROCEDURE'
        AND ROUTINE_SCHEMA = ?
        ORDER BY ROUTINE_NAME
        """
        
        self.cursor.execute(query, schema)
        return [row.ROUTINE_NAME for row in self.cursor.fetchall()]
    
    def get_all_tables(self, schema: str = 'dbo') -> List[str]:
        """取得所有資料表名稱"""
        query = """
        SELECT TABLE_NAME
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_TYPE = 'BASE TABLE'
        AND TABLE_SCHEMA = ?
        ORDER BY TABLE_NAME
        """
        
        self.cursor.execute(query, schema)
        return [row.TABLE_NAME for row in self.cursor.fetchall()]

    def get_all_views(self, schema: str = 'dbo') -> List[str]:
        """取得所有 View（檢視表）名稱"""
        query = """
        SELECT TABLE_NAME
        FROM INFORMATION_SCHEMA.VIEWS
        WHERE TABLE_SCHEMA = ?
        ORDER BY TABLE_NAME
        """
        self.cursor.execute(query, schema)
        return [row.TABLE_NAME for row in self.cursor.fetchall()]

    def get_all_functions(self, schema: str = 'dbo') -> List[str]:
        """取得所有使用者定義函數（UDF）名稱"""
        query = """
        SELECT ROUTINE_NAME
        FROM INFORMATION_SCHEMA.ROUTINES
        WHERE ROUTINE_TYPE = 'FUNCTION'
        AND ROUTINE_SCHEMA = ?
        ORDER BY ROUTINE_NAME
        """
        self.cursor.execute(query, schema)
        return [row.ROUTINE_NAME for row in self.cursor.fetchall()]

    def get_all_dependencies(self, schema: str = 'dbo') -> Dict[str, Dict[str, List[str]]]:
        """
        一次查出整個 schema 內所有物件（SP/View/Function）的原生依賴關係
        （取代 _quick_extract_tables 的 regex 猜測），使用 SQL Server 中繼資料
        `sys.sql_expression_dependencies`（一次查整個資料庫，效能佳，不需要
        逐物件呼叫），同時建立正向（depends_on：這個物件依賴誰）與反向
        （depended_by：誰依賴這個物件）兩種索引，供上下游影響分析使用。

        已知限制（SQL Server 本身的限制，非查詢方式問題）：
        - 動態 SQL（EXEC(@sql)）組出來的引用一律看不到。
        - 跨資料庫依賴的 referenced_id 可能是 NULL（無法解析），這裡會被
          WHERE referenced_id IS NOT NULL 排除，不會出現在結果中。

        回傳: { "usp_SO_Qry": {"depends_on": ["Customers","SOrder",...],
                               "depended_by": [...]}, ... }
        （key 為 schema 下該物件自己的名稱，不含 schema 前綴）
        """
        query = """
        SELECT
            OBJECT_NAME(referencing_id) AS referencing_name,
            COALESCE(referenced_schema_name, ?) AS referenced_schema,
            referenced_entity_name
        FROM sys.sql_expression_dependencies AS d
        JOIN sys.objects AS o ON d.referencing_id = o.object_id
        WHERE SCHEMA_NAME(o.schema_id) = ?
          AND referenced_id IS NOT NULL
          AND referenced_entity_name IS NOT NULL
        """
        self.cursor.execute(query, schema, schema)
        rows = self.cursor.fetchall()

        dependencies: Dict[str, Dict[str, List[str]]] = {}

        def _ensure(name: str) -> Dict[str, List[str]]:
            return dependencies.setdefault(name, {"depends_on": [], "depended_by": []})

        for row in rows:
            referencing_name, referenced_schema, referenced_name = row[0], row[1], row[2]
            if not referencing_name or not referenced_name:
                continue
            src = _ensure(referencing_name)
            if referenced_name not in src["depends_on"]:
                src["depends_on"].append(referenced_name)
            dst = _ensure(referenced_name)
            if referencing_name not in dst["depended_by"]:
                dst["depended_by"].append(referencing_name)

        return dependencies

    def _get_native_referenced_tables(self, proc_name: str, schema: str = 'dbo') -> Set[str]:
        """
        單一物件的原生依賴查詢（給 quick_analyze_sp 即時分析單一 SP 用），
        使用 `sys.dm_sql_referenced_entities`（比 sys.sql_expression_dependencies
        更適合單一物件查詢，且能一併過濾出實際「資料表/View」類型的引用）。
        查詢失敗（權限不足、物件含無法解析的動態 SQL 導致 TVF 整個丟例外等）
        一律回傳空集合，由呼叫端 fallback 回 regex 版 _quick_extract_tables。
        """
        clean_name = proc_name.replace('[', '').replace(']', '')
        if '.' in clean_name:
            full_name = clean_name
        else:
            full_name = f"{schema}.{clean_name}"

        query = """
        SELECT DISTINCT referenced_entity_name
        FROM sys.dm_sql_referenced_entities(?, 'OBJECT')
        WHERE referenced_entity_name IS NOT NULL
          AND referenced_minor_name IS NULL
        """
        try:
            self.cursor.execute(query, full_name)
            rows = self.cursor.fetchall()
        except Exception:
            return set()

        tables: Set[str] = set()
        for row in rows:
            name = row[0]
            if name:
                tables.add(name)
        return tables

    def get_sp_write_info(self, proc_name: str, schema: str = 'dbo') -> Dict:
        """
        單一 SP 的讀寫資訊查詢（給 dump_all_sql_objects 落地快取用），沿用
        `_get_native_referenced_tables()` 同一套 `sys.dm_sql_referenced_entities`
        查詢方式，額外多讀 `is_selected`/`is_updated`/`referenced_minor_name`
        （欄位層級）三個欄位，藉此分辨「這支 SP 到底是讀還是寫這張表」——
        `_get_native_referenced_tables()` 本身不分讀寫，只回傳「有引用到」。

        回傳：{"writes_tables": [...], "reads_tables": [...],
               "writes_columns": {table_name: [col, ...]}}
        - 物件層級列（referenced_minor_name IS NULL）：is_updated=1 → writes_tables；
          is_selected=1 → reads_tables（兩者不互斥，同一張表可能同時被 SELECT 又
          被 UPDATE，因此可能同時出現在兩個清單，不能互斥判斷）。
        - 欄位層級列（referenced_minor_name IS NOT NULL）且 is_updated=1 → 累加進
          writes_columns[table_name]（如 SOrder.CancelBy/CancelTime，對「復原刪除」
          類問題有幫助）。
        - 查詢失敗（權限不足、動態 SQL 導致例外等）一律回傳空 dict，不中斷整包
          dump_all_sql_objects()（呼叫端會把這支 SP 視為「無寫入資訊記錄」，
          find_by_table 端 fallback 回 regex 文字比對）。
        """
        clean_name = proc_name.replace('[', '').replace(']', '')
        if '.' in clean_name:
            full_name = clean_name
        else:
            full_name = f"{schema}.{clean_name}"

        query = """
        SELECT referenced_entity_name, referenced_minor_name, is_selected, is_updated
        FROM sys.dm_sql_referenced_entities(?, 'OBJECT')
        WHERE referenced_entity_name IS NOT NULL
        """
        try:
            self.cursor.execute(query, full_name)
            rows = self.cursor.fetchall()
        except Exception:
            return {}

        writes_tables: Set[str] = set()
        reads_tables: Set[str] = set()
        writes_columns: Dict[str, List[str]] = {}
        for row in rows:
            table_name, minor_name, is_selected, is_updated = row[0], row[1], row[2], row[3]
            if not table_name:
                continue
            if minor_name is None:
                if is_updated:
                    writes_tables.add(table_name)
                if is_selected:
                    reads_tables.add(table_name)
            elif is_updated:
                writes_columns.setdefault(table_name, [])
                if minor_name not in writes_columns[table_name]:
                    writes_columns[table_name].append(minor_name)

        if not writes_tables and not reads_tables and not writes_columns:
            return {}

        return {
            "writes_tables": sorted(writes_tables),
            "reads_tables": sorted(reads_tables),
            "writes_columns": writes_columns,
        }

    def get_object_definition(self, name: str, schema: str = 'dbo') -> str:
        """
        取得任意物件（View/Function/Procedure）的完整定義本體（通用版，
        不含參數解析，供 View/Function 這類「只需要本體」的物件使用）。
        """
        query = "SELECT OBJECT_DEFINITION(OBJECT_ID(?))"
        full_name = f"{schema}.{name}" if '.' not in name else name
        self.cursor.execute(query, full_name)
        row = self.cursor.fetchone()
        return (row[0] or "") if row else ""

    def get_function_parameters(self, func_name: str, schema: str = 'dbo') -> Tuple[List[str], str]:
        """取得函數的參數清單與回傳型別。"""
        param_query = """
        SELECT PARAMETER_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, PARAMETER_MODE
        FROM INFORMATION_SCHEMA.PARAMETERS
        WHERE SPECIFIC_NAME = ? AND SPECIFIC_SCHEMA = ?
        ORDER BY ORDINAL_POSITION
        """
        self.cursor.execute(param_query, func_name, schema)
        parameters: List[str] = []
        return_type = ""
        for r in self.cursor.fetchall():
            # 回傳值在 INFORMATION_SCHEMA.PARAMETERS 裡 PARAMETER_NAME 為 NULL
            if r[0] is None:
                return_type = r[1].upper() if r[1] else ""
                continue
            ptype = r[1].upper() if r[1] else ""
            if r[2]:
                ptype += f"({r[2]})" if r[2] != -1 else "(MAX)"
            parameters.append(f"{r[0]} {ptype}")
        return parameters, return_type

    def get_primary_key_columns(self, table_name: str, schema: str = 'dbo') -> List[str]:
        """取得資料表的主鍵欄位名稱清單（依組成順序）。

        供「命名慣例推論關聯」使用（見 service/fk_resolver.py）：資料庫沒有
        建立實際 FK 約束時，改用「某表的主鍵欄位名稱，剛好也出現在其他表當
        欄位名」這種命名慣例，推論兩表可能相關（例如 Customer 表主鍵
        CustomerCode，Order 表也有 CustomerCode 欄位）。純靜態 Schema 查詢，
        不需要額外連線（跟其他 dump_all_sql_objects 內的查詢共用同一次連線）。
        """
        query = """
        SELECT kcu.COLUMN_NAME
        FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
        JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu
          ON tc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME AND tc.TABLE_SCHEMA = kcu.TABLE_SCHEMA
        WHERE tc.CONSTRAINT_TYPE = 'PRIMARY KEY' AND tc.TABLE_NAME = ? AND tc.TABLE_SCHEMA = ?
        ORDER BY kcu.ORDINAL_POSITION
        """
        self.cursor.execute(query, table_name, schema)
        return [row[0] for row in self.cursor.fetchall()]

    def get_table_columns(self, table_name: str, schema: str = 'dbo') -> List[Dict]:
        """取得資料表的欄位 Schema（名稱/型別/長度/是否可為 NULL）。"""
        query = """
        SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, IS_NULLABLE, COLUMN_DEFAULT
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_NAME = ? AND TABLE_SCHEMA = ?
        ORDER BY ORDINAL_POSITION
        """
        self.cursor.execute(query, table_name, schema)
        columns: List[Dict] = []
        for r in self.cursor.fetchall():
            col_type = r[1] or ""
            if r[2]:
                col_type += f"({r[2]})" if r[2] != -1 else "(MAX)"
            columns.append({
                "name": r[0],
                "type": col_type,
                "nullable": (r[3] or "").upper() == "YES",
                "default": r[4],
            })
        return columns

    def dump_all_sql_objects(
        self,
        schema: str = 'dbo',
        progress_callback: Optional[Callable[[str, int, int, str], None]] = None,
    ) -> Dict:
        """
        把整個資料庫（指定 schema）的 SP/View/Function 完整定義與資料表欄位 Schema
        一次全部撈出來，供本機落地快取（sql_cache_store.py），避免每次問問題都要
        即時連線查詢。純靜態擷取，不含任何 AI 摘要（AI 注記交由 spec-rag 端按需做）。

        逐類別（SP/View/Function/資料表）顯示 tqdm 進度條，避免物件數量多時
        （尤其逐一查詢 SP 定義/參數）使用者看著終端機沒有任何輸出、以為當機。

        回傳結構：
        {
            "database": alias, "schema": schema,
            "procedures": [{"name","definition","parameters"}],
            "views": [{"name","definition"}],
            "functions": [{"name","definition","parameters","return_type"}],
            "tables": [{"name","columns":[{"name","type","nullable","default"}]}],
        }
        """
        from tqdm import tqdm

        procedures: List[Dict] = []
        proc_names = self.get_all_procedures(schema)
        _report_progress(progress_callback, "procedures", 0, len(proc_names), "")
        for current, name in enumerate(
            tqdm(proc_names, desc="   SP 定義", unit="個"), start=1
        ):
            info = self._get_sp_basic_info(name, schema) or {}
            procedures.append({
                "name": name,
                "definition": info.get("definition", ""),
                "parameters": info.get("parameters", []),
            })
            _report_progress(progress_callback, "procedures", current, len(proc_names), name)

        views: List[Dict] = []
        view_names = self.get_all_views(schema)
        _report_progress(progress_callback, "views", 0, len(view_names), "")
        for current, name in enumerate(
            tqdm(view_names, desc="   View 定義", unit="個"), start=1
        ):
            views.append({
                "name": name,
                "definition": self.get_object_definition(name, schema),
            })
            _report_progress(progress_callback, "views", current, len(view_names), name)

        functions: List[Dict] = []
        function_names = self.get_all_functions(schema)
        _report_progress(progress_callback, "functions", 0, len(function_names), "")
        for current, name in enumerate(
            tqdm(function_names, desc="   Function 定義", unit="個"), start=1
        ):
            parameters, return_type = self.get_function_parameters(name, schema)
            functions.append({
                "name": name,
                "definition": self.get_object_definition(name, schema),
                "parameters": parameters,
                "return_type": return_type,
            })
            _report_progress(progress_callback, "functions", current, len(function_names), name)

        tables: List[Dict] = []
        table_names = self.get_all_tables(schema)
        _report_progress(progress_callback, "tables", 0, len(table_names), "")
        for current, name in enumerate(
            tqdm(table_names, desc="   資料表 Schema", unit="個"), start=1
        ):
            tables.append({
                "name": name,
                "columns": self.get_table_columns(name, schema),
                "primary_keys": self.get_primary_key_columns(name, schema),
            })
            _report_progress(progress_callback, "tables", current, len(table_names), name)

        return {
            "database": self.db_config.alias,
            "schema": schema,
            "procedures": procedures,
            "views": views,
            "functions": functions,
            "tables": tables,
        }
    # ========================================
    # 單一 SP 快速分析
    # ========================================
    
    def quick_analyze_sp(
        self, 
        proc_name: str, 
        schema: str = 'dbo'
    ) -> SimplifiedSPInfo:
        """
        快速分析單一預存程序
        只做靜態分析，不深入解析複雜邏輯
        """
        print(f"\n🔍 快速分析: {proc_name}")
        
        info = SimplifiedSPInfo(
            procedure_name=proc_name,
            database=self.db_config.alias,
            schema=schema
        )
        
        # 1. 檢查是否存在
        info.exists = self._check_sp_exists(proc_name, schema)
        
        if not info.exists:
            print(f"   ❌ 預存程序不存在")
            return info
        
        # 2. 取得基本資訊
        basic_info = self._get_sp_basic_info(proc_name, schema)
        if basic_info:
            info.parameters = basic_info['parameters']
            info.created_date = basic_info['created_date']
            info.modified_date = basic_info['modified_date']
            info.definition = basic_info['definition']
            info.definition_length = len(info.definition)
            info.line_count = info.definition.count('\n') + 1
            
            # 3. 快速特徵識別
            info.has_dynamic_sql = self._detect_dynamic_sql(info.definition)
            info.has_temp_tables = self._detect_temp_tables(info.definition)
            info.has_cursor = self._detect_cursor(info.definition)
            info.has_transaction = self._detect_transaction(info.definition)
            
            # 4. 提取資料表：原生依賴查詢（sys.dm_sql_referenced_entities）優先，
            #    查不到（權限不足/動態SQL導致整包查詢失敗/查得到但結果是空集合）
            #    才 fallback 回 regex 版 _quick_extract_tables
            native_tables = self._get_native_referenced_tables(proc_name, schema)
            if native_tables:
                info.referenced_tables = native_tables
                info.dependency_source = "native"
            else:
                info.referenced_tables = self._quick_extract_tables(info.definition)
                info.dependency_source = "regex"
            
            # 5. 估算複雜度
            info.estimated_complexity = self._estimate_complexity(info)
            
            print(f"   ✅ 完成 - 複雜度: {info.estimated_complexity}")
            print(f"      參數: {len(info.parameters)}")
            print(f"      資料表: {len(info.referenced_tables)}（來源: {info.dependency_source}）")
        
        return info
    
    def _check_sp_exists(self, proc_name: str, schema: str) -> bool:
        """檢查 SP 是否存在 (修正 schema 支援)"""
        
        # 1. 正常查詢 (使用指定 schema)
        query = """
        SELECT COUNT(*)
        FROM INFORMATION_SCHEMA.ROUTINES
        WHERE ROUTINE_NAME = ? AND ROUTINE_SCHEMA = ? AND ROUTINE_TYPE = 'PROCEDURE'
        """
        self.cursor.execute(query, proc_name, schema)
        if self.cursor.fetchone()[0] > 0:
            return True
            
        # 2. 如果失敗，嘗試移除方括號 (處理像 [dbo].[spName] 或 [spName] 的情況)
        clean_name = proc_name.replace('[', '').replace(']', '')
        if '.' in clean_name:
            # 如果包含 schema.name
            parts = clean_name.split('.')
            if len(parts) == 2:
                sp_schema, sp_name = parts
                self.cursor.execute(query, sp_name, sp_schema)
                if self.cursor.fetchone()[0] > 0:
                    return True
        else:
            # 只有名稱，用傳入的 schema 再試一次
            self.cursor.execute(query, clean_name, schema)
            if self.cursor.fetchone()[0] > 0:
                return True
                
        return False
    
    def _get_sp_basic_info(self, proc_name: str, schema: str) -> Optional[Dict]:
        """取得 SP 基本資訊 (修正 schema 支援)"""
        
        # 預處理名稱
        target_name = proc_name
        target_schema = schema
        
        clean_name = proc_name.replace('[', '').replace(']', '')
        if '.' in clean_name:
            parts = clean_name.split('.')
            if len(parts) == 2:
                target_schema = parts[0]
                target_name = parts[1]
        else:
            target_name = clean_name

        # 取得定義和時間
        query = """
        SELECT 
            ROUTINE_DEFINITION,
            CREATED,
            LAST_ALTERED
        FROM INFORMATION_SCHEMA.ROUTINES
        WHERE ROUTINE_NAME = ? AND ROUTINE_SCHEMA = ?
        """
        self.cursor.execute(query, target_name, target_schema)
        row = self.cursor.fetchone()
        
        if not row:
            return None
        
        # ROUTINE_DEFINITION is NVARCHAR(4000); anything that long may be
        # truncated mid-statement, so re-fetch the untruncated body via
        # OBJECT_DEFINITION (NVARCHAR(MAX)). Bound as a parameter, not
        # string-formatted, to avoid SQL injection through the object name.
        definition = row[0] or ""
        if not definition or len(definition) >= 4000:
            self.cursor.execute(
                "SELECT OBJECT_DEFINITION(OBJECT_ID(?))",
                f"{target_schema}.{target_name}",
            )
            def_row = self.cursor.fetchone()
            if def_row and def_row[0]:
                definition = def_row[0]

        # 取得參數
        param_query = """
        SELECT 
            PARAMETER_NAME,
            DATA_TYPE,
            CHARACTER_MAXIMUM_LENGTH,
            PARAMETER_MODE
        FROM INFORMATION_SCHEMA.PARAMETERS
        WHERE SPECIFIC_NAME = ? AND SPECIFIC_SCHEMA = ?
        ORDER BY ORDINAL_POSITION
        """
        self.cursor.execute(param_query, target_name, target_schema)
        
        parameters = []
        for r in self.cursor.fetchall():
            param_type = r[1].upper()
            if r[2]:  # 有長度
                param_type += f"({r[2]})" if r[2] != -1 else "(MAX)"
            
            param_str = f"{r[0]} {param_type}"
            if r[3] and r[3] != 'IN':
                param_str += f" ({r[3]})"
            
            parameters.append(param_str)
        
        return {
            'definition': definition,
            'created_date': str(row[1]) if row[1] else None,
            'modified_date': str(row[2]) if row[2] else None,
            'parameters': parameters
        }
    
    # ========================================
    # 快速特徵識別（正規表達式）
    # ========================================
    
    def _detect_dynamic_sql(self, sql: str) -> bool:
        """偵測動態 SQL"""
        patterns = [
            r'EXEC\s*\(\s*@',
            r'sp_executesql',
            r'EXECUTE\s+sp_executesql'
        ]
        return any(re.search(p, sql, re.IGNORECASE) for p in patterns)
    
    def _detect_temp_tables(self, sql: str) -> bool:
        """偵測暫存資料表"""
        return bool(re.search(r'#\w+', sql))
    
    def _detect_cursor(self, sql: str) -> bool:
        """偵測游標"""
        return bool(re.search(r'DECLARE\s+\w+\s+CURSOR', sql, re.IGNORECASE))
    
    def _detect_transaction(self, sql: str) -> bool:
        """偵測交易"""
        return bool(re.search(r'BEGIN\s+(?:TRAN|TRANSACTION)', sql, re.IGNORECASE))
    
    def _quick_extract_tables(self, sql: str) -> Set[str]:
        """
        快速提取資料表（簡單模式）
        只提取明顯的資料表引用，不深入分析
        """
        tables = set()
        
        # 移除註解（避免誤判）
        sql = re.sub(r'--.*?$', '', sql, flags=re.MULTILINE)
        sql = re.sub(r'/\*.*?\*/', '', sql, flags=re.DOTALL)
        
        # 提取模式 (修正：支援 schema.table 格式)
        # 允許捕捉 字母、數字、底線、方括號 [] 以及 點號 .
        patterns = [
            (r'FROM\s+([\[\w\]\.]+)', 'FROM'),
            (r'JOIN\s+([\[\w\]\.]+)', 'JOIN'),
            (r'INTO\s+([\[\w\]\.]+)', 'INTO'),
            (r'UPDATE\s+([\[\w\]\.]+)', 'UPDATE'),
        ]
        
        for pattern, context in patterns:
            matches = re.findall(pattern, sql, re.IGNORECASE)
            for match in matches:
                # 清理表格名稱
                table = match.strip('[]').strip()
                
                # 過濾條件
                if (
                    table and 
                    not table.startswith('#') and  # 排除暫存表
                    not table.startswith('@') and  # 排除變數
                    table.upper() not in ['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'EXEC', 'EXECUTE'] and
                    len(table) > 1 and
                    not table.startswith('(')  # 排除子查詢
                ):
                    # 處理 schema.table 格式
                    if '.' in table:
                        table = table.split('.')[-1].strip('[]')
                    
                    tables.add(table)
        
        return tables
    
    def _estimate_complexity(self, info: SimplifiedSPInfo) -> str:
        """估算複雜度"""
        score = 0
        
        # 特徵評分
        if info.has_dynamic_sql:
            score += 3
        if info.has_temp_tables:
            score += 2
        if info.has_cursor:
            score += 2
        if info.has_transaction:
            score += 1
        
        # 長度評分
        if info.definition_length > 10000:
            score += 3
        elif info.definition_length > 5000:
            score += 2
        elif info.definition_length > 2000:
            score += 1
        
        # 資料表數量評分
        table_count = len(info.referenced_tables)
        if table_count > 10:
            score += 2
        elif table_count > 5:
            score += 1
        
        # 行數評分
        if info.line_count > 500:
            score += 2
        elif info.line_count > 200:
            score += 1
        
        # 判定
        if score >= 6:
            return "複雜"
        elif score >= 3:
            return "中等"
        else:
            return "簡單"

    # ========================================
    # 批次分析
    # ========================================
    
    def analyze_all_procedures(
        self, 
        schema: str = 'dbo',
        limit: Optional[int] = None
    ) -> DatabaseSummary:
        """
        分析所有預存程序
        
        Args:
            schema: Schema 名稱
            limit: 限制數量（用於測試）
        """
        print("\n" + "=" * 80)
        print(f"批次分析資料庫: {self.db_config.alias}")
        print("=" * 80)
        
        # 取得摘要
        summary = self.get_database_summary()
        
        # 取得所有 SP
        all_procs = self.get_all_procedures(schema)
        
        if limit:
            all_procs = all_procs[:limit]
        
        print(f"\n找到 {len(all_procs)} 個預存程序")
        print("開始分析...\n")
        
        # 批次分析
        from tqdm import tqdm
        
        for proc_name in tqdm(all_procs, desc="分析進度"):
            try:
                sp_info = self.quick_analyze_sp(proc_name, schema)
                summary.procedures.append(sp_info)
                summary.analyzed_procedures += 1
            except Exception as e:
                print(f"\n   ⚠️  分析失敗 ({proc_name}): {e}")
        
        print(f"\n✅ 分析完成: {summary.analyzed_procedures}/{len(all_procs)}")
        
        return summary
    
    # ========================================
    # 輸出與匯出
    # ========================================
    
    def print_sp_info(self, info: SimplifiedSPInfo, detailed: bool = True):
        """美化輸出 SP 資訊"""
        print("\n" + "=" * 80)
        print(f"預存程序: {info.procedure_name}")
        print("=" * 80)
        
        if not info.exists:
            print("❌ 預存程序不存在")
            return
        
        # 基本資訊
        print(f"\n📋 基本資訊:")
        print(f"   資料庫: {info.database}")
        print(f"   Schema: {info.schema}")
        print(f"   建立時間: {info.created_date}")
        print(f"   修改時間: {info.modified_date}")
        print(f"   複雜度: {info.estimated_complexity}")
        
        # 統計
        print(f"\n📊 統計:")
        print(f"   行數: {info.line_count}")
        print(f"   字元數: {info.definition_length}")
        print(f"   參數數: {len(info.parameters)}")
        print(f"   資料表數: {len(info.referenced_tables)}")
        
        # 特���
        features = []
        if info.has_dynamic_sql:
            features.append("動態 SQL")
        if info.has_temp_tables:
            features.append("暫存資料表")
        if info.has_cursor:
            features.append("游標")
        if info.has_transaction:
            features.append("交易")
        
        if features:
            print(f"\n⚙️  特徵:")
            for feature in features:
                print(f"   - {feature}")
        
        # 參數
        if info.parameters:
            print(f"\n📥 參數 ({len(info.parameters)}):")
            for param in info.parameters:
                print(f"   - {param}")
        
        # 資料表
        if info.referenced_tables:
            print(f"\n📊 涉及的資料表 ({len(info.referenced_tables)}):")
            for table in sorted(info.referenced_tables):
                print(f"   - {table}")
        
        # 詳細定義
        if detailed and info.definition:
            print(f"\n📝 SQL 定義（前 500 字元）:")
            print("   " + "-" * 76)
            preview = info.definition[:500].replace('\n', '\n   ')
            print(f"   {preview}")
            if len(info.definition) > 500:
                print(f"   ... (共 {len(info.definition)} 字元)")
            print("   " + "-" * 76)
        
        print("\n" + "=" * 80)
    
    def print_summary(self, summary: DatabaseSummary):
        """輸出資料庫摘要"""
        print("\n" + "=" * 80)
        print(f"資料庫摘要: {summary.database}")
        print("=" * 80)
        
        print(f"\n📊 統計:")
        print(f"   資料表: {summary.total_tables}")
        print(f"   檢視表: {summary.total_views}")
        print(f"   預存程序: {summary.total_procedures}")
        print(f"   函數: {summary.total_functions}")
        print(f"   已分析: {summary.analyzed_procedures}")
        
        if summary.procedures:
            # 按複雜度分組
            by_complexity = {'簡單': [], '中等': [], '複雜': []}
            for sp in summary.procedures:
                by_complexity[sp.estimated_complexity].append(sp)
            
            print(f"\n📈 複雜度分布:")
            print(f"   簡單: {len(by_complexity['簡單'])}")
            print(f"   中等: {len(by_complexity['中等'])}")
            print(f"   複雜: {len(by_complexity['複雜'])}")
            
            # 特徵統計
            dynamic_sql_count = sum(1 for sp in summary.procedures if sp.has_dynamic_sql)
            temp_table_count = sum(1 for sp in summary.procedures if sp.has_temp_tables)
            cursor_count = sum(1 for sp in summary.procedures if sp.has_cursor)
            
            if any([dynamic_sql_count, temp_table_count, cursor_count]):
                print(f"\n⚙️  特徵統計:")
                if dynamic_sql_count:
                    print(f"   動態 SQL: {dynamic_sql_count}")
                if temp_table_count:
                    print(f"   暫存資料表: {temp_table_count}")
                if cursor_count:
                    print(f"   游標: {cursor_count}")
        
        print("\n" + "=" * 80)
    
    def export_to_json(
        self, 
        data, 
        output_path: str = None
    ) -> str:
        """
        匯出為 JSON
        
        Args:
            data: SimplifiedSPInfo 或 DatabaseSummary
            output_path: 輸出路徑
        """
        if output_path is None:
            # 自動生成路徑
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            
            if isinstance(data, SimplifiedSPInfo):
                output_path = f"output/sp_analysis/{data.database}_{data.procedure_name}_{timestamp}.json"
            elif isinstance(data, DatabaseSummary):
                output_path = f"output/sp_analysis/{data.database}_summary_{timestamp}.json"
            else:
                output_path = f"output/sp_analysis/export_{timestamp}.json"
        
        # 建立目錄
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        
        # 轉換為字典
        if isinstance(data, SimplifiedSPInfo):
            export_data = data.to_dict()
        elif isinstance(data, DatabaseSummary):
            export_data = data.to_dict()
        else:
            export_data = data
        
        # 寫入檔案
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False)
        
        print(f"✅ 已匯出: {output_path}")
        return output_path
    
    def export_summary_to_excel(
        self,
        summary: DatabaseSummary,
        output_path: str = None
    ) -> str:
        """匯出摘要為 Excel"""
        import pandas as pd
        
        if output_path is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_path = f"output/sp_analysis/{summary.database}_summary_{timestamp}.xlsx"
        
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        
        # 準備資料
        data = []
        for sp in summary.procedures:
            data.append({
                '預存程序名稱': sp.procedure_name,
                'Schema': sp.schema,
                '是否存在': '是' if sp.exists else '否',
                '複雜度': sp.estimated_complexity,
                '參數數量': len(sp.parameters),
                '資料表數量': len(sp.referenced_tables),
                '行數': sp.line_count,
                '動態SQL': '是' if sp.has_dynamic_sql else '否',
                '暫存資料表': '是' if sp.has_temp_tables else '否',
                '游標': '是' if sp.has_cursor else '否',
                '建立時間': sp.created_date,
                '修改時間': sp.modified_date,
                '涉及資料表': ', '.join(sorted(sp.referenced_tables))
            })
        
        df = pd.DataFrame(data)
        
        # 寫入 Excel
        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='預存程序清單', index=False)
            
            # 調整欄寬
            worksheet = writer.sheets['預存程序清單']
            for column in worksheet.columns:
                max_length = 0
                column_letter = column[0].column_letter
                for cell in column:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except:
                        pass
                adjusted_width = min(max_length + 2, 50)
                worksheet.column_dimensions[column_letter].width = adjusted_width
        
        print(f"✅ 已匯出 Excel: {output_path}")
        return output_path


# ============================================
# 純字串靜態分析（不需要資料庫連線）
# ============================================

def _report_progress(
    callback: Optional[Callable[[str, int, int, str], None]],
    stage: str,
    current: int,
    total: int,
    item: str,
) -> None:
    if callback is None:
        return
    try:
        callback(stage, current, total, item)
    except Exception:
        pass


def estimate_complexity_from_definition(definition: str) -> str:
    """依 SP/View/UDF 的完整定義文字估算複雜度，純字串正規表達式分析，
    不需要任何資料庫連線 —— 給「已有 definition 文字、但沒有走 quick_analyze_sp()
    即時查詢」的路徑使用（例如 service/sp_fetcher.py 從本機 SQL 快取
    sql_cache_store.py 讀出的 definition，之前一直缺這個複雜度欄位）。

    邏輯與 quick_analyze_sp() 內的複雜度估算步驟（動態 SQL/暫存表/游標/交易偵測、
    資料表提取、_estimate_complexity 計分）完全一致，只是輸入從即時查詢改成
    現成的 definition 字串。4 個 `_detect_*`／`_quick_extract_tables`／
    `_estimate_complexity` 方法本身都是純字串分析（不使用 self 的任何屬性），
    故用 `object.__new__` 建立一個不觸發 `__init__`（不需要 DB 連線設定）的
    空殼實例即可安全呼叫。
    """
    definition = definition or ""
    info = SimplifiedSPInfo(procedure_name="", database="")
    info.definition = definition
    info.definition_length = len(definition)
    info.line_count = definition.count("\n") + 1 if definition else 0

    analyzer = object.__new__(SQLAnalyzer)
    info.has_dynamic_sql = analyzer._detect_dynamic_sql(definition)
    info.has_temp_tables = analyzer._detect_temp_tables(definition)
    info.has_cursor = analyzer._detect_cursor(definition)
    info.has_transaction = analyzer._detect_transaction(definition)
    info.referenced_tables = analyzer._quick_extract_tables(definition)

    return analyzer._estimate_complexity(info)


def extract_tables_from_definition(definition: str) -> Set[str]:
    """依 SP/View/UDF 的完整定義文字提取引用資料表，純字串分析，不需要資料庫連線。

    給「已有 definition 文字、但沒有走 quick_analyze_sp() 即時查詢」的路徑使用
    （例如 service/sp_fetcher.py 從本機 SQL 快取讀出的 definition，先前這個欄位
    在快取路徑一直是空清單——estimate_complexity_from_definition() 內部其實已經
    算出 referenced_tables，只是沒有另外回傳，這裡把它獨立成一個公開函式）。
    做法與 estimate_complexity_from_definition() 相同：用 object.__new__ 建立
    不觸發 __init__（不需要 DB 連線設定）的空殼實例呼叫純字串方法
    _quick_extract_tables。
    """
    if not definition:
        return set()
    analyzer = object.__new__(SQLAnalyzer)
    return analyzer._quick_extract_tables(definition)


# ============================================
# 測試與使用範例
# ============================================

def main():
    """主測試程式"""
    print("=" * 80)
    print("SQL 分析器測試")
    print("=" * 80)
    
    # 顯示可用資料庫
    all_dbs = settings.get_all_databases()
    print(f"\n可用的資料庫 ({len(all_dbs)}):")
    for i, (alias, db_config) in enumerate(all_dbs.items(), 1):
        print(f"  {i}. {alias}: {db_config.database_name}")
    
    # 選擇資料庫
    choice = input(f"\n請選擇資料庫 (預設: {settings.DB_DEFAULT_DATABASE}): ").strip()
    
    if choice.isdigit():
        db_alias = list(all_dbs.keys())[int(choice) - 1]
    elif choice in all_dbs:
        db_alias = choice
    else:
        db_alias = settings.DB_DEFAULT_DATABASE
    
    try:
        # 建立分析器
        analyzer = SQLAnalyzer(db_alias)
        
        # 連接資料庫
        if not analyzer.connect():
            return
        
        # 選擇功能
        print("\n" + "=" * 80)
        print("請選擇功能:")
        print("  1. 分析單一預存程序")
        print("  2. 分析所有預存程序")
        print("  3. 顯示資料庫摘要")
        print("=" * 80)
        
        function_choice = input("\n請輸入選項 (1-3): ").strip()
        
        if function_choice == '1':
            # 單一 SP 分析
            procedures = analyzer.get_all_procedures()
            print(f"\n找到 {len(procedures)} 個預存程序")
            print("\n前 20 個:")
            for i, proc in enumerate(procedures[:20], 1):
                print(f"  {i}. {proc}")
            
            sp_choice = input("\n請輸入預存程序名稱（或編號）: ").strip()
            
            if sp_choice.isdigit():
                sp_index = int(sp_choice) - 1
                if 0 <= sp_index < len(procedures):
                    sp_name = procedures[sp_index]
                else:
                    print("❌ 編號無效")
                    analyzer.disconnect()
                    return
            else:
                sp_name = sp_choice
            
            # 分析
            sp_info = analyzer.quick_analyze_sp(sp_name)
            analyzer.print_sp_info(sp_info, detailed=True)
            
            # 匯出
            export = input("\n是否匯出為 JSON？(y/n): ").strip().lower()
            if export == 'y':
                analyzer.export_to_json(sp_info)
        
        elif function_choice == '2':
            # 批次分析
            limit_input = input("\n限制數量（測試用，直接按 Enter 分析全部）: ").strip()
            limit = int(limit_input) if limit_input.isdigit() else None
            
            summary = analyzer.analyze_all_procedures(limit=limit)
            analyzer.print_summary(summary)
            
            # 匯出
            export = input("\n是否匯出結果？(json/excel/n): ").strip().lower()
            if export == 'json':
                analyzer.export_to_json(summary)
            elif export == 'excel':
                analyzer.export_summary_to_excel(summary)
        
        elif function_choice == '3':
            # 資料庫摘要
            summary = analyzer.get_database_summary()
            analyzer.print_summary(summary)
        
        # 關閉連線
        analyzer.disconnect()
        
    except Exception as e:
        print(f"\n❌ 錯誤: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 80)
    print("✅ 測試完成")
    print("=" * 80)


if __name__ == "__main__":
    main()