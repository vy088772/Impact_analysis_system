# service/analyze_service.py
"""
影響分析服務核心（無 AI）。

職責：
  1. 依請求的 source（project/repo/branch/path）解析出本機原始碼路徑
     （必要時透過 Azure DevOps clone/pull；多系統共用 repo 時以 path 子資料夾區分）。
  2. 以既有 ProjectScanner 做靜態掃描（不連資料庫：analyze_sp=False）。
  3. 依 program_names 過濾出對應檔案的 方法 / SP / Table，組成 AnalyzeResponse。

對應設計書 §5.3 / §5.4。code_snippets 與 call_chains 於 S2b / S3 補上。
"""
from __future__ import annotations

import re
import os
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Tuple

from config.settings import settings
from code_analyzer.azure_fetcher import AzureDevOpsFetcher, AzureFetchError
from code_analyzer.csharp_analysis_gateway import (
    CSharpAnalysisGateway,
    DbInvocation,
    InvocationEvidence,
    SpCatalog,
    WRAPPER_EVIDENCE_FIELDS,
    invocation_wrapper_evidence_fields,
    load_external_wrapper_contract,
    load_wrapper_review_exclusions,
    normalize_procedure_name,
    wrapper_observation_identity,
)
from code_analyzer.project_scanner import ProjectScanner, ProjectScanResult
from code_analyzer.static_analyzer_host import StaticAnalyzerHost, StaticAnalyzerHostError

from .schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    ProgramAnalysis,
    FindBySPRequest,
    FindBySPResponse,
    SPMatchProgram,
    FindByTableRequest,
    FindByTableResponse,
    TableMatchProgram,
    LocateObjectRequest,
    LocateObjectResponse,
    LocatedDatabase,
    FlowChainRequest,
    FlowChainResponse,
    PathEvidenceRequest,
    PathEvidenceResponse,
)
from .snippet_extractor import extract_snippets
from .call_chain_builder import build_call_chains
from .fk_resolver import resolve_fk_related
from .sp_fetcher import fetch_sp_definitions
from .view_fetcher import fetch_view_definitions
from .udf_fetcher import fetch_udf_definitions
from .execution_path_builder import (
    MAX_COMPACT_PATHS,
    build_compact_execution_path_payload,
    build_execution_paths,
)
from .graph_queries import query_table_accesses
from .reference_expander import expand_related_programs
from .repo_manager import repo_dir, resolve_scan_roots, peek_scan_roots
from .scan_store import cache_status, cached_commit, get_or_scan, has_cache, save_scan
from . import sql_cache_store
from . import flow_chain_builder
from .contract_preflight import (
    load_system_contract_selector,
    normalize_contract_selector,
    run_contract_preflight,
)
from .contract_registry import load_contract_registry
from .contract_transaction import (
    ContractTransactionError,
    DEFAULT_CATALOG_PATH as CONTRACT_TRANSACTION_CATALOG_PATH,
    DEFAULT_REGISTRY_PATH as CONTRACT_TRANSACTION_REGISTRY_PATH,
    commit_staged_contract_transaction,
)

DECOMPILED_AUTO_EVIDENCE_KIND = "decompiled_auto"


class PathEvidenceError(ValueError):
    """A path cannot be expanded from the current source or SQL snapshots."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class SqlExecutionGraphRequiredError(ValueError):
    """A formal SQL relationship requires a ready, database-scoped graph."""

    code = "sql_execution_graph_required"
    rebuild_action = "POST /refresh_sql"

    def __init__(
        self,
        database: str,
        reason: str = "missing_or_invalid",
        message: str = "",
    ) -> None:
        self.database = str(database or "").strip()
        self.reason = reason or "missing_or_invalid"
        super().__init__(
            message
            or (
                f"SQL execution graph cache 不可用：{self.database}。"
                "請重新執行 POST /refresh_sql。"
            )
        )


@dataclass
class ProgramRefreshResult:
    """Result of replacing only the files belonging to requested programs."""

    scan: ProjectScanResult
    updated_files: List[str] = field(default_factory=list)
    removed_files: List[str] = field(default_factory=list)
    matched_programs: List[str] = field(default_factory=list)
    not_found: List[str] = field(default_factory=list)
    full_refresh: bool = False


class ProgramRefreshCacheError(ValueError):
    """A program refresh cannot safely proceed without a current scan cache."""

    code = "program_refresh_requires_current_cache"

    def __init__(self, root: Path, status: str):
        self.root = root
        self.status = status
        super().__init__(
            "指定 program 更新需要目前版本的 scan cache，不能靜默改成完整 system refresh："
            f"{root}（狀態：{status}）。請先執行不帶 --program 的完整 refresh。"
        )


def _require_current_program_cache(root: Path) -> None:
    status = cache_status(root)
    if status != "current":
        raise ProgramRefreshCacheError(root, status)


# 以「解析後的本機路徑」為鍵，快取掃描結果，避免同一 repo 重複掃描
_scan_cache: Dict[str, ProjectScanResult] = {}

# 程式名常見副檔名（用於正規化比對）
_KNOWN_SUFFIXES = (".aspx.cs", ".ascx.cs", ".aspx", ".ascx", ".cshtml", ".vue", ".cs")


def _safe_dirname(text: str) -> str:
    """把 project/repo 名稱轉成安全的資料夾名。"""
    return re.sub(r"[^A-Za-z0-9._-]", "_", text or "").strip("_") or "default"


def _normalize_program(name: str) -> str:
    """去除副檔名與路徑，回傳小寫的程式基底名，供比對使用。"""
    base = Path(name.strip()).name
    low = base.lower()
    for suf in _KNOWN_SUFFIXES:
        if low.endswith(suf):
            return low[: -len(suf)]
    return low


def _file_matches(file_path: str, program_base: str) -> bool:
    """判斷某檔案是否對應到指定程式名（以基底名比對）。"""
    fname = Path(file_path).name.lower()
    file_base = _normalize_program(fname)
    if not program_base:
        return False
    return file_base == program_base or program_base in fname


def _view_layer_summary(fr, root: Path) -> Dict:
    """把 View 層解析結果（ASPXParser/RazorParser/VueParser）整理成精簡摘要。

    這幾個解析器目前只把統計資訊（指示詞/控制項/事件處理/Tag Helpers/元件 props 等
    數量）存在 FileAnalysisResult.dependencies（字串集合）與 warnings，沒有更細的
    結構化欄位，故直接原樣列出，不臆測未提供的細節。

    fields：ASPXParser 額外整理出「畫面上實際顯示給使用者看的文字」（GridView 欄位
    HeaderText、Label/Button 的 Text 等），供「畫面會顯示哪些欄位」這類問題直接引用。
    """
    return {
        "file": _rel(fr.file_path, root),
        "type": getattr(fr.file_type, "value", str(fr.file_type)),
        "framework": getattr(fr.framework, "value", str(fr.framework)),
        "summary": sorted(fr.dependencies),
        "fields": list(getattr(fr, "ui_fields", []) or []),
        "warnings": list(fr.warnings),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 來源解析
# ─────────────────────────────────────────────────────────────────────────────

def resolve_source(req: AnalyzeRequest) -> List[Path]:
    """
    解析請求來源 → 回傳要掃描的本機路徑清單（一律位於 data/repos 之下）。

    - 透過 repo_manager 確保程式碼已 clone 至 data/；不讀取任意本機路徑。
    - req.refresh=True 時，已存在的 clone 會先 git pull 取得最新。
    - source.path 通常只有一個子資料夾；若為清單（同一套系統拆成多個 VS 專案
      資料夾），回傳多個路徑，呼叫端需各自取得掃描結果後合併（見 _merge_scans）。
    """
    return resolve_scan_roots(
        {
            "project": req.source.project if req.source else "",
            "repo": req.source.repo if req.source else "",
            "branch": req.source.branch if req.source else "",
            "path": req.source.path if req.source else "",
        },
        refresh=getattr(req, "refresh", False),
    )


def _get_scan(root: Path, refresh: bool = False) -> ProjectScanResult:
    """取得（或建立）指定路徑的掃描結果，使用持久化快取。analyze_sp=False → 不連資料庫。"""
    return get_or_scan(root, refresh=refresh)


def _merge_scans(scans: List[ProjectScanResult]) -> ProjectScanResult:
    """把同一系統底下、分散在多個子資料夾（同一套系統拆成多個 VS 專案）的多次
    掃描結果合併成一個邏輯上的 ProjectScanResult，讓後續依檔名/SP 名比對的邏輯
    可以直接沿用既有單一 scan 的處理方式，不需另外改寫。
    """
    merged = ProjectScanResult(
        project_root=" + ".join(s.project_root for s in scans),
        project_name=scans[0].project_name if scans else "",
        scan_time=max((s.scan_time for s in scans), default=datetime.now()),
    )
    scan_roots = [str(Path(s.project_root).resolve()) for s in scans if s.project_root]
    try:
        canonical_root = Path(os.path.commonpath(scan_roots)).resolve()
    except (ValueError, IndexError):
        canonical_root = None
    for s in scans:
        merged.total_files += s.total_files
        merged.scanned_files += s.scanned_files
        merged.failed_files += s.failed_files
        merged.csharp_results.extend(s.csharp_results)
        for key, snapshot in getattr(s, "source_snapshots", {}).items():
            relative_path = str(snapshot.relative_path or key).replace("\\", "/")
            if canonical_root is not None:
                source_path = Path(s.project_root) / relative_path
                try:
                    relative_path = source_path.resolve().relative_to(canonical_root).as_posix()
                except ValueError:
                    pass
            merged.source_snapshots[relative_path] = replace(
                snapshot,
                relative_path=relative_path,
            )
        merged.db_invocations.update(getattr(s, "db_invocations", {}))
        merged.connection_sources.update(getattr(s, "connection_sources", {}))
        merged.contract_preflight_proposals.extend(
            getattr(s, "contract_preflight_proposals", []) or []
        )
        merged.contract_proposals.extend(getattr(s, "contract_proposals", []) or [])
        merged.verified_implementation_snapshots.extend(
            getattr(s, "verified_implementation_snapshots", []) or []
        )
        merged.semantic_binding_availability.extend(
            getattr(s, "semantic_binding_availability", []) or []
        )
        merged.aspx_results.extend(s.aspx_results)
        merged.razor_results.extend(s.razor_results)
        merged.vue_results.extend(s.vue_results)
        merged.sp_relations.extend(s.sp_relations)
        merged.legacy_sp_relations.extend(
            getattr(s, "legacy_sp_relations", []) or []
        )
        merged.table_relations.extend(s.table_relations)
    merged.calculate_statistics()
    return merged


def _wrapper_receiver_sources(
    scan: ProjectScanResult,
    *,
    external_only: bool,
) -> dict[str, list[str]]:
    receiver_sources: dict[str, set[str]] = {}
    raw_by_file = getattr(scan, "db_invocations", {}) or {}
    if not isinstance(raw_by_file, Mapping):
        return {}
    for source_file, records in raw_by_file.items():
        for record in records or ():
            if not isinstance(record, Mapping):
                continue
            if str(record.get("invocation_kind") or "").casefold() != "source_wrapper":
                continue
            if external_only and record.get("wrapper_source_available") is True:
                continue
            receiver = str(record.get("wrapper_receiver_type") or "").strip()
            if receiver:
                receiver_sources.setdefault(receiver, set()).add(str(source_file))
    return {
        receiver: sorted(source_files, key=str.casefold)
        for receiver, source_files in receiver_sources.items()
    }


def _external_wrapper_sources(scan: ProjectScanResult) -> dict[str, list[str]]:
    return _wrapper_receiver_sources(scan, external_only=True)


def _all_wrapper_receivers(scan: ProjectScanResult) -> set[str]:
    return set(_wrapper_receiver_sources(scan, external_only=False))


def _proposal_receiver_types(proposal: Mapping[str, Any]) -> set[str]:
    values: set[str] = set()
    receiver_types = proposal.get("receiver_types")
    if isinstance(receiver_types, str):
        values.add(receiver_types.strip())
    elif isinstance(receiver_types, (list, tuple, set)):
        values.update(str(value).strip() for value in receiver_types if str(value).strip())
    for key in (
        "receiver_type",
        "implementation_identity",
        "wrapper_implementation_identity",
    ):
        value = proposal.get(key)
        if value is not None and str(value).strip():
            values.add(str(value).strip())
    snapshot = proposal.get("implementation_snapshot")
    if isinstance(snapshot, Mapping):
        for key in ("behavior_surface_unit", "implementation_identity"):
            value = snapshot.get(key)
            if value is not None and str(value).strip():
                values.add(str(value).strip())
    return values


def _has_source_backed_wrapper_evidence(
    scan: ProjectScanResult,
    receiver_type: str,
) -> bool:
    raw_by_file = getattr(scan, "db_invocations", {}) or {}
    if isinstance(raw_by_file, Mapping):
        for records in raw_by_file.values():
            for record in records or ():
                if not isinstance(record, Mapping):
                    continue
                if (
                    str(record.get("invocation_kind") or "").casefold() == "source_wrapper"
                    and str(record.get("wrapper_receiver_type") or "").strip() == receiver_type
                    and record.get("wrapper_source_available") is True
                ):
                    return True

    for attribute in (
        "contract_preflight_proposals",
        "contract_proposals",
        "verified_implementation_snapshots",
    ):
        proposals = getattr(scan, attribute, None) or ()
        if isinstance(proposals, Mapping):
            proposals = (proposals,)
        for proposal in proposals:
            if not isinstance(proposal, Mapping):
                continue
            if receiver_type not in _proposal_receiver_types(proposal):
                continue
            evidence_kind = str(proposal.get("evidence_kind") or "").casefold()
            if proposal.get("source_backed") is True or evidence_kind in {
                "source",
                "source_backed",
                "local_source",
                "verified_source",
            }:
                return True
    return False


def _find_source_csproj(root: Path, source_files: list[str]) -> Path | None:
    root = root.resolve()
    candidates: set[Path] = set()
    for source_file in source_files:
        source_path = Path(source_file)
        if not source_path.is_absolute():
            source_path = root / source_path
        source_path = source_path.resolve()
        try:
            source_path.relative_to(root)
        except ValueError:
            continue
        current = source_path.parent
        while True:
            candidates.update(path for path in current.glob("*.csproj") if path.is_file())
            if current == root or root not in current.parents:
                break
            current = current.parent
    if not candidates:
        return None
    deepest = max(len(path.parts) for path in candidates)
    deepest_candidates = sorted(
        (path for path in candidates if len(path.parts) == deepest),
        key=lambda path: str(path).casefold(),
    )
    return deepest_candidates[0] if len(deepest_candidates) == 1 else None


def _decompilation_reasons(response: Mapping[str, Any]) -> list[str]:
    outcome = str(response.get("attempt_outcome") or "").strip()
    if not outcome:
        attempt = response.get("decompilation_attempt")
        if isinstance(attempt, Mapping):
            outcome = str(attempt.get("outcome") or "").strip()
    status = str(response.get("status") or "").strip()
    if outcome == "not_attempted" and status in {
        "csproj_not_found",
        "csproj_unreadable",
        "receiver_not_referenced",
        "hint_path_missing",
        "referenced_dll_missing",
    }:
        return [status]
    if outcome != "incomplete":
        return []

    reasons: list[str] = []
    if status and status != "resolved":
        reasons.append(status)
    if response.get("translation_problem_methods"):
        reasons.append("decompiler_translation_problem")
    for definition in response.get("wrapper_definitions") or ():
        if not isinstance(definition, Mapping):
            continue
        reason = str(definition.get("unresolved_reason") or "").strip()
        if reason:
            reasons.append(reason)
    if not reasons:
        reasons.append("decompilation_incomplete")
    return list(dict.fromkeys(reasons))


def _decompilation_attempt_record(
    response: Mapping[str, Any],
    *,
    receiver_type: str,
    csproj_path: Path,
) -> dict[str, Any]:
    attempt = response.get("decompilation_attempt")
    cache_status = str(response.get("cache_status") or "").strip()
    attempted = (
        bool(attempt.get("attempted"))
        if isinstance(attempt, Mapping) and "attempted" in attempt
        else cache_status != "hit"
    )
    outcome = str(response.get("attempt_outcome") or "").strip()
    if not outcome and isinstance(attempt, Mapping):
        outcome = str(attempt.get("outcome") or "").strip()
    if not outcome:
        outcome = (
            "complete"
            if response.get("status") == "resolved" and response.get("contract_proposals")
            else "incomplete"
        )
    display_outcome = "cached-skip" if not attempted and cache_status == "hit" else outcome
    return {
        "receiver_type": receiver_type,
        "csproj_path": str(csproj_path),
        "dll_path": str(response.get("dll_path") or ""),
        "assembly_identity": str(response.get("assembly_identity") or ""),
        "attempted": attempted,
        "outcome": display_outcome,
        "attempt_outcome": outcome,
        "cache_status": cache_status,
        "reasons": _decompilation_reasons(response),
        "detail": str(response.get("detail") or ""),
    }


def _not_attempted_decompilation_record(
    *,
    receiver_type: str,
    reason: str,
    csproj_path: Path | None = None,
) -> dict[str, Any]:
    return {
        "receiver_type": receiver_type,
        "csproj_path": str(csproj_path) if csproj_path is not None else "",
        "dll_path": "",
        "assembly_identity": "",
        "attempted": False,
        "outcome": "not_attempted",
        "attempt_outcome": "not_attempted",
        "cache_status": "not_applicable",
        "reasons": [reason],
        "detail": "",
    }


def _incomplete_decompilation_record(
    *,
    receiver_type: str,
    csproj_path: Path,
    reason: str,
    detail: str,
    attempted: bool,
) -> dict[str, Any]:
    return {
        **_not_attempted_decompilation_record(
            receiver_type=receiver_type,
            reason=reason,
            csproj_path=csproj_path,
        ),
        "attempted": attempted,
        "outcome": "incomplete",
        "attempt_outcome": "incomplete",
        "detail": detail,
    }


def _decompilation_summary(
    attempts: list[dict[str, Any]],
    *,
    reason: str = "",
) -> dict[str, Any]:
    outcomes = [str(item.get("outcome") or "") for item in attempts]
    if any(outcome == "incomplete" for outcome in outcomes):
        outcome = "incomplete"
    elif any(outcome == "complete" for outcome in outcomes):
        outcome = "complete"
    elif any(outcome == "cached-skip" for outcome in outcomes):
        outcome = "cached-skip"
    else:
        outcome = "not_attempted"
    reasons = [
        str(item_reason)
        for item in attempts
        for item_reason in item.get("reasons") or ()
        if str(item_reason)
    ]
    if reason:
        reasons.append(reason)
    return {
        "attempted": any(bool(item.get("attempted")) for item in attempts),
        "outcome": outcome,
        "reasons": list(dict.fromkeys(reasons)),
        "attempts": attempts,
    }


def _populate_decompilation_proposals(
    scans: Iterable[ProjectScanResult],
    *,
    enabled: bool,
    disabled_reason: str = "",
    rerun_receiver_types: Iterable[str] | None = None,
) -> dict[str, Any]:
    if not enabled:
        return _decompilation_summary([], reason=disabled_reason)

    scan_list = list(scans)
    attempts: list[dict[str, Any]] = []
    skipped_reasons: set[str] = set()
    rerun_receivers = {
        value.strip().casefold()
        for value in (rerun_receiver_types or ())
        if str(value).strip()
    }
    source_backed_receivers = {
        receiver
        for scan in scan_list
        for receiver in _all_wrapper_receivers(scan)
        if any(
            _has_source_backed_wrapper_evidence(other_scan, receiver)
            for other_scan in scan_list
        )
    }
    host: StaticAnalyzerHost | None = None
    host_error: str | None = None
    for scan in scan_list:
        root = Path(scan.project_root)
        external_sources = _external_wrapper_sources(scan)
        for receiver_type in sorted(external_sources, key=str.casefold):
            if receiver_type in source_backed_receivers:
                skipped_reasons.add("source_backed_evidence")
                continue
            csproj_path = _find_source_csproj(root, external_sources[receiver_type])
            if csproj_path is None:
                # Distinct from the host's "receiver_not_referenced" (a .csproj was
                # found but has no matching <Reference> for the receiver): here no
                # single .csproj could even be found/disambiguated for this call
                # site, so the host is never reached.
                attempts.append(
                    _not_attempted_decompilation_record(
                        receiver_type=receiver_type,
                        reason="csproj_not_found",
                    )
                )
                continue
            if host_error is not None:
                attempts.append(
                    _incomplete_decompilation_record(
                        receiver_type=receiver_type,
                        csproj_path=csproj_path,
                        reason="decompiler_host_unavailable",
                        detail=host_error,
                        attempted=False,
                    )
                )
                continue
            if host is None:
                try:
                    host = StaticAnalyzerHost.for_project(
                        Path(__file__).resolve().parent.parent
                    )
                    host.ensure_ready()
                except StaticAnalyzerHostError as exc:
                    host_error = str(exc)
                    attempts.append(
                        _incomplete_decompilation_record(
                            receiver_type=receiver_type,
                            csproj_path=csproj_path,
                            reason="decompiler_host_unavailable",
                            detail=host_error,
                            attempted=False,
                        )
                    )
                    continue
            try:
                response = host.decompile_wrapper(
                    csproj_path,
                    receiver_type,
                    rerun=receiver_type.casefold() in rerun_receivers,
                )
            except StaticAnalyzerHostError as exc:
                attempts.append(
                    _incomplete_decompilation_record(
                        receiver_type=receiver_type,
                        csproj_path=csproj_path,
                        reason="decompiler_failed",
                        detail=str(exc),
                        attempted=True,
                    )
                )
                continue
            proposals = response.get("contract_proposals") or []
            if isinstance(proposals, Mapping):
                proposals = [proposals]
            current_proposals = getattr(scan, "contract_proposals", None)
            if not isinstance(current_proposals, list):
                current_proposals = []
                scan.contract_proposals = current_proposals
            for proposal in proposals:
                if not isinstance(proposal, Mapping):
                    continue
                proposal_entry = dict(proposal)
                if not str(proposal_entry.get("evidence_kind") or "").strip():
                    proposal_entry["evidence_kind"] = DECOMPILED_AUTO_EVIDENCE_KIND
                if proposal_entry not in current_proposals:
                    current_proposals.append(proposal_entry)
            attempts.append(
                _decompilation_attempt_record(
                    response,
                    receiver_type=receiver_type,
                    csproj_path=csproj_path,
                )
            )

    reason = ",".join(sorted(skipped_reasons))
    return _decompilation_summary(attempts, reason=reason)


def _execution_sql_context(
    database_alias: str,
    db_server: str = "",
) -> Tuple[SpCatalog, Dict, str]:
    """Load one SQL cache scope and build its graph-backed SP catalog.

    ``db_server`` names the server whose cache to read. Requests that carry a
    ``db_server`` always pass it, so the lookup never depends on which other
    cache files happen to sit in the cache directory.
    """
    database_alias = str(database_alias or "").strip()
    cached = (
        sql_cache_store.load_cached(database_alias, "dbo", server=str(db_server or ""))
        if database_alias
        else None
    )
    graph = dict((cached or {}).get("sql_execution_graph") or {})
    graph_database = str(
        graph.get("database")
        or (cached or {}).get("database")
        or database_alias
        or ""
    )
    if graph_database and not graph.get("database"):
        graph["database"] = graph_database

    procedures_by_database: Dict[str, set[str]] = {}

    def add_procedure(database: str, name: str) -> None:
        database = database.strip()
        name = name.strip()
        if not database or not name or database.casefold() == "unknown":
            return
        procedures_by_database.setdefault(database, set()).add(name)

    def qualified_procedure_name(item: Mapping[str, object]) -> str:
        name = str(item.get("name") or "").strip()
        schema = str(item.get("schema") or "").strip()
        return f"{schema}.{name}" if schema and "." not in name else name

    for node in graph.get("nodes", []) or []:
        if node.get("type") == "stored_procedure":
            add_procedure(graph_database, qualified_procedure_name(node))

    for procedure in (cached or {}).get("procedures", []) or []:
        add_procedure(graph_database, qualified_procedure_name(procedure))

    schema = str((cached or {}).get("schema") or "dbo")
    return SpCatalog.from_databases(procedures_by_database, default_schema=schema), graph, graph_database


def load_sp_catalog(database: str = "") -> SpCatalog:
    """Return the read-only stored-procedure catalog for a SQL cache scope.

    No caller of this one has a server to give: the refresh path and
    tools/discover_external_wrappers.py only know a database name.
    """
    catalog, _, _ = _execution_sql_context(database)
    return catalog


def _require_sql_execution_graph(database: str, db_server: str = "") -> Tuple[Dict, Dict]:
    database = str(database or "").strip()
    if not database:
        raise ValueError(
            "database 不可為空；Gateway path analysis 需要指定 SQL execution graph cache。"
        )
    cached = sql_cache_store.load_cached(database, "dbo", server=str(db_server or ""))
    graph = (cached or {}).get("sql_execution_graph") if cached else None
    if not cached or not graph:
        raise SqlExecutionGraphRequiredError(
            database,
            reason="missing_or_invalid",
            message=(
                f"SQL execution graph cache 不存在或版本已失效：{database}。"
                "請重新執行 refresh_sql_cli <system_id> 或 POST /refresh_sql。"
            ),
        )
    return cached, dict(graph)


def _connection_source_database(value: Any) -> str:
    """One connection_sources entry's database name, whichever shape it is in.

    An entry is either the legacy plain database-name string, or a
    {"database": ..., "server": ...} mapping produced by the Web.config
    connection-string resolver (ticket 01) -- both shapes can coexist within
    the same ProjectScanResult (a freshly re-scanned file gets the new shape;
    an untouched file keeps whatever an older scan wrote), so every reader of
    connection_sources must tolerate both.
    """
    if isinstance(value, Mapping):
        return str(value.get("database") or "")
    return str(value or "")


def _is_resolved_connection_source(value: Any) -> bool:
    """True when a connection_sources entry carries a database the resolver worked out.

    The {"database": ..., "server": ...} mapping shape comes from the Web.config
    connection-string resolver and names the database the connection really opens. The
    legacy plain-string shape is a system_id-shaped label an older scan wrote, which says
    nothing about which database the connection reaches.
    """
    return isinstance(value, Mapping)


def _remap_connection_source(value: Any, database: str) -> Any:
    """Rebuild one connection_sources entry with a new resolved database.

    Preserves the entry's server when it carried one, so remapping a file's
    ambiguous multi-database sources onto the selected graph scope never
    drops the server ticket 01 threaded through connection_sources.
    """
    if isinstance(value, Mapping):
        return {"database": database, "server": value.get("server")}
    return database


def _execution_connection_sources(
    scan: ProjectScanResult,
    file_path: str,
    graph_database: str,
    database_aliases: Iterable[str] = (),
) -> Dict[str, Any]:
    """Resolve raw connection expressions for one file into the selected graph scope."""
    file_key = str(Path(file_path).resolve())
    sources = dict(getattr(scan, "connection_sources", {}).get(file_key, {}) or {})

    if not graph_database:
        return sources

    # One /analyze request selects one SQL cache scope. An entry whose database name is one
    # of that scope's aliases is rewritten to the scope's own name. This matches on name
    # alone, not on the (server, database, schema) identity ADR-0009 defines, because the
    # selected scope reaches this function as a bare name. Multiple distinct labels are kept
    # separate so one file cannot silently map cross-database connections to the graph.
    known_databases = {
        value.strip().casefold()
        for value in (*database_aliases, graph_database)
        if value and value.strip()
    }
    source_values = {
        _connection_source_database(value).strip().casefold()
        for value in sources.values()
        if _connection_source_database(value).strip()
    }
    if not source_values:
        return sources

    # A resolved entry names the database Web.config actually points at, so it survives
    # untouched unless its name is an alias of the selected scope. Remapping it would report
    # an invocation against the wrong database and lose the one fact that tells an analyst
    # which database is still unscanned. A legacy entry carries no such evidence, so a file
    # holding exactly one of them still resolves to the selected scope.
    holds_one_label = len(source_values) <= 1

    def remapped_onto_scope(value: Any) -> Any:
        names_the_scope = (
            _connection_source_database(value).strip().casefold() in known_databases
        )
        if names_the_scope or (holds_one_label and not _is_resolved_connection_source(value)):
            return _remap_connection_source(value, graph_database)
        return value

    return {
        expression: remapped_onto_scope(value)
        for expression, value in sources.items()
    }


def _method_chain_for_file(
    file_result,
    class_name: str,
    method_name: str,
) -> List[str]:
    """Return the longest deterministic same-file caller chain to a sink method."""
    methods: Dict[Tuple[str, str], object] = {}
    methods_by_name: Dict[str, List[Tuple[str, str]]] = {}
    for class_info in file_result.classes:
        for method in class_info.methods:
            key = (class_info.name, method.name)
            methods[key] = method
            methods_by_name.setdefault(method.name, []).append(key)

    sink_candidates = [(class_name, method_name)]
    if sink_candidates[0] not in methods:
        sink_candidates = methods_by_name.get(method_name, []) if not class_name else []
    if not sink_candidates:
        return [method_name]

    parents: Dict[Tuple[str, str], set[Tuple[str, str]]] = {}
    for caller_key, method in methods.items():
        caller_class, _ = caller_key
        for call in method.calls:
            target_name = str(call).rsplit(".", 1)[-1]
            qualifier = str(call).rsplit(".", 1)[0] if "." in str(call) else ""
            candidates = [
                candidate
                for candidate in methods_by_name.get(target_name, [])
                if candidate[0] == (qualifier or caller_class)
            ]
            if len(candidates) == 1:
                parents.setdefault(candidates[0], set()).add(caller_key)

    def expand(key: Tuple[str, str], visited: set[Tuple[str, str]]) -> List[List[str]]:
        if key in visited or not parents.get(key):
            return [[key[1]]]
        chains: List[List[str]] = []
        for parent in sorted(parents[key]):
            for prefix in expand(parent, visited | {key}):
                chains.append(prefix + [key[1]])
        return chains or [[key[1]]]

    candidates: List[List[str]] = []
    for sink in sorted(sink_candidates):
        candidates.extend(expand(sink, set()))
    return max(candidates, key=lambda chain: (len(chain), tuple(chain)))


def _merge_method_chains(
    caller_chain: List[str],
    invocation_chain: Tuple[str, ...],
) -> List[str]:
    """Append raw cross-boundary methods after the same-file caller chain."""
    if not invocation_chain:
        return caller_chain

    max_overlap = min(len(caller_chain), len(invocation_chain))
    overlap = 0
    for size in range(1, max_overlap + 1):
        if caller_chain[-size:] == list(invocation_chain[:size]):
            overlap = size
    return caller_chain + list(invocation_chain[overlap:])


def _method_class_chain_for_file(
    file_result,
    class_name: str,
    method_chain: List[str],
) -> List[str]:
    """Resolve method names to class hints without changing the public name chain."""
    methods_by_class: Dict[str, Dict[str, object]] = {
        class_info.name: {method.name: method for method in class_info.methods}
        for class_info in file_result.classes
    }
    classes_by_method: Dict[str, List[str]] = {}
    for class_info in file_result.classes:
        for method in class_info.methods:
            classes_by_method.setdefault(method.name, []).append(class_info.name)

    result: List[str] = []
    current_class = class_name
    for index, method_name in enumerate(method_chain):
        if index == 0:
            result.append(current_class)
            continue
        if method_name in methods_by_class.get(current_class, {}):
            result.append(current_class)
            continue
        matches = classes_by_method.get(method_name, [])
        if len(matches) == 1:
            current_class = matches[0]
            result.append(current_class)
            continue
        result.append("")
    return result


def _overlay_method_class_chain(
    method_chain: List[str],
    base_classes: List[str],
    invocation_chain: Tuple[str, ...],
    invocation_classes: Tuple[str, ...],
) -> List[str]:
    """Overlay gateway-known cross-file classes onto the full caller chain."""
    if not invocation_chain or not invocation_classes:
        return base_classes
    width = len(invocation_chain)
    start = -1
    for candidate in range(len(method_chain) - width + 1):
        if method_chain[candidate : candidate + width] == list(invocation_chain):
            start = candidate
    if start < 0:
        return base_classes
    result = list(base_classes)
    if len(invocation_classes) == 2 and width >= 2:
        caller_class, wrapper_class = invocation_classes
        if caller_class:
            for offset in range(width - 1):
                if start + offset < len(result):
                    result[start + offset] = caller_class
        if wrapper_class and start + width - 1 < len(result):
            result[start + width - 1] = wrapper_class
        return result
    for offset, class_hint in enumerate(invocation_classes[:width]):
        if class_hint and start + offset < len(result):
            result[start + offset] = class_hint
    return result


def _rated_execution_invocations(
    req: AnalyzeRequest,
    scan: ProjectScanResult,
    matched_files: List,
    root: Path,
) -> Tuple[List[DbInvocation], Dict[str, object]]:
    """Rate raw C# facts once so path discovery and evidence use the same join."""
    catalog, graph, graph_database = _execution_sql_context(
        str(getattr(req, "database", "") or ""),
        str(getattr(req, "db_server", "") or ""),
    )
    rated_invocations = []
    raw_by_file = getattr(scan, "db_invocations", {})
    external_wrapper_contract = load_external_wrapper_contract(
        getattr(req, "wrapper_contract", "")
        if isinstance(getattr(req, "wrapper_contract", ""), str)
        else ""
    )
    contract_registry = load_contract_registry()
    wrapper_review_exclusions = load_wrapper_review_exclusions(
        str(getattr(req, "database", "") or "")
    )

    for file_result in matched_files:
        file_key = str(Path(file_result.file_path).resolve())
        raw_invocations = raw_by_file.get(file_key, [])
        if not raw_invocations:
            continue
        gateway = CSharpAnalysisGateway(
            catalog,
            connection_sources=_execution_connection_sources(
                scan,
                file_result.file_path,
                graph_database,
                database_aliases=(
                    getattr(req, "database", ""),
                    getattr(req, "db_name", ""),
                ),
            ),
            external_wrapper_contract=external_wrapper_contract,
            external_wrapper_contracts=contract_registry,
            wrapper_review_exclusions=wrapper_review_exclusions,
        )
        relative_path = _rel(file_result.file_path, root)
        for invocation in gateway.resolve_direct_invocations(
            relative_path,
            raw_invocations,
            scan_root=str(root),
            explicit_contract=getattr(req, "wrapper_contract", "") or None,
        ):
            method_chain = _merge_method_chains(
                _method_chain_for_file(file_result, invocation.class_name, invocation.method_name),
                invocation.method_chain,
            )
            snapshot = _find_source_snapshot(scan, relative_path)
            method_class_chain = _overlay_method_class_chain(
                method_chain,
                _method_class_chain_for_file(
                    file_result,
                    invocation.class_name,
                    method_chain,
                ),
                invocation.method_chain,
                invocation.method_class_chain,
            )
            rated_invocations.append(
                replace(
                    invocation,
                    method_chain=tuple(method_chain),
                    method_class_chain=tuple(method_class_chain),
                    source_snapshot_hash=(snapshot.content_hash if snapshot else ""),
                )
            )

    return rated_invocations, graph


def _serialize_db_invocation(invocation: DbInvocation) -> Dict:
    caller_method = (
        invocation.method_chain[0]
        if invocation.method_chain
        else invocation.method_name
    )
    caller = (
        f"{invocation.class_name}.{caller_method}"
        if invocation.class_name
        else caller_method
    )
    serialized = {
        "class_name": invocation.class_name,
        "method_name": invocation.method_name,
        "database": invocation.database,
        "database_candidates": list(invocation.database_candidates),
        "database_attribution": (
            "resolved"
            if invocation.database
            else "candidate"
            if invocation.database_candidates
            else "unresolved"
        ),
        "procedure_name": invocation.procedure_name,
        "procedure_schema": invocation.procedure_schema,
        "raw_command_text": invocation.raw_command_text,
        "evidence": invocation.evidence.value,
        "reason": invocation.reason,
        "caller": caller,
        "caller_class": invocation.class_name,
        "caller_method": invocation.method_name,
        "source_span": {
            "relative_path": invocation.source.relative_path,
            "start_offset": invocation.source.start_offset,
            "end_offset": invocation.source.end_offset,
            "content_hash": invocation.source_snapshot_hash,
        },
        "method_chain": list(invocation.method_chain),
        "method_class_chain": list(invocation.method_class_chain),
        "external_wrapper_method": invocation.external_wrapper_method,
        "wrapper_contract": invocation.wrapper_contract,
        "wrapper_contract_source": invocation.wrapper_contract_source,
        "wrapper_receiver_type": invocation.wrapper_receiver_type,
        "wrapper_contract_candidates": list(invocation.wrapper_contract_candidates),
        "branch_context": list(invocation.branch_context),
        "source_snapshot_hash": invocation.source_snapshot_hash,
    }
    serialized.update(invocation_wrapper_evidence_fields(invocation))
    serialized["reason"] = invocation.reason
    serialized["unresolved_reason"] = (
        invocation.reason if invocation.evidence is not InvocationEvidence.PROVEN else ""
    )
    serialized["source_span"] = {
        "relative_path": invocation.source.relative_path,
        "start_offset": invocation.source.start_offset,
        "end_offset": invocation.source.end_offset,
        "content_hash": invocation.source_snapshot_hash,
    }
    serialized["source_snapshot_hash"] = invocation.source_snapshot_hash
    return serialized


def _wrapper_projection_fields(
    source: Mapping[str, Any],
    *,
    exclude: Iterable[str] = (),
) -> Dict[str, Any]:
    excluded = set(exclude)
    return {
        key: list(value) if isinstance(value, tuple) else value
        for key in (*WRAPPER_EVIDENCE_FIELDS, "unresolved_reason")
        if key in source and key not in excluded
        for value in (source[key],)
    }


def _invocation_response_fields(invocation: DbInvocation) -> Dict:
    serialized = _serialize_db_invocation(invocation)
    response = {
        key: serialized[key]
        for key in (
            "reason",
            "database",
            "database_candidates",
            "database_attribution",
            "caller",
            "caller_class",
            "caller_method",
            "external_wrapper_method",
            "wrapper_contract",
            "wrapper_contract_source",
            "wrapper_receiver_type",
            "wrapper_contract_candidates",
            "procedure_name",
            "procedure_schema",
            "raw_command_text",
            "branch_context",
            "source_span",
            "source_snapshot_hash",
            "unresolved_reason",
        )
    }
    response.update(_wrapper_projection_fields(serialized))
    return response


def _invocation_diagnostic(
    invocation: DbInvocation,
    **context: object,
) -> Dict:
    diagnostic = _serialize_db_invocation(invocation)
    diagnostic["diagnostic"] = True
    diagnostic.update(context)
    return diagnostic


def _build_program_execution_paths(
    req: AnalyzeRequest,
    scan: ProjectScanResult,
    matched_files: List,
    root: Path,
) -> Tuple[List[Dict], Dict[str, object]]:
    """Join one program's raw C# facts to the selected SQL execution graph."""
    if req.database:
        _require_sql_execution_graph(req.database, req.db_server)
    rated_invocations, graph = _rated_execution_invocations(req, scan, matched_files, root)

    paths = build_execution_paths(rated_invocations, graph)
    if not graph and not req.database:
        for path in paths:
            if path.get("unresolved_reason") == "not_in_resolved_catalog":
                path["unresolved_reason"] = "stored_procedure_not_in_graph"
                targets = list(path.get("sp_chain") or [])
                if targets and "." not in targets[0]:
                    targets[0] = f"dbo.{targets[0]}"
                path["unresolved_targets"] = targets[:1]
    compact_payload = build_compact_execution_path_payload(
        paths,
        max_paths=MAX_COMPACT_PATHS if req.max_paths is None else req.max_paths,
        question=req.question,
    )
    return paths, compact_payload


def get_path_evidence(req: PathEvidenceRequest) -> PathEvidenceResponse:
    """Expand one current Execution Path into source-backed, path-scoped evidence."""
    path_id = (req.path_id or "").strip()
    if not path_id:
        raise PathEvidenceError("invalid_path_id", "path_id 不可為空")

    cached, graph = _require_sql_execution_graph(req.database, req.db_server)

    roots = resolve_source(req)  # type: ignore[arg-type]
    if not roots:
        raise PathEvidenceError("source_not_found", "找不到 path evidence 的原始碼來源")
    scans = [_get_scan(root, refresh=req.refresh) for root in roots]
    scan = scans[0] if len(scans) == 1 else _merge_scans(scans)
    root = roots[0] if len(roots) == 1 else repo_dir(
        req.source.project if req.source else "",
        req.source.repo if req.source else "",
    )

    if req.program_names:
        program_bases = {_normalize_program(name) for name in req.program_names}
        matched_files = [
            result
            for result in scan.csharp_results
            if any(_file_matches(result.file_path, base) for base in program_bases)
        ]
    else:
        matched_files = list(scan.csharp_results)

    rated_invocations, joined_graph = _rated_execution_invocations(
        req, scan, matched_files, root  # type: ignore[arg-type]
    )
    selected_path: Dict | None = None
    selected_invocation: DbInvocation | None = None
    for invocation in rated_invocations:
        for candidate in build_execution_paths([invocation], joined_graph):
            if candidate.get("path_id") == path_id:
                selected_path = candidate
                selected_invocation = invocation
                break
        if selected_path is not None:
            break

    if selected_path is None or selected_invocation is None:
        missing_snapshot = any(
            _find_source_snapshot(scan, invocation.source.relative_path) is None
            for invocation in rated_invocations
        )
        raise PathEvidenceError(
            "stale_path" if missing_snapshot else "path_not_found",
            (
                "path 對應的 C# source snapshot 已不存在"
                if missing_snapshot
                else f"目前 source/SQL snapshot 找不到 path_id={path_id}"
            ),
        )

    return _materialize_path_evidence(
        selected_path,
        selected_invocation,
        scan,
        cached,
        joined_graph,
        db_server=req.db_server,
    )


def _materialize_path_evidence(
    path: Mapping[str, object],
    invocation: DbInvocation,
    scan: ProjectScanResult,
    cached: Mapping[str, object],
    graph: Mapping[str, object],
    db_server: str = "",
) -> PathEvidenceResponse:
    nodes = {
        str(node.get("id")): node
        for node in graph.get("nodes", []) or []
        if node.get("id")
    }
    module_ids = [str(value) for value in path.get("module_chain_ids", []) or []]

    module_objects: Dict[str, Dict] = {}
    stored_procedures: List[Dict] = []
    seen_stored_procedures: set[str] = set()
    for module_id in module_ids:
        node = nodes.get(module_id)
        if node is None or node.get("type") not in {"stored_procedure", "view", "function"}:
            raise PathEvidenceError("stale_path", f"SQL module identity 已不存在：{module_id}")
        sql_object = _cached_sql_object(cached, node)
        if sql_object is None:
            raise PathEvidenceError("stale_path", f"SQL module definition 已不存在：{module_id}")
        module_objects[module_id] = sql_object
        if node.get("type") == "stored_procedure" and module_id not in seen_stored_procedures:
            stored_procedures.append(sql_object)
            seen_stored_procedures.add(module_id)

    operation_id = str(path.get("terminal_operation_id") or "")
    operation = nodes.get(operation_id)
    if operation is not None and operation.get("type") not in {
        "dml_operation",
        "unresolved_dynamic_sql",
    }:
        raise PathEvidenceError("stale_path", f"terminal operation 已不存在：{operation_id}")
    if operation is None and path.get("evidence") not in {"unresolved", "likely"}:
        raise PathEvidenceError("stale_path", f"terminal operation 已不存在：{operation_id}")

    operation_evidence: Dict = {}
    if operation is not None:
        operation_evidence = dict(operation)
        source_location = dict(operation.get("source") or {})
        operation_module_id = str(operation.get("module_id") or "")
        operation_module = module_objects.get(operation_module_id)
        if operation_module is not None and source_location:
            current_definition = str(operation_module.get("definition") or "")
            recorded_length = source_location.get("module_definition_length")
            if recorded_length is not None:
                try:
                    length_matches = int(recorded_length) == len(current_definition)
                except (TypeError, ValueError) as exc:
                    raise PathEvidenceError(
                        "stale_path",
                        f"SQL module definition length 記錄已失效：{operation_module_id}（{exc}）",
                    ) from exc
                if not length_matches:
                    raise PathEvidenceError(
                        "stale_path",
                        "SQL module definition 長度已變更，offset 已失效："
                        f"{operation_module_id}（記錄 {recorded_length}，目前 {len(current_definition)}）",
                    )
            try:
                source_text = _slice_utf16(
                    current_definition,
                    int(source_location.get("start_offset") or 0),
                    int(source_location.get("length") or 0),
                )
            except (TypeError, ValueError) as exc:
                raise PathEvidenceError(
                    "stale_path",
                    f"SQL operation source span 已失效：{exc}",
                ) from exc
            if source_text:
                operation_evidence["source_text"] = source_text

    csharp_methods = _source_methods_for_path(scan, invocation, path)
    literal_sp_candidates = []
    if (
        invocation.evidence is not InvocationEvidence.PROVEN
        and invocation.procedure_name
        and invocation.raw_command_text is not None
    ):
        candidate = _serialize_db_invocation(invocation)
        database_alias = str(
            path.get("database")
            or cached.get("database")
            or graph.get("database")
            or invocation.database
            or ""
        ).strip()
        if database_alias:
            definitions = fetch_sp_definitions(
                [invocation.raw_command_text or invocation.procedure_name],
                database_alias=database_alias,
                db_server=db_server or None,
            )
            if definitions:
                definition = definitions[0]
                candidate.update(definition)
                if definition.get("dependency_source") == "execution_graph":
                    candidate["sql_cache_matched"] = True
                    candidate["sql_cache_database"] = database_alias
        literal_sp_candidates.append(candidate)
    views: List[Dict] = []
    functions: List[Dict] = []
    referenced_object_ids: set[str] = set()
    if operation is not None:
        for relationship in graph.get("relationships", []) or []:
            if relationship.get("type") != "reads" or relationship.get("source") != operation_id:
                continue
            target_id = str(relationship.get("target") or "")
            target_node = nodes.get(target_id)
            if target_node and target_node.get("type") in {"view", "function"}:
                referenced_object_ids.add(target_id)

        for function_name in operation.get("function_references", []) or []:
            target_id = _find_graph_object_id(nodes, "function", str(function_name))
            if target_id:
                referenced_object_ids.add(target_id)

    for object_id in sorted(referenced_object_ids):
        object_node = nodes[object_id]
        sql_object = _cached_sql_object(cached, object_node)
        if sql_object is None:
            raise PathEvidenceError(
                "stale_path",
                f"directly used SQL object definition 已不存在：{object_id}",
            )
        if object_node.get("type") == "view":
            views.append(sql_object)
        else:
            functions.append(sql_object)

    wrapper_projection = _wrapper_projection_fields(
        path,
        exclude=("evidence_status", "source_span", "source_snapshot_hash", "unresolved_reason"),
    )
    return PathEvidenceResponse(
        path_id=str(path.get("path_id") or ""),
        entry_method=str(path.get("entry_method") or ""),
        method_chain=list(path.get("method_chain", []) or []),
        database=str(path.get("database") or ""),
        database_candidates=list(path.get("database_candidates", []) or []),
        database_attribution=str(
            path.get("database_attribution") or "unresolved"
        ),
        caller=str(path.get("caller") or ""),
        caller_class=str(path.get("caller_class") or ""),
        caller_method=str(path.get("caller_method") or ""),
        procedure_name=str(path.get("procedure_name") or ""),
        procedure_schema=str(path.get("procedure_schema") or ""),
        branch_context=list(path.get("branch_context", []) or []),
        source_span=dict(path.get("source_span", {}) or {}),
        source_snapshot_hash=str(
            (path.get("source_span", {}) or {}).get("content_hash") or ""
        ),
        sp_chain=list(path.get("sp_chain", []) or []),
        conditions=list(path.get("conditions", []) or []),
        risk_flags=list(path.get("risk_flags", []) or []),
        evidence_status=str(path.get("evidence") or "unresolved"),
        confirmed=bool(path.get("confirmed", False)),
        reason=str(path.get("reason") or ""),
        unresolved_reason=str(path.get("unresolved_reason") or ""),
        unresolved_targets=list(path.get("unresolved_targets", []) or []),
        csharp_methods=csharp_methods,
        literal_sp_candidates=literal_sp_candidates,
        stored_procedures=stored_procedures,
        operations=[operation_evidence] if operation_evidence else [],
        views=views,
        functions=functions,
        **wrapper_projection,
    )


def _source_methods_for_path(
    scan: ProjectScanResult,
    invocation: DbInvocation,
    path: Mapping[str, object],
) -> List[Dict]:
    snapshot = _find_source_snapshot(scan, invocation.source.relative_path)
    if snapshot is None:
        raise PathEvidenceError(
            "stale_path",
            f"C# source snapshot 已不存在：{invocation.source.relative_path}",
        )

    methods: List[Dict] = []
    seen_spans: set[tuple[str, str, int, int]] = set()
    method_names = list(path.get("method_chain", []) or [])
    if not method_names:
        method_names = [invocation.method_name]
    external_wrapper_method = str(path.get("external_wrapper_method") or "").casefold()
    method_classes = list(path.get("method_class_chain", []) or [])
    for index, method_name in enumerate(method_names):
        class_hint = method_classes[index] if index < len(method_classes) else ""
        if not class_hint and index == 0:
            class_hint = invocation.class_name
        source_match = _find_method_source(
            scan,
            snapshot,
            method_name,
            class_hint,
        )
        if source_match is None:
            if external_wrapper_method and method_name.casefold() == external_wrapper_method:
                continue
            raise PathEvidenceError(
                "stale_path",
                f"C# method span 已不存在或不唯一：{method_name}",
            )
        method_snapshot, span = source_match
        key = (
            method_snapshot.relative_path,
            span.class_name,
            span.start_offset,
            span.end_offset,
        )
        if key in seen_spans:
            continue
        try:
            source = method_snapshot.source_for(span)
        except ValueError as exc:
            raise PathEvidenceError("stale_path", str(exc)) from exc
        seen_spans.add(key)
        methods.append(
            {
                "file": method_snapshot.relative_path,
                "content_hash": method_snapshot.content_hash,
                "class": span.class_name,
                "method": span.method_name,
                "start_offset": span.start_offset,
                "end_offset": span.end_offset,
                "source": source,
            }
        )
    return methods


def _find_source_snapshot(scan: ProjectScanResult, relative_path: str):
    normalized = str(relative_path).replace("\\", "/").casefold()
    for key, snapshot in getattr(scan, "source_snapshots", {}).items():
        if str(key).replace("\\", "/").casefold() == normalized:
            return snapshot
    return None


def _find_method_source(scan, preferred_snapshot, method_name: str, class_hint: str):
    preferred_matches = [
        span
        for span in preferred_snapshot.method_spans
        if span.method_name == method_name
        and (not class_hint or span.class_name == class_hint)
    ]
    if preferred_matches:
        return (preferred_snapshot, preferred_matches[0]) if len(preferred_matches) == 1 else None

    matches = [
        (snapshot, span)
        for key, snapshot in sorted(
            getattr(scan, "source_snapshots", {}).items(),
            key=lambda item: str(item[0]).casefold(),
        )
        if snapshot is not preferred_snapshot
        for span in snapshot.method_spans
        if span.method_name == method_name
        and (not class_hint or span.class_name == class_hint)
    ]
    return matches[0] if len(matches) == 1 else None


def _cached_sql_object(cached: Mapping[str, object], node: Mapping[str, object]) -> Dict | None:
    collection = {
        "stored_procedure": "procedures",
        "view": "views",
        "function": "functions",
    }.get(str(node.get("type") or ""))
    if collection is None:
        return None
    node_schema = str(node.get("schema") or "dbo").casefold()
    node_name = str(node.get("name") or "").casefold()
    for item in cached.get(collection, []) or []:
        item_dict = dict(item)
        item_schema, item_name = _split_sql_object_name(
            item_dict.get("name", ""),
            str(item_dict.get("schema") or node.get("schema") or "dbo"),
        )
        if item_schema.casefold() == node_schema and item_name.casefold() == node_name:
            return item_dict
    return None


def _find_graph_object_id(
    nodes: Mapping[str, Mapping[str, object]],
    object_type: str,
    object_name: str,
) -> str:
    schema, name = _split_sql_object_name(object_name, "dbo")
    for node_id, node in nodes.items():
        if (
            node.get("type") == object_type
            and str(node.get("schema") or "dbo").casefold() == schema.casefold()
            and str(node.get("name") or "").casefold() == name.casefold()
        ):
            return node_id
    return ""


def _split_sql_object_name(value: object, default_schema: str) -> tuple[str, str]:
    cleaned = str(value or "").replace("[", "").replace("]", "").replace('"', "").strip()
    parts = [part.strip() for part in cleaned.split(".") if part.strip()]
    if not parts:
        return default_schema, ""
    if len(parts) == 1:
        return default_schema, parts[0]
    return parts[-2], parts[-1]


def _slice_utf16(text: str, start_offset: int, length: int) -> str:
    if length <= 0:
        return ""
    start = _utf16_index(text, start_offset)
    end = _utf16_index(text, start_offset + length)
    return text[start:end]


def _utf16_index(text: str, offset: int) -> int:
    if offset < 0:
        raise ValueError("negative UTF-16 offset")
    units = 0
    for index, character in enumerate(text):
        if units >= offset:
            return index
        units += 2 if ord(character) > 0xFFFF else 1
    if units == offset:
        return len(text)
    raise ValueError("UTF-16 offset outside SQL definition")


# ─────────────────────────────────────────────────────────────────────────────
# 主分析
# ─────────────────────────────────────────────────────────────────────────────

def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    """依 program_names 過濾掃描結果，組成回應（純靜態，無 AI）。"""
    roots = resolve_source(req)
    scans = [_get_scan(r, refresh=getattr(req, "refresh", False)) for r in roots]
    scan = scans[0] if len(scans) == 1 else _merge_scans(scans)
    root = roots[0] if len(roots) == 1 else repo_dir(
        req.source.project if req.source else "", req.source.repo if req.source else ""
    )

    programs: List[ProgramAnalysis] = []
    not_found: List[str] = []

    for raw_name in req.program_names:
        program_base = _normalize_program(raw_name)

        # 1) 比對 C# 解析結果（取得檔案、框架、方法）
        matched_files = [
            r for r in scan.csharp_results if _file_matches(r.file_path, program_base)
        ]

        # 2) Join C# database facts through the Gateway; legacy relations are not
        # part of the formal response path.
        rated_invocations: List[DbInvocation] = []
        if matched_files:
            rated_invocations, _ = _rated_execution_invocations(
                req,
                scan,
                matched_files,
                root,
            )
        sp_names: List[str] = []
        for invocation in rated_invocations:
            if (
                invocation.evidence is InvocationEvidence.PROVEN
                and invocation.procedure_name
                and invocation.procedure_name not in sp_names
            ):
                sp_names.append(invocation.procedure_name)
        database_invocations = [
            _serialize_db_invocation(invocation)
            for invocation in rated_invocations
        ]
        diagnostics = [
            _invocation_diagnostic(invocation)
            for invocation in rated_invocations
            if invocation.evidence is not InvocationEvidence.PROVEN
        ]

        table_names: List[str] = []
        for rel in scan.table_relations:
            if _file_matches(rel.csharp_file, program_base) and rel.table_name not in table_names:
                table_names.append(rel.table_name)

        if not matched_files and not sp_names and not table_names:
            not_found.append(raw_name)
            continue

        # 取第一個對應檔案作為主要檔案資訊
        file_path = ""
        framework = ""
        methods: List[Dict] = []
        if matched_files:
            primary = matched_files[0]
            file_path = _rel(primary.file_path, root)
            framework = getattr(primary.framework, "value", str(primary.framework))
            for fr in matched_files:
                for cls in fr.classes:
                    for m in cls.methods:
                        methods.append({"name": m.name, "class": cls.name})

        # 程式碼片段（S2b）：依方法位置擷取，可由 include_snippets 關閉
        code_snippets = []
        if req.include_snippets and matched_files:
            for fr in matched_files:
                code_snippets.extend(extract_snippets(fr, root))

        # 呼叫鏈（S3）：程式內部方法呼叫路徑
        call_chains = build_call_chains(matched_files) if matched_files else []

        # FK 連動資料表（S3，盡力而為：無資料庫則為空）
        related_tables: List[str] = []
        if req.fk_depth > 0 and table_names:
            related_tables = resolve_fk_related(
                table_names,
                database_alias=req.database or None,
                depth=req.fk_depth,
                db_server=req.db_server or None,
                db_name=req.db_name or None,
            )

        # SP 完整定義（選用，需 DB 連線；讓 AI 看得到 SP 實際邏輯）
        sp_definitions: List[Dict] = []
        if req.include_sp_defs and sp_names:
            sp_definitions = fetch_sp_definitions(
                sp_names,
                database_alias=req.database or None,
                db_server=req.db_server or None,
                db_name=req.db_name or None,
            )

        # SQL View 完整定義（選用）：table_names 裡如果其實是 View（而非一般資料表），
        # 從本機 SQL 快取（sql_cache_store，由 /refresh_sql 落地）取得其完整定義，
        # 讓 AI 看得到 View 實際查詢邏輯，而不只是一個表名。只讀本機快取，不即時連線
        # （見 view_fetcher.py 說明），避免每個表名都額外連線判斷是否為 View。
        view_definitions: List[Dict] = []
        if req.include_sp_defs and table_names:
            view_definitions = fetch_view_definitions(
                table_names,
                database_alias=req.database or None,
                db_server=req.db_server or None,
            )

        # 使用者定義函數（UDF）完整定義（選用）：靜態解析沒有專門的「UDF 呼叫」
        # 關聯（沒有專門的 database invocation fact），改用「比對」取代「解析」——把該程式自己
        # 內嵌的 SQL 查詢文字（matched_files 的 sql_queries）跟本機 SQL 快取的整庫
        # UDF 名單比對，只有真的以函數呼叫形式出現在這支程式 SQL 裡的 UDF 才會附上
        # 完整定義，做到「依程式篩選相關 UDF」而不是整庫塞給 AI（見 udf_fetcher.py）。
        udf_definitions: List[Dict] = []
        if req.include_sp_defs and matched_files:
            sql_texts = [
                q.query_text
                for fr in matched_files
                for q in fr.sql_queries
                if getattr(q, "query_text", "")
            ]
            if sql_texts:
                udf_definitions = fetch_udf_definitions(
                    sql_texts,
                    database_alias=req.database or None,
                    db_server=req.db_server or None,
                )

        # 跨程式呼叫參照展開（類似 Copilot 跟隨參照）：
        # 找出這支程式呼叫了、但定義在「其他檔案」的方法，帶入相關程式碼片段。
        related_programs: List[Dict] = []
        if req.expand_depth > 0 and matched_files:
            related = expand_related_programs(
                scan.csharp_results,
                matched_files,
                depth=req.expand_depth,
                max_programs=req.expand_max_programs,
            )
            for rel in related:
                entry: Dict = {
                    "file": _rel(rel["file"], root),
                    "class": rel["class"],
                    "method": rel["method"],
                    "called_by": rel["called_by"],
                    "depth": rel["depth"],
                }
                if req.include_snippets:
                    target_fr = next(
                        (r for r in scan.csharp_results if r.file_path == rel["file"]), None
                    )
                    if target_fr:
                        snips = extract_snippets(
                            target_fr, root, method_filter={rel["method"]}
                        )
                        if snips:
                            entry["lines"] = snips[0].lines
                            entry["snippet"] = snips[0].text
                related_programs.append(entry)

        # View 層資訊（選用）：ASPXParser/RazorParser/VueParser 解析出的控制項/指示詞/
        # Tag Helpers/元件等摘要。預設關閉（include_view_layer=False）以維持既有行為與
        # prompt 長度，只有明確要求時才附上。
        view_layer: List[Dict] = []
        if req.include_view_layer:
            for fr in scan.aspx_results + scan.razor_results + scan.vue_results:
                if _file_matches(fr.file_path, program_base):
                    view_layer.append(_view_layer_summary(fr, root))

        execution_paths: List[Dict] = []
        compact_execution_paths: List[Dict] = []
        compact_execution_paths_meta: Dict[str, int] = {}
        if req.include_execution_paths and matched_files:
            execution_paths, compact_payload = _build_program_execution_paths(
                req,
                scan,
                matched_files,
                root,
            )
            compact_execution_paths = compact_payload["paths"]
            compact_execution_paths_meta = {
                key: int(compact_payload[key])
                for key in ("total_paths", "returned_paths", "omitted_paths")
            }

        programs.append(
            ProgramAnalysis(
                program=raw_name,
                file=file_path,
                framework=framework,
                methods=methods,
                stored_procedures=sp_names,
                tables=table_names,
                related_tables=related_tables,
                call_chains=call_chains,
                code_snippets=code_snippets,
                sp_definitions=sp_definitions,
                view_definitions=view_definitions,
                udf_definitions=udf_definitions,
                database_invocations=database_invocations,
                diagnostics=diagnostics,
                related_programs=related_programs,
                view_layer=view_layer,
                execution_paths=execution_paths,
                compact_execution_paths=compact_execution_paths,
                compact_execution_paths_meta=compact_execution_paths_meta,
            )
        )

    return AnalyzeResponse(
        programs=programs,
        not_found=not_found,
        source_root=str(root),
    )


def _rel(file_path: str, root: Path) -> str:
    """盡量回傳相對 root 的路徑，失敗則回傳原路徑。"""
    try:
        return Path(file_path).resolve().relative_to(root.resolve()).as_posix()
    except Exception:
        return str(file_path).replace("\\", "/")


def _source_file_for_span(
    scan: ProjectScanResult,
    root: Path,
    relative_path: str,
) -> str:
    """Resolve an Execution Path source span back to its scanned C# file."""
    normalized = str(relative_path).replace("\\", "/").casefold()
    for result in scan.csharp_results:
        candidate = str(Path(_rel(result.file_path, root))).replace("\\", "/").casefold()
        if candidate == normalized:
            return result.file_path
    matches = [
        result.file_path
        for result in scan.csharp_results
        if Path(result.file_path).name.casefold() == Path(relative_path).name.casefold()
    ]
    return matches[0] if len(matches) == 1 else ""


def _prefer_table_match(
    matches_by_file: Dict[str, TableMatchProgram],
    candidate: TableMatchProgram,
) -> None:
    """Keep the strongest access fact when one file contributes many paths."""
    current = matches_by_file.get(candidate.file)
    if current is None or _table_match_rank(candidate) > _table_match_rank(current):
        matches_by_file[candidate.file] = candidate


def _table_match_rank(match: TableMatchProgram) -> tuple[int, int, int]:
    access_type = (match.access_type or "").upper()
    is_write = access_type in {"WRITE", "WRITE_INDIRECT", "INSERT", "UPDATE", "DELETE", "SELECT_INTO"}
    is_indirect = access_type.endswith("_INDIRECT")
    return (
        2 if is_write else 1 if access_type.startswith("READ") else 0,
        1 if not is_indirect else 0,
        1 if match.via_sp else 0,
    )


def find_by_sp(req: FindBySPRequest) -> FindBySPResponse:
    """反查「哪些程式呼叫了這支 SP」，使用 Gateway invocation 與 SQL Execution Graph，無 AI。

    req.cache_only=True（預設）時，若這個系統實際會掃描到的路徑「還沒有掃描快取」
    就直接跳過（skipped=True），不觸發 Azure clone、也不觸發任何掃描 —— 因為呼叫端
    （spec-rag 的 search_specs_by_sp 工具）通常不知道這支 SP 屬於哪個系統，得逐系統
    嘗試，若每個未分析過的系統都重新掃一次會太貴。

    注意：不能只用 repo_manager.is_cloned(project, repo) 判斷「這個系統是否已分析
    過」——多個系統可能共用同一個 Azure repo、只是 path 子資料夾不同（例如
    Y-Docs_TTPUR 與 Y-DOCs_TTRDQ 都指向 repo=Y-DOCs，只差 path=TTPUR/TTRDQ）。
    is_cloned() 只檢查 repo 根目錄有沒有 .git，只要「任一」共用該 repo 的系統先
    分析過，其他共用系統的 is_cloned() 也會回傳 True，即使它自己的子路徑從沒被
    掃描過、快取根本不存在 —— 那樣會誤判成「已分析過」而略過 cache_only 檢查，
    導致直接掉進下面的 get_or_scan() 觸發一次全新的完整掃描（就是使用者看到
    「明明 cache_only=True 卻還是重新掃描」的成因）。
    正確做法：比對「這個系統實際會用到的掃描快取」是否存在（scan_store.has_cache()，
    以解析後的實際路徑雜湊為鍵），而不是只看 repo 有沒有 clone 過。
    """
    sp_name = (req.sp_name or "").strip()
    if not sp_name:
        return FindBySPResponse(sp_name=sp_name, matches=[])

    project = req.source.project if req.source else ""
    repo = req.source.repo if req.source else ""
    sub_path = req.source.path if req.source else ""

    if req.cache_only and not req.refresh:
        # 在不觸發 clone/pull 的前提下，推算這個系統實際會掃描的路徑清單
        # （與 resolve_scan_roots() 內部邏輯一致：子路徑存在才用子路徑，
        # 否則用整個 repo 根目錄），只用來檢查快取是否已存在。若 source.path 是
        # 多個子資料夾清單，必須每個都已有快取才算「已分析過」，只要有任一個
        # 尚未掃描就跳過，避免回傳部分過時的比對結果。
        candidate_roots = peek_scan_roots({"project": project, "repo": repo, "path": sub_path})
        if not all(has_cache(r) for r in candidate_roots):
            return FindBySPResponse(sp_name=sp_name, matches=[], skipped=True)

    source = {
        "project": project,
        "repo": repo,
        "branch": req.source.branch if req.source else "",
        "path": sub_path,
    }
    roots = resolve_scan_roots(source, refresh=req.refresh)
    scans = [_get_scan(r, refresh=req.refresh) for r in roots]
    scan = scans[0] if len(scans) == 1 else _merge_scans(scans)
    root = roots[0] if len(roots) == 1 else repo_dir(project, repo)

    sp_lower = normalize_procedure_name(sp_name)
    matches: List[SPMatchProgram] = []
    diagnostics: List[Dict] = []
    seen_invocations: set[tuple[str, int, int]] = set()
    if not req.database:
        raise ValueError(
            "find_by_sp 需要 database 以載入 SQL execution graph；"
            "請提供 system_id 並先執行 refresh_sql_cli。"
        )
    # FindBySPRequest 沒有 db_server 欄位，這裡只能給 database；
    # sql_cache_store.resolve_server() 會從磁碟回推唯一一份同名快取。
    _cached, _graph = _require_sql_execution_graph(req.database)
    rated_invocations, _ = _rated_execution_invocations(
        req,
        scan,
        list(scan.csharp_results),
        root,
    )
    for invocation in rated_invocations:
        if (
            not invocation.procedure_name
            or normalize_procedure_name(invocation.procedure_name) != sp_lower
        ):
            continue
        csharp_file = _source_file_for_span(
            scan,
            root,
            invocation.source.relative_path,
        )
        identity = (
            csharp_file or invocation.source.relative_path,
            invocation.source.start_offset,
            invocation.source.end_offset,
        )
        if identity in seen_invocations:
            continue
        seen_invocations.add(identity)
        if invocation.evidence is not InvocationEvidence.PROVEN:
            diagnostics.append(
                _invocation_diagnostic(
                    invocation,
                    requested_sp=sp_name,
                )
            )
            continue
        if not csharp_file:
            continue
        match_fields = _invocation_response_fields(invocation)
        match_fields.update(
            {
                "program": _normalize_program(Path(csharp_file).name),
                "file": _rel(csharp_file, root),
            }
        )
        matches.append(SPMatchProgram(**match_fields))

    return FindBySPResponse(
        sp_name=sp_name,
        matches=matches,
        diagnostics=diagnostics,
        source_root=str(root),
    )


def _normalize_table(name: str) -> str:
    """正規化資料表名稱供 inline SQL facts 與 SQL graph query 比對。

    例如 `[dbo].[Customers]`／`dbo.Customers`／`Customers` 都會正規化成 `customers`。
    """
    cleaned = (name or "").replace("[", "").replace("]", "").strip()
    return cleaned.rsplit(".", 1)[-1].lower()


def find_by_table(req: FindByTableRequest) -> FindByTableResponse:
    """反查「哪些程式存取了這張資料表」，結合 inline SQL facts 與 SQL Execution Graph，無 AI。

    inline SQL facts 保留直接出現在 C# SQL 文字中的表存取；SP/View/Function
    lineage 則必須由 Gateway invocation join 到 SQL Execution Graph 取得。詳見
    find_by_sp() 的 docstring 說明 cache_only 為何不能只用 repo_manager.is_cloned() 判斷。
    """
    table_name = (req.table_name or "").strip()
    if not table_name:
        return FindByTableResponse(table_name=table_name, matches=[])

    project = req.source.project if req.source else ""
    repo = req.source.repo if req.source else ""
    sub_path = req.source.path if req.source else ""

    if req.cache_only and not req.refresh:
        candidate_roots = peek_scan_roots({"project": project, "repo": repo, "path": sub_path})
        if not all(has_cache(r) for r in candidate_roots):
            return FindByTableResponse(table_name=table_name, matches=[], skipped=True)

    source = {
        "project": project,
        "repo": repo,
        "branch": req.source.branch if req.source else "",
        "path": sub_path,
    }
    roots = resolve_scan_roots(source, refresh=req.refresh)
    scans = [_get_scan(r, refresh=req.refresh) for r in roots]
    scan = scans[0] if len(scans) == 1 else _merge_scans(scans)
    root = roots[0] if len(roots) == 1 else repo_dir(project, repo)

    table_norm = _normalize_table(table_name)
    matches_by_file: Dict[str, TableMatchProgram] = {}
    diagnostics: List[Dict] = []
    for rel in scan.table_relations:
        if _normalize_table(rel.table_name) != table_norm:
            continue
        database = str(getattr(rel, "database", "") or "")
        caller_class = str(getattr(rel, "class_name", "") or "")
        caller_method = str(getattr(rel, "method_name", "") or "")
        candidate = TableMatchProgram(
            program=_normalize_program(Path(rel.csharp_file).name),
            file=_rel(rel.csharp_file, root),
            # Inline C# SQL remains a direct source fact; SQL-module relationships
            # are queried from the Execution Graph below.
            access_type=rel.access_type,
            reason="inline_sql_source_fact",
            evidence_status="not_applicable",
            evidence_reason="inline_sql",
            database=database,
            database_attribution="resolved" if database else "unresolved",
            caller=(
                f"{caller_class}.{caller_method}"
                if caller_class
                else caller_method
            ),
            caller_class=caller_class,
            caller_method=caller_method,
        )
        _prefer_table_match(matches_by_file, candidate)

    # Stored-procedure access is joined through Gateway invocations and the graph.
    # Do not fall back to SQL dependency dictionaries or definition-text guesses.
    if req.database:
        # FindByTableRequest 同樣沒有 db_server 欄位；理由見 find_by_sp。
        _sql_cache, graph = _require_sql_execution_graph(req.database)
        rated_invocations, graph = _rated_execution_invocations(
            req,
            scan,
            list(scan.csharp_results),
            root,
        )
        diagnostics.extend(
            _invocation_diagnostic(invocation, requested_table=table_name)
            for invocation in rated_invocations
            if invocation.evidence is not InvocationEvidence.PROVEN
        )
        for access_record in query_table_accesses(
            graph,
            rated_invocations,
            table_name,
            access="all",
        ):
            source_span = access_record.get("source_span") or {}
            relative_path = str(source_span.get("relative_path") or "")
            csharp_file = _source_file_for_span(scan, root, relative_path)
            if not csharp_file:
                continue
            is_write = bool(access_record.get("is_write"))
            is_indirect = bool(access_record.get("is_indirect"))
            operation_type = str(access_record.get("operation_type") or "")
            access_type = (
                "WRITE_INDIRECT"
                if is_write and is_indirect
                else operation_type
                if is_write
                else "READ_INDIRECT"
                if is_indirect
                else "READ"
            )
            sp_chain = list(access_record.get("sp_chain") or [])
            wrapper_projection = _wrapper_projection_fields(
                access_record,
                exclude=("evidence_status", "source_span", "source_snapshot_hash"),
            )
            candidate = TableMatchProgram(
                program=_normalize_program(Path(csharp_file).name),
                file=_rel(csharp_file, root),
                via_sp=True,
                access_type=access_type,
                path_id=str(access_record.get("path_id") or ""),
                entry_method=str(access_record.get("entry_method") or ""),
                sp_chain=sp_chain,
                evidence_status=str(access_record.get("evidence") or "unresolved"),
                reason=str(access_record.get("reason") or ""),
                database=str(access_record.get("database") or ""),
                database_candidates=list(access_record.get("database_candidates") or []),
                database_attribution=str(
                    access_record.get("database_attribution") or "unresolved"
                ),
                caller=str(access_record.get("caller") or ""),
                caller_class=str(access_record.get("caller_class") or ""),
                caller_method=str(access_record.get("caller_method") or ""),
                procedure_name=str(access_record.get("procedure_name") or ""),
                procedure_schema=str(access_record.get("procedure_schema") or ""),
                branch_context=list(access_record.get("branch_context") or []),
                source_span=dict(source_span),
                source_snapshot_hash=str(source_span.get("content_hash") or ""),
                operation_type=operation_type,
                **wrapper_projection,
            )
            _prefer_table_match(matches_by_file, candidate)

    if req.write_only:
        write_types = {
            "WRITE",
            "WRITE_INDIRECT",
            "INSERT",
            "UPDATE",
            "DELETE",
            "SELECT_INTO",
        }
        matches_by_file = {
            key: match
            for key, match in matches_by_file.items()
            if match.access_type in write_types
        }

    return FindByTableResponse(
        table_name=table_name,
        matches=sorted(matches_by_file.values(), key=lambda item: (item.program, item.file)),
        diagnostics=diagnostics,
        source_root=str(root),
    )


_LOCATE_OBJECT_KINDS = {"sp", "table"}


def locate_object(req: LocateObjectRequest) -> LocateObjectResponse:
    """從磁碟上每一份 SQL 快取的 Object Location Index 猜哪些 Database 可能持有這個
    物件名稱，一律不開任何 SQL 快取本體（見 ADR-0012）。

    kind="sp" 用 normalize_procedure_name 正規化查詢名稱，比對索引的 stored_procedures
    桶——跟 find_by_sp() 比對 invocation 用同一個函式。kind="table" 用
    sql_cache_store.normalize_table_name（= graph_queries._normalize_table）正規化，
    比對索引的 tables 桶——跟 find_by_table() 經 SQL Execution Graph 比對表名用同一個
    函式。索引因此不會剪掉一個對應端點其實找得到的名字。

    一份索引新鮮且持有這個名稱 → matched；快取存在但索引依 staleness 規則判定缺席
    （缺失/讀不了/舊/版本不符/身分不符）→ unindexed；索引新鮮但不持有這個名稱 →
    兩份清單都不出現，那就是剪枝本身，是權威結果而非不確定。
    """
    kind = (req.kind or "").strip().casefold()
    if kind not in _LOCATE_OBJECT_KINDS:
        raise ValueError(f"kind 必須是 sp 或 table，收到：{req.kind!r}")

    object_name = (req.object_name or "").strip()
    normalized = (
        normalize_procedure_name(object_name)
        if kind == "sp"
        else sql_cache_store.normalize_table_name(object_name)
    )

    matched: List[LocatedDatabase] = []
    unindexed: List[LocatedDatabase] = []
    indexes_consulted = 0

    for row in sql_cache_store.list_caches():
        try:
            identity = sql_cache_store.CacheIdentity.of(row.server, row.database, row.schema)
        except ValueError:
            # A file whose name doesn't fit the {server}__{database}__{schema}
            # shape (see list_caches()'s own docstring): no identity to report
            # a caller could match against a Declared Database Dependency, so
            # it is neither counted nor listed — not a cache this endpoint can
            # answer for, in either direction.
            continue
        indexes_consulted += 1
        located = LocatedDatabase(server=identity.server, database=identity.database)
        index = sql_cache_store.load_object_location_index(identity)
        if index is None:
            unindexed.append(located)
            continue
        bucket = index.stored_procedures if kind == "sp" else index.tables
        if normalized in bucket:
            matched.append(located)
        # else: a fresh index that does not hold the name — pruned, appears in neither list.

    return LocateObjectResponse(
        object_name=object_name,
        kind=kind,
        matched=matched,
        unindexed=unindexed,
        indexes_consulted=indexes_consulted,
    )


def flow_chain(req: FlowChainRequest) -> FlowChainResponse:
    """組出「關係鏈」候選清單（純靜態組裝，見 flow_chain_builder.py，無 AI 判斷）。

    cache_only 的 skip 判斷邏輯與 find_by_sp()/find_by_table() 完全對稱
    （多子資料夾 source 需全部已有快取才算「已分析過」），詳見 find_by_sp()
    的 docstring 說明為何不能只用 repo_manager.is_cloned() 判斷。
    """
    project = req.source.project if req.source else ""
    repo = req.source.repo if req.source else ""
    sub_path = req.source.path if req.source else ""

    if req.cache_only and not req.refresh:
        candidate_roots = peek_scan_roots({"project": project, "repo": repo, "path": sub_path})
        if not all(has_cache(r) for r in candidate_roots):
            return FlowChainResponse(direction=req.direction, skipped=True)

    source = {
        "project": project,
        "repo": repo,
        "branch": req.source.branch if req.source else "",
        "path": sub_path,
    }
    roots = resolve_scan_roots(source, refresh=req.refresh)
    scans = [_get_scan(r, refresh=req.refresh) for r in roots]
    scan = scans[0] if len(scans) == 1 else _merge_scans(scans)
    root = roots[0] if len(roots) == 1 else repo_dir(project, repo)

    database_alias = req.database or None
    db_server = req.db_server or None
    db_name = req.db_name or None

    if req.direction == "backward":
        rated_invocations: List[DbInvocation] = []
        execution_graph: Dict[str, object] = {}
        if req.database:
            _cached, execution_graph = _require_sql_execution_graph(req.database, req.db_server)
            rated_invocations, execution_graph = _rated_execution_invocations(
                req,
                scan,
                list(scan.csharp_results),
                root,
            )
        diagnostics = [
            _invocation_diagnostic(invocation, requested_table=req.table_name)
            for invocation in rated_invocations
            if invocation.evidence is not InvocationEvidence.PROVEN
        ]
        chains = flow_chain_builder.build_backward_chains(
            scan,
            root,
            req.table_name,
            column_name=req.column_name or None,
            database_alias=database_alias,
            graph=execution_graph,
            invocations=rated_invocations,
        )
        return FlowChainResponse(
            direction="backward",
            backward_chains=chains,
            diagnostics=diagnostics,
            source_root=str(root),
        )

    # direction == "forward"（預設）
    program_base = _normalize_program(req.program_name)
    matched_files = [r for r in scan.csharp_results if _file_matches(r.file_path, program_base)]
    if not matched_files:
        return FlowChainResponse(direction="forward", forward_chain=None, source_root=str(root))

    rated_invocations: List[DbInvocation] = []
    execution_graph: Dict[str, object] = {}
    if req.database:
        _cached, execution_graph = _require_sql_execution_graph(req.database, req.db_server)
        rated_invocations, execution_graph = _rated_execution_invocations(
            req,
            scan,
            matched_files,
            root,
        )

    forward = flow_chain_builder.build_forward_chain(
        matched_files,
        [],
        root,
        req.anchor_method,
        database_alias=database_alias,
        db_server=db_server,
        db_name=db_name,
        max_sp_depth=req.max_sp_depth,
        fk_depth=req.fk_depth,
        graph=execution_graph,
        invocations=rated_invocations,
    )
    return FlowChainResponse(
        direction="forward",
        forward_chain=forward,
        diagnostics=list((forward or {}).get("diagnostics", []) or []),
        source_root=str(root),
    )


def _normalize_refresh_program_path(name: str) -> str:
    normalized = str(name or "").strip().replace("\\", "/").casefold()
    normalized = re.sub(r"/+", "/", normalized).lstrip("./")
    for suffix in _KNOWN_SUFFIXES:
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)]
            break
    return normalized.strip("/")


def _refresh_file_matches(file_path: str, root: Path, program_name: str) -> bool:
    try:
        relative_path = Path(file_path).resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        relative_path = Path(file_path).name
    candidate = _normalize_refresh_program_path(relative_path)
    requested = _normalize_refresh_program_path(program_name)
    if not candidate or not requested:
        return False
    if "/" in requested:
        return candidate == requested or candidate.endswith(f"/{requested}")
    return candidate.rsplit("/", 1)[-1] == requested


def _unique_refresh_paths(file_paths: Iterable[str]) -> List[str]:
    unique: Dict[str, str] = {}
    for file_path in file_paths:
        resolved = str(Path(file_path).resolve())
        unique.setdefault(resolved.casefold(), resolved)
    return list(unique.values())


def _cached_csharp_files(scan: ProjectScanResult, root: Path) -> List[str]:
    """Return every C# path represented by the current cache snapshot.

    Raw analyzer facts can outlive a failed parser result, so stale-file
    reconciliation must not rely on ``csharp_results`` alone.
    """
    cached_paths: List[str] = [
        result.file_path
        for result in scan.csharp_results
    ]
    cached_paths.extend(str(path) for path in getattr(scan, "db_invocations", {}))
    cached_paths.extend(str(path) for path in getattr(scan, "connection_sources", {}))
    cached_paths.extend(
        str(Path(root) / str(snapshot.relative_path).replace("/", os.sep))
        for snapshot in getattr(scan, "source_snapshots", {}).values()
    )
    return _unique_refresh_paths(cached_paths)


def _relative_refresh_path(file_path: str, root: Path) -> str:
    try:
        return Path(file_path).resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(Path(file_path).resolve())


def _is_refresh_wrapper_record(record: Mapping[str, object]) -> bool:
    """Return whether a raw scan fact describes a wrapper observation."""
    invocation_kind = str(record.get("invocation_kind") or "").casefold()
    return invocation_kind == "source_wrapper" or bool(
        str(record.get("wrapper_method_name") or "").strip()
        or str(record.get("wrapper_receiver_type") or "").strip()
    )


def _refresh_wrapper_snapshot_hash(
    scan: ProjectScanResult,
    relative_path: str,
) -> str:
    normalized = str(relative_path).replace("\\", "/").casefold()
    for path, snapshot in getattr(scan, "source_snapshots", {}).items():
        if str(path).replace("\\", "/").casefold() == normalized:
            return str(getattr(snapshot, "content_hash", "") or "")
    return ""


def _refresh_wrapper_location(
    record: Mapping[str, object],
    source_file: str,
    relative_path: str,
    snapshot_hash: str,
    evidence: Optional[DbInvocation] = None,
    observation: Optional[Mapping[str, object]] = None,
) -> Dict[str, object]:
    command_text = record.get("command_text")
    location: Dict[str, object] = {
        "file": relative_path,
        "line": int(record.get("line_number") or 0),
        "start_offset": int(record.get("start_offset") or 0),
        "end_offset": int(record.get("end_offset") or 0),
        "command_text_kind": str(record.get("command_text_kind") or ""),
        "command_text": str(command_text) if command_text is not None else "",
        "wrapper_mode": str(record.get("wrapper_mode") or ""),
        "source_file": str(source_file),
        "source_snapshot_hash": snapshot_hash,
    }
    if observation is not None:
        location.update(dict(observation))
    elif evidence is None:
        location.update(
            {
                "evidence_status": "not_applicable",
                "evidence_reason": "inline_sql",
                "procedure_name": "",
                "database": "",
                "database_candidates": [],
            }
        )
    else:
        location.update(
            {
                "evidence_status": evidence.evidence.value,
                "evidence_reason": evidence.reason,
                "procedure_name": evidence.procedure_name or "",
                "database": evidence.database or "",
                "database_candidates": list(evidence.database_candidates),
            }
        )
    return location


def reconcile_refresh_wrappers(
    scans: Iterable[ProjectScanResult],
    *,
    explicit_contract: Any = "",
    contract_registry: Optional[Mapping[str, Any]] = None,
    database: str = "",
    contract_preflight: Optional[Mapping[str, Any]] = None,
    contract_preflight_failure_reason: str = "",
) -> Dict[str, object]:
    """Reconcile raw wrapper facts from already completed source scans.

    The wrapper boundary can report contract classification and review gaps
    without opening a database connection.  When ``database`` identifies a
    local SQL cache, its stored-procedure catalog is used for evidence rating;
    an empty or unavailable scope keeps source-only evidence semantics.
    """
    observations_by_key: Dict[tuple, Dict[str, object]] = {}
    scan_summaries: List[Dict[str, object]] = []
    total_wrapper_calls = 0
    total_semantic_binding_resolved = 0
    if isinstance(explicit_contract, str):
        normalized_contract: Any = explicit_contract.strip()
    elif isinstance(explicit_contract, (list, tuple)):
        normalized_contract = [
            str(item).strip()
            for item in explicit_contract
            if isinstance(item, str) and str(item).strip()
        ]
    else:
        normalized_contract = explicit_contract
    # refresh 流程只知道 database 名稱（沒有請求帶 db_server 進來），
    # 由 sql_cache_store.resolve_server() 回推。
    catalog = load_sp_catalog(database)
    wrapper_review_exclusions = load_wrapper_review_exclusions(database)

    for scan in scans:
        root = Path(scan.project_root)
        external_wrapper_contract = (
            load_external_wrapper_contract(normalized_contract)
            if contract_registry is None
            else None
        )
        wrapper_calls = 0
        root_observation_keys: set[tuple] = set()
        raw_by_file = getattr(scan, "db_invocations", {}) or {}
        for source_file in sorted(raw_by_file, key=lambda item: str(item).casefold()):
            relative_path = _rel(str(source_file), root)
            snapshot_hash = _refresh_wrapper_snapshot_hash(scan, relative_path)
            gateway = CSharpAnalysisGateway(
                catalog,
                connection_sources=_execution_connection_sources(
                    scan,
                    str(source_file),
                    "",
                ),
                external_wrapper_contract=external_wrapper_contract,
                external_wrapper_contracts=contract_registry,
                wrapper_review_exclusions=wrapper_review_exclusions,
            )
            records = raw_by_file.get(source_file, []) or []
            for record in records:
                if not isinstance(record, Mapping) or not _is_refresh_wrapper_record(record):
                    continue
                observation = gateway.reconcile_wrapper_observation(
                    relative_path,
                    record,
                    scan_root=str(root),
                    source_snapshot_hash=snapshot_hash,
                    explicit_contract=normalized_contract or None,
                )
                if observation["status"] == "not_applicable":
                    # A reviewed wrapper-review exclusion: a maintainer already
                    # confirmed this exact (receiver, method) pair is not a
                    # database wrapper call, so it should not occupy the
                    # wrapper-call totals or the observation list at all --
                    # not just drop out of the printed review detail.
                    continue
                wrapper_calls += 1
                if observation.get("semantic_binding_accepted") is True:
                    # `semantic_binding_accepted` is the gateway's own verdict, not a raw
                    # call-site fact: the compiler bound this call to one method symbol *and*
                    # that symbol's containing assembly matched the contract's -- a call whose
                    # bound symbol was rejected (assembly mismatch) never sets this, so it is
                    # never counted here even though the raw record still carries the rejected
                    # identity.
                    total_semantic_binding_resolved += 1
                if (
                    contract_preflight_failure_reason
                    and observation.get("wrapper_kind") == "external_wrapper"
                    and observation.get("source_available") is not True
                ):
                    observation = _mark_contract_preflight_failed(
                        observation,
                        contract_preflight_failure_reason,
                    )
                evidence_status = str(observation["evidence_status"])
                evidence_reason = str(observation["evidence_reason"])
                wrapper_class = str(record.get("wrapper_class_name") or "").strip()
                receiver_type = str(record.get("wrapper_receiver_type") or "").strip()
                method_name = str(record.get("wrapper_method_name") or "").strip()
                group_key = (
                    observation["scan_root"],
                    wrapper_class,
                    receiver_type,
                    method_name,
                    observation["wrapper_kind"],
                    observation["status"],
                    observation["contract"],
                    observation["selection_source"],
                    observation["classification_reason"],
                    evidence_status,
                    evidence_reason,
                    wrapper_observation_identity(observation),
                    (
                        observation["source_span"]["relative_path"],
                        observation["source_span"]["start_offset"],
                        observation["source_span"]["end_offset"],
                        snapshot_hash,
                    )
                    if observation["review_candidate"]
                    else (),
                )
                root_observation_keys.add(group_key)
                group = observations_by_key.get(group_key)
                if group is None:
                    reason = str(observation["classification_reason"] or "")
                    group = {
                        "wrapper_class": wrapper_class,
                        "receiver_type": receiver_type,
                        "wrapper_method": method_name,
                        "observed_method": method_name,
                        "observed_methods": [method_name] if method_name else [],
                        "methods": [method_name] if method_name else [],
                        **observation,
                        "evidence_status": evidence_status,
                        "evidence_reason": evidence_reason,
                        "reason": reason,
                        "unresolved_reason": reason,
                        "review_reasons": [reason] if reason else [],
                        "calls": 0,
                        "locations": [],
                    }
                    observations_by_key[group_key] = group
                group["calls"] = int(group["calls"]) + 1
                locations = group["locations"]
                assert isinstance(locations, list)
                locations.append(
                    _refresh_wrapper_location(
                        record,
                        str(source_file),
                        relative_path,
                        snapshot_hash,
                        observation=observation,
                    )
                )

        total_wrapper_calls += wrapper_calls
        scan_summaries.append(
            {
                "root": str(root),
                "cache": True,
                "wrapper_calls": wrapper_calls,
                "observation_groups": len(root_observation_keys),
                "groups": len(root_observation_keys),
            }
        )

    observations = sorted(
        observations_by_key.values(),
        key=lambda item: (
            str(item["scan_root"]).casefold(),
            str(item["receiver_type"]).casefold(),
            str(item["wrapper_method"]).casefold(),
            str(item["status"]),
        ),
    )
    observed_receiver_types = sorted(
        {
            str(item["receiver_type"])
            for item in observations
            if str(item["receiver_type"])
        },
        key=str.casefold,
    )
    observed_methods = sorted(
        {
            str(method)
            for item in observations
            for method in item["observed_methods"]
            if str(method)
        },
        key=str.casefold,
    )
    selected_contracts = sorted(
        {
            str(item["selected_contract"])
            for item in observations
            if str(item["selected_contract"])
        },
        key=str.casefold,
    )
    selection_sources = sorted(
        {
            str(item["selection_source"])
            for item in observations
            if str(item["selection_source"])
        },
        key=str.casefold,
    )
    candidate_contracts = sorted(
        {
            str(candidate)
            for item in observations
            for candidate in item["candidate_contracts"]
            if str(candidate)
        },
        key=str.casefold,
    )
    review_items = [item for item in observations if item["review_candidate"]]
    review_reasons = sorted(
        {
            str(reason)
            for item in observations
            for reason in item["review_reasons"]
            if str(reason)
        },
        key=str.casefold,
    )
    statuses = sorted(
        {str(item["status"]) for item in observations if str(item["status"])},
        key=str.casefold,
    )
    unresolved_statuses = {
        "ambiguous_contract",
        "unresolved_contract",
        "unresolved_method",
        "receiver_mismatch",
    }
    return {
        "source_scan_count": len(scan_summaries),
        "scans": scan_summaries,
        "observed_receiver_types": observed_receiver_types,
        "observed_methods": observed_methods,
        "classification_statuses": statuses,
        "evidence_statuses": sorted(
            {
                str(item["evidence_status"])
                for item in observations
                if str(item["evidence_status"])
            },
            key=str.casefold,
        ),
        "selected_contracts": selected_contracts,
        "selection_sources": selection_sources,
        "candidate_contracts": candidate_contracts,
        "observations": observations,
        "review_items": review_items,
        "review_reasons": review_reasons,
        "contract_preflight": dict(contract_preflight or {}),
        "contract_onboarding_status": str(
            (contract_preflight or {}).get("contract_onboarding_status") or ""
        ),
        "contract_preflight_failed": bool(
            (contract_preflight or {}).get("contract_preflight_failed")
        ),
        "totals": {
            "wrapper_calls": total_wrapper_calls,
            "semantic_binding_resolved": total_semantic_binding_resolved,
            "observation_groups": len(observations),
            "source_wrappers": sum(
                item["wrapper_kind"] == "source_wrapper" for item in observations
            ),
            "external_wrappers": sum(
                item["wrapper_kind"] == "external_wrapper" for item in observations
            ),
            "auto_selected": sum(
                item["status"] == "auto_selected" for item in observations
            ),
            "explicit_selected": sum(
                item["status"] == "explicit_selected" for item in observations
            ),
            "unresolved": sum(
                item["status"] in unresolved_statuses for item in observations
            ),
            "evidence_proven": sum(
                item["evidence_status"] == InvocationEvidence.PROVEN.value
                for item in observations
            ),
            "evidence_likely": sum(
                item["evidence_status"] == InvocationEvidence.LIKELY.value
                for item in observations
            ),
            "evidence_unresolved": sum(
                item["evidence_status"] == InvocationEvidence.UNRESOLVED.value
                for item in observations
            ),
            "evidence_not_applicable": sum(
                item["evidence_status"] == "not_applicable"
                for item in observations
            ),
            "review_candidates": len(review_items),
        },
    }


def _mark_contract_preflight_failed(
    observation: Mapping[str, Any],
    reason: str,
) -> Dict[str, Any]:
    marked = dict(observation)
    marked.update(
        {
            "contract_preflight_status": "failed",
            "contract_preflight_failed": True,
            "contract_preflight_reason": reason,
            "preflight_failure_reason": reason,
        }
    )
    return marked


_ONBOARDING_STATUSES_ELIGIBLE_FOR_COMMIT = frozenset({"created", "reused"})


def _contract_revision_reference(
    preflight_registry: Optional[Mapping[str, Any]],
    formal_selector: Any,
) -> Dict[str, Any]:
    """Build the Analysis Manifest's Contract Revision Reference for a run.

    Historical manifests must never change meaning when a later refresh
    changes the registry, so this only reports the fingerprint/status/report
    references the current run actually used -- it never rewrites a prior
    manifest.
    """
    contracts = (
        (preflight_registry or {}).get("contracts", {})
        if isinstance(preflight_registry, Mapping)
        else {}
    )
    if isinstance(formal_selector, str):
        names = [formal_selector] if formal_selector else []
    elif isinstance(formal_selector, (list, tuple)):
        names = [str(item) for item in formal_selector if str(item)]
    else:
        names = []
    references: Dict[str, Any] = {}
    for name in names:
        entry = contracts.get(name) if isinstance(contracts, Mapping) else None
        if not isinstance(entry, Mapping):
            continue
        references[name] = {
            "contract_fingerprint": str(entry.get("contract_fingerprint") or ""),
            "signature_version": str(entry.get("signature_version") or ""),
            "contract_status": str(entry.get("status") or ""),
            "implementation_snapshot": (
                list(entry.get("implementation_snapshots") or [])[-1]
                if entry.get("implementation_snapshots")
                else None
            ),
            "comparison_report_reference": str(entry.get("comparison_report") or ""),
            "system_binding_revision": (
                entry.get("lifecycle", {}).get("revision")
                if isinstance(entry.get("lifecycle"), Mapping)
                else None
            ),
        }
    return references


def _select_refresh_files(
    file_paths: Iterable[str],
    root: Path,
    program_names: List[str],
) -> List[str]:
    return _unique_refresh_paths(
        file_path
        for file_path in file_paths
        if any(_refresh_file_matches(file_path, root, name) for name in program_names)
    )


def _view_extensions(scanner: ProjectScanner) -> set[str]:
    extensions: set[str] = set()
    if "aspx" in scanner.parsers:
        extensions.update({".aspx", ".ascx"})
    if "razor" in scanner.parsers:
        extensions.add(".cshtml")
    if "vue" in scanner.parsers:
        extensions.add(".vue")
    return extensions


def refresh_programs(root: Path, program_names: List[str]) -> ProgramRefreshResult:
    """Refresh only files matching the requested programs in one scan root."""
    requested = list(dict.fromkeys(name.strip() for name in program_names if name.strip()))
    _require_current_program_cache(root)
    scan = get_or_scan(root, refresh=False)

    scanner = ProjectScanner(project_root=str(root))
    current_csharp_files = _unique_refresh_paths(scanner.find_csharp_files())
    cached_csharp_files = _cached_csharp_files(scan, root)
    current_targets = _select_refresh_files(current_csharp_files, root, requested)
    cached_targets = _select_refresh_files(cached_csharp_files, root, requested)
    current_keys = {path.casefold() for path in current_targets}
    removed_csharp_files = [
        path for path in cached_targets if path.casefold() not in current_keys
    ]

    view_extensions = _view_extensions(scanner)
    current_view_files = _unique_refresh_paths(
        scanner._find_files_by_extensions(view_extensions)
        if view_extensions
        else []
    )
    cached_view_files = _unique_refresh_paths(
        result.file_path
        for results in (
            scan.aspx_results,
            scan.razor_results,
            scan.vue_results,
        )
        for result in results
    )
    current_view_targets = _select_refresh_files(current_view_files, root, requested)
    cached_view_targets = _select_refresh_files(cached_view_files, root, requested)
    current_view_keys = {path.casefold() for path in current_view_targets}
    removed_view_files = [
        path for path in cached_view_targets if path.casefold() not in current_view_keys
    ]

    matched_programs = [
        name
        for name in requested
        if any(
            _refresh_file_matches(file_path, root, name)
            for file_path in [
                *current_targets,
                *removed_csharp_files,
                *current_view_targets,
                *removed_view_files,
            ]
        )
    ]
    not_found = [name for name in requested if name not in matched_programs]
    if not matched_programs:
        return ProgramRefreshResult(scan=scan, not_found=not_found)

    previous_csharp_count = len(cached_targets)
    scanner.refresh_csharp_files(scan, current_targets, removed_csharp_files)
    if current_view_targets or removed_view_files:
        scanner.refresh_view_files(scan, current_view_targets, removed_view_files)

    scan.total_files = max(
        0,
        scan.total_files - previous_csharp_count + len(current_targets),
    )
    scan.scanned_files = max(
        0,
        scan.scanned_files - previous_csharp_count + len(current_targets),
    )
    scan.failed_files = max(0, scan.total_files - scan.scanned_files)
    scan.scan_time = datetime.now()
    scan.calculate_statistics()
    save_scan(root, scan)

    updated_files = [
        _relative_refresh_path(file_path, root)
        for file_path in [*current_targets, *current_view_targets]
    ]
    removed_files = [
        _relative_refresh_path(file_path, root)
        for file_path in [*removed_csharp_files, *removed_view_files]
    ]
    return ProgramRefreshResult(
        scan=scan,
        updated_files=updated_files,
        removed_files=removed_files,
        matched_programs=matched_programs,
        not_found=not_found,
    )


def refresh_source(
    source: dict,
    program_names: List[str] | None = None,
    wrapper_contract: Any = "",
    database: str = "",
    rerun_receiver_types: Iterable[str] | None = None,
) -> dict:
    """Pull source and refresh either the whole system or selected programs.

    rerun_receiver_types: receiver types (e.g. "SQLFunc") for which a maintainer
    explicitly requests a fresh decompilation attempt, bypassing any cached
    incomplete/failed attempt for that DLL only (US21). An unnamed receiver type
    still reuses its cached attempt untouched.
    """
    roots = resolve_scan_roots(source, refresh=True)
    requested = list(
        dict.fromkeys(name.strip() for name in (program_names or []) if name.strip())
    )
    root = roots[0] if len(roots) == 1 else repo_dir(
        (source or {}).get("project", ""), (source or {}).get("repo", "")
    )

    if not requested:
        scans = [get_or_scan(r, refresh=True) for r in roots]
        scan = scans[0] if len(scans) == 1 else _merge_scans(scans)
        scope = "system"
        partial = False
        updated_files: List[str] = []
        removed_files: List[str] = []
        matched_programs: List[str] = []
        not_found: List[str] = []
    else:
        for refresh_root in roots:
            _require_current_program_cache(refresh_root)
        partial_results = [refresh_programs(r, requested) for r in roots]
        scans = []
        updated_files = []
        removed_files = []
        matched_programs = []
        not_found = list(requested)
        full_fallback = False
        for result in partial_results:
            if isinstance(result, ProgramRefreshResult):
                scans.append(result.scan)
                updated_files.extend(result.updated_files)
                removed_files.extend(result.removed_files)
                matched_programs.extend(result.matched_programs)
                not_found = [name for name in not_found if name in result.not_found]
                full_fallback = full_fallback or result.full_refresh
            else:
                scans.append(result)
                matched_programs.extend(requested)
                not_found = []
        scan = scans[0] if len(scans) == 1 else _merge_scans(scans)
        scope = "system" if full_fallback else "program"
        partial = not full_fallback
        matched_programs = list(dict.fromkeys(matched_programs))
        not_found = [name for name in requested if name not in matched_programs]

    configured_selector = wrapper_contract
    if configured_selector is None or (
        isinstance(configured_selector, str) and not configured_selector.strip()
    ):
        configured_selector = load_system_contract_selector(database)
    registry = load_contract_registry()
    selector_state = normalize_contract_selector(configured_selector, registry)
    # Decision (US2, spec.md "Implementation Decisions"): a selector that was
    # explicitly given but fails to resolve (selector_contract_not_found /
    # selector_type_invalid) is deliberately treated the same as a valid
    # selector here, not as "unspecified" — normalize_contract_selector()
    # reports its status as "unspecified" but still sets `reason` for this
    # case, so gating on `not selector_state.reason` (in addition to status)
    # keeps decompile-based onboarding fail-closed for it. The operator
    # explicitly configured something; auto-decompile must never second-guess
    # that by silently substituting a guess for a selector they got wrong.
    decompilation_enabled = (
        not requested
        and selector_state.status == "unspecified"
        and not selector_state.reason
    )
    if requested:
        decompilation_disabled_reason = "program_scope"
    elif selector_state.status == "valid":
        decompilation_disabled_reason = "selector_configured"
    elif selector_state.reason:
        decompilation_disabled_reason = selector_state.reason
    else:
        decompilation_disabled_reason = ""
    decompilation_summary = _populate_decompilation_proposals(
        scans,
        enabled=decompilation_enabled,
        disabled_reason=decompilation_disabled_reason,
        rerun_receiver_types=rerun_receiver_types,
    )
    preflight = run_contract_preflight(
        scans,
        selector=configured_selector,
        registry=registry,
        allow_onboarding=not partial,
    )
    preflight_summary = preflight.to_dict()
    wrapper_summary = reconcile_refresh_wrappers(
        scans,
        explicit_contract=preflight.formal_selector,
        contract_registry=preflight.formal_registry or {"contracts": {}},
        database=database,
        contract_preflight=preflight_summary,
        contract_preflight_failure_reason=(
            preflight.reason if preflight.failed else ""
        ),
    )
    wrapper_summary["decompilation"] = decompilation_summary

    # Registry/catalog writes happen only after formal classification and
    # wrapper reconciliation above have already succeeded, and only for a
    # staged proposal complete enough to reuse or create a contract.
    contract_transaction_summary: Dict[str, Any] = {"status": "not_required"}
    if (
        not partial
        and str(database or "").strip()
        and preflight.onboarding_status in _ONBOARDING_STATUSES_ELIGIBLE_FOR_COMMIT
    ):
        try:
            contract_transaction_summary = commit_staged_contract_transaction(
                staged_registry=preflight.staged_registry or {"contracts": {}},
                trigger="refresh",
                staged_selector=preflight.staged_selector,
                system_id=database,
                registry_path=CONTRACT_TRANSACTION_REGISTRY_PATH,
                catalog_path=CONTRACT_TRANSACTION_CATALOG_PATH,
                source_revision={
                    "scan_root": str(root),
                    "source_commit": cached_commit(root) or "",
                },
            )
        except ContractTransactionError as exc:
            contract_transaction_summary = {
                "status": "failed",
                "error_code": exc.code,
                "error": str(exc),
            }

    database_invocation_count = len(scan.iter_formal_sp_invocations())
    inline_table_fact_count = len(scan.table_relations)
    return {
        "source_root": str(root),
        "files": len(scan.csharp_results),
        "database_invocations": database_invocation_count,
        "inline_table_facts": inline_table_fact_count,
        "scope": scope,
        "partial": partial,
        "requested_programs": requested,
        "updated_programs": matched_programs,
        "not_found": not_found,
        "updated_files": list(dict.fromkeys(updated_files)),
        "removed_files": list(dict.fromkeys(removed_files)),
        "wrapper_summary": wrapper_summary,
        "semantic_binding_availability": getattr(scan, "semantic_binding_availability", []) or [],
        "contract_transaction": contract_transaction_summary,
        "analysis_manifest": {
            "contract_revision_reference": _contract_revision_reference(
                preflight.formal_registry,
                preflight.formal_selector,
            ),
        },
        # Deprecated aliases retained for existing clients during migration.
        "sp_relations": database_invocation_count,
        "table_relations": inline_table_fact_count,
    }


def refresh_sql_source(
    database: str,
    server: str,
    db_name: str,
    schema: str = "dbo",
    user_id: str = "",
    password: str = "",
    progress_callback: Callable[[str, int, int, str], None] | None = None,
) -> dict:
    """更新 SQL 快取指令：重新連線 SQL Server 撈取整庫 SP/View/Function 定義與
    資料表 Schema，覆寫本機落地快取（data/sql_cache/）。

    database：顯示／工單用簡稱，不參與快取鍵計算。
    server/db_name：實際連線目標，也是快取鍵的兩個組成，由呼叫端（catalog）提供；缺一時
    get_or_dump()→SQLAnalyzer 會直接報錯，不嘗試連線。
    user_id/password：這台伺服器的掃描帳密覆寫，兩者都有值才生效（ADR-0010）。

    回傳 {database, db_schema, procedures, views, functions, tables} 數量摘要；
    SQL Execution Graph 會與 object definitions 一起落地到 SQL cache。
    """
    from .sql_cache_store import get_or_dump

    data = get_or_dump(
        database,
        schema=schema,
        refresh=True,
        server=server,
        db_name=db_name,
        user_id=user_id,
        password=password,
        progress_callback=progress_callback,
    )
    return {
        "database": data.get("database", database),
        "db_schema": data.get("schema", schema),
        "procedures": len(data.get("procedures", [])),
        "views": len(data.get("views", [])),
        "functions": len(data.get("functions", [])),
        "tables": len(data.get("tables", [])),
    }
