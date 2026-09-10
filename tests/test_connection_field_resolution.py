"""測試「連線字串放在欄位裡」這個形狀的連線解析。

涵蓋 09-connection-string-held-in-a-field 這張票：一個原始 ADO.NET 呼叫，它
的連線來自呼叫端類別的一個欄位，必須解析得出 Resolved Connection Source。
票 08 處理的是資料庫內容型別的形狀；這張票處理欄位的形狀，兩者共用同一張
Project Connection Scope 查找表（ADR-0018）。

每一個斷言「解析不出來」的測試，同時斷言它說出了什麼理由——這份程式碼要防
止的失敗模式是沉默的空結果，不是當掉。
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from code_analyzer.db_connection_tracker import DBConnectionTracker
from code_analyzer.project_connection_scope import (
    build_project_connection_scope,
    CONNECTION_KEY_NOT_IN_PROJECT_SCOPE,
    FIELD_HELD_CONNECTION_NOT_TRACED,
    ProjectConnectionScopeIndex,
    ROOT_CONFIGURATION_NAMESPACE,
)
from code_analyzer.project_scanner import ProjectScanner, ProjectScanResult
from code_analyzer.source_text import decode_source_bytes

ETR_REPOSITORY = PROJECT_ROOT / "data/repos/System_Dept_1/ETR"

requires_etr_fixture = pytest.mark.skipif(
    not (ETR_REPOSITORY / "appsettings.json").exists(),
    reason="local data/repos/System_Dept_1/ETR fixture checkout is not present",
)


# ============================================================
# 測試用的最小專案：依房規寫進暫存目錄，沒有 fixtures 目錄
# ============================================================


def _write_project(
    directory: Path,
    *,
    connection_strings: dict,
    root_configuration: dict = None,
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
    return directory


def _write_source(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _track(index: ProjectConnectionScopeIndex, source_file: Path, content: str):
    """依掃描器的做法，用這個檔案所屬的查找表解析它的連線。"""
    tracker = DBConnectionTracker(connection_resolver=index.scope_for(source_file))
    tracker.analyze_connections(content)
    return tracker


def _controller(assignment: str) -> str:
    """一個 ETR 形狀的控制器：建構子把連線字串讀進欄位，方法從欄位開連線。"""
    return (
        "public class ReportController : Controller\n"
        "{\n"
        "    private readonly string _connetStr;\n"
        "    public ReportController(IConfiguration config) {\n"
        f"        {assignment}\n"
        "    }\n"
        "    private void Load() {\n"
        "        using (SqlConnection con = new SqlConnection(_connetStr)) {\n"
        '            using (SqlCommand cmd = new SqlCommand("spLoad", con)) {\n'
        "                cmd.CommandType = CommandType.StoredProcedure;\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n"
    )


def _reasons(tracker) -> dict:
    return {entry.variable_name: entry.reason for entry in tracker.unresolved}


# ============================================================
# 欄位持有的連線字串
# ============================================================


class TestConnectionHeldInAField:
    def test_a_field_assigned_a_named_connection_string_resolves_its_calls(
        self, tmp_path: Path
    ):
        """從欄位開出來的連線，解析成欄位那條連線字串的 {server, database}。

        呼叫端記錄的連線變數是 `con`，不是欄位，所以 `con` 本身必須解析得
        出來，否則這個呼叫仍然到不了 SP Catalog。"""
        project = _write_project(
            tmp_path / "Payroll",
            connection_strings={"Payroll": "Server=srvA;Database=PayrollDb"},
        )
        content = _controller('_connetStr = config.GetConnectionString("Payroll");')
        source = _write_source(project / "Controllers" / "ReportController.cs", content)

        tracker = _track(ProjectConnectionScopeIndex(tmp_path), source, content)

        assert tracker.connections["con"].database_name == "PayrollDb"
        assert tracker.connections["con"].server == "srvA"
        assert tracker.connections["con"].connection_string_key == "Payroll"

    def test_a_field_resolves_through_its_own_project_connection_scope(
        self, tmp_path: Path
    ):
        """同一個鍵名在兩個專案裡開兩個不同伺服器上的資料庫。兩張表永不合
        併（ADR-0018），欄位形狀走的是同一張表。"""
        payroll = _write_project(
            tmp_path / "Payroll",
            connection_strings={"Db": "Server=srvA;Database=PayrollDb"},
        )
        ledger = _write_project(
            tmp_path / "Ledger",
            connection_strings={"Db": "Server=srvB;Database=LedgerDb"},
        )
        content = _controller('_connetStr = config.GetConnectionString("Db");')
        payroll_source = _write_source(payroll / "Controllers" / "R.cs", content)
        ledger_source = _write_source(ledger / "Controllers" / "R.cs", content)

        index = ProjectConnectionScopeIndex(tmp_path)
        payroll_tracker = _track(index, payroll_source, content)
        ledger_tracker = _track(index, ledger_source, content)

        assert payroll_tracker.connections["con"].database_name == "PayrollDb"
        assert payroll_tracker.connections["con"].server == "srvA"
        assert ledger_tracker.connections["con"].database_name == "LedgerDb"
        assert ledger_tracker.connections["con"].server == "srvB"

    def test_a_field_read_from_the_root_configuration_namespace_says_why(
        self, tmp_path: Path
    ):
        """`GetValue<string>("Key")` 讀的是 Configuration 根命名空間，不是
        ConnectionStrings 區段。兩個命名空間不合併（ADR-0008），所以解析不
        到連線，並說出這就是理由——實測的 ETR 儲存庫正是這樣寫的。"""
        project = _write_project(
            tmp_path / "Payroll",
            connection_strings={"Payroll": "Server=srvA;Database=PayrollDb"},
        )
        content = _controller('_connetStr = config.GetValue<string>("Payroll");')
        source = _write_source(project / "Controllers" / "R.cs", content)

        tracker = _track(ProjectConnectionScopeIndex(tmp_path), source, content)

        assert "con" not in tracker.connections
        assert "_connetStr" not in tracker.connections
        reasons = _reasons(tracker)
        assert reasons["_connetStr"] == ROOT_CONFIGURATION_NAMESPACE
        assert reasons["con"] == ROOT_CONFIGURATION_NAMESPACE

    def test_a_field_read_with_the_connection_strings_prefix_resolves(
        self, tmp_path: Path
    ):
        """`GetValue<string>("ConnectionStrings:Key")` 帶著區段前綴，讀的是
        連線查找表，照常解析。"""
        project = _write_project(
            tmp_path / "Payroll",
            connection_strings={"Payroll": "Server=srvA;Database=PayrollDb"},
        )
        content = _controller(
            '_connetStr = config.GetValue<string>("ConnectionStrings:Payroll");'
        )
        source = _write_source(project / "Controllers" / "R.cs", content)

        tracker = _track(ProjectConnectionScopeIndex(tmp_path), source, content)

        assert tracker.connections["con"].database_name == "PayrollDb"
        assert tracker.connections["con"].server == "srvA"

    def test_a_root_configuration_read_that_names_no_connection_is_not_reported(
        self, tmp_path: Path
    ):
        """讀根命名空間的程式碼絕大多數在讀日誌層級、功能開關這類與資料庫無
        關的設定。把它們全部記成解析不出來的連線只會淹沒真正的缺口。"""
        project = _write_project(
            tmp_path / "Payroll",
            connection_strings={"Payroll": "Server=srvA;Database=PayrollDb"},
            root_configuration={"ProgramSettings": {"AppName": "Payroll"}},
        )
        content = (
            "public class Startup {\n"
            "    private readonly string _appName = "
            'config.GetValue<string>("ProgramSettings:AppName");\n'
            "}\n"
        )
        source = _write_source(project / "Startup.cs", content)

        tracker = _track(ProjectConnectionScopeIndex(tmp_path), source, content)

        assert tracker.connections == {}
        assert tracker.unresolved == []

    def test_a_field_whose_value_cannot_be_traced_says_why(self, tmp_path: Path):
        """欄位的值來自一次方法呼叫，靜態掃描追不到它的連線字串。追不到就維
        持 unresolved 並指名理由，絕不猜——unresolved 看得見，錯的
        {server, database} 不是。"""
        project = _write_project(
            tmp_path / "Payroll",
            connection_strings={"Payroll": "Server=srvA;Database=PayrollDb"},
        )
        content = _controller("_connetStr = factory.Build();")
        source = _write_source(project / "Controllers" / "R.cs", content)

        tracker = _track(ProjectConnectionScopeIndex(tmp_path), source, content)

        assert "con" not in tracker.connections
        reasons = _reasons(tracker)
        assert reasons["con"] == FIELD_HELD_CONNECTION_NOT_TRACED
        assert [
            entry.lookup_key
            for entry in tracker.unresolved
            if entry.variable_name == "con"
        ] == ["_connetStr"]


# ============================================================
# 實測儲存庫：ETR 完全以這個形狀寫成
# ============================================================


@requires_etr_fixture
def test_the_measured_repository_resolves_its_raw_ado_net_calls():
    """ETR 有三十五處 `new SqlConnection(_connetStr)`。其中三十四處的欄位讀
    自 ConnectionStrings 區段，必須解析成 ETR 資料庫；一處讀自根命名空間，
    必須解析不出來並說出理由（那是 ETR 自己的組態缺陷，看得見才能修）。"""
    index = ProjectConnectionScopeIndex(ETR_REPOSITORY)
    call_site = re.compile(r"new\s+SqlConnection\s*\(\s*(\w+)\s*\)")

    resolved: list = []
    unresolved: list = []
    for source in sorted(ETR_REPOSITORY.rglob("*.cs")):
        if any(part in {"bin", "obj"} for part in source.parts):
            continue
        content = decode_source_bytes(source.read_bytes())
        if not call_site.search(content):
            continue
        tracker = _track(index, source, content)
        reasons = _reasons(tracker)
        for match in call_site.finditer(content):
            variable = match.group(1)
            info = tracker.connections.get(variable)
            if info is not None:
                resolved.append((info.server, info.database_name))
            else:
                unresolved.append(reasons.get(variable))

    assert len(resolved) + len(unresolved) == 35
    assert set(resolved) == {("vmsystest08\\vmsystest08_PDCS", "ETR")}
    assert len(resolved) == 34
    assert unresolved == [ROOT_CONFIGURATION_NAMESPACE]


class TestFieldConnectionReasons:
    def test_a_field_key_absent_from_its_scope_says_why(self, tmp_path: Path):
        """查找鍵在這個專案的 ConnectionStrings 區段裡不存在，是被分析系統自
        己的組態缺陷。它必須看得見，才有人能修。"""
        project = _write_project(
            tmp_path / "Payroll",
            connection_strings={"Payroll": "Server=srvA;Database=PayrollDb"},
        )
        content = _controller('_connetStr = config.GetConnectionString("Missing");')
        source = _write_source(project / "Controllers" / "R.cs", content)

        tracker = _track(ProjectConnectionScopeIndex(tmp_path), source, content)

        assert "con" not in tracker.connections
        reasons = _reasons(tracker)
        assert reasons["con"] == CONNECTION_KEY_NOT_IN_PROJECT_SCOPE
        assert reasons["_connetStr"] == CONNECTION_KEY_NOT_IN_PROJECT_SCOPE

    def test_one_call_site_resolving_does_not_silence_another(self, tmp_path: Path):
        """同一個檔案的兩個方法各有一個 `con`，一個解析得出、一個解析不出
        來。解析得出的那個不能讓另一個變成沉默的空結果——每一個解析不出來的
        呼叫都必須說出理由。"""
        project = _write_project(
            tmp_path / "Payroll",
            connection_strings={"Payroll": "Server=srvA;Database=PayrollDb"},
        )
        content = (
            "public class TwoWays\n"
            "{\n"
            "    private readonly string _payroll;\n"
            "    private readonly string _opaque;\n"
            "    public TwoWays(IConfiguration config, IFactory factory) {\n"
            '        _payroll = config.GetConnectionString("Payroll");\n'
            "        _opaque = factory.Build();\n"
            "    }\n"
            "    private void Known() {\n"
            "        using (SqlConnection con = new SqlConnection(_payroll)) { }\n"
            "    }\n"
            "    private void Opaque() {\n"
            "        using (SqlConnection con = new SqlConnection(_opaque)) { }\n"
            "    }\n"
            "}\n"
        )
        source = _write_source(project / "Data" / "TwoWays.cs", content)

        tracker = _track(ProjectConnectionScopeIndex(tmp_path), source, content)

        assert tracker.connections["con"].database_name == "PayrollDb"
        opaque_call = [
            entry
            for entry in tracker.unresolved
            if entry.variable_name == "con"
            and entry.reason == FIELD_HELD_CONNECTION_NOT_TRACED
        ]
        assert [entry.lookup_key for entry in opaque_call] == ["_opaque"]

    def test_a_composition_root_that_is_not_utf8_still_registers_its_contexts(
        self, tmp_path: Path
    ):
        """實測的 ETR 儲存庫的 Program.cs 註解是 Big5。嚴格解碼會丟例外，而
        整個掃描根的連線解析會隨之消失——那正是這份程式碼要防止的沉默空結
        果，不是當掉。"""
        project = _write_project(
            tmp_path / "Payroll",
            connection_strings={"Payroll": "Server=srvA;Database=PayrollDb"},
        )
        composition_root = (
            "var builder = WebApplication.CreateBuilder(args);\n"
            "// 錯誤處理 middleware\n"
            "builder.Services.AddDbContext<PayrollContext>(options =>\n"
            '    options.UseSqlServer(builder.Configuration.GetConnectionString("Payroll")));\n'
        )
        (project / "Program.cs").write_bytes(composition_root.encode("cp950"))
        assert b"\xbf\xf9" in (project / "Program.cs").read_bytes()

        scope = build_project_connection_scope(project / "Payroll.csproj")

        assert scope.context_connection_keys == {"PayrollContext": "Payroll"}


# ============================================================
# End-to-end: ProjectScanner 把欄位形狀的解析結果寫進掃描結果
# ============================================================


def test_project_scanner_records_a_field_held_connection(tmp_path: Path):
    """掃描器把呼叫端的連線變數寫進 connection_sources，把讀根命名空間的欄位
    的理由寫進 unresolved_connections。這是分析真正回報出去的那一層。"""
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
    source = _write_source(
        tmp_path / "Controllers" / "ReportController.cs",
        "public class ReportController : Controller\n"
        "{\n"
        "    private readonly string _payroll;\n"
        "    private readonly string _ledger;\n"
        "    public ReportController(IConfiguration config) {\n"
        '        _payroll = config.GetConnectionString("Payroll");\n'
        '        _ledger = config.GetValue<string>("Ledger");\n'
        "    }\n"
        "    private void Load() {\n"
        "        using (SqlConnection con = new SqlConnection(_payroll)) { }\n"
        "    }\n"
        "    private void LoadLedger() {\n"
        "        using (SqlConnection cnLedger = new SqlConnection(_ledger)) { }\n"
        "    }\n"
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
    assert scan_result.connection_sources[file_key]["con"] == {
        "database": "PayrollDb",
        "server": "srvA",
    }
    assert "cnLedger" not in scan_result.connection_sources[file_key]
    reasons = {
        entry["variable_name"]: entry["reason"]
        for entry in scan_result.unresolved_connections[file_key]
    }
    assert reasons["cnLedger"] == ROOT_CONFIGURATION_NAMESPACE
