# code_analyzer/db_connection_tracker.py
"""
資料庫連線追蹤器
用於識別程式碼中的多資料庫連線
"""

import re
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

from .webconfig_connection_resolver import WebConfigConnections, ResolvedConnection


@dataclass
class ConnectionInfo:
    """連線資訊"""
    variable_name: str          # 變數名稱 (例如: "obj", "objPUR", "_connetStrRead")
    database_name: str          # 資料庫名稱 (例如: "STC", "PUR", "QDmsDB")
    connection_string_key: str  # 連線字串的 key
    line_number: int            # 宣告行號
    scope: str = "class"        # 作用域 (class, method, local)
    server: Optional[str] = None  # 伺服器位址 (例如: "vmsystest07")；未知時為 None


class DBConnectionTracker:
    """資料庫連線追蹤器

    connection_resolver 是由 webconfig_connection_resolver.parse_web_config_connections()
    解析專案 Web.config 得到的 WebConfigConnections，內含 app_settings/
    connection_strings 兩張各自獨立的 {查找鍵: ResolvedConnection} 表。程式碼裡從
    ConfigurationManager.AppSettings["x"] 或
    ConfigurationManager.ConnectionStrings["x"].ConnectionString 擷取出的查找鍵
    "x"，一律配對到產生它的存取式，透過對應那張表解析成真正的
    {server, database}——絕不把 "x" 本身當成資料庫名稱來猜，也絕不讓兩個
    XML 命名空間的同名查找鍵互相混用（ADR-0008：<appSettings> 的 key 與
    <connectionStrings> 的 name 是兩個獨立的命名空間，即使字面上撞名也可能指向
    不同的連線）。

    沒有提供 connection_resolver（例如脫離專案情境、單純測試某個 regex 樣式）時，
    退回成把查找鍵當成資料庫名稱的舊行為，讓沒有 Web.config 可解析的呼叫方仍能
    得到可用（雖然較不精確）的結果；一旦提供了 connection_resolver，任何查找不到
    的鍵就一律視為無法解析（不再退回猜測），因為此時「這個鍵不在 Web.config 裡」
    本身就是一個明確的事實。
    """

    APP_SETTINGS = "app_settings"
    CONNECTION_STRINGS = "connection_strings"

    def __init__(self, connection_resolver: Optional[WebConfigConnections] = None):
        self.connections: Dict[str, ConnectionInfo] = {}
        self.connection_resolver: Optional[WebConfigConnections] = connection_resolver

    def _resolve(self, key: str, kind: str) -> Tuple[Optional[str], Optional[str]]:
        """把一個 Web.config 連線查找鍵解析成 (database, server)。

        kind 是 DBConnectionTracker.APP_SETTINGS 或 DBConnectionTracker.CONNECTION_STRINGS，
        決定去哪一張表查找——絕不讓 AppSettings 的 key 誤解析到 ConnectionStrings
        的同名 name，反之亦然。
        """
        if not self.connection_resolver:
            return key, None

        table: Dict[str, ResolvedConnection] = getattr(self.connection_resolver, kind)
        resolved = table.get(key)
        if resolved is None:
            folded = key.casefold()
            resolved = next(
                (
                    value
                    for candidate_key, value in table.items()
                    if candidate_key.casefold() == folded
                ),
                None,
            )
        if resolved is not None and resolved.database:
            return resolved.database, resolved.server
        return None, None

    def analyze_connections(self, content: str) -> Dict[str, ConnectionInfo]:
        """
        分析程式碼中的資料庫連線

        Returns:
            Dict[變數名稱, ConnectionInfo]
        """
        self.connections.clear()

        # 模式 1: WebForms/舊版模式
        # SQLFunc obj = new SQLFunc(ConfigurationManager.AppSettings["STC"]);
        self._extract_sqlfunc_connections(content)

        # 模式 2: MVC/新版模式 - Constructor 注入
        # _connetStrRead = _config.GetConnectionString("QDmsDB");
        self._extract_mvc_connections(content)

        # 模式 3: 直接 SqlConnection
        # using (SqlConnection cn = new SqlConnection(_connetStrRead))
        # using (SqlConnection cn = new SqlConnection(ConfigurationManager.AppSettings["error"]))
        # using (SqlConnection cn = new SqlConnection(ConfigurationManager.ConnectionStrings["MyDB"].ConnectionString))
        self._extract_sqlconnection_declarations(content)

        return self.connections

    def _extract_sqlfunc_connections(self, content: str):
        """
        提取 SQLFunc 類型的連線
        格式: SQLFunc obj = new SQLFunc(ConfigurationManager.AppSettings["STC"]);
        """
        # 模式 1: 完整格式
        pattern1 = r'SQLFunc\s+(\w+)\s*=\s*new\s+SQLFunc\s*\(\s*ConfigurationManager\.AppSettings\s*\[\s*["\']([^"\']+)["\']\s*\]\s*\)'
        matches1 = re.finditer(pattern1, content, re.IGNORECASE)

        for match in matches1:
            var_name = match.group(1)
            key = match.group(2)
            line_num = content[:match.start()].count('\n') + 1
            database_name, server = self._resolve(key, self.APP_SETTINGS)
            if not database_name:
                continue

            self.connections[var_name] = ConnectionInfo(
                variable_name=var_name,
                database_name=database_name,
                connection_string_key=key,
                line_number=line_num,
                scope="class",
                server=server,
            )

        # 模式 2: 簡化格式（可能有不同的類別名稱）
        pattern2 = r'(\w+Func|\w+Helper|\w+Manager)\s+(\w+)\s*=\s*new\s+\1\s*\(\s*[^)]*["\']([^"\']+)["\']\s*[^)]*\)'
        matches2 = re.finditer(pattern2, content, re.IGNORECASE)

        for match in matches2:
            class_name = match.group(1)
            var_name = match.group(2)
            db_name = match.group(3)
            line_num = content[:match.start()].count('\n') + 1

            if var_name not in self.connections:
                self.connections[var_name] = ConnectionInfo(
                    variable_name=var_name,
                    database_name=db_name,
                    connection_string_key=db_name,
                    line_number=line_num,
                    scope="class"
                )

        # 模式 3: SQLObject/自訂類別 (ConnectionStrings)
        # SQLObject obj = new SQLObject(ConfigurationManager.ConnectionStrings["PUR"].ConnectionString);
        # 支援任何類別名稱，不限於變數名稱與類別名稱相同
        pattern3 = r'(\w+)\s+(\w+)\s*=\s*new\s+(\w+)\s*\(\s*ConfigurationManager\.ConnectionStrings\s*\[\s*["\']([^"\']+)["\']\s*\]\.ConnectionString\s*\)'
        matches3 = re.finditer(pattern3, content, re.IGNORECASE)

        for match in matches3:
            type_name = match.group(1)    # 類型名稱（例如：SQLObject）
            var_name = match.group(2)     # 變數名稱（例如：obj）
            class_name = match.group(3)   # 建構子類別名稱
            key = match.group(4)          # 連線字串名稱（例如：PUR）
            line_num = content[:match.start()].count('\n') + 1
            database_name, server = self._resolve(key, self.CONNECTION_STRINGS)

            if var_name not in self.connections and database_name:
                self.connections[var_name] = ConnectionInfo(
                    variable_name=var_name,
                    database_name=database_name,
                    connection_string_key=key,
                    line_number=line_num,
                    scope="class",
                    server=server,
                )

    def _extract_mvc_connections(self, content: str):
        """
        提取 MVC 模式的連線
        格式: _connetStrRead = _config.GetConnectionString("QDmsDB");
        """
        # 模式 1: GetConnectionString
        pattern1 = r'(\w+)\s*=\s*\w+\.GetConnectionString\s*\(\s*["\']([^"\']+)["\']\s*\)'
        matches1 = re.finditer(pattern1, content, re.IGNORECASE)

        for match in matches1:
            var_name = match.group(1)
            db_name = match.group(2)
            line_num = content[:match.start()].count('\n') + 1

            self.connections[var_name] = ConnectionInfo(
                variable_name=var_name,
                database_name=db_name,
                connection_string_key=db_name,
                line_number=line_num,
                scope="class"
            )

        # 模式 2: ConfigurationManager.ConnectionStrings
        pattern2 = r'(\w+)\s*=\s*ConfigurationManager\.ConnectionStrings\s*\[\s*["\']([^"\']+)["\']\s*\]\.ConnectionString'
        matches2 = re.finditer(pattern2, content, re.IGNORECASE)

        for match in matches2:
            var_name = match.group(1)
            key = match.group(2)
            line_num = content[:match.start()].count('\n') + 1
            database_name, server = self._resolve(key, self.CONNECTION_STRINGS)

            if var_name not in self.connections and database_name:
                self.connections[var_name] = ConnectionInfo(
                    variable_name=var_name,
                    database_name=database_name,
                    connection_string_key=key,
                    line_number=line_num,
                    scope="class",
                    server=server,
                )

        # 模式 3: DbContext 注入（ASP.NET Core MVC）
        # private readonly TOPCSCYContext _TOPCSCY_db;
        # 從類別名稱推斷資料庫名稱
        pattern3 = r'(?:private\s+)?(?:readonly\s+)?(\w+Context)\s+(\w+)\s*;'
        matches3 = re.finditer(pattern3, content, re.IGNORECASE)

        for match in matches3:
            context_type = match.group(1)  # 例如: TOPCSCYContext
            var_name = match.group(2)      # 例如: _TOPCSCY_db

            # 從 Context 類型推斷資料庫名稱
            # TOPCSCYContext -> TOPCSCY
            # ApplicationDbContext -> ApplicationDb
            db_name = context_type.replace('Context', '').replace('Db', '')

            line_num = content[:match.start()].count('\n') + 1

            if var_name not in self.connections:
                self.connections[var_name] = ConnectionInfo(
                    variable_name=var_name,
                    database_name=db_name,
                    connection_string_key=db_name,
                    line_number=line_num,
                    scope="class"
                )

    def _extract_sqlconnection_declarations(self, content: str):
        """
        提取 SqlConnection 宣告
        格式:
          using (SqlConnection cn = new SqlConnection(_connetStrRead))
          SqlConnection cn = new SqlConnection(ConfigurationManager.AppSettings["error"]);
          SqlConnection cn = new SqlConnection(ConfigurationManager.ConnectionStrings["TTOA"].ConnectionString);
        """
        # 直接從 AppSettings 建構：SqlConnection 建構參數本身就是 ConfigurationManager 存取式，
        # 不經過中介變數。這是 STC/Global.asax.cs 這類「行內直接開連線」寫法唯一會匹配到的樣式。
        pattern_appsettings = (
            r'SqlConnection\s+(\w+)\s*=\s*new\s+SqlConnection\s*\(\s*'
            r'ConfigurationManager\.AppSettings\s*\[\s*["\']([^"\']+)["\']\s*\]\s*\)'
        )
        for match in re.finditer(pattern_appsettings, content, re.IGNORECASE):
            var_name = match.group(1)
            key = match.group(2)
            line_num = content[:match.start()].count('\n') + 1
            database_name, server = self._resolve(key, self.APP_SETTINGS)
            if database_name:
                self.connections[var_name] = ConnectionInfo(
                    variable_name=var_name,
                    database_name=database_name,
                    connection_string_key=key,
                    line_number=line_num,
                    scope="local",
                    server=server,
                )

        # 直接從 ConnectionStrings 建構（同上，行內直接開連線，不經中介變數）
        pattern_connectionstrings = (
            r'SqlConnection\s+(\w+)\s*=\s*new\s+SqlConnection\s*\(\s*'
            r'ConfigurationManager\.ConnectionStrings\s*\[\s*["\']([^"\']+)["\']\s*\]\.ConnectionString\s*\)'
        )
        for match in re.finditer(pattern_connectionstrings, content, re.IGNORECASE):
            var_name = match.group(1)
            key = match.group(2)
            line_num = content[:match.start()].count('\n') + 1
            database_name, server = self._resolve(key, self.CONNECTION_STRINGS)
            if database_name:
                self.connections[var_name] = ConnectionInfo(
                    variable_name=var_name,
                    database_name=database_name,
                    connection_string_key=key,
                    line_number=line_num,
                    scope="local",
                    server=server,
                )

        # 找出所有 SqlConnection(source_var) 宣告，source_var 是先前已追蹤過的變數
        pattern = r'SqlConnection\s+(\w+)\s*=\s*new\s+SqlConnection\s*\(\s*(\w+)\s*\)'
        matches = re.finditer(pattern, content, re.IGNORECASE)

        for match in matches:
            connection_var = match.group(1)  # cn
            source_var = match.group(2)      # _connetStrRead

            # 如果 source_var 已經在追蹤清單中，建立對應
            if source_var in self.connections:
                line_num = content[:match.start()].count('\n') + 1

                # 複製來源連線資訊
                source_info = self.connections[source_var]
                self.connections[connection_var] = ConnectionInfo(
                    variable_name=connection_var,
                    database_name=source_info.database_name,
                    connection_string_key=source_info.connection_string_key,
                    line_number=line_num,
                    scope="local",
                    server=source_info.server,
                )

    def get_database_source(self, variable_name: str) -> Optional[str]:
        """
        根據變數名稱取得資料庫來源

        Args:
            variable_name: 變數名稱 (例如: "obj", "objPUR", "cn")

        Returns:
            資料庫名稱 (例如: "STC", "PUR", "QDmsDB") 或 None
        """
        if variable_name in self.connections:
            return self.connections[variable_name].database_name
        return None

    def get_all_databases(self) -> List[str]:
        """取得所有使用的資料庫"""
        return list(set(conn.database_name for conn in self.connections.values()))

    def print_connections(self):
        """顯示所有連線資訊"""
        print("=" * 60)
        print("資料庫連線追蹤")
        print("=" * 60)

        if not self.connections:
            print("未找到資料庫連線")
            return

        for var_name, conn in self.connections.items():
            print(f"\n變數: {var_name}")
            print(f"  資料庫: {conn.database_name}")
            print(f"  伺服器: {conn.server}")
            print(f"  連線字串 Key: {conn.connection_string_key}")
            print(f"  宣告行號: {conn.line_number}")
            print(f"  作用域: {conn.scope}")

        print(f"\n使用的資料庫 ({len(self.get_all_databases())}):")
        for db in self.get_all_databases():
            print(f"  - {db}")

        print("=" * 60)


# ============================================
# 測試程式碼
# ============================================

if __name__ == "__main__":
    test_code = """
    using System;
    using System.Configuration;

    namespace TestApp
    {
        public class DataAccess
        {
            SQLFunc obj = new SQLFunc(ConfigurationManager.AppSettings["STC"]);
            SQLFunc objPUR = new SQLFunc(ConfigurationManager.AppSettings["PUR"]);

            public void TestMethod()
            {
                var result1 = obj.CreateReader("SELECT * FROM Users");
                var result2 = objPUR.ExeProcRead("spGetCompany", par);
            }
        }

        public class MvcController
        {
            private readonly string _connetStrWrite;
            private readonly string _connetStrRead;

            public MvcController(IConfiguration config)
            {
                _connetStrWrite = config.GetConnectionString("DmsDB");
                _connetStrRead = config.GetConnectionString("QDmsDB");
            }

            public void GetData()
            {
                using (SqlConnection cn = new SqlConnection(_connetStrRead))
                {
                    using (SqlCommand cmd = new SqlCommand("spGetUsers", cn))
                    {
                        // ...
                    }
                }
            }
        }
    }
    """

    tracker = DBConnectionTracker()
    tracker.analyze_connections(test_code)
    tracker.print_connections()
