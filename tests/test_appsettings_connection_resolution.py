"""測試 appsettings.json 連線解析，以及它的 Project Connection Scope（ADR-0018）。

涵蓋 08-appsettings-connection-resolution-scoped-to-the-project 這張票：一個
ASP.NET Core 系統的 Database Invocation 必須解析得出 Resolved Connection
Source。在這之前沒有任何 Core 系統解析得出來，因為解析只讀 Web.config，而沒
有一個 Core 系統有 Web.config。

每一個斷言「解析不出來」的測試，同時斷言它說出了什麼理由——這份程式碼要防
止的失敗模式是沉默的空結果，不是當掉。
"""

import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from code_analyzer.appsettings_connection_resolver import (
    parse_appsettings_connections,
    parse_appsettings_file,
)
from code_analyzer.connection_string_value import ResolvedConnection
from code_analyzer.db_connection_tracker import DBConnectionTracker
from code_analyzer.project_connection_scope import (
    CONTEXT_TYPE_NOT_REGISTERED,
    NO_PROJECT_CONNECTION_SCOPE,
    ProjectConnectionScopeIndex,
    RECEIVER_DECLARATION_UNRESOLVED,
    ROOT_CONFIGURATION_NAMESPACE,
)
from code_analyzer.project_scanner import ProjectScanner, ProjectScanResult
from code_analyzer.webconfig_connection_resolver import parse_web_config_file

STC_WEB_CONFIG = PROJECT_ROOT / "data/repos/System_Dept_1/STC/STC/Web.config"
STC_GLOBAL_ASAX = PROJECT_ROOT / "data/repos/System_Dept_1/STC/STC/Global.asax.cs"

requires_web_config_fixtures = pytest.mark.skipif(
    not (STC_WEB_CONFIG.exists() and STC_GLOBAL_ASAX.exists()),
    reason="local data/repos/System_Dept_1 fixture checkout is not present",
)


# ============================================================
# 測試用的最小專案：依房規寫進暫存目錄，沒有 fixtures 目錄
# ============================================================


def _write_project(
    directory: Path,
    *,
    connection_strings: dict,
    composition_root: str = "",
    root_configuration: dict = None,
    environment: dict = None,
) -> Path:
    """寫出一個最小的 ASP.NET Core 專案，回傳它的目錄。"""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{directory.name}.csproj").write_text(
        '<Project Sdk="Microsoft.NET.Sdk.Web"></Project>', encoding="utf-8"
    )
    document = {"ConnectionStrings": dict(connection_strings)}
    document.update(root_configuration or {})
    (directory / "appsettings.json").write_text(
        json.dumps(document, indent=2), encoding="utf-8"
    )
    if composition_root:
        (directory / "Program.cs").write_text(composition_root, encoding="utf-8")
    if environment:
        (directory / "appsettings.Production.json").write_text(
            json.dumps({"ConnectionStrings": dict(environment)}, indent=2),
            encoding="utf-8",
        )
    return directory


def _write_source(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _track(
    index: ProjectConnectionScopeIndex,
    source_file: Path,
    content: str,
    *,
    invoked: frozenset = frozenset(),
):
    """依掃描器的做法，用這個檔案所屬的查找表解析它的連線。

    `invoked` 模擬 `ProjectScanner` 從 db_invocations 讀出來、餵給 tracker 的
    「這個檔案裡曾經真的發生過呼叫的連線運算式」集合（ticket 17）。
    """
    tracker = DBConnectionTracker(connection_resolver=index.scope_for(source_file))
    tracker.invoked_connection_expressions = set(invoked)
    tracker.analyze_connections(content)
    return tracker


def _composition_root(*registrations: tuple) -> str:
    lines = [
        "var builder = WebApplication.CreateBuilder(args);",
    ]
    for context_type, lookup_key in registrations:
        lines.append(
            f"builder.Services.AddDbContext<{context_type}>(options =>\n"
            f'    options.UseSqlServer(builder.Configuration.GetConnectionString("{lookup_key}")));'
        )
    lines.append("var app = builder.Build();")
    return "\n".join(lines)


# ============================================================
# appsettings_connection_resolver：直接解析設定檔內容
# ============================================================


class TestParseAppSettingsConnections:
    def test_named_connection_string_resolves_to_a_server_and_database(self):
        """查找鍵不是資料庫名稱（ADR-0008）——真正的 {server, database} 只能
        從連線字串的值解析出來。"""
        content = json.dumps(
            {
                "ConnectionStrings": {
                    "eHRIS": "Server=vmsystest05.topmost.com.tw;Database=eHRISDb;User ID=u;Password=p"
                }
            }
        )
        resolved = parse_appsettings_connections(content)
        assert resolved.connection_strings["eHRIS"] == ResolvedConnection(
            server="vmsystest05.topmost.com.tw", database="eHRISDb"
        )

    def test_a_settings_file_carrying_a_byte_order_mark_parses(self, tmp_path: Path):
        """真實的設定檔會帶位元組順序記號，解析必須照樣成立。"""
        settings_file = tmp_path / "appsettings.json"
        settings_file.write_text(
            json.dumps(
                {"ConnectionStrings": {"Payroll": "Server=srvA;Database=PayrollDb"}}
            ),
            encoding="utf-8-sig",
        )
        assert settings_file.read_bytes().startswith(b"\xef\xbb\xbf")

        resolved = parse_appsettings_file(settings_file)
        assert resolved.connection_strings["Payroll"] == ResolvedConnection(
            server="srvA", database="PayrollDb"
        )

    def test_a_settings_file_carrying_comments_parses(self):
        """`//` 與 `/* */` 註解在 JSON 標準裡不合法，但 .NET 的設定讀取器接受
        它們，真實檔案也真的這樣寫。字串常值裡的 `//`（例如網址）不是註解，
        不能被剝掉。"""
        content = """{
          // 正式環境的薪資資料庫
          "ConnectionStrings": {
            "Payroll": "Server=srvA;Database=PayrollDb", // 行尾註解
            /* 這一條先停用
            "Ledger": "Server=srvB;Database=LedgerDb",
            */
            "Docs": "Server=srvC;Database=DocsDb"
          },
          "ServiceUrl": "https://example.test/api",
        }"""
        resolved = parse_appsettings_connections(content)
        assert resolved.connection_strings["Payroll"] == ResolvedConnection(
            server="srvA", database="PayrollDb"
        )
        assert resolved.connection_strings["Docs"] == ResolvedConnection(
            server="srvC", database="DocsDb"
        )
        assert "Ledger" not in resolved.connection_strings
        assert "ServiceUrl" in resolved.root_configuration_keys


# ============================================================
# 組合根註冊的內容型別，依接收者的宣告型別解析
# ============================================================


class TestDbContextResolution:
    def test_a_registered_context_type_resolves_calls_made_on_that_type(
        self, tmp_path: Path
    ):
        """內容型別在組合根被註冊到一個具名連線字串上，使用它的類別自己不說
        出開哪個資料庫。"""
        project = _write_project(
            tmp_path / "Payroll",
            connection_strings={"Payroll": "Server=srvA;Database=PayrollDb"},
            composition_root=_composition_root(("PayrollContext", "Payroll")),
        )
        source = _write_source(
            project / "Controllers" / "PayrollController.cs",
            "public class PayrollController {\n"
            "    private readonly PayrollContext _payroll;\n"
            "    public PayrollController(PayrollContext payroll) { _payroll = payroll; }\n"
            "}\n",
        )

        tracker = _track(ProjectConnectionScopeIndex(tmp_path), source, source.read_text(encoding="utf-8"))

        assert tracker.connections["_payroll"].database_name == "PayrollDb"
        assert tracker.connections["_payroll"].server == "srvA"

    def test_two_context_types_in_one_class_resolve_by_the_receiver(
        self, tmp_path: Path
    ):
        """一個類別持有兩個不同的內容型別時，每一次呼叫由接收者的*宣告型別*
        決定開哪個資料庫，不是由類別決定。"""
        project = _write_project(
            tmp_path / "Portal",
            connection_strings={
                "Payroll": "Server=srvA;Database=PayrollDb",
                "Ledger": "Server=srvB;Database=LedgerDb",
            },
            composition_root=_composition_root(
                ("PayrollContext", "Payroll"), ("LedgerContext", "Ledger")
            ),
        )
        source = _write_source(
            project / "Services" / "ReportService.cs",
            "public class ReportService {\n"
            "    private readonly PayrollContext _payroll;\n"
            "    private readonly LedgerContext _ledger;\n"
            "}\n",
        )

        tracker = _track(ProjectConnectionScopeIndex(tmp_path), source, source.read_text(encoding="utf-8"))

        assert tracker.connections["_payroll"].database_name == "PayrollDb"
        assert tracker.connections["_payroll"].server == "srvA"
        assert tracker.connections["_ledger"].database_name == "LedgerDb"
        assert tracker.connections["_ledger"].server == "srvB"

    def test_an_unregistered_context_type_resolves_to_nothing_with_a_reason(
        self, tmp_path: Path
    ):
        """型別名稱不是資料庫名稱——組合根沒有註冊它時，維持 unresolved，而
        不是把 `LedgerContext` 猜成 `Ledger`。理由只在這個接收者真的被拿去
        做過一次 Database Invocation 時才出現（ticket 17）。"""
        project = _write_project(
            tmp_path / "Portal",
            connection_strings={"Payroll": "Server=srvA;Database=PayrollDb"},
            composition_root=_composition_root(("PayrollContext", "Payroll")),
        )
        source = _write_source(
            project / "Services" / "LedgerService.cs",
            "public class LedgerService {\n"
            "    private readonly LedgerContext _ledger;\n"
            "    public void Run() { _ledger.Ledgers.ToList(); }\n"
            "}\n",
        )

        tracker = _track(
            ProjectConnectionScopeIndex(tmp_path),
            source,
            source.read_text(encoding="utf-8"),
            invoked=frozenset({"_ledger"}),
        )

        assert "_ledger" not in tracker.connections
        assert [entry.reason for entry in tracker.unresolved] == [
            CONTEXT_TYPE_NOT_REGISTERED
        ]

    def test_an_unregistered_context_type_never_invoked_is_not_reported(
        self, tmp_path: Path
    ):
        """一個沒註冊的內容型別只是宣告出來、從沒被拿去做過一次 Database
        Invocation 時，這裡問不到它——理由來自呼叫本身，不是宣告本身
        （ticket 17）。"""
        project = _write_project(
            tmp_path / "Portal",
            connection_strings={"Payroll": "Server=srvA;Database=PayrollDb"},
            composition_root=_composition_root(("PayrollContext", "Payroll")),
        )
        source = _write_source(
            project / "Services" / "LedgerService.cs",
            "public class LedgerService {\n"
            "    private readonly LedgerContext _ledger;\n"
            "}\n",
        )

        tracker = _track(
            ProjectConnectionScopeIndex(tmp_path), source, source.read_text(encoding="utf-8")
        )

        assert tracker.connections == {}
        assert tracker.unresolved == []

    def test_an_invoked_receiver_whose_declared_type_cannot_be_read_names_its_own_reason(
        self, tmp_path: Path
    ):
        """一次呼叫發生在一個這個檔案完全找不到宣告的接收者上——連它是不是
        資料庫內容型別都讀不到。這跟「型別讀得到、只是沒註冊」是不同的缺
        口，不能共用 `context_type_not_registered`（ticket 17）。"""
        project = _write_project(
            tmp_path / "Portal",
            connection_strings={"Payroll": "Server=srvA;Database=PayrollDb"},
            composition_root=_composition_root(("PayrollContext", "Payroll")),
        )
        source = _write_source(
            project / "Services" / "LedgerService.cs",
            "public partial class LedgerService {\n"
            "    public void Run() { _ledger.Ledgers.ToList(); }\n"
            "}\n",
        )

        tracker = _track(
            ProjectConnectionScopeIndex(tmp_path),
            source,
            source.read_text(encoding="utf-8"),
            invoked=frozenset({"_ledger"}),
        )

        assert "_ledger" not in tracker.connections
        assert [entry.reason for entry in tracker.unresolved] == [
            RECEIVER_DECLARATION_UNRESOLVED
        ]

    def test_a_framework_context_type_is_not_reported_as_unregistered(
        self, tmp_path: Path
    ):
        """名字結尾是 Context 的框架型別不是資料庫內容型別，但這裡不需要靠
        認得它們的名字才能不誤報——ASP.NET 的過濾器與標籤協助程式、Active
        Directory 的目錄內容從來不會被拿去做一次 Database Invocation，所以
        即使它們的宣告就在這個檔案裡，理由只問曾經被呼叫過的接收者，天生問
        不到它們（ticket 17；實測的五個儲存庫裡，舊的名字比對規則報了二十四
        次，沒有一次是真的）。"""
        project = _write_project(
            tmp_path / "Portal",
            connection_strings={"Payroll": "Server=srvA;Database=PayrollDb"},
            composition_root=_composition_root(("PayrollContext", "Payroll")),
        )
        source = _write_source(
            project / "Filters" / "AuditFilter.cs",
            "public class AuditFilter : IActionFilter, IClientModelValidator {\n"
            "    public void OnActionExecuting(ActionExecutingContext context) { }\n"
            "    public void OnActionExecuted(ActionExecutedContext context) { }\n"
            "    public void OnAuthorization(AuthorizationFilterContext context) { }\n"
            "    public void AddValidation(ClientModelValidationContext context) { }\n"
            "    public override void Process(TagHelperContext context) { }\n"
            "    public void Lookup() {\n"
            "        using (PrincipalContext directory = new PrincipalContext(ContextType.Domain)) { }\n"
            "    }\n"
            "}\n",
        )

        tracker = _track(
            ProjectConnectionScopeIndex(tmp_path),
            source,
            source.read_text(encoding="utf-8"),
        )

        assert tracker.connections == {}
        assert tracker.unresolved == []


# ============================================================
# Project Connection Scope：一張表涵蓋一個專案檔目錄（ADR-0018）
# ============================================================


class TestProjectConnectionScope:
    def test_a_source_file_belongs_to_the_nearest_project_file_above_it(
        self, tmp_path: Path
    ):
        """一個巢狀專案裡的原始檔屬於巢狀的那個專案，不是外層那個。"""
        _write_project(
            tmp_path / "Outer",
            connection_strings={"Main": "Server=srvOuter;Database=OuterDb"},
        )
        inner = _write_project(
            tmp_path / "Outer" / "Inner",
            connection_strings={"Main": "Server=srvInner;Database=InnerDb"},
        )
        source = _write_source(
            inner / "Data" / "Repository.cs",
            'string connection = configuration.GetConnectionString("Main");\n',
        )

        tracker = _track(ProjectConnectionScopeIndex(tmp_path), source, source.read_text(encoding="utf-8"))

        assert tracker.connections["connection"].database_name == "InnerDb"
        assert tracker.connections["connection"].server == "srvInner"

    def test_two_projects_using_one_key_name_resolve_to_their_own_database(
        self, tmp_path: Path
    ):
        """實測的 EnterpriseApi 儲存庫有六個專案這樣做：同一個鍵名在兩個專案
        裡開兩台不同伺服器上的兩個不同資料庫。合併成一張表會讓其中一邊任意
        勝出，輸的那一邊解析到它從來沒開過的資料庫。"""
        api = _write_project(
            tmp_path / "EnterpriseApi",
            connection_strings={
                "eHRIS": "Server=vmsystest08;Database=YMTHRPortal"
            },
        )
        runner = _write_project(
            tmp_path / "TaskRunner",
            connection_strings={
                "eHRIS": "Server=vmsystest05.topmost.com.tw;Database=eHRIS"
            },
        )
        call = 'string connection = configuration.GetConnectionString("eHRIS");\n'
        api_source = _write_source(api / "Data" / "HrRepository.cs", call)
        runner_source = _write_source(runner / "Jobs" / "HrJob.cs", call)

        index = ProjectConnectionScopeIndex(tmp_path)
        api_tracker = _track(index, api_source, call)
        runner_tracker = _track(index, runner_source, call)

        assert api_tracker.connections["connection"].database_name == "YMTHRPortal"
        assert api_tracker.connections["connection"].server == "vmsystest08"
        assert runner_tracker.connections["connection"].database_name == "eHRIS"
        assert (
            runner_tracker.connections["connection"].server
            == "vmsystest05.topmost.com.tw"
        )
        assert api_tracker.unresolved == []
        assert runner_tracker.unresolved == []

    def test_a_source_file_with_no_project_file_above_it_states_a_reason(
        self, tmp_path: Path
    ):
        """上方沒有專案檔的原始檔沒有表，它不借用鄰居的表——並說出理由。"""
        _write_project(
            tmp_path / "Payroll",
            connection_strings={"Payroll": "Server=srvA;Database=PayrollDb"},
        )
        content = 'string connection = configuration.GetConnectionString("Payroll");\n'
        source = _write_source(tmp_path / "loose" / "Orphan.cs", content)

        tracker = _track(ProjectConnectionScopeIndex(tmp_path), source, content)

        assert tracker.connections == {}
        assert [entry.reason for entry in tracker.unresolved] == [
            NO_PROJECT_CONNECTION_SCOPE
        ]

    def test_a_root_configuration_key_resolves_to_nothing_and_says_why(
        self, tmp_path: Path
    ):
        """根命名空間與 ConnectionStrings 區段是兩個命名空間，不合併
        （ADR-0008）。即使兩邊都有 "Payroll" 這個鍵，讀根命名空間也不會拿到
        連線字串區段裡的那一條。"""
        project = _write_project(
            tmp_path / "Payroll",
            connection_strings={"Payroll": "Server=srvA;Database=PayrollDb"},
            root_configuration={"Payroll": "Server=srvB;Database=RootPayrollDb"},
        )
        content = 'string connection = _configuration["Payroll"];\n'
        source = _write_source(project / "Data" / "Repository.cs", content)

        tracker = _track(ProjectConnectionScopeIndex(tmp_path), source, content)

        assert "connection" not in tracker.connections
        assert [entry.reason for entry in tracker.unresolved] == [
            ROOT_CONFIGURATION_NAMESPACE
        ]

    def test_a_root_configuration_read_that_names_no_connection_is_not_reported(
        self, tmp_path: Path
    ):
        """讀根命名空間的程式碼絕大多數在讀日誌層級、功能開關這類與資料庫無關
        的設定。把它們全部記成「解析不出來的連線」只會淹沒真正的缺口。"""
        project = _write_project(
            tmp_path / "Payroll",
            connection_strings={"Payroll": "Server=srvA;Database=PayrollDb"},
            root_configuration={"LogLevel": "Warning"},
        )
        content = 'string level = _configuration["LogLevel"];\n'
        source = _write_source(project / "Startup" / "Logging.cs", content)

        tracker = _track(ProjectConnectionScopeIndex(tmp_path), source, content)

        assert tracker.connections == {}
        assert tracker.unresolved == []

    def test_a_connection_strings_section_read_through_the_indexer_resolves(
        self, tmp_path: Path
    ):
        """`Configuration["ConnectionStrings:Key"]` 帶著區段前綴，讀的是連線查
        找表，不是根命名空間。"""
        project = _write_project(
            tmp_path / "Payroll",
            connection_strings={"Payroll": "Server=srvA;Database=PayrollDb"},
        )
        content = 'string connection = _configuration["ConnectionStrings:Payroll"];\n'
        source = _write_source(project / "Data" / "Repository.cs", content)

        tracker = _track(ProjectConnectionScopeIndex(tmp_path), source, content)

        assert tracker.connections["connection"].database_name == "PayrollDb"
        assert tracker.connections["connection"].server == "srvA"

    def test_an_environment_settings_override_is_reported_and_not_applied(
        self, tmp_path: Path
    ):
        """哪一個環境會跑起來是部署時才知道的事。套用其中一個等於猜測；完全
        不提則讓「正式環境開的是另一個資料庫」這件事消失。所以只回報。"""
        project = _write_project(
            tmp_path / "Payroll",
            connection_strings={"Payroll": "Server=srvA;Database=PayrollDb"},
            environment={"Payroll": "Server=srvB;Database=PayrollProdDb"},
        )
        content = 'string connection = configuration.GetConnectionString("Payroll");\n'
        source = _write_source(project / "Data" / "Repository.cs", content)

        index = ProjectConnectionScopeIndex(tmp_path)
        tracker = _track(index, source, content)

        assert tracker.connections["connection"].database_name == "PayrollDb"
        assert tracker.connections["connection"].server == "srvA"

        observations = index.environment_overrides()
        assert len(observations) == 1
        observation = observations[0]
        assert observation["lookup_key"] == "Payroll"
        assert observation["database"] == "PayrollProdDb"
        assert observation["server"] == "srvB"
        assert observation["applied"] is False
        assert observation["settings_file"] == str(
            project / "appsettings.Production.json"
        )


# ============================================================
# Web.config 解析路徑不變
# ============================================================


@requires_web_config_fixtures
def test_the_web_config_resolution_path_is_unchanged():
    """WebForms 系統底下沒有任何 appsettings.json，所以新的查找表完全不作用，
    STC/Global.asax.cs 仍然透過 Web.config 解析成 SysErrorRecord。"""
    web_forms_root = STC_GLOBAL_ASAX.parent

    index = ProjectConnectionScopeIndex(web_forms_root)
    assert index.enabled is False
    assert index.scope_for(STC_GLOBAL_ASAX) is None

    tracker = DBConnectionTracker(
        connection_resolver=parse_web_config_file(STC_WEB_CONFIG)
    )
    connections = tracker.analyze_connections(
        STC_GLOBAL_ASAX.read_text(encoding="utf-8")
    )

    assert connections["cn"].database_name == "SysErrorRecord"
    assert connections["cn"].server == "vmsystest07"


# ============================================================
# End-to-end: ProjectScanner 把 scope 解析結果寫進掃描結果
# ============================================================


def test_project_scanner_records_resolved_and_unresolved_connections(tmp_path: Path):
    """掃描一個 Core 專案：解析得出的連線寫進 connection_sources，解析不出來
    的寫進 unresolved_connections 並帶著理由。"""
    (tmp_path / "App.csproj").write_text(
        '<Project ToolsVersion="15.0"></Project>', encoding="utf-8"
    )
    (tmp_path / "appsettings.json").write_text(
        json.dumps(
            {
                "ConnectionStrings": {"Payroll": "Server=srvA;Database=PayrollDb"},
                "Ledger": "Server=srvB;Database=RootLedgerDb",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (tmp_path / "Program.cs").write_text(
        _composition_root(("PayrollContext", "Payroll")), encoding="utf-8"
    )
    source = _write_source(
        tmp_path / "Data" / "Repository.cs",
        "public class Repository {\n"
        "    private readonly PayrollContext _payroll;\n"
        '    private readonly string _ledger = _configuration["Ledger"];\n'
        "}\n",
    )

    scanner = ProjectScanner(project_root=str(tmp_path), project_name="App")
    scan_result = ProjectScanResult(
        project_root=str(tmp_path),
        project_name="App",
        scan_time=datetime.now(),
    )
    scan_result = scanner.refresh_csharp_files(scan_result, [str(source)])

    file_key = str(source.resolve())
    assert scan_result.connection_sources[file_key]["_payroll"] == {
        "database": "PayrollDb",
        "server": "srvA",
    }
    reasons = {
        entry["variable_name"]: entry["reason"]
        for entry in scan_result.unresolved_connections[file_key]
    }
    assert reasons["_ledger"] == ROOT_CONFIGURATION_NAMESPACE


def test_project_scanner_only_reports_an_unregistered_context_type_that_a_real_invocation_names(
    tmp_path: Path,
):
    """`db_invocations` 已經是 host 解析出來的真實呼叫事實（見
    `_parse_csharp_file` 呼叫前一步就寫進 `scan_result.db_invocations`）；
    `ProjectScanner` 把它引用過的連線運算式餵給 tracker，理由只問這些變數
    （ticket 17）。這裡直接呼叫 `_parse_csharp_file`，不必真的跑一次
    StaticAnalyzerHost 去產生 db_invocations。"""
    (tmp_path / "App.csproj").write_text(
        '<Project ToolsVersion="15.0"></Project>', encoding="utf-8"
    )
    (tmp_path / "appsettings.json").write_text(
        json.dumps(
            {"ConnectionStrings": {"Payroll": "Server=srvA;Database=PayrollDb"}},
            indent=2,
        ),
        encoding="utf-8",
    )
    (tmp_path / "Program.cs").write_text(
        _composition_root(("PayrollContext", "Payroll")), encoding="utf-8"
    )
    source = _write_source(
        tmp_path / "Services" / "LedgerService.cs",
        "public class LedgerService {\n"
        "    private readonly LedgerContext _ledger;\n"
        "    public void Run() { _ledger.Ledgers.ToList(); }\n"
        "}\n",
    )

    scanner = ProjectScanner(project_root=str(tmp_path), project_name="App")
    scanner.scan_result = ProjectScanResult(
        project_root=str(tmp_path), project_name="App", scan_time=datetime.now()
    )
    file_key = str(source.resolve())
    scanner.scan_result.db_invocations[file_key] = [
        {"connection_expression": "_ledger"}
    ]

    scanner._parse_csharp_file(str(source), file_key)

    assert "_ledger" not in scanner.scan_result.connection_sources.get(file_key, {})
    reasons = {
        entry["variable_name"]: entry["reason"]
        for entry in scanner.scan_result.unresolved_connections[file_key]
    }
    assert reasons["_ledger"] == CONTEXT_TYPE_NOT_REGISTERED
