# config/settings.py

import os
import sys
from pathlib import Path
from typing import List, Optional, Dict
from dotenv import load_dotenv

# 載入 .env 檔案
env_path = Path(__file__).parent.parent / '.env'
if env_path.exists():
    load_dotenv(env_path)
    print(f"✅ 已載入環境設定: {env_path}", file=sys.stderr)
else:
    print(f"⚠️ 找不到 .env 檔案: {env_path}", file=sys.stderr)
    load_dotenv()


class DatabaseConfig:
    """單一資料庫設定"""
    
    def __init__(self, alias: str, database_name: str, server: str, **kwargs):
        self.alias = alias              # 簡稱 (例如: STC, PUR)
        self.database_name = database_name  # 實際資料庫名稱
        self.server = server
        self.auth_mode = kwargs.get('auth_mode', 'windows')
        self.user_id = kwargs.get('user_id')
        self.password = kwargs.get('password')
        self.port = kwargs.get('port', 1433)
        self.timeout = kwargs.get('timeout', 30)
        self.encrypt = kwargs.get('encrypt', True)
        self.trust_server_certificate = kwargs.get('trust_server_certificate', True)
        self.application_name = kwargs.get('application_name', 'ImpactAnalysisSystem')
        self.driver = kwargs.get('driver', 'ODBC Driver 17 for SQL Server')
    
    def get_connection_string(self) -> str:
        """取得連線字串"""
        server = self.server
        if self.port != 1433:
            server = f"{server},{self.port}"
        
        conn_str = (
            f"Driver={{{self.driver}}};"
            f"Server={server};"
            f"Database={self.database_name};"
        )
        
        # Windows 驗證 vs SQL Server 驗證
        if self.auth_mode.lower() == 'windows':
            conn_str += "Trusted_Connection=yes;"
        else:
            conn_str += f"UID={self.user_id};PWD={self.password};"
        
        # 其他參數
        if self.encrypt:
            conn_str += "Encrypt=yes;"
        
        if self.trust_server_certificate:
            conn_str += "TrustServerCertificate=yes;"
        
        if self.application_name:
            conn_str += f"APP={self.application_name};"
        
        conn_str += f"Connection Timeout={self.timeout};"
        
        return conn_str
    
    def get_safe_connection_string(self) -> str:
        """取得安全的連線字串（隱藏密碼）"""
        conn_str = self.get_connection_string()
        if self.password:
            conn_str = conn_str.replace(self.password, "***")
        return conn_str
    
    def __str__(self):
        return f"{self.alias} -> {self.database_name} @ {self.server}"


class Settings:
    """應用程式設定"""
    
    # ========================================
    # 環境設定
    # ========================================
    ENVIRONMENT: str = os.getenv('ENVIRONMENT', 'development')
    
    # ========================================
    # 資料庫伺服器設定（共用）
    # ========================================
    DB_SERVER: str = os.getenv('DB_SERVER', 'localhost')
    DB_PORT: int = int(os.getenv('DB_PORT', '1433'))
    DB_AUTH_MODE: str = os.getenv('DB_AUTH_MODE', 'windows')
    DB_USER_ID: Optional[str] = os.getenv('DB_USER_ID')
    DB_PASSWORD: Optional[str] = os.getenv('DB_PASSWORD')
    
    DB_TIMEOUT: int = int(os.getenv('DB_TIMEOUT', '30'))
    DB_ENCRYPT: bool = os.getenv('DB_ENCRYPT', 'True').lower() == 'true'
    DB_TRUST_SERVER_CERTIFICATE: bool = os.getenv('DB_TRUST_SERVER_CERTIFICATE', 'True').lower() == 'true'
    DB_APPLICATION_NAME: str = os.getenv('DB_APPLICATION_NAME', 'ImpactAnalysisSystem')
    DB_DRIVER: str = os.getenv('DB_DRIVER', 'ODBC Driver 17 for SQL Server')
    
    # ========================================
    # 多資料庫設定
    # ========================================
    DB_DATABASES_RAW: str = os.getenv('DB_DATABASES', 'STC,PUR')
    DB_DEFAULT_DATABASE: str = os.getenv('DB_DEFAULT_DATABASE', 'STC')
    
    # ========================================
    # 專案掃描設定
    # ========================================
    EXCLUDE_FOLDERS: List[str] = os.getenv('EXCLUDE_FOLDERS', 'bin,obj,packages,node_modules,.git,.vs').split(',')
    EXCLUDE_PATTERNS: List[str] = os.getenv('EXCLUDE_PATTERNS', '*.Designer.cs,*.g.cs,*.g.i.cs').split(',')

    # ========================================
    # Azure DevOps 設定
    # ========================================
    AZURE_DEVOPS_ORG: str = os.getenv('AZURE_DEVOPS_ORG', '')
    AZURE_DEVOPS_PROJECT: str = os.getenv('AZURE_DEVOPS_PROJECT', '')
    AZURE_DEVOPS_REPO: str = os.getenv('AZURE_DEVOPS_REPO', '')
    AZURE_DEVOPS_PAT: str = os.getenv('AZURE_DEVOPS_PAT', '')
    AZURE_DEVOPS_BRANCH: str = os.getenv('AZURE_DEVOPS_BRANCH', 'main')
    # Clone 目標目錄（留空則使用系統暫存目錄）
    AZURE_DEVOPS_CLONE_DIR: str = os.getenv('AZURE_DEVOPS_CLONE_DIR', '')

    # ========================================
    # HTTP 服務設定（FastAPI / 影響分析服務）
    # ========================================
    SERVICE_HOST: str = os.getenv('SERVICE_HOST', '127.0.0.1')
    SERVICE_PORT: int = int(os.getenv('SERVICE_PORT', '8800'))
    # 多系統共用 repo 的本機快取根目錄；依 <project>__<repo> 分目錄
    AZURE_CLONE_ROOT: str = os.getenv('AZURE_CLONE_ROOT', './data/repos')
    # 靜態掃描結果的持久化快取根目錄（pickle）；避免每次重新解析 C#
    SCAN_CACHE_ROOT: str = os.getenv('SCAN_CACHE_ROOT', './data/scan_cache')
    # SQL 物件（SP/View/Function/資料表 Schema）的本機落地快取根目錄（JSON）；
    # 避免每次問問題都要即時連線 SQL Server 查詢，只有明確執行「更新 SQL 快取」
    # 指令時才重新連線撈取並覆寫。
    SQL_CACHE_ROOT: str = os.getenv('SQL_CACHE_ROOT', './data/sql_cache')

    # ========================================
    # 檔案路徑設定
    # ========================================
    FILE_LIST_PATH: str = os.getenv('FILE_LIST_PATH', 'data/檔案一覽表.xlsx')
    DEFINITION_PATH: str = os.getenv('DEFINITION_PATH', 'data/定義書.xlsx')
    SPEC_FILES: List[str] = [f.strip() for f in os.getenv('SPEC_FILES', '').split(',') if f.strip()]
    
    # ========================================
    # 輸出設定
    # ========================================
    OUTPUT_DIR: str = os.getenv('OUTPUT_DIR', 'output')
    GENERATE_CHARTS: bool = os.getenv('GENERATE_CHARTS', 'True').lower() == 'true'
    GENERATE_HTML_REPORT: bool = os.getenv('GENERATE_HTML_REPORT', 'True').lower() == 'true'
    
    # ========================================
    # 日誌設定
    # ========================================
    LOG_LEVEL: str = os.getenv('LOG_LEVEL', 'INFO')
    LOG_FILE: str = os.getenv('LOG_FILE', 'logs/analysis.log')
    
    # ========================================
    # 解析多資料庫設定
    # ========================================
    _databases: Dict[str, DatabaseConfig] = {}
    
    @classmethod
    def _parse_databases(cls):
        """解析資料庫設定"""
        if cls._databases:
            return  # 已經解析過
        
        # 解析格式: "STC:STC_Production,PUR:PUR_Production" 或 "STC,PUR"
        db_entries = [entry.strip() for entry in cls.DB_DATABASES_RAW.split(',') if entry.strip()]
        
        # 共用參數
        common_params = {
            'auth_mode': cls.DB_AUTH_MODE,
            'user_id': cls.DB_USER_ID,
            'password': cls.DB_PASSWORD,
            'port': cls.DB_PORT,
            'timeout': cls.DB_TIMEOUT,
            'encrypt': cls.DB_ENCRYPT,
            'trust_server_certificate': cls.DB_TRUST_SERVER_CERTIFICATE,
            'application_name': cls.DB_APPLICATION_NAME,
            'driver': cls.DB_DRIVER
        }
        
        for entry in db_entries:
            if ':' in entry:
                # 格式: 簡稱:資料庫名稱
                alias, db_name = entry.split(':', 1)
                alias = alias.strip()
                db_name = db_name.strip()
            else:
                # 格式: 資料庫名稱（簡稱和資料庫名稱相同）
                alias = db_name = entry.strip()
            
            cls._databases[alias] = DatabaseConfig(
                alias=alias,
                database_name=db_name,
                server=cls.DB_SERVER,
                **common_params
            )
    
    @classmethod
    def get_database_config(cls, alias: str) -> Optional[DatabaseConfig]:
        """
        取得資料庫設定
        
        Args:
            alias: 資料庫簡稱 (例如: "STC", "PUR")
            
        Returns:
            DatabaseConfig 或 None
        """
        cls._parse_databases()
        return cls._databases.get(alias)

    @classmethod
    def build_database_config(cls, alias: str, server: str, database_name: str) -> DatabaseConfig:
        """
        依「呼叫端明確提供的 server + database_name」現組一個 DatabaseConfig，
        不查 .env 的 DB_SERVER／DB_DATABASES（每個系統的伺服器/資料庫不同，
        改由 spec-rag 的 catalog 逐系統標注、隨請求帶入）。

        連線共用參數（帳號/密碼/連線模式/連接埠/逾時/加密/驅動程式等）
        仍沿用 .env（跨系統共用，通常是同一組服務帳號）。

        Args:
            alias: 用於顯示/快取鍵的簡稱（通常是呼叫端的 system_id）
            server: 實際主機位址（不可為空）
            database_name: 實際資料庫名稱（不可為空）

        Raises:
            ValueError: server 或 database_name 為空時，不嘗試連線。
        """
        if not server or not database_name:
            raise ValueError(
                f"資料庫連線資訊不完整（alias={alias!r}, server={server!r}, "
                f"database={database_name!r}）：server/database 需由呼叫端（catalog）"
                f"提供，不會使用 .env 的 DB_SERVER/DB_DATABASES 作為 fallback。"
            )
        return DatabaseConfig(
            alias=alias,
            database_name=database_name,
            server=server,
            auth_mode=cls.DB_AUTH_MODE,
            user_id=cls.DB_USER_ID,
            password=cls.DB_PASSWORD,
            port=cls.DB_PORT,
            timeout=cls.DB_TIMEOUT,
            encrypt=cls.DB_ENCRYPT,
            trust_server_certificate=cls.DB_TRUST_SERVER_CERTIFICATE,
            application_name=cls.DB_APPLICATION_NAME,
            driver=cls.DB_DRIVER,
        )

    
    @classmethod
    def get_all_databases(cls) -> Dict[str, DatabaseConfig]:
        """取得所有資料庫設定"""
        cls._parse_databases()
        return cls._databases.copy()
    
    @classmethod
    def get_default_database(cls) -> Optional[DatabaseConfig]:
        """取得預設資料庫設定"""
        return cls.get_database_config(cls.DB_DEFAULT_DATABASE)
    
    @classmethod
    def validate(cls) -> List[str]:
        """驗證設定"""
        errors = []
        
        # 檢查資料庫設定
        cls._parse_databases()
        
        if not cls._databases:
            errors.append("未設定任何資料庫（DB_DATABASES）")
        
        # 檢查預設資料庫
        if cls.DB_DEFAULT_DATABASE not in cls._databases:
            errors.append(f"預設資料庫 '{cls.DB_DEFAULT_DATABASE}' 不存在於資料庫清單中")
        
        # 檢查 SQL Server 驗證
        if cls.DB_AUTH_MODE.lower() == 'sql':
            if not cls.DB_USER_ID:
                errors.append("SQL Server 驗證模式需要設定 DB_USER_ID")
            if not cls.DB_PASSWORD:
                errors.append("SQL Server 驗證模式需要設定 DB_PASSWORD")
        
        # 建立必要目錄
        Path(cls.OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
        Path(cls.LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
        
        return errors
    
    @classmethod
    def print_settings(cls):
        """顯示目前設定"""
        print("=" * 80)
        print("目前設定")
        print("=" * 80)
        print(f"環境: {cls.ENVIRONMENT}")
        
        print(f"\n資料庫伺服器:")
        print(f"  伺服器: {cls.DB_SERVER}:{cls.DB_PORT}")
        print(f"  驗證模式: {cls.DB_AUTH_MODE}")
        
        cls._parse_databases()
        print(f"\n設定的資料庫 ({len(cls._databases)}):")
        for alias, db_config in cls._databases.items():
            print(f"  {alias}:")
            print(f"    資料庫名稱: {db_config.database_name}")
            print(f"    連線字串: {db_config.get_safe_connection_string()}")
        
        print(f"\n預設資料庫: {cls.DB_DEFAULT_DATABASE}")
        
        print(f"\n專案:")
        print(f"  排除資料夾: {', '.join(cls.EXCLUDE_FOLDERS)}")
        
        print(f"\n輸出:")
        print(f"  輸出目錄: {cls.OUTPUT_DIR}")
        print(f"  產生圖表: {cls.GENERATE_CHARTS}")
        
        print("=" * 80)
    
    @classmethod
    def test_database_connections(cls):
        """測試所有資料庫連線"""
        print("\n" + "=" * 80)
        print("測試資料庫連線")
        print("=" * 80)
        
        cls._parse_databases()
        
        if not cls._databases:
            print("❌ 未設定任何資料庫")
            return
        
        import pyodbc
        
        for alias, db_config in cls._databases.items():
            print(f"\n測試 {alias} ({db_config.database_name})...")
            
            try:
                conn = pyodbc.connect(db_config.get_connection_string())
                cursor = conn.cursor()
                
                # 取得資料庫資訊
                cursor.execute("SELECT DB_NAME(), SUSER_SNAME(), @@VERSION")
                row = cursor.fetchone()
                
                print(f"  ✅ 連線成功")
                print(f"     資料庫: {row[0]}")
                print(f"     登入身分: {row[1]}")
                print(f"     SQL Server: {row[2].split(chr(10))[0]}")
                
                # 取得資料表數量
                cursor.execute("""
                    SELECT COUNT(*) 
                    FROM INFORMATION_SCHEMA.TABLES 
                    WHERE TABLE_TYPE = 'BASE TABLE'
                """)
                table_count = cursor.fetchone()[0]
                print(f"     資料表數: {table_count}")
                
                conn.close()
                
            except pyodbc.Error as e:
                print(f"  ❌ 連線失敗")
                print(f"     錯誤: {e}")
            except Exception as e:
                print(f"  ❌ 發生錯誤: {e}")
        
        print("\n" + "=" * 80)


# 全域設定實例
settings = Settings()


# ============================================
# 測試程式碼
# ============================================

if __name__ == "__main__":
    # 顯示設定
    settings.print_settings()
    
    # 驗證設定
    print("\n驗證設定:")
    errors = settings.validate()
    
    if errors:
        print("❌ 設定錯誤:")
        for error in errors:
            print(f"  - {error}")
    else:
        print("✅ 設定驗證通過")
    
    # 測試資料庫連線
    test_connections = input("\n是否測試資料庫連線？(y/n): ").strip().lower()
    if test_connections == 'y':
        settings.test_database_connections()