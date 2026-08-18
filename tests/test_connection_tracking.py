"""測試 Web.config 連線字串解析與 DBConnectionTracker 的整合。

涵蓋 01-web-config-connection-string-resolution 這張票要修的核心 bug：
ConfigurationManager.AppSettings["error"] 應該解析成真正的資料庫
SysErrorRecord，而不是把查找鍵 "error" 大寫成 "ERROR" 當資料庫名稱（舊的
「模式4」heuristic 的行為）；ConfigurationManager.ConnectionStrings["TTOA"]
.ConnectionString 應該解析成真正的資料庫 EFNETDB，而不是連線字串的 name
"TTOA"。
"""

import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from code_analyzer.db_connection_tracker import DBConnectionTracker
from code_analyzer.project_scanner import ProjectScanner, ProjectScanResult
from code_analyzer.webconfig_connection_resolver import (
    ResolvedConnection,
    parse_web_config_connections,
    parse_web_config_file,
)

STC_WEB_CONFIG = PROJECT_ROOT / "data/repos/System_Dept_1/STC/STC/Web.config"
TTPUR_WEB_CONFIG = PROJECT_ROOT / "data/repos/System_Dept_1/Y-DOCs/TTPUR/Web.config"
RESPONSE_WEB_CONFIG = PROJECT_ROOT / "data/repos/System_Dept_1/Y-DOCs/Response/Web.config"
STC_GLOBAL_ASAX = PROJECT_ROOT / "data/repos/System_Dept_1/STC/STC/Global.asax.cs"


# ============================================================
# webconfig_connection_resolver：直接解析 Web.config 內容
# ============================================================


class TestParseWebConfigConnections:
    def test_appsettings_short_hostname_style(self):
        """STC 自己的 <appSettings key="error">——鎖住這張票要修的 bug 本身：
        查找鍵 "error" 與真正的資料庫 SysErrorRecord 完全不同。"""
        resolved = parse_web_config_file(STC_WEB_CONFIG)
        assert resolved.app_settings["error"] == ResolvedConnection(
            server="vmsystest07", database="SysErrorRecord"
        )

    def test_appsettings_key_can_coincidentally_equal_database_name(self):
        """STC 的 "STC" 鍵巧合等於資料庫名稱，但兩者仍必須各自從值解析出來，
        不能只是把查找鍵原樣搬過去當資料庫名稱。"""
        resolved = parse_web_config_file(STC_WEB_CONFIG)
        assert resolved.app_settings["STC"] == ResolvedConnection(
            server="vmsystest07", database="STC"
        )

    def test_connectionstrings_fqdn_style_with_named_instance(self):
        """TTPUR 的 <connectionStrings name="TTOA">——查找鍵 "TTOA" 與真正的
        資料庫 EFNETDB 完全不同；伺服器帶有具名執行個體後綴，維持未正規化
        （正規化是 02/03 號票的範圍）。"""
        resolved = parse_web_config_file(TTPUR_WEB_CONFIG)
        assert resolved.connection_strings["TTOA"] == ResolvedConnection(
            server="vmsystest08.topmost.com.tw\\vmsystest08_pdcs",
            database="EFNETDB",
        )

    def test_connectionstrings_active_entry_in_ttpur(self):
        """TTPUR 的 Web.config 裡 "ErrLog" 是一個活躍（未被註解）的
        <connectionStrings> entry，同樣解析成真正的資料庫 SysErrorRecord，
        而不是連線字串的 name "ErrLog"。"""
        resolved = parse_web_config_file(TTPUR_WEB_CONFIG)
        assert resolved.connection_strings["ErrLog"] == ResolvedConnection(
            server="vmsystest07.topmost.com.tw", database="SysErrorRecord"
        )

    def test_connectionstrings_active_entry_in_response(self):
        resolved = parse_web_config_file(RESPONSE_WEB_CONFIG)
        assert resolved.connection_strings["PUR-FAQ"] == ResolvedConnection(
            server="vmsystest07", database="Response"
        )

    def test_commented_out_entries_never_resolve(self):
        """Response 的 Web.config 裡 "PUR" 與 "ErrLog" 兩個 <connectionStrings>
        entry 都被整段註解掉（"ErrLog" 這個查找鍵在 TTPUR 是活躍的，但在
        Response 是死的）；真正的 XML 解析器讓它們在解析樹裡根本不是
        element，絕不能被誤判為有效連線。"""
        resolved = parse_web_config_file(RESPONSE_WEB_CONFIG)
        assert "PUR" not in resolved.connection_strings
        assert "ErrLog" not in resolved.connection_strings

    def test_entries_without_a_database_are_omitted(self):
        """沒有資料庫可解析的 appSettings entry（純郵件伺服器、路徑設定等）
        不該出現在結果裡。"""
        resolved = parse_web_config_file(STC_WEB_CONFIG)
        assert "MailServer" not in resolved.app_settings
        assert "SysAdminMail" not in resolved.app_settings

    def test_data_source_synonym(self):
        content = """<configuration>
          <connectionStrings>
            <add name="Foo" connectionString="Data Source=srv1;Initial Catalog=FooDb;User ID=u;Password=p"/>
          </connectionStrings>
        </configuration>"""
        resolved = parse_web_config_connections(content)
        assert resolved.connection_strings["Foo"] == ResolvedConnection(
            server="srv1", database="FooDb"
        )

    def test_address_and_addr_synonyms(self):
        content = """<configuration>
          <appSettings>
            <add key="AddressKey" value="Address=srvA;Database=DbA"/>
            <add key="AddrKey" value="Addr=srvB;Database=DbB"/>
          </appSettings>
        </configuration>"""
        resolved = parse_web_config_connections(content)
        assert resolved.app_settings["AddressKey"] == ResolvedConnection(
            server="srvA", database="DbA"
        )
        assert resolved.app_settings["AddrKey"] == ResolvedConnection(
            server="srvB", database="DbB"
        )

    def test_malformed_xml_returns_empty(self):
        resolved = parse_web_config_connections("<configuration><unterminated>")
        assert not resolved
        assert resolved.app_settings == {}
        assert resolved.connection_strings == {}

    def test_appsettings_and_connectionstrings_are_independent_namespaces(self):
        """ADR-0008：<appSettings> 的 key 與 <connectionStrings> 的 name 是兩個
        獨立的 XML 命名空間，即使字面上撞名也可能指向不同的連線——絕不能合併
        成一張平面表格，讓後解析的那個命名空間悄悄覆蓋掉前一個。"""
        content = """<configuration>
          <appSettings>
            <add key="PUR" value="server=srvA;database=DbFromAppSettings"/>
          </appSettings>
          <connectionStrings>
            <add name="PUR" connectionString="Data Source=srvB;Initial Catalog=DbFromConnectionStrings"/>
          </connectionStrings>
        </configuration>"""
        resolved = parse_web_config_connections(content)
        assert resolved.app_settings["PUR"] == ResolvedConnection(
            server="srvA", database="DbFromAppSettings"
        )
        assert resolved.connection_strings["PUR"] == ResolvedConnection(
            server="srvB", database="DbFromConnectionStrings"
        )


# ============================================================
# DBConnectionTracker：接上 resolver 之後，程式碼裡的查找鍵解析成真正目標
# ============================================================


class TestDBConnectionTrackerWithResolver:
    @staticmethod
    def _stc_resolver():
        return parse_web_config_file(STC_WEB_CONFIG)

    def test_direct_sqlconnection_from_appsettings_resolves_real_database(self):
        """鎖住這張票要修的核心 bug：STC/Global.asax.cs 的
        `SqlConnection cn = new SqlConnection(ConfigurationManager.AppSettings["error"])`
        必須解析成真正的資料庫 SysErrorRecord，而不是把 key "error" 大寫成
        "ERROR" 當資料庫名稱。"""
        content = STC_GLOBAL_ASAX.read_text(encoding="utf-8")
        tracker = DBConnectionTracker(connection_resolver=self._stc_resolver())
        connections = tracker.analyze_connections(content)

        assert connections["cn"].database_name == "SysErrorRecord"
        assert connections["cn"].server == "vmsystest07"
        assert connections["cn"].connection_string_key == "error"

    def test_direct_sqlconnection_from_connectionstrings_resolves_real_database(self):
        """TTOA -> EFNETDB，不是連線字串的 name "TTOA"。"""
        content = (
            "using System.Data.SqlClient;\n"
            "using System.Configuration;\n"
            "public class Foo {\n"
            "    void Bar() {\n"
            '        SqlConnection cn = new SqlConnection(ConfigurationManager.ConnectionStrings["TTOA"].ConnectionString);\n'
            "    }\n"
            "}\n"
        )
        resolver = parse_web_config_file(TTPUR_WEB_CONFIG)
        tracker = DBConnectionTracker(connection_resolver=resolver)
        connections = tracker.analyze_connections(content)

        assert connections["cn"].database_name == "EFNETDB"
        assert connections["cn"].server == "vmsystest08.topmost.com.tw\\vmsystest08_pdcs"

    def test_unresolvable_key_produces_no_connection_when_resolver_present(self):
        """一旦提供了 connection_resolver，查找不到的鍵就不再退回猜測——維持
        unresolved，而不是捏造一個資料庫名稱。"""
        content = (
            'SqlConnection cn = new SqlConnection(ConfigurationManager.AppSettings["NotInWebConfig"]);'
        )
        tracker = DBConnectionTracker(connection_resolver=self._stc_resolver())
        connections = tracker.analyze_connections(content)
        assert "cn" not in connections

    def test_no_resolver_falls_back_to_key_as_database(self):
        """沒有 Web.config 情境時（例如單獨測試某個 regex 樣式），退回舊行為，
        不會讓沒有專案情境的呼叫方直接失去現有功能。"""
        content = 'SQLFunc obj = new SQLFunc(ConfigurationManager.AppSettings["PUR"]);'
        tracker = DBConnectionTracker()
        connections = tracker.analyze_connections(content)
        assert connections["obj"].database_name == "PUR"
        assert connections["obj"].server is None

    def test_pattern4_flexible_heuristic_is_removed(self):
        """舊的「模式4」會把任何 `Type var = new Type(...)` 建構式裡 2-10 個
        字母的字串常數當成資料庫名稱（不論是否透過 ConfigurationManager 存
        取），現在完全移除，不能再誤判。"""
        content = 'SomeClass instance = new SomeClass(ConfigurationManager.AppSettings["error"]);'
        tracker = DBConnectionTracker(connection_resolver=self._stc_resolver())
        connections = tracker.analyze_connections(content)
        assert "instance" not in connections

    def test_sqlfunc_appsettings_resolves_through_web_config(self):
        content = 'SQLFunc obj = new SQLFunc(ConfigurationManager.AppSettings["error"]);'
        tracker = DBConnectionTracker(connection_resolver=self._stc_resolver())
        connections = tracker.analyze_connections(content)
        assert connections["obj"].database_name == "SysErrorRecord"
        assert connections["obj"].server == "vmsystest07"

    def test_sqlobject_connectionstrings_resolves_through_web_config(self):
        content = (
            'SQLObject obj = new SQLObject(ConfigurationManager.ConnectionStrings["TTOA"].ConnectionString);'
        )
        resolver = parse_web_config_file(TTPUR_WEB_CONFIG)
        tracker = DBConnectionTracker(connection_resolver=resolver)
        connections = tracker.analyze_connections(content)
        assert connections["obj"].database_name == "EFNETDB"
        assert connections["obj"].server == "vmsystest08.topmost.com.tw\\vmsystest08_pdcs"

    def test_appsettings_and_connectionstrings_keys_never_cross_resolve(self):
        """ADR-0008：一個 `AppSettings["PUR"]` 存取式只能查 app_settings 表，
        絕不能誤中 connection_strings 表裡同名但目標不同的 "PUR" entry
        （反之亦然）。"""
        content = """<configuration>
          <appSettings>
            <add key="PUR" value="server=srvA;database=DbFromAppSettings"/>
          </appSettings>
          <connectionStrings>
            <add name="PUR" connectionString="Data Source=srvB;Initial Catalog=DbFromConnectionStrings"/>
          </connectionStrings>
        </configuration>"""
        resolver = parse_web_config_connections(content)

        appsettings_code = 'SqlConnection cn = new SqlConnection(ConfigurationManager.AppSettings["PUR"]);'
        connectionstrings_code = (
            'SqlConnection cn = new SqlConnection(ConfigurationManager.ConnectionStrings["PUR"].ConnectionString);'
        )

        appsettings_connections = DBConnectionTracker(
            connection_resolver=resolver
        ).analyze_connections(appsettings_code)
        connectionstrings_connections = DBConnectionTracker(
            connection_resolver=resolver
        ).analyze_connections(connectionstrings_code)

        assert appsettings_connections["cn"].database_name == "DbFromAppSettings"
        assert appsettings_connections["cn"].server == "srvA"
        assert connectionstrings_connections["cn"].database_name == "DbFromConnectionStrings"
        assert connectionstrings_connections["cn"].server == "srvB"


# ============================================================
# End-to-end: ProjectScanner 掃描 STC/Global.asax.cs
# ============================================================


def test_project_scanner_resolves_stc_global_asax_connection_source():
    """驗收條件：掃描 STC/Global.asax.cs 應該讓 connection_sources 裡 "cn"
    這個項目 database=SysErrorRecord, server=vmsystest07（未正規化——正規化
    是 02/03 號票的範圍）。"""
    project_root = STC_GLOBAL_ASAX.parent
    scanner = ProjectScanner(project_root=str(project_root), project_name="STC")
    scan_result = ProjectScanResult(
        project_root=str(project_root),
        project_name="STC",
        scan_time=datetime.now(),
    )
    scan_result = scanner.refresh_csharp_files(scan_result, [str(STC_GLOBAL_ASAX)])

    file_key = str(STC_GLOBAL_ASAX.resolve())
    assert scan_result.connection_sources[file_key]["cn"] == {
        "database": "SysErrorRecord",
        "server": "vmsystest07",
    }
