# code_analyzer/project_scanner.py
"""
專案掃描器
整合 C# 解析、SQL 分析、資料庫連線追蹤
"""


import hashlib
import os
from pathlib import Path
from typing import Any, List, Dict, Set, Optional, Tuple
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
from .models import FileAnalysisResult, StoredProcedureCall, SQLQuery, FrameworkType, MethodSourceSpan, SourceSnapshot
from .static_analyzer_host import StaticAnalyzerHost, StaticAnalyzerHostError
from .smart_file_finder import SmartFileFinder, FileSearchResult
from .config_parser import WebConfigParser
from .project_connection_scope import ProjectConnectionScopeIndex
from .source_text import decode_source_bytes
from .webconfig_connection_resolver import parse_web_config_connections, WebConfigConnections
from .razor_display_field_resolver import resolve_razor_display_fields
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
    source_snapshots: Dict[str, SourceSnapshot] = field(default_factory=dict)
    db_invocations: Dict[str, List[Dict]] = field(default_factory=dict)
    # 每個變數解析後的連線來源；值為舊制的純資料庫名稱字串，或
    # {"database": ..., "server": ...} 這種由 Web.config 解析器產生的新形狀
    # （兩種形狀都被 _connection_source_database/_connection_source_server 接受）。
    connection_sources: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    contract_preflight_proposals: List[Dict] = field(default_factory=list)
    contract_proposals: List[Dict] = field(default_factory=list)
    verified_implementation_snapshots: List[Dict] = field(default_factory=list)
    # Semantic Binding Availability (ticket 05): one entry per project file found under this
    # scan's project_root, each holding "availability" (available /
    # unavailable_no_project_file / unavailable_reference_resolution_failed), when it
    # failed, "unresolved_references", and "source_file_count" — how many source files the
    # project reader found for that project. An SDK-style project names none of its source
    # files, so the count is the only place a maintainer sees what the model actually holds.
    # A degraded analysis must never look like a confident one, so this is always populated,
    # never inferred silently.
    semantic_binding_availability: List[Dict] = field(default_factory=list)
    # Framework Label reports; it does not gate (ADR-0021). One entry per scan
    # root that a ProjectScanner ran against — {"scan_root", "framework",
    # "parsers"} — populated by ProjectScanner._record_framework_report() and
    # merged across a system's scan roots by _merge_scans (service/analyze_service.py).
    framework_reports: List[Dict] = field(default_factory=list)
    # Connections that resolved to nothing, per source file, each naming why
    # (Project Connection Scope, ADR-0018). A ratio alone cannot tell a
    # resolution that improved from one that merely became confident, so every
    # connection below the line names its reason.
    unresolved_connections: Dict[str, List[Dict]] = field(default_factory=dict)
    # Observations about connection resolution that are reported and never
    # applied — today, an environment-specific settings file that overrides a
    # connection. Which environment runs is a deployment-time fact this scan
    # cannot know, so applying one would be a guess and hiding it would lose a
    # real per-environment database difference.
    connection_observations: List[Dict] = field(default_factory=list)

    # View 層分析結果（依框架偵測結果選擇性填入；未偵測到對應框架時維持空清單）
    aspx_results: List[FileAnalysisResult] = field(default_factory=list)    # .aspx / .ascx
    razor_results: List[FileAnalysisResult] = field(default_factory=list)  # .cshtml
    vue_results: List[FileAnalysisResult] = field(default_factory=list)    # .vue
    
    # 關聯資訊
    # Formal C# database facts are stored in db_invocations and rated by
    # CSharpAnalysisGateway at the service boundary.
    sp_relations: List[CSharpSPRelation] = field(default_factory=list)
    legacy_sp_relations: List[CSharpSPRelation] = field(default_factory=list)
    table_relations: List[CSharpTableRelation] = field(default_factory=list)
    
    # 資料庫統計
    databases_used: Set[str] = field(default_factory=set)
    total_sp_calls: int = 0
    total_sql_queries: int = 0
    unique_sps: Set[str] = field(default_factory=set)
    unique_tables: Set[str] = field(default_factory=set)

    def record_framework_report(self, report: Dict) -> None:
        """Add/replace one scan root's Framework Label report (ADR-0021).

        Replaces any earlier report for the same `scan_root` instead of piling
        up duplicates across repeated scans/refreshes of the same root —
        `framework_reports` owns that invariant itself, rather than each
        caller re-implementing the dedup-by-scan_root list surgery.
        """
        self.framework_reports[:] = [
            existing
            for existing in self.framework_reports
            if existing.get("scan_root") != report.get("scan_root")
        ]
        self.framework_reports.append(dict(report))

    def __getstate__(self):
        state = self.__dict__.copy()
        state.pop("legacy_sp_relations", None)
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)
        self.legacy_sp_relations = []
        self.contract_preflight_proposals = getattr(
            self, "contract_preflight_proposals", []
        )
        self.contract_proposals = getattr(self, "contract_proposals", [])
        self.verified_implementation_snapshots = getattr(
            self, "verified_implementation_snapshots", []
        )
        self.semantic_binding_availability = getattr(
            self, "semantic_binding_availability", []
        )
        self.framework_reports = getattr(self, "framework_reports", [])
        self.unresolved_connections = getattr(self, "unresolved_connections", {})
        self.connection_observations = getattr(self, "connection_observations", [])

    @staticmethod
    def _connection_source_database(value: Any) -> Optional[str]:
        """One connection_sources entry's resolved database name.

        An entry is either the legacy plain database-name string, or a
        {"database": ..., "server": ...} mapping produced by the Web.config
        connection-string resolver -- both shapes are accepted so callers
        never need to know which one they were handed.
        """
        if isinstance(value, dict):
            return value.get("database")
        return value

    @staticmethod
    def _connection_source_server(value: Any) -> Optional[str]:
        """One connection_sources entry's resolved server, or None when the
        entry is the legacy plain-string shape (no server was ever tracked)."""
        if isinstance(value, dict):
            return value.get("server")
        return None

    @staticmethod
    def _is_formal_sp_invocation(record: Dict) -> bool:
        """Return whether a raw StaticAnalyzerHost record is an SP attempt."""
        invocation_kind = str(record.get("invocation_kind") or "").casefold()
        mode = str(
            record.get("wrapper_mode")
            or record.get("adapter_mode")
            or ""
        ).casefold()
        return bool(
            record.get("command_type_stored_procedure") is True
            or (
                invocation_kind
                in {"source_wrapper", "dapper", "entity_framework", "entityframework", "ef"}
                and mode == "stored_procedure"
            )
        )

    def iter_formal_sp_invocations(self) -> List[Dict]:
        """Return raw SP invocation facts for formal reporting consumers.

        These records are Roslyn facts only. Database catalog evidence, graph
        joins, and proven/likely/unresolved ratings are added by the Gateway at
        the service boundary and must not be inferred here.
        """
        result: List[Dict] = []
        for source_file, records in self.db_invocations.items():
            connection_sources = self.connection_sources.get(source_file, {})
            for record in records or []:
                if not self._is_formal_sp_invocation(record):
                    continue
                command_text = str(record.get("command_text") or "").strip()
                procedure_name = (
                    command_text
                    if record.get("command_text_kind") == "literal" and command_text
                    else ""
                )
                connection_variable = str(
                    record.get("connection_expression")
                    or record.get("connection_variable")
                    or ""
                )
                resolved_source = connection_sources.get(connection_variable)
                result.append(
                    {
                        "source_file": source_file,
                        "class_name": str(record.get("class_name") or ""),
                        "method_name": str(record.get("method_name") or ""),
                        "line_number": int(record.get("line_number") or 0),
                        "procedure_name": procedure_name,
                        "database": str(
                            record.get("database")
                            or self._connection_source_database(resolved_source)
                            or "unknown"
                        ),
                        "connection_variable": connection_variable,
                        "invocation_kind": str(record.get("invocation_kind") or "direct_sqlclient"),
                        "command_text_kind": str(record.get("command_text_kind") or ""),
                        "start_offset": int(record.get("start_offset") or 0),
                        "end_offset": int(record.get("end_offset") or 0),
                    }
                )
        return sorted(
            result,
            key=lambda item: (
                item["source_file"],
                item["start_offset"],
                item["end_offset"],
                item["method_name"],
                item["procedure_name"],
            ),
        )
    
    def calculate_statistics(self):
        """計算統計資訊"""
        self.databases_used = {
            database
            for sources in self.connection_sources.values()
            for database in (
                self._connection_source_database(value) for value in sources.values()
            )
            if database
        }
        formal_sp_invocations = self.iter_formal_sp_invocations()
        self.total_sp_calls = len(formal_sp_invocations)
        self.total_sql_queries = sum(len(r.sql_queries) for r in self.csharp_results)
        self.unique_sps = {
            invocation["procedure_name"].lower()
            for invocation in formal_sp_invocations
            if invocation["procedure_name"]
        }
        self.unique_tables = set(rel.table_name for rel in self.table_relations)

    def capture_source_snapshot(self, file_path: str, host_result: Dict) -> None:
        """Store one complete, project-relative C# file snapshot for this scan."""
        path = Path(file_path)
        source_bytes = path.read_bytes()
        content = decode_source_bytes(source_bytes)
        relative_path = str(path.resolve().relative_to(Path(self.project_root).resolve())).replace("\\", "/")
        content_hash = hashlib.sha256(source_bytes).hexdigest()
        if host_result.get("source_id") != content_hash:
            raise StaticAnalyzerHostError(f"StaticAnalyzerHost source hash mismatch: {relative_path}")
        method_spans = [
            MethodSourceSpan(
                class_name=item["class_name"],
                method_name=item["method_name"],
                start_offset=item["start_offset"],
                end_offset=item["end_offset"],
            )
            for item in host_result.get("methods", [])
        ]
        self.source_snapshots[relative_path] = SourceSnapshot(
            relative_path=relative_path,
            content_hash=content_hash,
            content=content,
            method_spans=method_spans,
        )

    
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
            'database_invocations': self.db_invocations,
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
        self.project_root = project_root
        self.project_name = project_name or Path(self.project_root).name
        
        if not self.project_root or not Path(self.project_root).exists():
            raise ValueError(f"專案路徑不存在: {self.project_root}")
        
        # 🆕 偵測專案類型——標籤只回報，不再決定掛載哪些解析器（ADR-0021）。
        detector = ProjectTypeDetector(self.project_root)
        self.framework_type = detector.detect()
        if self.framework_type == FrameworkType.UNKNOWN:
            raise ValueError(
                f"無法辨識框架類型（Framework Label = Unknown），拒絕退回純 C# 掃描："
                f"{self.project_root}"
            )
        # 解析器改依「掃描根目錄下實際存在的 view 檔案副檔名」聯集掛載，而不是
        # 依偵測到的框架二選一——一個同時有 WebForms 頁面與 Razor 檢視的掃描根，
        # 兩邊都會被解析，不會有任何一邊被靜默丟掉。
        self.required_parsers = detector.required_parsers_by_extension()
        self.scan_extensions = detector.file_extensions_present()
        
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
        self.static_analyzer_host = StaticAnalyzerHost.for_project(Path(__file__).resolve().parent.parent)

        # 解析專案的 Web.config，讓 db_tracker 能把程式碼裡的 AppSettings/
        # ConnectionStrings 查找鍵解析成真正的 {server, database}，而不是把
        # 查找鍵本身當成資料庫名稱來猜。
        self.connection_resolver: WebConfigConnections = self._load_connection_resolver()
        if self.csharp_parser is not None:
            self.csharp_parser.db_tracker.connection_resolver = self.connection_resolver

        # ASP.NET Core 的 appsettings.json 查找表，依專案檔目錄分範圍
        # （ADR-0018）。掃描根底下沒有任何 appsettings.json 時它不作用，
        # Web.config 解析路徑因此完全不變。
        self.connection_scopes = ProjectConnectionScopeIndex(self.project_root)
        
        # 初始化 SQL 分析器（多資料庫）
        self.sql_analyzers: Dict[str, SQLAnalyzer] = {}

        # 初始化智慧檔案搜尋器
        self.file_finder = SmartFileFinder(self.project_root)
        
        # 掃描結果
        self.scan_result: Optional[ProjectScanResult] = None

        # Framework Label 報告（ADR-0021）：這個掃描根偵測到的框架，以及實際
        # 掛載的解析器——寫到 scan_result 上，供 /refresh 回應與 refresh_cli
        # 逐一掃描根印出。
        self._framework_report: Dict[str, Any] = {
            "scan_root": str(self.project_root),
            "framework": self.framework_type.value,
            "parsers": list(self.required_parsers),
        }

        print(f"✅ 專案掃描器已初始化")
        print(f"   專案: {self.project_name}")
        print(f"   路徑: {self.project_root}")
        print(f"   類型: {self.framework_type.value}")
        print(f"   解析器: {', '.join(self.required_parsers)}")
        print(f"   掃描檔案: {', '.join([f'*.{ext}' for ext in self.scan_extensions])}")
    
    # ========================================
    # Web.config 連線字串解析
    # ========================================
    def _load_connection_resolver(self) -> WebConfigConnections:
        """尋找專案的 Web.config，解析成 app_settings/connection_strings 兩張表。

        找不到 Web.config 時回傳空的 WebConfigConnections——db_tracker 會退回
        舊行為（把查找鍵當成資料庫名稱），而不是拋出例外讓整個掃描失敗。
        """
        web_config_path = WebConfigParser(self.project_root)._find_file("web.config")
        if not web_config_path:
            return WebConfigConnections()
        try:
            content = Path(web_config_path).read_text(encoding="utf-8-sig")
        except OSError as error:
            print(f"⚠️ 讀取 web.config 失敗: {error}")
            return WebConfigConnections()
        return parse_web_config_connections(content)

    def _parse_csharp_file(self, file_path: str, file_key: str) -> FileAnalysisResult:
        """解析一個 C# 檔，並記下它解析出來的連線來源與解不出來的理由。

        連線查找表一律來自這個檔案所屬的 Project Connection Scope；
        這個掃描根沒有 appsettings.json 時，改用掃描根的 Web.config
        查找表（ADR-0018）。一個檔案的連線永遠不能借用另一個專案的表，
        因為同一個鍵名在兩個專案裡可以開兩個不同的資料庫。
        """
        tracker = self.csharp_parser.db_tracker
        scope = self.connection_scopes.scope_for(file_path)
        tracker.connection_resolver = (
            scope if scope is not None else self.connection_resolver
        )
        tracker.invoked_connection_expressions = self._invoked_connection_expressions(
            file_key
        )

        result = self.csharp_parser.parse_file(file_path)

        self.scan_result.connection_sources[file_key] = {
            name: {"database": info.database_name, "server": info.server}
            for name, info in tracker.connections.items()
            if info.database_name
        }
        unresolved = [entry.to_dict() for entry in tracker.unresolved]
        if unresolved:
            self.scan_result.unresolved_connections[file_key] = unresolved
        else:
            self.scan_result.unresolved_connections.pop(file_key, None)
        self._record_connection_observations()
        return result

    def _invoked_connection_expressions(self, file_key: str) -> Set[str]:
        """一個檔案裡，被一次真的 Database Invocation 引用過的連線運算式。

        這個集合已經在 db_invocations[file_key] 上，因為 host 的原始事實在
        呼叫 `_parse_csharp_file` 之前就寫進去了。回傳給
        `DBConnectionTracker`，讓「這個接收者的型別沒註冊」這個理由只問曾經
        真的發生過呼叫的接收者，不是這個檔案裡任何一個宣告（ticket 17）。
        """
        records = self.scan_result.db_invocations.get(file_key) or []
        expressions: Set[str] = set()
        for record in records:
            expression = record.get("connection_expression") or record.get(
                "connection_variable"
            )
            if expression and str(expression).strip():
                expressions.add(str(expression).strip())
        return expressions

    def _record_connection_observations(self) -> None:
        """把目前已建立的每一個 scope 觀察到的環境改寫併進掃描結果。

        併入而不是取代：一次只重掃一個檔案的 refresh 只建立得出那個檔案所屬
        的 scope，取代會讓完整掃描記下的其他觀察憑空消失。以
        (設定檔, 查找鍵) 去重，所以重複掃描同一個專案不會累積重複項。
        """
        observations = {
            (entry.get("settings_file"), entry.get("lookup_key")): entry
            for entry in self.scan_result.connection_observations
        }
        for entry in self.connection_scopes.environment_overrides():
            observations[(entry.get("settings_file"), entry.get("lookup_key"))] = entry
        self.scan_result.connection_observations[:] = [
            observations[key] for key in sorted(observations)
        ]

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
    
    def _find_files_by_extensions(self, extensions: Set[str]) -> List[str]:
        """依副檔名尋找檔案（套用與 find_csharp_files 相同的排除資料夾／樣式規則）。

        供 View 層解析器（aspx/razor/vue）使用；這些解析器過去雖已依框架偵測
        結果被建立（self.parsers），卻從未被呼叫，.aspx/.cshtml/.vue 本身
        從未被搜尋或讀取。
        """
        found_files = []
        exclude_folders = set(settings.EXCLUDE_FOLDERS)
        exclude_patterns = settings.EXCLUDE_PATTERNS

        for root, dirs, files in os.walk(self.project_root):
            dirs[:] = [d for d in dirs if d not in exclude_folders]

            for file in files:
                if Path(file).suffix.lower() not in extensions:
                    continue

                should_exclude = False
                for pattern in exclude_patterns:
                    import fnmatch
                    if fnmatch.fnmatch(file, pattern):
                        should_exclude = True
                        break

                if not should_exclude:
                    found_files.append(os.path.join(root, file))

        return found_files
    
    def _analyze_csharp_with_progress(self, file_paths: List[str]) -> List[Dict]:
        """Run the analyzer host over `file_paths`, reporting one line per finished batch.

        Both the full scan and the incremental refresh go through here, because both pay the
        same fixed cost per host invocation: the host re-parses every project source file as
        analysis context before it looks at a single requested file — about fourteen seconds on
        the 541-file Y-Docs TTPUR project. A refresh of one file is therefore silent for just as
        long as a scan of five hundred, and silence reads as a hang. The progress line is what
        tells the user the run is alive.
        """
        self.static_analyzer_host.ensure_ready()
        self._refresh_semantic_binding_availability()
        print(f"   C# analyzer 批次進度：0/{len(file_paths)}", flush=True)
        return self.static_analyzer_host.analyze_csharp_files(
            [Path(file_path) for file_path in file_paths],
            source_roots=[Path(self.project_root)],
            progress_callback=lambda current, total, item: print(
                f"   C# analyzer 批次進度：{current}/{total}（{Path(item).name}）",
                flush=True,
            ),
        )

    def _refresh_semantic_binding_availability(self) -> None:
        """Recompute Semantic Binding Availability for every project file under
        project_root, once per scan/refresh pass that touches C# files."""
        self.scan_result.semantic_binding_availability = (
            self.static_analyzer_host.semantic_binding_availability(
                [Path(self.project_root)]
            )
        )

    def _record_framework_report(self) -> None:
        """Write this scanner's Framework Label report onto `self.scan_result`
        (ADR-0021). `ProjectScanResult.record_framework_report` owns the
        dedup-by-scan_root invariant; this just supplies this scanner's report.

        A no-op when `_framework_report` was never set: some tests construct
        a `ProjectScanner` via `object.__new__` or a subclass that overrides
        `__init__` without calling it, to stub out the analyzer host. Those
        scanners never went through framework detection, so there is nothing
        honest to report.
        """
        own_report = getattr(self, "_framework_report", None)
        if own_report is None:
            return
        self.scan_result.record_framework_report(own_report)

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
        self._record_framework_report()

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
        if csharp_files:
            host_results = self._analyze_csharp_with_progress(csharp_files)

            for file_path, host_result in tqdm(
                zip(csharp_files, host_results),
                total=len(csharp_files),
                desc="整理 C# 解析結果",
            ):
                try:
                    self.scan_result.capture_source_snapshot(file_path, host_result)
                    file_key = str(Path(file_path).resolve())
                    self.scan_result.db_invocations[file_key] = [
                        dict(invocation)
                        for invocation in host_result.get("db_invocations", []) or []
                    ]
                    result = self._parse_csharp_file(file_path, file_key)
                    self.scan_result.csharp_results.append(result)
                    self.scan_result.scanned_files += 1
                except Exception as e:
                    self.scan_result.failed_files += 1
                    print(f"\n   ⚠️  解析失敗 ({Path(file_path).name}): {e}")
        
        print(f"\n   ✅ 完成: {self.scan_result.scanned_files}/{self.scan_result.total_files}")
        
        # 3.5 解析 View 層檔案（aspx/ascx、razor .cshtml、vue .vue）
        # 只解析框架偵測結果實際需要的類型（self.parsers 依 required_parsers 建立）；
        # 失敗採「盡力而為」，單一檔案解析失敗不影響其餘掃描流程。
        if 'aspx' in self.parsers:
            aspx_files = self._find_files_by_extensions({'.aspx', '.ascx'})
            print(f"\n📝 解析 ASPX/ASCX 檔案（共 {len(aspx_files)} 個）...")
            for file_path in tqdm(aspx_files, desc="ASPX 解析進度"):
                try:
                    result = self.parsers['aspx'].parse_file(file_path)
                    self.scan_result.aspx_results.append(result)
                except Exception as e:
                    print(f"\n   ⚠️  ASPX 解析失敗 ({Path(file_path).name}): {e}")
        
        if 'razor' in self.parsers:
            razor_files = self._find_files_by_extensions({'.cshtml'})
            print(f"\n📝 解析 Razor 檔案（共 {len(razor_files)} 個）...")
            for file_path in tqdm(razor_files, desc="Razor 解析進度"):
                try:
                    result = self.parsers['razor'].parse_file(file_path)
                    self.scan_result.razor_results.append(result)
                except Exception as e:
                    print(f"\n   ⚠️  Razor 解析失敗 ({Path(file_path).name}): {e}")
        
        if 'vue' in self.parsers:
            vue_files = self._find_files_by_extensions({'.vue'})
            print(f"\n📝 解析 Vue 檔案（共 {len(vue_files)} 個）...")
            for file_path in tqdm(vue_files, desc="Vue 解析進度"):
                try:
                    result = self.parsers['vue'].parse_file(file_path)
                    self.scan_result.vue_results.append(result)
                except Exception as e:
                    print(f"\n   ⚠️  Vue 解析失敗 ({Path(file_path).name}): {e}")
        
        # 3.6 把 Razor 畫面的 ui_fields 缺文字的模型繫結欄位，接上模型類別的
        # [Display] attribute（含資源檔查找）——這一步要等 C# 與 Razor 兩邊都解析完，
        # 因為 RazorParser 一次只看得到一個 .cshtml 檔案，看不到模型類別的 attribute。
        resolve_razor_display_fields(
            self.scan_result.razor_results, self.scan_result.csharp_results, Path(self.project_root)
        )

        # 4. 建立關聯
        print(f"\n🔗 建立關聯...")
        self._build_relations(analyze_sp)
        
        # 5. 計算統計
        self.scan_result.calculate_statistics()
        
        # 6. 關閉資料庫連線
        if analyze_sp:
            self.close_databases()
        
        print(f"\n✅ 掃描完成")
        return self.scan_result

    def refresh_csharp_files(
        self,
        scan_result: ProjectScanResult,
        csharp_files: List[str],
        removed_files: Optional[List[str]] = None,
    ) -> ProjectScanResult:
        """Replace selected C# records in an existing scan result."""
        self.scan_result = scan_result
        self._record_framework_report()
        current_files = self._unique_project_files(csharp_files)
        stale_files = self._unique_project_files(removed_files or [])
        affected_files = self._unique_project_files([*current_files, *stale_files])

        for file_path in affected_files:
            self._remove_csharp_records(file_path)

        refreshed_results: List[FileAnalysisResult] = []
        if current_files:
            print(f"\n📝 重新解析 C# 檔案（{len(current_files)} 個）...")
            host_results = self._analyze_csharp_with_progress(current_files)
            for file_path, host_result in zip(current_files, host_results):
                self.scan_result.capture_source_snapshot(file_path, host_result)
                file_key = str(Path(file_path).resolve())
                self.scan_result.db_invocations[file_key] = [
                    dict(invocation)
                    for invocation in host_result.get("db_invocations", []) or []
                ]
                result = self._parse_csharp_file(file_path, file_key)
                self.scan_result.csharp_results.append(result)
                refreshed_results.append(result)

        self.scan_result.csharp_results.sort(
            key=lambda result: str(Path(result.file_path).resolve())
        )
        for result in refreshed_results:
            self._build_table_relations(result.sql_queries)
        resolve_razor_display_fields(
            self.scan_result.razor_results, self.scan_result.csharp_results, Path(self.project_root)
        )
        self.scan_result.calculate_statistics()
        return self.scan_result

    def refresh_view_files(
        self,
        scan_result: ProjectScanResult,
        view_files: List[str],
        removed_files: Optional[List[str]] = None,
    ) -> ProjectScanResult:
        """Replace selected ASPX, Razor, and Vue records in an existing scan."""
        self.scan_result = scan_result
        self._record_framework_report()
        current_files = self._unique_project_files(view_files)
        stale_files = self._unique_project_files(removed_files or [])
        affected_files = self._unique_project_files([*current_files, *stale_files])

        for file_path in affected_files:
            parser_key, result_attribute = self._view_parser_for(file_path)
            if not parser_key:
                continue
            results = getattr(self.scan_result, result_attribute)
            results[:] = [
                result
                for result in results
                if not self._same_project_file(result.file_path, file_path)
            ]

        for file_path in current_files:
            parser_key, result_attribute = self._view_parser_for(file_path)
            parser = self.parsers.get(parser_key) if parser_key else None
            if parser is None:
                continue
            result = parser.parse_file(file_path)
            getattr(self.scan_result, result_attribute).append(result)

        for result_attribute in ("aspx_results", "razor_results", "vue_results"):
            getattr(self.scan_result, result_attribute).sort(
                key=lambda result: str(Path(result.file_path).resolve())
            )
        resolve_razor_display_fields(
            self.scan_result.razor_results, self.scan_result.csharp_results, Path(self.project_root)
        )
        return self.scan_result

    def _remove_csharp_records(self, file_path: str) -> None:
        self.scan_result.csharp_results[:] = [
            result
            for result in self.scan_result.csharp_results
            if not self._same_project_file(result.file_path, file_path)
        ]
        for records in (
            self.scan_result.db_invocations,
            self.scan_result.connection_sources,
            self.scan_result.unresolved_connections,
        ):
            for key in list(records):
                if self._same_project_file(key, file_path):
                    records.pop(key, None)

        root = Path(self.project_root).resolve()
        try:
            relative_path = Path(file_path).resolve().relative_to(root).as_posix()
        except ValueError:
            relative_path = Path(file_path).name
        for key in list(self.scan_result.source_snapshots):
            snapshot_path = root / str(key).replace("/", os.sep)
            if snapshot_path.resolve() == (root / relative_path).resolve():
                self.scan_result.source_snapshots.pop(key, None)

        for relation_attribute in ("sp_relations", "legacy_sp_relations", "table_relations"):
            relations = getattr(self.scan_result, relation_attribute, [])
            relations[:] = [
                relation
                for relation in relations
                if not self._same_project_file(relation.csharp_file, file_path)
            ]

    def _unique_project_files(self, file_paths: List[str]) -> List[str]:
        unique: Dict[str, str] = {}
        for file_path in file_paths:
            path = str(Path(file_path).resolve())
            unique.setdefault(path.casefold(), path)
        return list(unique.values())

    def _same_project_file(self, left: str, right: str) -> bool:
        def resolve(path: str) -> Path:
            candidate = Path(path)
            if not candidate.is_absolute():
                candidate = Path(self.project_root) / candidate
            return candidate.resolve()

        return resolve(left) == resolve(right)

    @staticmethod
    def _view_parser_for(file_path: str) -> Tuple[str, str]:
        suffix = Path(file_path).suffix.casefold()
        return {
            ".aspx": ("aspx", "aspx_results"),
            ".ascx": ("aspx", "aspx_results"),
            ".cshtml": ("razor", "razor_results"),
            ".vue": ("vue", "vue_results"),
        }.get(suffix, ("", ""))
    
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
            self._build_legacy_sp_relations(all_sp_calls, analyze_sp)
        
        # 建立資料表關聯
        if all_sql_queries:
            self._build_table_relations(all_sql_queries)
    
    def _build_legacy_sp_relations(self, sp_calls: List[StoredProcedureCall], analyze_sp: bool):
        """Retain legacy regex detections for migration comparison only."""
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
            
            self.scan_result.legacy_sp_relations.append(relation)
    
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
    
    def _find_class_and_method(
        self, 
        file_path: str, 
        line_number: int
    ) -> Tuple[str, str]:
        """找出特定行號所屬的類別和方法。

        修正（重要）：先前的邏輯是「遇到第一個 method.location.line_number <=
        line_number 的方法就直接回傳」——由於 cls.methods 是依宣告順序排列，
        類別裡宣告在最前面的方法（例如 WebForms code-behind 常見的
        `Page_Load`）幾乎必然滿足「起始行 <= 任何後面呼叫的行號」，導致同一支
        程式裡「所有」SP/資料表呼叫，不論實際寫在哪個方法裡，全部被誤判成
        `Page_Load` 呼叫的（除非 Page_Load 本身就在該行號之後才宣告）。這個
        bug 影響全域：sp_relations／table_relations 的 method_name 欄位長期
        不可信，只是先前的功能大多只用到「檔案層級」的 SP/表清單（不在乎是
        哪個方法呼叫的），沒有明顯暴露出來；直到需要「方法層級」精準歸屬的
        新功能（flow_chain_builder.py 的正向鏈）才實際觸發並被發現。

        修正做法：在同一個類別的所有方法裡，找出「起始行號 <= line_number
        且起始行號最大」的那一個（也就是「這行之前，最後宣告的方法」），而不
        是第一個符合條件就回傳——沒有方法結束行號可用時，這是判斷「這行屬於
        哪個方法」最合理的近似值。
        """
        # 從已解析的結果中查找
        for result in self.scan_result.csharp_results:
            if result.file_path == file_path:
                for cls in result.classes:
                    best_method = None
                    best_line = -1
                    for method in cls.methods:
                        if method.location and method.location.line_number <= line_number:
                            if method.location.line_number > best_line:
                                best_line = method.location.line_number
                                best_method = method
                    if best_method:
                        return cls.name, best_method.name

                    # 沒有任何方法起始行號在該行之前，至少返回類別
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
            formal_invocations = result.iter_formal_sp_invocations()
            for db in sorted(result.databases_used):
                sp_count = sum(
                    1 for invocation in formal_invocations
                    if invocation["database"] == db
                )
                print(f"      - {db}: {sp_count} 個 SP 呼叫")
        
        # SP 統計
        print(f"\n📞 預存程序統計:")
        print(f"   總呼叫次數: {result.total_sp_calls}")
        print(f"   不重複 SP: {len(result.unique_sps)}")
        
        dynamic_sp_calls = [
            invocation
            for invocation in result.iter_formal_sp_invocations()
            if not invocation["procedure_name"]
        ]
        if dynamic_sp_calls:
            print(f"   ⚠️  動態 SP 名稱（待 Gateway 判定）: {len(dynamic_sp_calls)}")
        
        # SQL 統計
        print(f"\n📊 SQL 查詢統計:")
        print(f"   總查詢數: {result.total_sql_queries}")
        print(f"   涉及資料表: {len(result.unique_tables)}")
        
        print("\n⚙️  SP 複雜度分布:")
        print("   未在 scanner 階段評級（請使用 SQL Execution Graph evidence）")
        
        print("\n" + "=" * 80)
    
    def print_sp_relations(self, limit: int = 20):
        """輸出 formal Database Invocation 清單。"""
        if not self.scan_result:
            print("❌ 尚未執行掃描")
            return
        
        print("\n" + "=" * 80)
        print("C# Database Invocation（raw facts）")
        print("=" * 80)
        
        invocations = self.scan_result.iter_formal_sp_invocations()
        for i, invocation in enumerate(invocations[:limit], 1):
            procedure_name = invocation["procedure_name"] or "<dynamic command text>"
            print(f"\n{i}. {procedure_name}")
            print(f"   檔案: {Path(invocation['source_file']).name}")
            print(
                f"   類別.方法: {invocation['class_name']}."
                f"{invocation['method_name']}"
            )
            print(f"   資料庫: {invocation['database']}")
            print(f"   Invocation kind: {invocation['invocation_kind']}")

        if len(invocations) > limit:
            print(f"\n... 還有 {len(invocations) - limit} 個 invocation")
    
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
            
            # 2. Database Invocations
            formal_invocations = self.scan_result.iter_formal_sp_invocations()
            if formal_invocations:
                sp_data = []
                for invocation in formal_invocations:
                    row = {
                        'C# 檔案': Path(invocation['source_file']).name,
                        '完整路徑': invocation['source_file'],
                        '類別': invocation['class_name'],
                        '方法': invocation['method_name'],
                        'SP 名稱': invocation['procedure_name'] or '<dynamic>',
                        '資料庫': invocation['database'],
                        'Evidence': 'raw',
                        '連線變數': invocation['connection_variable'],
                        'Invocation kind': invocation['invocation_kind'],
                    }
                    sp_data.append(row)
                
                pd.DataFrame(sp_data).to_excel(writer, sheet_name='Database Invocations', index=False)
            
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