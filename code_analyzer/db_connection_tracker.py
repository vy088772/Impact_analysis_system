# code_analyzer/db_connection_tracker.py
"""
資料庫連線追蹤器
用於識別程式碼中的多資料庫連線
"""

import re
from typing import Any, Dict, List, Optional, Tuple, Union
from dataclasses import dataclass, field, replace

from .project_connection_scope import (
    CONNECTION_KEY_NOT_IN_PROJECT_SCOPE,
    CONTEXT_TYPE_NOT_REGISTERED,
    FIELD_HELD_CONNECTION_NOT_TRACED,
    ProjectConnectionScope,
    ROOT_CONFIGURATION_NAMESPACE,
)
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


@dataclass(frozen=True)
class UnresolvedConnection:
    """一個解析不出 {server, database} 的連線，以及它為什麼解析不出來。

    一個比例數字本身分不出「解析變好了」與「只是變得有自信」，所以每一個解
    不出來的連線都必須指名理由。沉默的空結果正是這份程式碼存在的目的所要防
    止的失敗模式。
    """

    variable_name: str
    lookup_key: str
    namespace: str
    reason: str
    line_number: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "variable_name": self.variable_name,
            "lookup_key": self.lookup_key,
            "namespace": self.namespace,
            "reason": self.reason,
            "line_number": self.line_number,
        }


# 一份設定檔解析出來的連線查找表：Web.config 的，或 appsettings.json 的。
# 兩者有相同的 app_settings/connection_strings 兩張表，所以查找的程式碼只有一份。
ConnectionLookupTables = Union[WebConfigConnections, ProjectConnectionScope]


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

    connection_resolver 也可以是一個 ProjectConnectionScope（ASP.NET Core 的
    appsettings.json 查找表，ADR-0018）。它與 WebConfigConnections 有相同的
    app_settings/connection_strings 兩張表，所以查找的程式碼只有一份；它另外帶著
    組合根裡的 DbContext 註冊與 Configuration 根命名空間的鍵名，讓解析不出來的
    連線說得出理由。Web.config 的解析路徑不因此改變任何一步。
    """

    APP_SETTINGS = "app_settings"
    CONNECTION_STRINGS = "connection_strings"
    # Configuration 根命名空間（IConfiguration["Key"] 與
    # IConfiguration.GetValue<string>("Key") 讀到的那一層）。它不是連線查找表，
    # 所以這個 kind 永遠不查任何一張表——兩個命名空間不合併。
    ROOT_CONFIGURATION = "root_configuration"
    DB_CONTEXT_TYPE = "db_context_type"
    # 一個 Field-Held Connection：連線來自呼叫端類別的一個欄位，而不是來自任何
    # 一張查找表。這個 kind 記的是「那個欄位追不回一個查找鍵」，所以它也不查表。
    FIELD_HELD_CONNECTION = "field_held_connection"

    def __init__(self, connection_resolver: Optional[ConnectionLookupTables] = None):
        self.connections: Dict[str, ConnectionInfo] = {}
        self.connection_resolver: Optional[ConnectionLookupTables] = connection_resolver
        self.unresolved: List[UnresolvedConnection] = []

    def _project_scope(self) -> Optional[ProjectConnectionScope]:
        """回傳目前的 ProjectConnectionScope，若解析器是 Web.config 的則回傳 None。

        以型別分辨，不以「有沒有某個屬性」分辨：屬性改名會讓每一個 Core 專案
        無聲地退回 Web.config 路徑，也就是退回這張票要消滅的猜測。
        """
        resolver = self.connection_resolver
        return resolver if isinstance(resolver, ProjectConnectionScope) else None

    def _record_unresolved(
        self, variable_name: str, key: str, namespace: str, reason: str, line_number: int
    ) -> None:
        self.unresolved.append(
            UnresolvedConnection(
                variable_name=variable_name,
                lookup_key=key,
                namespace=namespace,
                reason=reason,
                line_number=line_number,
            )
        )

    @staticmethod
    def _lookup(
        table: Dict[str, ResolvedConnection], key: str
    ) -> Tuple[Optional[str], Optional[str]]:
        """在一張連線查找表裡找一個鍵，大小寫不敏感。"""
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

    def _resolve(
        self,
        key: str,
        kind: str,
        variable_name: str = "",
        line_number: int = 0,
    ) -> Tuple[Optional[str], Optional[str]]:
        """把一個連線查找鍵解析成 (database, server)。

        kind 是 DBConnectionTracker.APP_SETTINGS 或 DBConnectionTracker.CONNECTION_STRINGS，
        決定去哪一張表查找——絕不讓 AppSettings 的 key 誤解析到 ConnectionStrings
        的同名 name，反之亦然。kind 是 ROOT_CONFIGURATION 時不查任何一張表。
        """
        scope = self._project_scope()
        if scope is not None:
            return self._resolve_in_scope(scope, key, kind, variable_name, line_number)

        if not self.connection_resolver:
            return key, None
        return self._lookup(getattr(self.connection_resolver, kind), key)

    def _resolve_in_scope(
        self,
        scope: ProjectConnectionScope,
        key: str,
        kind: str,
        variable_name: str,
        line_number: int,
    ) -> Tuple[Optional[str], Optional[str]]:
        """在一個 Project Connection Scope 裡解析，解不出來時說出理由。"""
        if scope.unresolved_reason:
            self._record_unresolved(
                variable_name, key, kind, scope.unresolved_reason, line_number
            )
            return None, None

        if kind == self.ROOT_CONFIGURATION:
            self._record_unresolved(
                variable_name, key, kind, ROOT_CONFIGURATION_NAMESPACE, line_number
            )
            return None, None

        database, server = self._lookup(getattr(scope, kind), key)
        if database:
            return database, server

        reason = (
            ROOT_CONFIGURATION_NAMESPACE
            if key in scope.root_configuration_keys
            else CONNECTION_KEY_NOT_IN_PROJECT_SCOPE
        )
        self._record_unresolved(variable_name, key, kind, reason, line_number)
        return None, None

    def _resolve_context_type(
        self, context_type: str, variable_name: str, line_number: int
    ) -> Tuple[Optional[str], Optional[str], str]:
        """把一個資料庫內容型別解析成 (database, server, 連線查找鍵)。

        型別名稱本身不是資料庫名稱，就像連線查找鍵不是資料庫名稱一樣
        （ADR-0008）。答案只來自組合根裡的註冊。
        """
        scope = self._project_scope()
        if scope is None:
            return None, None, ""
        if scope.unresolved_reason:
            self._record_unresolved(
                variable_name,
                context_type,
                self.DB_CONTEXT_TYPE,
                scope.unresolved_reason,
                line_number,
            )
            return None, None, ""

        key = scope.context_connection_keys.get(context_type)
        if not key:
            self._record_unresolved(
                variable_name,
                context_type,
                self.DB_CONTEXT_TYPE,
                CONTEXT_TYPE_NOT_REGISTERED,
                line_number,
            )
            return None, None, ""

        database, server = self._resolve(
            key, self.CONNECTION_STRINGS, variable_name, line_number
        )
        return database, server, key

    def analyze_connections(self, content: str) -> Dict[str, ConnectionInfo]:
        """
        分析程式碼中的資料庫連線

        Returns:
            Dict[變數名稱, ConnectionInfo]
        """
        self.connections.clear()
        self.unresolved.clear()

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
            database_name, server = self._resolve(key, self.APP_SETTINGS, var_name, line_num)
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
            database_name, server = self._resolve(key, self.CONNECTION_STRINGS, var_name, line_num)

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
        # 有 Project Connection Scope 時，鍵一律透過 appsettings.json 的
        # ConnectionStrings 區段解析成真正的 {server, database}；沒有 scope 時
        # 維持既有行為（把鍵當資料庫名稱），Web.config 路徑一步都不變。
        pattern1 = r'(\w+)\s*=\s*\w+\.GetConnectionString\s*\(\s*["\']([^"\']+)["\']\s*\)'
        matches1 = re.finditer(pattern1, content, re.IGNORECASE)

        for match in matches1:
            var_name = match.group(1)
            key = match.group(2)
            line_num = content[:match.start()].count('\n') + 1

            if self._project_scope() is None:
                self.connections[var_name] = ConnectionInfo(
                    variable_name=var_name,
                    database_name=key,
                    connection_string_key=key,
                    line_number=line_num,
                    scope="class"
                )
                continue

            database_name, server = self._resolve(
                key, self.CONNECTION_STRINGS, var_name, line_num
            )
            if database_name:
                self.connections[var_name] = ConnectionInfo(
                    variable_name=var_name,
                    database_name=database_name,
                    connection_string_key=key,
                    line_number=line_num,
                    scope="class",
                    server=server,
                )

        # 模式 2: ConfigurationManager.ConnectionStrings
        pattern2 = r'(\w+)\s*=\s*ConfigurationManager\.ConnectionStrings\s*\[\s*["\']([^"\']+)["\']\s*\]\.ConnectionString'
        matches2 = re.finditer(pattern2, content, re.IGNORECASE)

        for match in matches2:
            var_name = match.group(1)
            key = match.group(2)
            line_num = content[:match.start()].count('\n') + 1
            database_name, server = self._resolve(key, self.CONNECTION_STRINGS, var_name, line_num)

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
        self._extract_db_context_connections(content)

        # 模式 4: Configuration 根命名空間讀取
        self._extract_root_configuration_reads(content)

    # 一個內容型別的宣告：欄位、建構子參數、主要建構子參數都算。接收者的
    # *宣告型別*決定這次呼叫開哪個資料庫，所以同一個類別可以持有兩個不同的
    # 內容型別，各自解析到各自的資料庫。
    _CONTEXT_DECLARATION = r'\b{context_type}\s+(@?\w+)\s*(?=[;,)={{])'

    def _extract_db_context_connections(self, content: str):
        """把資料庫內容型別的接收者，解析成它在組合根裡註冊的那個連線。

        答案只來自組合根的註冊。從型別名稱推斷資料庫（`PayrollContext` ->
        `Payroll`）是 ADR-0008 指名要換掉、不是延伸的捷徑，所以沒有
        Project Connection Scope 時不猜，什麼都不做。
        """
        scope = self._project_scope()
        if scope is None:
            return

        self._report_unregistered_context_types(content, scope)

        for context_type in sorted(scope.context_connection_keys):
            pattern = self._CONTEXT_DECLARATION.format(
                context_type=re.escape(context_type)
            )
            for match in re.finditer(pattern, content):
                var_name = match.group(1)
                line_num = content[:match.start()].count('\n') + 1
                if var_name in self.connections:
                    continue
                database_name, server, key = self._resolve_context_type(
                    context_type, var_name, line_num
                )
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

    # 框架自己的環境物件，名字結尾是 Context 但一個資料庫都不開。把它們一併報
    # 成「組合根沒有註冊」只會製造雜訊，讓真正的缺口被淹沒。
    #
    # 下半段的六個名字，是實測五個儲存庫掃出來的：這條規則在它們身上報了二十
    # 四次，二十四次都是這些框架型別，沒有一次是真的——每一個宣告出來的資料庫
    # 內容型別，組合根都註冊了。
    #
    # 一份名單擋不住下一個儲存庫帶來的第七個框架型別。真正的分辨依據是「這個
    # 型別有沒有被宣告成資料庫內容型別」，而不是它叫什麼名字；換成那條規則是
    # 另一張票的事，這裡先讓已知的雜訊消失。
    _AMBIENT_CONTEXT_TYPES = frozenset(
        {
            "DbContext",
            "HttpContext",
            "ActionContext",
            "ControllerContext",
            "ViewContext",
            "PageContext",
            "SynchronizationContext",
            "SecurityContext",
            "ModelBindingContext",
            "ValidationContext",
            # ASP.NET Core MVC 的過濾器管線
            "ActionExecutingContext",
            "ActionExecutedContext",
            "AuthorizationFilterContext",
            # ASP.NET Core MVC 的用戶端驗證與標籤協助程式
            "ClientModelValidationContext",
            "TagHelperContext",
            # System.DirectoryServices.AccountManagement：目錄，不是資料庫
            "PrincipalContext",
        }
    )

    _ANY_CONTEXT_DECLARATION = r'\b(\w+Context)\s+(@?\w+)\s*(?=[;,)={])'

    def _report_unregistered_context_types(
        self, content: str, scope: ProjectConnectionScope
    ) -> None:
        """為組合根沒有註冊的資料庫內容型別留下理由。

        沒有這一步，一個沒被註冊的內容型別就只是安靜地不出現在結果裡——正是
        這份程式碼要防止的沉默空結果。
        """
        for match in re.finditer(self._ANY_CONTEXT_DECLARATION, content):
            context_type = match.group(1)
            var_name = match.group(2)
            if context_type in self._AMBIENT_CONTEXT_TYPES:
                continue
            if context_type in scope.context_connection_keys:
                continue
            line_num = content[:match.start()].count('\n') + 1
            self._resolve_context_type(context_type, var_name, line_num)

    # 讀 Configuration 根命名空間的兩種寫法。兩種都是「從根往下找一個鍵」，
    # 不是讀 ConnectionStrings 區段，所以走同一條規則。
    # 1. 索引子：_config["Key"] / Configuration["Key"] / builder.Configuration["Key"]
    # 2. GetValue：config.GetValue<string>("Key")——實測的 ETR 儲存庫的五個
    #    控制器都這樣讀連線字串，而它的連線字串只存在於 ConnectionStrings 區
    #    段，所以那五個讀取在執行期拿到的是 null。
    # 兩種寫法共用同一個接收者前綴，寫一次以免兩邊漂開。
    _CONFIGURATION_RECEIVER = r'(\w+)\s*=\s*(?:\w+\.)*\w*[Cc]onfig\w*\s*'
    _ROOT_CONFIGURATION_READS = (
        _CONFIGURATION_RECEIVER + r'\[\s*["\']([^"\']+)["\']\s*\]',
        _CONFIGURATION_RECEIVER
        + r'\.\s*GetValue\s*<[^>]*>\s*\(\s*["\']([^"\']+)["\']\s*\)',
    )

    def _names_a_connection(self, key: str) -> bool:
        """這個根命名空間的鍵，讀起來是不是在讀一條連線字串。

        讀根命名空間的程式碼絕大多數在讀日誌層級、功能開關這類與資料庫無關的
        設定。把它們全部記成「解析不出來的連線」只會淹沒真正的缺口，所以只有
        鍵名在連線字串區段裡、或它自己的值就是一條連線字串時才回報。
        """
        scope = self._project_scope()
        if scope is None:
            return False
        folded = key.casefold()
        return any(
            name.casefold() == folded
            for name in (*scope.root_connection_keys, *scope.connection_strings)
        )

    def _extract_root_configuration_reads(self, content: str):
        """處理從 Configuration 根命名空間讀出來的連線鍵。

        `Configuration["Key"]` 與 `Configuration.GetValue<string>("Key")` 讀的
        都是根命名空間，`GetConnectionString("Key")` 讀的是 ConnectionStrings
        區段——兩個命名空間不合併（ADR-0008），所以根命名空間的讀取永遠解析
        不到連線，並說出這就是理由。
        `Configuration["ConnectionStrings:Key"]` 帶著區段前綴，是同一張連線查
        找表的另一種寫法，照常解析。
        """
        if self._project_scope() is None:
            return

        for pattern in self._ROOT_CONFIGURATION_READS:
            for match in re.finditer(pattern, content):
                var_name = match.group(1)
                raw_key = match.group(2)
                line_num = content[:match.start()].count('\n') + 1
                if var_name in self.connections:
                    continue

                section, separator, key = raw_key.partition(":")
                if separator and section.casefold() == "connectionstrings":
                    database_name, server = self._resolve(
                        key, self.CONNECTION_STRINGS, var_name, line_num
                    )
                    if database_name:
                        self.connections[var_name] = ConnectionInfo(
                            variable_name=var_name,
                            database_name=database_name,
                            connection_string_key=key,
                            line_number=line_num,
                            scope="class",
                            server=server,
                        )
                    continue

                if not self._names_a_connection(raw_key):
                    continue
                self._resolve(raw_key, self.ROOT_CONFIGURATION, var_name, line_num)

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
            database_name, server = self._resolve(key, self.APP_SETTINGS, var_name, line_num)
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
            database_name, server = self._resolve(key, self.CONNECTION_STRINGS, var_name, line_num)
            if database_name:
                self.connections[var_name] = ConnectionInfo(
                    variable_name=var_name,
                    database_name=database_name,
                    connection_string_key=key,
                    line_number=line_num,
                    scope="local",
                    server=server,
                )

        # 找出所有 SqlConnection(source_var) 宣告。source_var 是持有連線字串的
        # 欄位或區域變數——實測的 ETR 儲存庫三十五處原始 ADO.NET 呼叫全部是這
        # 個形狀。呼叫端記錄的連線變數是 connection_var，不是那個欄位，所以解
        # 析結果與解析不出來的理由都必須掛在 connection_var 上。
        pattern = r'SqlConnection\s+(\w+)\s*=\s*new\s+SqlConnection\s*\(\s*(\w+)\s*\)'
        matches = re.finditer(pattern, content, re.IGNORECASE)

        for match in matches:
            connection_var = match.group(1)  # cn
            source_var = match.group(2)      # _connetStrRead
            line_num = content[:match.start()].count('\n') + 1

            # 如果 source_var 已經在追蹤清單中，建立對應
            if source_var in self.connections:
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
                continue

            # 不因為同名的連線變數已經在別處解析出來就跳過。同一個檔案的兩個
            # 方法可以各有一個 `con`，一個解析得出、一個解析不出來；跳過會讓
            # 後者變成沉默的空結果，而它正是一個必須說出理由的呼叫。
            self._record_unresolved_field_held_connection(
                connection_var, source_var, line_num
            )

    def _record_unresolved_field_held_connection(
        self, connection_var: str, source_var: str, line_number: int
    ) -> None:
        """為一個解析不出來的 Field-Held Connection 留下理由。

        沒有這一步，這個呼叫就只是安靜地不出現在結果裡——正是這份程式碼要防
        止的沉默空結果。理由分兩種：持有連線字串的那個欄位自己已經說過為什麼
        解析不出來（例如它讀的是 Configuration 根命名空間），就原樣沿用它的
        理由，讓讀的人一眼看到根因；那個欄位的值根本追不回任何查找鍵（例如它
        來自一次方法呼叫），就記 FIELD_HELD_CONNECTION_NOT_TRACED，並把欄位名
        放進 lookup_key——那一欄的意義本來就由 namespace 決定，資料庫內容型別
        的形狀放的也是型別名而不是查找鍵。

        只在有 Project Connection Scope 時記錄。Web.config 的解析路徑從來不
        產生理由，在那裡開始產生會改變既有系統的輸出，而這張票談的是 Core
        系統（ADR-0018）。
        """
        if self._project_scope() is None:
            return

        source_reason = self._nearest_unresolved(source_var, line_number)
        if source_reason is not None:
            self.unresolved.append(
                replace(
                    source_reason,
                    variable_name=connection_var,
                    line_number=line_number,
                )
            )
            return

        self._record_unresolved(
            connection_var,
            source_var,
            self.FIELD_HELD_CONNECTION,
            FIELD_HELD_CONNECTION_NOT_TRACED,
            line_number,
        )

    def _nearest_unresolved(
        self, variable_name: str, line_number: int
    ) -> Optional[UnresolvedConnection]:
        """離某一行最近的那個同名 unresolved 紀錄，沒有就回傳 None。

        一個檔案可以放兩個類別，兩個類別可以各有一個同名的連線欄位而值不同。
        取「檔案裡第一個同名紀錄」會讓第二個類別繼承第一個類別的理由；取最近
        的那一個，答案至少來自同一段程式碼。
        """
        candidates = [
            entry for entry in self.unresolved if entry.variable_name == variable_name
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda entry: abs(entry.line_number - line_number))

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
