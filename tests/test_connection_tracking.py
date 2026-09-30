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

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from code_analyzer.connection_lookup import ConnectionLookup
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

requires_web_config_fixtures = pytest.mark.skipif(
    not (
        STC_WEB_CONFIG.exists()
        and TTPUR_WEB_CONFIG.exists()
        and RESPONSE_WEB_CONFIG.exists()
        and STC_GLOBAL_ASAX.exists()
    ),
    reason="local data/repos/System_Dept_1 fixture checkout is not present",
)


# ============================================================
# webconfig_connection_resolver：直接解析 Web.config 內容
# ============================================================


class TestParseWebConfigConnections:
    @requires_web_config_fixtures
    def test_appsettings_short_hostname_style(self):
        """STC 自己的 <appSettings key="error">——鎖住這張票要修的 bug 本身：
        查找鍵 "error" 與真正的資料庫 SysErrorRecord 完全不同。"""
        resolved = parse_web_config_file(STC_WEB_CONFIG)
        assert resolved.app_settings["error"] == ResolvedConnection(
            server="vmsystest07", database="SysErrorRecord"
        )

    @requires_web_config_fixtures
    def test_appsettings_key_can_coincidentally_equal_database_name(self):
        """STC 的 "STC" 鍵巧合等於資料庫名稱，但兩者仍必須各自從值解析出來，
        不能只是把查找鍵原樣搬過去當資料庫名稱。"""
        resolved = parse_web_config_file(STC_WEB_CONFIG)
        assert resolved.app_settings["STC"] == ResolvedConnection(
            server="vmsystest07", database="STC"
        )

    @requires_web_config_fixtures
    def test_connectionstrings_fqdn_style_with_named_instance(self):
        """TTPUR 的 <connectionStrings name="TTOA">——查找鍵 "TTOA" 與真正的
        資料庫 EFNETDB 完全不同；伺服器帶有具名執行個體後綴，維持未正規化
        （正規化是 02/03 號票的範圍）。"""
        resolved = parse_web_config_file(TTPUR_WEB_CONFIG)
        assert resolved.connection_strings["TTOA"] == ResolvedConnection(
            server="vmsystest08.topmost.com.tw\\vmsystest08_pdcs",
            database="EFNETDB",
        )

    @requires_web_config_fixtures
    def test_connectionstrings_active_entry_in_ttpur(self):
        """TTPUR 的 Web.config 裡 "ErrLog" 是一個活躍（未被註解）的
        <connectionStrings> entry，同樣解析成真正的資料庫 SysErrorRecord，
        而不是連線字串的 name "ErrLog"。"""
        resolved = parse_web_config_file(TTPUR_WEB_CONFIG)
        assert resolved.connection_strings["ErrLog"] == ResolvedConnection(
            server="vmsystest07.topmost.com.tw", database="SysErrorRecord"
        )

    @requires_web_config_fixtures
    def test_connectionstrings_active_entry_in_response(self):
        resolved = parse_web_config_file(RESPONSE_WEB_CONFIG)
        assert resolved.connection_strings["PUR-FAQ"] == ResolvedConnection(
            server="vmsystest07", database="Response"
        )

    @requires_web_config_fixtures
    def test_commented_out_entries_never_resolve(self):
        """Response 的 Web.config 裡 "PUR" 與 "ErrLog" 兩個 <connectionStrings>
        entry 都被整段註解掉（"ErrLog" 這個查找鍵在 TTPUR 是活躍的，但在
        Response 是死的）；真正的 XML 解析器讓它們在解析樹裡根本不是
        element，絕不能被誤判為有效連線。"""
        resolved = parse_web_config_file(RESPONSE_WEB_CONFIG)
        assert "PUR" not in resolved.connection_strings
        assert "ErrLog" not in resolved.connection_strings

    @requires_web_config_fixtures
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
# DBConnectionTracker：拿到 Connection Lookup 的 view 之後，程式碼裡的查找鍵解析成真正目標
# ============================================================


def _view_of(source_file: Path):
    """依掃描器的做法，向 Connection Lookup 要這個原始檔的 view。

    掃描根是原始檔所在的專案目錄，所以 view 來自那個目錄裡真的存在的
    Web.config 檔。"""
    return ConnectionLookup(source_file.parent).for_file(source_file)


class TestDBConnectionTrackerWithView:
    @staticmethod
    def _stc_view():
        return _view_of(STC_GLOBAL_ASAX)

    @staticmethod
    def _ttpur_view():
        return _view_of(TTPUR_WEB_CONFIG.parent / "Default.aspx.cs")

    @requires_web_config_fixtures
    def test_direct_sqlconnection_from_appsettings_resolves_real_database(self):
        """鎖住這張票要修的核心 bug：STC/Global.asax.cs 的
        `SqlConnection cn = new SqlConnection(ConfigurationManager.AppSettings["error"])`
        必須解析成真正的資料庫 SysErrorRecord，而不是把 key "error" 大寫成
        "ERROR" 當資料庫名稱。"""
        content = STC_GLOBAL_ASAX.read_text(encoding="utf-8")
        tracker = DBConnectionTracker(connections=self._stc_view())
        connections = tracker.analyze_connections(content)

        assert connections["cn"].database_name == "SysErrorRecord"
        assert connections["cn"].server == "vmsystest07"
        assert connections["cn"].connection_string_key == "error"

    @requires_web_config_fixtures
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
        tracker = DBConnectionTracker(connections=self._ttpur_view())
        connections = tracker.analyze_connections(content)

        assert connections["cn"].database_name == "EFNETDB"
        assert connections["cn"].server == "vmsystest08.topmost.com.tw\\vmsystest08_pdcs"

    @requires_web_config_fixtures
    def test_unresolvable_key_produces_no_connection_when_a_table_is_present(self):
        """一旦 view 有一張 Web.config 查找表，查找不到的鍵就不再退回猜測——維持
        unresolved，而不是捏造一個資料庫名稱。"""
        content = (
            'SqlConnection cn = new SqlConnection(ConfigurationManager.AppSettings["NotInWebConfig"]);'
        )
        tracker = DBConnectionTracker(connections=self._stc_view())
        connections = tracker.analyze_connections(content)
        assert "cn" not in connections

    def test_a_tracker_with_no_view_keeps_the_key_as_name_guess(self):
        """沒有拿到 view 的 tracker（例如單獨測試某個 regex 樣式）把查找鍵當成
        資料庫名稱，不會讓沒有專案情境的呼叫方直接失去現有功能。"""
        content = 'SQLFunc obj = new SQLFunc(ConfigurationManager.AppSettings["PUR"]);'
        tracker = DBConnectionTracker()
        connections = tracker.analyze_connections(content)
        assert connections["obj"].database_name == "PUR"
        assert connections["obj"].server is None

    @requires_web_config_fixtures
    def test_pattern4_flexible_heuristic_is_removed(self):
        """舊的「模式4」會把任何 `Type var = new Type(...)` 建構式裡 2-10 個
        字母的字串常數當成資料庫名稱（不論是否透過 ConfigurationManager 存
        取），現在完全移除，不能再誤判。"""
        content = 'SomeClass instance = new SomeClass(ConfigurationManager.AppSettings["error"]);'
        tracker = DBConnectionTracker(connections=self._stc_view())
        connections = tracker.analyze_connections(content)
        assert "instance" not in connections

    @requires_web_config_fixtures
    def test_sqlfunc_appsettings_resolves_through_web_config(self):
        content = 'SQLFunc obj = new SQLFunc(ConfigurationManager.AppSettings["error"]);'
        tracker = DBConnectionTracker(connections=self._stc_view())
        connections = tracker.analyze_connections(content)
        assert connections["obj"].database_name == "SysErrorRecord"
        assert connections["obj"].server == "vmsystest07"

    @requires_web_config_fixtures
    def test_sqlobject_connectionstrings_resolves_through_web_config(self):
        content = (
            'SQLObject obj = new SQLObject(ConfigurationManager.ConnectionStrings["TTOA"].ConnectionString);'
        )
        tracker = DBConnectionTracker(connections=self._ttpur_view())
        connections = tracker.analyze_connections(content)
        assert connections["obj"].database_name == "EFNETDB"
        assert connections["obj"].server == "vmsystest08.topmost.com.tw\\vmsystest08_pdcs"

    def test_appsettings_and_connectionstrings_keys_never_cross_resolve(
        self, tmp_path: Path
    ):
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
        (tmp_path / "Shop.csproj").write_text("<Project></Project>", encoding="utf-8")
        (tmp_path / "Web.config").write_text(content, encoding="utf-8")
        view = ConnectionLookup(tmp_path).for_file(tmp_path / "Order.aspx.cs")

        appsettings_code = 'SqlConnection cn = new SqlConnection(ConfigurationManager.AppSettings["PUR"]);'
        connectionstrings_code = (
            'SqlConnection cn = new SqlConnection(ConfigurationManager.ConnectionStrings["PUR"].ConnectionString);'
        )

        appsettings_connections = DBConnectionTracker(
            connections=view
        ).analyze_connections(appsettings_code)
        connectionstrings_connections = DBConnectionTracker(
            connections=view
        ).analyze_connections(connectionstrings_code)

        assert appsettings_connections["cn"].database_name == "DbFromAppSettings"
        assert appsettings_connections["cn"].server == "srvA"
        assert connectionstrings_connections["cn"].database_name == "DbFromConnectionStrings"
        assert connectionstrings_connections["cn"].server == "srvB"


# ============================================================
# End-to-end: ProjectScanner 掃描 STC/Global.asax.cs
# ============================================================


@requires_web_config_fixtures
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
        "declared_in": "STC/Web.config",
    }


def _write_web_application(directory: Path, *, database: str, server: str) -> Path:
    """寫出一個最小的 WebForms 專案：專案檔、Web.config、一個頁面的 code-behind。"""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{directory.name}.csproj").write_text(
        '<Project ToolsVersion="15.0"></Project>', encoding="utf-8"
    )
    (directory / "Web.config").write_text(
        "<configuration><connectionStrings>"
        f'<add name="Main" connectionString="Data Source={server};Initial Catalog={database}"/>'
        "</connectionStrings></configuration>",
        encoding="utf-8",
    )
    (directory / "Default.aspx").write_text(
        '<%@ Page Language="C#" CodeBehind="Default.aspx.cs" %>', encoding="utf-8"
    )
    source = directory / "Default.aspx.cs"
    source.write_text(
        "public class Default {\n"
        "    void Load() {\n"
        "        SqlConnection cn = new SqlConnection("
        'ConfigurationManager.ConnectionStrings["Main"].ConnectionString);\n'
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    return source


def test_project_scanner_gives_two_web_applications_under_one_scan_root_their_own_table(
    tmp_path: Path,
):
    """一張 Web.config 查找表涵蓋一個 Project Connection Scope（ADR-0018 的增
    補）：同一個掃描根底下的兩個 web application 用同一個鍵名，各自解析到自己
    的 Web.config 宣告的資料庫，不共用掃描根的那一張表。寫進 C# Scan Result
    的項目有 database、server 與宣告它的檔案 declared_in。"""
    shop_source = _write_web_application(tmp_path / "Shop", database="ShopDb", server="sql01")
    depot_source = _write_web_application(
        tmp_path / "Depot", database="DepotDb", server="sql02"
    )

    scanner = ProjectScanner(project_root=str(tmp_path), project_name="Sites")
    scan_result = ProjectScanResult(
        project_root=str(tmp_path),
        project_name="Sites",
        scan_time=datetime.now(),
    )
    scan_result = scanner.refresh_csharp_files(
        scan_result, [str(shop_source), str(depot_source)]
    )

    assert scan_result.connection_sources[str(shop_source.resolve())]["cn"] == {
        "database": "ShopDb",
        "server": "sql01",
        "declared_in": "Shop/Web.config",
    }
    assert scan_result.connection_sources[str(depot_source.resolve())]["cn"] == {
        "database": "DepotDb",
        "server": "sql02",
        "declared_in": "Depot/Web.config",
    }
    assert scan_result.unresolved_connections == {}


def test_project_scanner_writes_the_declaring_file_of_an_inherited_connection(
    tmp_path: Path,
):
    """一個子 web application 解析到它的 Parent Application 宣告的連線時，
    C# Scan Result 的連線來源帶 declared_in，指向宣告它的那份 Web.config；
    declared_in 相對於 repository clone，不含這台機器的目錄。掃描根只是
    repository 的一個子路徑。"""
    (tmp_path / ".git").mkdir()
    parent = tmp_path / "Site"
    parent.mkdir()
    (parent / "Site.csproj").write_text(
        "<Project><ProjectExtensions><VisualStudio><FlavorProperties>"
        "<WebProjectProperties><IISUrl>http://localhost/Site</IISUrl>"
        "</WebProjectProperties></FlavorProperties></VisualStudio>"
        "</ProjectExtensions></Project>",
        encoding="utf-8",
    )
    (parent / "Web.config").write_text(
        "<configuration><connectionStrings>"
        '<add name="Main" connectionString="Data Source=sql01;Initial Catalog=SiteDb"/>'
        "</connectionStrings></configuration>",
        encoding="utf-8",
    )
    child = tmp_path / "Site" / "Child"
    source = _write_web_application(child, database="ChildDb", server="sql02")
    (child / "Child.csproj").write_text(
        "<Project><ProjectExtensions><VisualStudio><FlavorProperties>"
        "<WebProjectProperties><IISUrl>http://localhost/Site/Child</IISUrl>"
        "</WebProjectProperties></FlavorProperties></VisualStudio>"
        "</ProjectExtensions></Project>",
        encoding="utf-8",
    )
    (child / "Web.config").write_text(
        "<configuration><connectionStrings>"
        '<add name="Other" connectionString="Data Source=sql02;Initial Catalog=OtherDb"/>'
        "</connectionStrings></configuration>",
        encoding="utf-8",
    )

    scanner = ProjectScanner(project_root=str(child), project_name="Child")
    scan_result = ProjectScanResult(
        project_root=str(child), project_name="Child", scan_time=datetime.now()
    )
    scan_result = scanner.refresh_csharp_files(scan_result, [str(source)])

    assert scan_result.connection_sources[str(source.resolve())]["cn"] == {
        "database": "SiteDb",
        "server": "sql01",
        "declared_in": "Site/Web.config",
    }


def test_project_scanner_writes_no_declaring_file_for_a_key_as_name_guess(tmp_path: Path):
    source = tmp_path / "Order.cs"
    source.write_text(
        "public class Order {\n"
        "    void Load() {\n"
        "        SqlConnection cn = new SqlConnection("
        'ConfigurationManager.ConnectionStrings["PUR"].ConnectionString);\n'
        "    }\n"
        "}\n",
        encoding="utf-8",
    )

    scanner = ProjectScanner(project_root=str(tmp_path), project_name="Bare")
    scan_result = ProjectScanResult(
        project_root=str(tmp_path), project_name="Bare", scan_time=datetime.now()
    )
    scan_result = scanner.refresh_csharp_files(scan_result, [str(source)])

    assert scan_result.connection_sources[str(source.resolve())]["cn"] == {
        "database": "PUR",
        "server": None,
        "declared_in": None,
    }


def test_project_scanner_records_an_ambiguous_parent_application_and_adds_no_connection_source(
    tmp_path: Path,
):
    """Two projects with one IIS URL make the Parent Application ambiguous. The
    unresolved connections of the C# Scan Result hold the reason. The
    key stays unresolved as before, so the rating of a call does not change."""
    (tmp_path / ".git").mkdir()
    web_project = (
        "<Project><ProjectExtensions><VisualStudio><FlavorProperties>"
        "<WebProjectProperties><IISUrl>{url}</IISUrl></WebProjectProperties>"
        "</FlavorProperties></VisualStudio></ProjectExtensions></Project>"
    )
    for name in ("SiteA", "SiteB"):
        (tmp_path / name).mkdir()
        (tmp_path / name / f"{name}.csproj").write_text(
            web_project.format(url="http://localhost/Site"), encoding="utf-8"
        )
    child = tmp_path / "Child"
    source = _write_web_application(child, database="ChildDb", server="sql02")
    (child / "Child.csproj").write_text(
        web_project.format(url="http://localhost/Site/Child"), encoding="utf-8"
    )
    (child / "Web.config").write_text(
        "<configuration><connectionStrings>"
        '<add name="Other" connectionString="Data Source=sql02;Initial Catalog=OtherDb"/>'
        "</connectionStrings></configuration>",
        encoding="utf-8",
    )

    scanner = ProjectScanner(project_root=str(child), project_name="Child")
    scan_result = ProjectScanResult(
        project_root=str(child), project_name="Child", scan_time=datetime.now()
    )
    scan_result = scanner.refresh_csharp_files(scan_result, [str(source)])

    file_key = str(source.resolve())
    assert [
        (entry["lookup_key"], entry["reason"])
        for entry in scan_result.unresolved_connections[file_key]
    ] == [("Main", "ambiguous_parent_application")]
    # The reason adds no connection source, so the rating of a call stays as it was.
    assert "cn" not in scan_result.connection_sources[file_key]
