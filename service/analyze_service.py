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
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, NamedTuple, Optional, Sequence, Set, Tuple

from code_analyzer.azure_fetcher import AzureFetchError
from code_analyzer.connection_source_entry import database_of
from canonical_object_identity import ObjectName, bare_key, full_key, parse, part_key
from code_analyzer.csharp_analysis_gateway import (
    CSharpAnalysisGateway,
    DbInvocation,
    InvocationEvidence,
    SpCatalog,
    WRAPPER_EVIDENCE_FIELDS,
    build_observed_call_evidence_index,
    invocation_wrapper_evidence_fields,
    load_external_wrapper_contract,
    load_wrapper_review_exclusions,
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
from .sp_fetcher import fetch_sp_definitions
from .view_fetcher import fetch_view_definitions
from .udf_fetcher import fetch_udf_definitions
from .execution_path_builder import (
    MAX_COMPACT_PATHS,
    build_compact_execution_path_payload,
)
from .graph_queries import filter_table_accesses
from .table_match import (
    UNPROVEN_SCHEMA,
    TableQuestion,
    is_write_access,
    names_another_database,
    names_listed_node,
)
from .program_screen import (
    ProgramScreen,
    resolve_program_screens,
    resolve_razor_page_screens,
    razor_page_model_path,
    view_identity,
)
from .shared_component import (
    VIEW_COMPONENT,
    SharedComponentContribution,
    resolve_shared_components,
)
from .reference_expander import expand_related_programs
from .repo_manager import repo_dir, resolve_scan_roots
from .scan_store import cache_status, cached_commit, get_or_scan, save_scan
from . import sql_cache_store
from .request_context import Skipped, build_request_context, merge_scans as _merge_scans
from .request_context_adapters import CacheIdentityResult, CacheStore, RealCacheStore, RealScanStore, ScanStore
from .derived_execution_evidence import (
    DerivedExecutionEvidence,
    DerivedExecutionEvidenceScope,
    EvidenceSource,
    evidence_for_scope,
    _execution_sql_context,
    _execution_connection_sources,
    _method_chain_for_file,
    _overlay_method_class_chain,
    _find_source_snapshot,
    _rel,
)
from . import flow_chain_builder
from . import inline_table_relations
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


class AmbiguousDatabaseError(ValueError):
    """A lookup names a Database that has a SQL cache on more than one host.

    It is the error form of ``sql_cache_store.AmbiguousServer``: that value says
    which hosts hold the Database, and this error carries it to the HTTP layer.
    """

    code = "ambiguous_database"

    def __init__(self, ambiguous: sql_cache_store.AmbiguousServer) -> None:
        self.database = ambiguous.database
        self.servers = list(ambiguous.servers)
        super().__init__(
            f"資料庫 {self.database} 在多台主機上都有 SQL 快取"
            f"（{', '.join(self.servers)}）；請用 db_server 指定主機。"
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


@dataclass(frozen=True)
class _ProgramResolution:
    """One unit of analysis for one requested program name.

    A Program Screen resolution names the view the code resolved to, the
    controllers that hold its actions, and those actions (ADR-0019). The
    legacy resolution keeps the base-name file match the WebForms path has
    always used, and filters no method.
    """

    program_base: str
    matched_files: List[Any] = field(default_factory=list)
    screen: Optional[ProgramScreen] = None
    view_result: Optional[Any] = None

    @property
    def is_program_screen(self) -> bool:
        return self.screen is not None

    @property
    def action_names(self) -> Optional[Set[str]]:
        """The actions this unit reports, or None when it filters no method."""
        if self.screen is None:
            return None
        return {action.name.lower() for action in self.screen.actions}

    def owns_file(self, file_path: str) -> bool:
        if self.screen is None:
            return _file_matches(file_path, self.program_base)
        return any(
            _same_path(file_path, action.controller_path)
            for action in self.screen.actions
        ) or _same_path(file_path, self.screen.controller_path)

    def owns_method(self, method_name: str) -> bool:
        """Whether one method name is an action of this unit, on any controller."""
        actions = self.action_names
        return actions is None or (method_name or "").lower() in actions

    def owns_action(self, file_path: str, method_name: str) -> bool:
        """Whether one controller file declares this unit's action of that name.

        A screen reaches its actions through several controllers, so the name
        alone does not say a method belongs to it: one controller can hold an
        action of this screen beside an action of another screen's. A screen
        that names no action on a file owns no method there. A file that could
        not be identified at all is judged by the name, which is all a caller
        holding no file has to go on.
        """
        if self.screen is None:
            return True
        if not file_path:
            return self.owns_method(method_name)
        return any(
            _same_path(file_path, action.controller_path)
            and _same_name(action.name, method_name)
            for action in self.screen.actions
        )

    def action_strength(self, file_path: str, method_name: str) -> str:
        """The strength this unit reaches one action at, or blank when none."""
        for action in self.screen.actions if self.screen is not None else ():
            if _same_path(file_path, action.controller_path) and _same_name(
                action.name, method_name
            ):
                return action.strength
        return ""

    def action_names_on(self, file_path: str) -> Optional[Set[str]]:
        """The actions this unit reports on one file, or None when it filters none."""
        if self.screen is None:
            return None
        return {
            action.name
            for action in self.screen.actions
            if _same_path(file_path, action.controller_path)
        }


def _same_name(left: str, right: str) -> bool:
    return (left or "").lower() == (right or "").lower()


def _same_path(left: str, right: str) -> bool:
    return bool(left) and bool(right) and Path(left) == Path(right)


def _append_once(name: str, *collections: List[str]) -> None:
    """Append `name` to every collection that does not already hold it."""
    for collection in collections:
        if name not in collection:
            collection.append(name)


def _invocation_entry_method(invocation: DbInvocation) -> str:
    """The method a Database Invocation is reached from, outermost first."""
    return invocation.method_chain[0] if invocation.method_chain else invocation.method_name


def _framework_name(result: Any) -> str:
    return getattr(result.framework, "value", str(result.framework))


def _program_resolutions(raw_name: str, scan: ProjectScanResult) -> List[_ProgramResolution]:
    """Resolve one requested program name to the units the response reports.

    A repository holding Razor views resolves through Program Screen
    resolution, which matches whole names only. A view carrying a page
    directive resolves through its page model first (Razor Pages), ahead of
    the MVC controller/action resolution below it. A code that resolves to no
    screen there falls back to the legacy base-name match only when it names a
    WebForms page or one C# file outright, because an open substring fallback
    would let a shorter code absorb a longer one again.
    """
    program_base = _normalize_program(raw_name)
    legacy = _ProgramResolution(
        program_base=program_base,
        matched_files=[
            r for r in scan.csharp_results if _file_matches(r.file_path, program_base)
        ],
    )
    if not scan.razor_results:
        return [legacy]

    csharp_by_path = {r.file_path: r for r in scan.csharp_results}

    def _resolutions(screens: List[ProgramScreen]) -> List[_ProgramResolution]:
        views_by_path = {r.file_path: r for r in scan.razor_results}
        return [
            _ProgramResolution(
                program_base=program_base,
                matched_files=_screen_files(screen, csharp_by_path),
                screen=screen,
                view_result=views_by_path.get(screen.view_path),
            )
            for screen in screens
        ]

    page_screens = resolve_razor_page_screens(
        raw_name,
        view_paths=[r.file_path for r in scan.razor_results],
        page_directives={
            r.file_path: r.has_page_directive for r in scan.razor_results
        },
        page_model_handlers={
            r.file_path: [
                m.name
                for cls in csharp_by_path[razor_page_model_path(r.file_path)].classes
                for m in cls.methods
            ]
            for r in scan.razor_results
            if razor_page_model_path(r.file_path) in csharp_by_path
        },
    )
    if page_screens:
        return _resolutions(page_screens)

    screens = resolve_program_screens(
        raw_name,
        view_paths=[r.file_path for r in scan.razor_results],
        controller_actions={
            path: [m.name for cls in result.classes for m in cls.methods]
            for path, result in csharp_by_path.items()
        },
        determined_anchors={
            r.file_path: r.view_anchors_determined for r in scan.razor_results
        },
        candidate_anchors={
            r.file_path: r.view_anchors_candidate for r in scan.razor_results
        },
    )
    if screens:
        return _resolutions(screens)

    if any(_file_matches(r.file_path, program_base) for r in scan.aspx_results):
        return [legacy]
    if any(_names_file_outright(r.file_path, program_base) for r in scan.csharp_results):
        return [legacy]
    return []


def _names_file_outright(file_path: str, program_base: str) -> bool:
    """Whether a program name is one file's whole base name, never a part of it."""
    return bool(program_base) and _normalize_program(Path(file_path).name) == program_base


def _resolution_owns_invocation(
    resolution: _ProgramResolution,
    invocation: DbInvocation,
    files_by_relative: Mapping[str, str],
) -> bool:
    """Whether one Database Invocation sits on an action this unit reports."""
    file_path = files_by_relative.get(
        str(invocation.source.relative_path).replace("\\", "/").casefold(),
        "",
    )
    return any(
        _same_path(file_path, result.file_path) for result in resolution.matched_files
    ) and resolution.owns_action(
        file_path,
        _invocation_entry_method(invocation),
    )


def _invocation_owner(
    resolutions: Sequence[_ProgramResolution], scan: ProjectScanResult, root: Path
) -> Callable[[DbInvocation], bool]:
    """A test for whether any of `resolutions` owns one Database Invocation's action."""
    files_by_relative = {
        _rel(result.file_path, root).casefold(): result.file_path
        for result in scan.csharp_results
    }

    def owned(invocation: DbInvocation) -> bool:
        return any(
            _resolution_owns_invocation(resolution, invocation, files_by_relative)
            for resolution in resolutions
        )

    return owned


def _program_resolutions_for_names(
    names: Sequence[str], scan: ProjectScanResult
) -> Tuple[List[Any], List[_ProgramResolution]]:
    """The scanned C# files, once each, and the resolutions of several program names.

    `/path_evidence` selects program files through this. `/analyze` resolves
    each name through the same `_program_resolutions`, so one name never
    matches different files on the two endpoints.
    """
    resolutions = [
        resolution for name in names for resolution in _program_resolutions(name, scan)
    ]
    files: List[Any] = []
    seen_paths: Set[str] = set()
    for resolution in resolutions:
        for result in resolution.matched_files:
            if result.file_path not in seen_paths:
                seen_paths.add(result.file_path)
                files.append(result)
    return files, resolutions


def _screen_files(screen: ProgramScreen, csharp_by_path: Dict[str, Any]) -> List[Any]:
    """The scanned C# files one screen reaches, its own controller first.

    A View Anchor can name an action on a controller the screen's own view
    folder never names, so the file set is the union of every controller the
    screen's actions sit on.
    """
    paths = [screen.controller_path] + [
        action.controller_path for action in screen.actions
    ]
    files: List[Any] = []
    seen: Set[str] = set()
    for path in paths:
        if path in seen or path not in csharp_by_path:
            continue
        seen.add(path)
        files.append(csharp_by_path[path])
    return files


class _AnalyzedUnit(NamedTuple):
    """One resolution of a requested name and the shared components its screen renders."""

    resolution: _ProgramResolution
    contributions: List[SharedComponentContribution]


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
            delegated_methods = response.get("delegated_methods")
            for proposal in proposals:
                if not isinstance(proposal, Mapping):
                    continue
                proposal_entry = dict(proposal)
                if not str(proposal_entry.get("evidence_kind") or "").strip():
                    proposal_entry["evidence_kind"] = DECOMPILED_AUTO_EVIDENCE_KIND
                if delegated_methods:
                    snapshot = proposal_entry.get("implementation_snapshot")
                    if isinstance(snapshot, Mapping) and not snapshot.get(
                        "delegated_methods"
                    ):
                        snapshot = dict(snapshot)
                        snapshot["delegated_methods"] = list(delegated_methods)
                        proposal_entry["implementation_snapshot"] = snapshot
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


def load_sp_catalog(database: str = "") -> SpCatalog:
    """Return the read-only stored-procedure catalog for a SQL cache scope.

    No caller of this one has a server to give: the refresh path and
    tools/discover_external_wrappers.py only know a database name, so the disk
    lookup happens here, at the call site.
    """
    identity = sql_cache_store.find_cache_identity(database)
    catalog, _, _ = _execution_sql_context(
        identity if isinstance(identity, sql_cache_store.CacheIdentity) else None,
        database,
    )
    return catalog


def _require_sql_execution_graph(
    database: str,
    sql_cache_identity: Optional[sql_cache_store.CacheIdentity],
) -> Tuple[Dict, Dict]:
    """Return the cache and graph of the identity the handler built, or raise "not scanned".

    ``database`` is the requested name; it only names the error. A missing
    identity (no cache, or a Database on several hosts) is "not scanned".
    """
    database = str(database or "").strip()
    if not database:
        raise ValueError(
            "database 不可為空；Gateway path analysis 需要指定 SQL execution graph cache。"
        )
    cached = sql_cache_store.load_cached(sql_cache_identity) if sql_cache_identity is not None else None
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


def _referenced_databases(scans: Iterable[ProjectScanResult]) -> List[str]:
    """Distinct real database names a system's own connection strings resolve to.

    `reconcile_refresh_wrappers`'s `database` argument is the string a whole-
    system `/refresh` request carries as `req.system` (see api.py) -- a system
    id such as "Y-Docs_TTPUR", not a real SQL database name; no cache file is
    ever saved under that name, so `load_sp_catalog(database)` alone always
    comes back empty for it. A system commonly spans several real databases
    (ADR-0009: Database identity is decoupled from System) named per file by
    its own Web.config connection string, exactly what `database_attribution`
    already reports as "resolved" on each review item. Walking every file's
    already-resolved connection sources here names those real databases too,
    so the catalog covers whatever a call could actually resolve to.
    """
    names: Dict[str, None] = {}
    for scan in scans:
        raw_by_file = getattr(scan, "db_invocations", {}) or {}
        for source_file in raw_by_file:
            sources = _execution_connection_sources(scan, str(source_file), "")
            for value in sources.values():
                name = database_of(value)
                if name:
                    names.setdefault(name, None)
    return list(names)


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
    evidence: DerivedExecutionEvidence,
    invocations: List[DbInvocation],
    *,
    scope: DerivedExecutionEvidenceScope,
) -> Tuple[List[Dict], Dict[str, object]]:
    """The Execution Paths of the invocations one program reports.

    `invocations` come from `evidence.rated_invocations`, already filtered to
    this program, so the compact payload's counts describe the paths this
    program actually reports. The paths belong to the evidence, which is
    read-only: the rewrite below changes a copy.
    """
    if req.database:
        _require_sql_execution_graph(req.database, scope.sql_cache_identity)
    paths = evidence.paths_of(invocations)
    if not evidence.graph and not req.database:
        paths = [
            _unresolved_without_graph(path)
            if path.get("unresolved_reason") == "not_in_resolved_catalog"
            else path
            for path in paths
        ]
    compact_payload = build_compact_execution_path_payload(
        paths,
        max_paths=MAX_COMPACT_PATHS if req.max_paths is None else req.max_paths,
        question=req.question,
    )
    return paths, compact_payload


def _unresolved_without_graph(path: Dict) -> Dict:
    """A copy of `path` that names the missing SQL graph as its unresolved reason."""
    path = dict(path)
    path["unresolved_reason"] = "stored_procedure_not_in_graph"
    targets = list(path.get("sp_chain") or [])
    if targets and "." not in targets[0]:
        targets[0] = f"dbo.{targets[0]}"
    path["unresolved_targets"] = targets[:1]
    return path


def get_path_evidence(
    req: PathEvidenceRequest, evidence_source: EvidenceSource = evidence_for_scope,
    *, scan_store: ScanStore | None = None, cache_store: CacheStore | None = None,
) -> PathEvidenceResponse:
    """Expand one current Execution Path into source-backed, path-scoped evidence.

    evidence_source 提供這個 scope 的 Derived Execution Evidence；預設是
    derived_execution_evidence 模組本身，測試可以給一份固定的 evidence。
    有 program_names 時把這些程式的檔案當作 needed files 交給模組：miss 時只
    rate 這些檔案，且不保留（ADR-0040）。沒有 program_names 時要整個 scope。
    path 透過 evidence 的 path_id 索引找出，不再逐一 invocation 重建。
    """
    path_id = (req.path_id or "").strip()
    if not path_id:
        raise PathEvidenceError("invalid_path_id", "path_id 不可為空")

    cached: dict = {}

    def check_identity(found: CacheIdentityResult) -> None:
        nonlocal cached
        identity = found if isinstance(found, sql_cache_store.CacheIdentity) else None
        cached, _ = _require_sql_execution_graph(req.database, identity)

    def check_roots(roots: list[Path]) -> None:
        if not roots:
            raise PathEvidenceError("source_not_found", "找不到 path evidence 的原始碼來源")

    context = build_request_context(
        req,
        scan_store=scan_store if scan_store is not None else RealScanStore(),
        cache_store=cache_store if cache_store is not None else RealCacheStore(),
        check_identity=check_identity,
        check_roots=check_roots,
    )
    assert not isinstance(context, Skipped)
    scans, scan, root = context.scans, context.scan, context.root
    sql_cache_identity = (
        context.sql_cache_identity
        if isinstance(context.sql_cache_identity, sql_cache_store.CacheIdentity) else None
    )

    if req.program_names:
        # Same program resolution as /analyze, so both endpoints agree on
        # which files a name matches and which actions on them it owns.
        matched_files, resolutions = _program_resolutions_for_names(
            req.program_names, scan
        )
    else:
        matched_files = list(scan.csharp_results)
        resolutions = []  # every file counts: no program filter below

    evidence = evidence_source(
        context.scope,
        scans,
        scan,
        root,  # type: ignore[arg-type]
        needed_files=matched_files if req.program_names else None,
        refresh=req.refresh,
    )
    joined_graph = evidence.graph
    rated_invocations = evidence.rated_invocations
    if req.program_names:
        owned = _invocation_owner(resolutions, scan, root)
        rated_invocations = [invocation for invocation in rated_invocations if owned(invocation)]
    selected_path: Mapping[str, object] | None = None
    selected_invocation: DbInvocation | None = None
    located = (
        evidence.path_by_id(path_id, produced_by=owned)
        if req.program_names
        else evidence.path_by_id(path_id)
    )
    if located is not None:
        selected_path, selected_invocation = located

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
        sql_cache_identity=sql_cache_identity,
    )


def _materialize_path_evidence(
    path: Mapping[str, object],
    invocation: DbInvocation,
    scan: ProjectScanResult,
    cached: Mapping[str, object],
    graph: Mapping[str, object],
    *,
    sql_cache_identity: Optional[sql_cache_store.CacheIdentity],
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
        # The handler's cache holds the joined graph, so the definition comes from
        # it even when the path names another Database (its C# connection).
        if sql_cache_identity is not None:
            definitions = fetch_sp_definitions(
                [invocation.raw_command_text or invocation.procedure_name],
                sql_cache_identity,
            )
            if definitions:
                definition = definitions[0]
                candidate.update(definition)
                if definition.get("dependency_source") == "execution_graph":
                    candidate["sql_cache_matched"] = True
                    candidate["sql_cache_database"] = sql_cache_identity.database
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

        cache_database = str(cached.get("database") or graph.get("database") or "")
        for function_reference in operation.get("function_references", []) or []:
            referenced_object_ids.update(
                _find_graph_object_ids(nodes, "function", function_reference, cache_database)
            )

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
    # Both sides state a schema, or nothing matches: an empty schema is not `dbo`.
    node_schema = str(node.get("schema") or "").casefold()
    node_name = str(node.get("name") or "").casefold()
    if not node_schema:
        return None
    for item in cached.get(collection, []) or []:
        item_dict = dict(item)
        item_name = parse(str(item_dict.get("name") or ""))
        item_schema = (item_name.schema or str(item_dict.get("schema") or "")).casefold()
        if item_schema and item_schema == node_schema and item_name.name.casefold() == node_name:
            return item_dict
    return None


def _find_graph_object_ids(
    nodes: Mapping[str, Mapping[str, object]],
    object_type: str,
    reference: Mapping[str, object],
    cache_database: str,
) -> List[str]:
    """Find the nodes one analyzer reference names; the reference holds four parts.

    The lookup obeys the two-bucket rule over listed nodes. A reference that states
    a schema matches the node of that schema. A reference that states no schema
    matches every node with the bare name. Listed nodes always carry a schema, so
    none of them carries the Unproven Schema mark.
    """
    # A reference to another Database matches no node: this cache holds no
    # definition of that object, so a local definition would be false evidence.
    if names_another_database(str(reference.get("database") or ""), cache_database):
        return []
    schema = str(reference.get("schema") or "")
    name = str(reference.get("name") or "")
    return [
        node_id
        for node_id, node in nodes.items()
        if node.get("type") == object_type and names_listed_node(node, schema, name)
    ]


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

def analyze(
    req: AnalyzeRequest, evidence_source: EvidenceSource = evidence_for_scope,
    *, scan_store: ScanStore | None = None, cache_store: CacheStore | None = None,
) -> AnalyzeResponse:
    """依 program_names 過濾掃描結果，組成回應（純靜態，無 AI）。

    evidence_source 提供這個 scope 的 Derived Execution Evidence；預設是
    derived_execution_evidence 模組本身，測試可以給一份固定的 evidence。
    一個請求只向模組要一次 evidence：所有解析結果的檔案，加上它們共用元件
    的檔案，當作 needed files（miss 時只 rate 這些檔案且不保留，ADR-0040）。
    每個解析結果、每個共用元件都從這一份 evidence 過濾出自己的 invocation。
    """
    context = build_request_context(
        req,
        scan_store=scan_store if scan_store is not None else RealScanStore(),
        cache_store=cache_store if cache_store is not None else RealCacheStore(),
    )
    assert not isinstance(context, Skipped)
    found = context.sql_cache_identity
    sql_cache_identity = found if isinstance(found, sql_cache_store.CacheIdentity) else None
    scans, scan, root, scope = context.scans, context.scan, context.root, context.scope

    programs: List[ProgramAnalysis] = []
    not_found: List[str] = []
    files_by_relative = {
        _rel(result.file_path, root).casefold(): result.file_path
        for result in scan.csharp_results
    }

    # 共用元件（ViewComponent／partial view）解析所需的資料，跟 raw_name 無關，
    # 整個請求只需要組一次。
    csharp_by_path = {r.file_path: r for r in scan.csharp_results}
    view_component_refs_by_path = {
        r.file_path: r.view_component_references for r in scan.razor_results
    }
    partial_view_refs_by_path = {
        r.file_path: r.partial_view_references for r in scan.razor_results
    }
    view_identities: Dict[str, Tuple[str, str, str]] = {}
    for r in scan.razor_results:
        identity = view_identity(r.file_path)
        if identity is not None:
            view_identities[r.file_path] = identity
    view_component_classes = [
        (r.file_path, cls.name, cls.base_class or "", [m.name for m in cls.methods])
        for r in scan.csharp_results
        for cls in r.classes
    ]

    # 先解析每個名稱和每個畫面渲染的共用元件，才能把需要的檔案一次交給模組。
    planned: List[Tuple[str, List[_AnalyzedUnit]]] = []
    needed_files: List[Any] = []
    needed_paths: Set[str] = set()
    for raw_name in req.program_names:
        units: List[_AnalyzedUnit] = []
        for resolution in _program_resolutions(raw_name, scan):
            contributions: List[SharedComponentContribution] = []
            if resolution.screen is not None:
                contributions = list(
                    resolve_shared_components(
                        resolution.screen.view_path,
                        view_component_refs=view_component_refs_by_path,
                        partial_view_refs=partial_view_refs_by_path,
                        view_component_classes=view_component_classes,
                        view_identities=view_identities,
                    )
                )
            for result in [
                *resolution.matched_files,
                *(
                    csharp_by_path[contribution.file_path]
                    for contribution in contributions
                    if contribution.file_path in csharp_by_path
                ),
            ]:
                if result.file_path not in needed_paths:
                    needed_paths.add(result.file_path)
                    needed_files.append(result)
            units.append(_AnalyzedUnit(resolution, contributions))
        planned.append((raw_name, units))

    evidence = (
        evidence_source(
            scope,
            scans,
            scan,
            root,
            needed_files=needed_files,
            refresh=getattr(req, "refresh", False),
        )
        if needed_files
        else DerivedExecutionEvidence([], {})
    )
    # 依來源檔分組；invocation 的 source 相對路徑就是 rating 時的 _rel(檔案, root)。
    invocations_by_file: Dict[str, List[DbInvocation]] = {}
    for invocation in evidence.rated_invocations:
        invocations_by_file.setdefault(str(invocation.source.relative_path), []).append(
            invocation
        )

    def invocations_in(files: Iterable[Any]) -> List[DbInvocation]:
        """The rated invocations of `files`, in file order, as one rating of them gives."""
        return [
            invocation
            for result in files
            for invocation in invocations_by_file.get(_rel(result.file_path, root), [])
        ]

    for raw_name, units in planned:
        reported = False

        for resolution, contributions in units:
            matched_files = resolution.matched_files

            def owns_invocation(
                invocation: DbInvocation, resolution=resolution
            ) -> bool:
                return _resolution_owns_invocation(
                    resolution, invocation, files_by_relative
                )

            # 2) Join C# database facts through the Gateway; legacy relations are not
            # part of the formal response path.
            rated_invocations = [
                invocation
                for invocation in invocations_in(matched_files)
                if owns_invocation(invocation)
            ]
            sp_names: List[str] = []
            for invocation in rated_invocations:
                if (
                    invocation.evidence is InvocationEvidence.PROVEN
                    and invocation.procedure_name
                ):
                    _append_once(invocation.procedure_name, sp_names)
            database_invocations = [
                _serialize_db_invocation(invocation)
                for invocation in rated_invocations
            ]
            diagnostics = [
                _invocation_diagnostic(invocation)
                for invocation in rated_invocations
                if invocation.evidence is not InvocationEvidence.PROVEN
            ]

            table_names = inline_table_relations.table_names_by_method(
                scan,
                lambda site: resolution.owns_file(site.file_path)
                and resolution.owns_action(site.file_path, site.method_name),
            )

            # 共用元件（S.15）：這個畫面渲染的 ViewComponent／partial view，貼上
            # 「來自共用元件」的標籤跟畫面自己的存取分開，不會混進 methods。
            shared_component_contributions: List[Dict] = []
            if resolution.screen is not None:
                for contribution in contributions:
                    component_file = csharp_by_path.get(contribution.file_path)
                    if component_file is None:
                        continue
                    component_invocations = [
                        invocation
                        for invocation in invocations_in([component_file])
                        if invocation.class_name == contribution.class_name
                        and _same_name(
                            _invocation_entry_method(invocation),
                            contribution.entry_method,
                        )
                    ]
                    component_sp_names: List[str] = []
                    for invocation in component_invocations:
                        label = {"kind": VIEW_COMPONENT, "name": contribution.name}
                        serialized = _serialize_db_invocation(invocation)
                        serialized["shared_component"] = label
                        database_invocations.append(serialized)
                        if invocation.evidence is not InvocationEvidence.PROVEN:
                            diagnostic = _invocation_diagnostic(invocation)
                            diagnostic["shared_component"] = label
                            diagnostics.append(diagnostic)
                            continue
                        _append_once(invocation.procedure_name, sp_names, component_sp_names)

                    component_table_names = inline_table_relations.table_names_by_method(
                        scan,
                        lambda site: site.file_path == contribution.file_path
                        and _same_name(site.method_name, contribution.entry_method),
                    )
                    for name in component_table_names:
                        _append_once(name, table_names)

                    if not component_invocations and not component_table_names:
                        continue
                    shared_component_contributions.append(
                        {
                            "kind": VIEW_COMPONENT,
                            "name": contribution.name,
                            "file": _rel(contribution.file_path, root),
                            "class": contribution.class_name,
                            "method": contribution.entry_method,
                            "stored_procedures": component_sp_names,
                            "tables": component_table_names,
                        }
                    )

            if (
                not resolution.is_program_screen
                and not matched_files
                and not sp_names
                and not table_names
            ):
                continue

            # 取第一個對應檔案作為主要檔案資訊；Program Screen 以它自己的 View 為主。
            file_path = ""
            framework = ""
            methods: List[Dict] = []
            if resolution.screen is not None:
                file_path = _rel(resolution.screen.view_path, root)
            if resolution.view_result is not None:
                framework = _framework_name(resolution.view_result)
            if matched_files:
                primary = matched_files[0]
                if not file_path:
                    file_path = _rel(primary.file_path, root)
                if not framework:
                    framework = _framework_name(primary)
                for fr in matched_files:
                    for cls in fr.classes:
                        for m in cls.methods:
                            if not resolution.owns_action(fr.file_path, m.name):
                                continue
                            method: Dict = {"name": m.name, "class": cls.name}
                            strength = resolution.action_strength(fr.file_path, m.name)
                            if strength:
                                method["strength"] = strength
                            methods.append(method)

            # 程式碼片段（S2b）：依方法位置擷取，可由 include_snippets 關閉
            code_snippets = []
            if req.include_snippets and matched_files:
                for fr in matched_files:
                    code_snippets.extend(
                        extract_snippets(
                            fr,
                            root,
                            method_filter=resolution.action_names_on(fr.file_path),
                        )
                    )

            # 呼叫鏈（S3）：程式內部方法呼叫路徑
            call_chains = build_call_chains(matched_files) if matched_files else []
            call_chains = [
                chain for chain in call_chains if resolution.owns_method(chain[0])
            ]

            # SP 完整定義（選用，需 DB 連線；讓 AI 看得到 SP 實際邏輯）
            sp_definitions: List[Dict] = []
            if req.include_sp_defs and sp_names:
                sp_definitions = fetch_sp_definitions(sp_names, sql_cache_identity)

            # SQL View 完整定義（選用）：table_names 裡如果其實是 View（而非一般資料表），
            # 從本機 SQL 快取（sql_cache_store，由 /refresh_sql 落地）取得其完整定義，
            # 讓 AI 看得到 View 實際查詢邏輯，而不只是一個表名。只讀本機快取，不即時連線
            # （見 view_fetcher.py 說明），避免每個表名都額外連線判斷是否為 View。
            view_definitions: List[Dict] = []
            if req.include_sp_defs and table_names:
                view_definitions = fetch_view_definitions(table_names, sql_cache_identity)

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
                    udf_definitions = fetch_udf_definitions(sql_texts, sql_cache_identity)

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
                    if not resolution.owns_method(rel["called_by"]):
                        continue
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
                if resolution.is_program_screen:
                    if resolution.view_result is not None:
                        view_layer.append(
                            _view_layer_summary(resolution.view_result, root)
                        )
                else:
                    for fr in scan.aspx_results + scan.razor_results + scan.vue_results:
                        if _file_matches(fr.file_path, resolution.program_base):
                            view_layer.append(_view_layer_summary(fr, root))

            execution_paths: List[Dict] = []
            compact_execution_paths: List[Dict] = []
            compact_execution_paths_meta: Dict[str, int] = {}
            if req.include_execution_paths and matched_files:
                execution_paths, compact_payload = _build_program_execution_paths(
                    req, evidence, rated_invocations, scope=scope
                )
                compact_execution_paths = compact_payload["paths"]
                compact_execution_paths_meta = {
                    key: int(compact_payload[key])
                    for key in ("total_paths", "returned_paths", "omitted_paths")
                }

            programs.append(
                ProgramAnalysis.model_validate(dict(
                    program=raw_name,
                    file=file_path,
                    framework=framework,
                    methods=methods,
                    stored_procedures=sp_names,
                    tables=table_names,
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
                    shared_component_contributions=shared_component_contributions,
                ))
            )
            reported = True

        if not reported:
            not_found.append(raw_name)

    return AnalyzeResponse(
        programs=programs,
        not_found=not_found,
        source_root=str(root),
    )


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


class _WriterEvidenceIdentity(NamedTuple):
    """The Execution Path identity ADR-0016 deduplicates a table match by.

    Program, file, `path_id`, entry method, stored-procedure chain, and
    access type -- not file alone. Two records that agree on all of these are
    one fact and collapse to one record; two that differ in any of them are
    two facts, and both survive. This is the identity the companion
    repository's glossary calls Writer Evidence Identity.
    """

    program: str
    file: str
    path_id: str
    entry_method: str
    sp_chain: Tuple[str, ...]
    access_type: str


def _table_match_identity(match: TableMatchProgram) -> _WriterEvidenceIdentity:
    return _WriterEvidenceIdentity(
        program=match.program,
        file=match.file,
        path_id=match.path_id,
        entry_method=match.entry_method,
        sp_chain=tuple(match.sp_chain),
        access_type=match.access_type,
    )


def _prefer_table_match(
    existing: Dict[Any, TableMatchProgram],
    key: Any,
    candidate: TableMatchProgram,
) -> None:
    """Keep the strongest of two records sharing ``key`` in ``existing``.

    The key decides what counts as "the same fact"; see `_table_match_identity`
    for the Execution Path identity ADR-0016 keys graph-derived matches by.
    """
    current = existing.get(key)
    if current is None or _table_match_rank(candidate) > _table_match_rank(current):
        existing[key] = candidate


def _table_match_rank(match: TableMatchProgram) -> tuple[int, int, int]:
    access_type = (match.access_type or "").upper()
    is_write = is_write_access(match.access_type)
    is_indirect = access_type.endswith("_INDIRECT")
    return (
        2 if is_write else 1 if access_type.startswith("READ") else 0,
        1 if not is_indirect else 0,
        1 if match.via_sp else 0,
    )


def _inline_match_rank(match: TableMatchProgram) -> tuple[bool, tuple[int, int, int]]:
    """The rank of an inline record: a direct read first, then `_table_match_rank`."""
    return not match.read_through, _table_match_rank(match)


def find_by_sp(
    req: FindBySPRequest, evidence_source: EvidenceSource = evidence_for_scope,
    *, scan_store: ScanStore | None = None, cache_store: CacheStore | None = None,
) -> FindBySPResponse:
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

    evidence_source 提供這個 scope 的 Derived Execution Evidence；預設是
    derived_execution_evidence 模組本身，測試可以給一份固定的 evidence。
    """
    sp_name = (req.sp_name or "").strip()
    if not sp_name:
        return FindBySPResponse(sp_name=sp_name, matches=[])
    def check_identity(found: CacheIdentityResult) -> None:
        if isinstance(found, sql_cache_store.AmbiguousServer):
            raise AmbiguousDatabaseError(found)

    context = build_request_context(
        req,
        scan_store=scan_store if scan_store is not None else RealScanStore(),
        cache_store=cache_store if cache_store is not None else RealCacheStore(),
        check_identity=check_identity,
    )
    if isinstance(context, Skipped):
        return FindBySPResponse(sp_name=sp_name, matches=[], skipped=True)
    scans, scan, root = context.scans, context.scan, context.root
    sql_cache_identity = context.scope.sql_cache_identity

    sp_lower = bare_key(sp_name)
    matches: List[SPMatchProgram] = []
    likely_matches: List[SPMatchProgram] = []
    diagnostics: List[Dict] = []
    seen_invocations: set[tuple[str, int, int]] = set()
    if not req.database:
        raise ValueError(
            "find_by_sp 需要 database 以載入 SQL execution graph；"
            "請提供 system_id 並先執行 refresh_sql_cli。"
        )
    _cached, _graph = _require_sql_execution_graph(req.database, sql_cache_identity)
    evidence = evidence_source(context.scope, scans, scan, root, refresh=req.refresh)
    rated_invocations = evidence.rated_invocations
    for invocation in rated_invocations:
        # `executed_procedure_name`, not `procedure_name`: a call whose inline SQL
        # text runs a procedure -- with `EXEC`, or relying on T-SQL running a bare
        # procedure name -- declares no procedure of its own, and reading only the
        # declared field answered "no callers" for a call the database really makes.
        executed = invocation.executed_procedure_name
        if not executed or bare_key(executed) != sp_lower:
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
        if invocation.evidence is InvocationEvidence.PROVEN:
            callers = matches
        else:
            diagnostics.append(
                _invocation_diagnostic(
                    invocation,
                    requested_sp=sp_name,
                )
            )
            # Only a `likely` call gains a list. An `unresolved` call stays in
            # `diagnostics` only.
            if invocation.evidence is not InvocationEvidence.LIKELY:
                continue
            callers = likely_matches
        # Each entry of a list names a program, so a call with no source file
        # goes into no list.
        if not csharp_file:
            continue
        match_fields = _invocation_response_fields(invocation)
        match_fields.update(
            {
                "program": _normalize_program(Path(csharp_file).name),
                "file": _rel(csharp_file, root),
                # The row has to name the procedure it matched. `procedure_name`
                # is empty on an invocation whose inline SQL text runs the
                # procedure, so read the executed name and say where it came from.
                "procedure_name": executed,
                "procedure_schema": invocation.executed_procedure_schema or "",
                "procedure_name_source": invocation.executed_procedure_name_source,
            }
        )
        # An absent value takes the default of the schema. A `likely` call has no
        # Database and no connection source; a `proven` call has both.
        callers.append(
            SPMatchProgram(**{key: value for key, value in match_fields.items() if value is not None})
        )

    return FindBySPResponse(
        sp_name=sp_name,
        matches=matches,
        likely_matches=likely_matches,
        diagnostics=diagnostics,
        source_root=str(root),
    )


def _record_table_reverse_lookup(table_name: str, scope: DerivedExecutionEvidenceScope) -> None:
    """Record the table name and the scope one table reverse lookup asked about.

    Ticket 01 of `.scratch/table-reverse-lookup-cost/`: a later ticket decides
    the stored evidence's shape from measured traffic, not from an assumption,
    and that decision needs to know how many distinct tables one scope is
    asked about before its inputs change. `find_by_table()` is the one place a
    table reverse lookup enters this service, whether an Agent called it as a
    tool or the service called it before an Agent existed (Object Kind
    Ambiguity), so this is the one place that records it -- an Agent's own
    tool-call record answers a different question and is not a second
    recording point for this one.
    """
    print(
        "🔎 資料表反查："
        f"table={table_name!r} scope_database={scope.database!r} "
        f"scope_sql_cache_identity={scope.sql_cache_identity!r} scope_db_name={scope.db_name!r} "
        f"scope_repo_roots={scope.repo_roots!r} scope_wrapper_contract={scope.wrapper_contract!r}"
    )


def find_by_table(
    req: FindByTableRequest, evidence_source: EvidenceSource = evidence_for_scope,
    *, scan_store: ScanStore | None = None, cache_store: CacheStore | None = None,
) -> FindByTableResponse:
    """反查「哪些程式存取了這張資料表」，結合 inline SQL facts 與 SQL Execution Graph，無 AI。

    inline SQL facts 保留直接出現在 C# SQL 文字中的表存取；SP/View/Function
    lineage 則必須由 Gateway invocation join 到 SQL Execution Graph 取得。詳見
    find_by_sp() 的 docstring 說明 cache_only 為何不能只用 repo_manager.is_cloned() 判斷。

    evidence_source 提供這個 scope 的 Derived Execution Evidence；預設是
    derived_execution_evidence 模組本身，測試可以給一份固定的 evidence。
    """
    table_name = (req.table_name or "").strip()
    if not table_name:
        return FindByTableResponse(table_name=table_name, matches=[])
    def check_identity(found: CacheIdentityResult) -> None:
        if isinstance(found, sql_cache_store.AmbiguousServer):
            raise AmbiguousDatabaseError(found)

    context = build_request_context(
        req,
        scan_store=scan_store if scan_store is not None else RealScanStore(),
        cache_store=cache_store if cache_store is not None else RealCacheStore(),
        check_identity=check_identity,
    )
    if isinstance(context, Skipped):
        return FindByTableResponse(table_name=table_name, matches=[], skipped=True)
    scans, scan, root = context.scans, context.scan, context.root
    scope = context.scope
    sql_cache_identity = scope.sql_cache_identity
    _record_table_reverse_lookup(table_name, scope)

    question = TableQuestion.of(table_name, req.database or "")
    # Graph-derived facts key by Execution Path identity, not by file
    # (ADR-0016) -- see `_table_match_identity`. An inline C# SQL fact carries
    # no such identity of its own; it keeps the pre-ticket file-scoped rule
    # below, so it still loses to a stronger graph-derived fact for the same
    # file instead of becoming a spurious extra record next to it.
    matches_by_identity: Dict[_WriterEvidenceIdentity, TableMatchProgram] = {}
    inline_matches_by_file: Dict[str, TableMatchProgram] = {}
    diagnostics: List[Dict] = []
    # The rating runs only when the request names a Database. The inline matches read its
    # result below, so a parsed relation takes the Database of its Database Invocation.
    rated_invocations: List[DbInvocation] = []
    execution_paths: List[Dict[str, object]] = []
    # The inline matches read the graph too: an inline read of a View or a Function
    # reaches the tables behind it only when the request names a Database.
    inline_graph: Optional[Mapping[str, Any]] = None
    if req.database:
        _require_sql_execution_graph(req.database, sql_cache_identity)
        # 重用同一 scope 的 rated invocations 與 Execution Paths（ticket 04/05）：
        # 同一 scope 內問第二個 table，不必重新 rate C# facts、也不必重建
        # Execution Paths —— 兩者共用 find_by_sp() 已經在用的同一份 evidence
        # 與同一條 validity stamp／explicit-refresh 規則，見
        # `derived_execution_evidence.evidence_for_scope` docstring。
        evidence = evidence_source(scope, scans, scan, root, refresh=req.refresh)
        rated_invocations = evidence.rated_invocations
        graph = evidence.graph
        execution_paths = evidence.execution_paths()
        inline_graph = graph
    for answer in inline_table_relations.by_table(
        scan, question, rated_invocations, root, inline_graph, sql_cache_identity
    ):
        rel = answer.relation
        caller_class = str(getattr(rel, "class_name", "") or "")
        caller_method = str(getattr(rel, "method_name", "") or "")
        candidate = TableMatchProgram(
            program=_normalize_program(Path(rel.csharp_file).name),
            file=_rel(rel.csharp_file, root),
            # Inline C# SQL remains a source fact; SQL-module relationships
            # are queried from the Execution Graph below. The relation names its
            # own source (parsed or regular expression). A direct answer keeps the
            # access type of its relation; an answer that reaches the table through
            # a View or a Function reads `READ_INDIRECT` or `UNRESOLVED`.
            access_type=answer.access_type,
            read_through=answer.read_through,
            reason=rel.reason,
            evidence_status="not_applicable",
            evidence_reason="inline_sql",
            database=answer.database,
            database_candidates=list(answer.database_candidates),
            database_attribution=answer.database_attribution,
            caller=(
                f"{caller_class}.{caller_method}"
                if caller_class
                else caller_method
            ),
            caller_class=caller_class,
            caller_method=caller_method,
            table=answer.table_name,
            risk_flags=[UNPROVEN_SCHEMA] if answer.match.unproven_schema else [],
            stated_database=answer.match.stated_database,
            schema_source=answer.match.schema_source,
        )
        # One inline record for each file, and a direct read beats a read through a
        # View or a Function: `_table_match_rank` alone orders `READ_INDIRECT` above
        # `SELECT`, so it would keep the indirect one.
        current = inline_matches_by_file.get(candidate.file)
        if current is None or _inline_match_rank(candidate) > _inline_match_rank(current):
            inline_matches_by_file[candidate.file] = candidate

    # Stored-procedure access is joined through Gateway invocations and the graph.
    # Do not fall back to SQL dependency dictionaries or definition-text guesses.
    if req.database:
        diagnostics.extend(
            _invocation_diagnostic(invocation, requested_table=table_name)
            for invocation in rated_invocations
            if invocation.evidence is not InvocationEvidence.PROVEN
        )
        for access_record in filter_table_accesses(
            execution_paths,
            graph,
            table_name,
            access="all",
            database=req.database or "",
        ):
            source_span = access_record.get("source_span") or {}
            relative_path = str(source_span.get("relative_path") or "")
            csharp_file = _source_file_for_span(scan, root, relative_path)
            if not csharp_file:
                continue
            is_write = bool(access_record.get("is_write"))
            is_indirect = bool(access_record.get("is_indirect"))
            operation_type = str(access_record.get("operation_type") or "")
            evidence_status = str(access_record.get("evidence") or "unresolved")
            # A path that is not `proven` never reaches here with `is_write`
            # True (see `graph_queries._access_record`), so this branch order
            # only has to add one case: claim no direction at all for it,
            # instead of mislabeling it READ (ADR-0015).
            access_type = (
                "WRITE_INDIRECT"
                if is_write and is_indirect
                else operation_type
                if is_write
                else "UNRESOLVED"
                if evidence_status != "proven"
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
                table=str(access_record.get("table") or ""),
                risk_flags=list(access_record.get("risk_flags") or []),
                stated_database=access_record.get("stated_database"),
                schema_source=str(access_record.get("schema_source") or ""),
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
            _prefer_table_match(matches_by_identity, _table_match_identity(candidate), candidate)

    # An inline fact joins the response only if no graph-derived fact for the
    # same file already outranks it (`_table_match_rank`: write beats read,
    # direct beats indirect, graph-derived beats inline) -- the blending rule
    # `tests/test_derived_execution_evidence_reuse_table.py` fixes in place,
    # predating this ticket. It never removes a graph-derived record: decision
    # 4 is about not collapsing distinct Execution Paths into each other, and
    # an inline fact is not an Execution Path, so it never enters
    # `matches_by_identity` at all.
    all_matches: List[TableMatchProgram] = list(matches_by_identity.values())
    for file, inline_match in inline_matches_by_file.items():
        outranked = any(
            match.file == file and _table_match_rank(match) > _table_match_rank(inline_match)
            for match in matches_by_identity.values()
        )
        if not outranked:
            all_matches.append(inline_match)

    # One decision per record: `is_write` is what the client reads and what
    # `write_only` filters on, so the field and the filter cannot differ.
    all_matches = [
        match.model_copy(update={"is_write": is_write_access(match.access_type)}) for match in all_matches
    ]
    excluded_count = 0
    if req.write_only:
        before = len(all_matches)
        all_matches = [match for match in all_matches if match.is_write]
        # `UNRESOLVED` and every read type are not write access types, so this
        # also counts a path the graph could not prove -- `write_only=True`
        # must keep meaning "proven writes and nothing else" (ADR-0015)
        # without silently reading as a complete list.
        excluded_count = before - len(all_matches)

    return FindByTableResponse(
        table_name=table_name,
        matches=sorted(all_matches, key=lambda item: (item.program, item.file)),
        excluded_count=excluded_count,
        diagnostics=diagnostics,
        source_root=str(root),
    )


_LOCATE_OBJECT_KINDS = {"sp", "table"}


def locate_object(req: LocateObjectRequest) -> LocateObjectResponse:
    """從磁碟上每一份 SQL 快取的 Object Location Index 猜哪些 Database 可能持有這個
    物件名稱，一律不開任何 SQL 快取本體（見 ADR-0012）。

    查詢名稱遵守 two-bucket 規則（見 CONTEXT.md 的 Object Location Index）：沒寫 schema
    的名稱問 bare 桶；寫了 schema 的名稱問 full 桶；寫了 schema 但 full 桶沒有，退回
    bare 桶，那仍是比對成功（Unproven Schema）。名稱沒寫 database 時，full key 的
    database 段取被問的那份索引自己的 Database。kind="sp" 問 stored_procedure 兩個桶，
    kind="table" 問 table 兩個桶。

    一份索引新鮮且持有這個名稱 → matched，比對到的每一把 full key 一列：server 與
    database 永遠是這份快取的身分，schema 是那把 key 的 schema，stated_database 只在
    那把 key 寫的是另一個 Database 時出現。快取存在但索引依 staleness 規則判定缺席
    （缺失/讀不了/舊/版本不符/缺桶/身分不符）→ unindexed；索引新鮮但不持有這個名稱
    → 兩份清單都不出現，那就是剪枝本身，是權威結果而非不確定。

    一個 Database 可以有多列；呼叫端只用 server 與 database 取交集，所以多出來的列
    不會改變 Candidate Database Set。indexes_consulted 逐份索引計數——它量的是成本，
    不是 Database 數。
    """
    kind = (req.kind or "").strip().casefold()
    if kind not in _LOCATE_OBJECT_KINDS:
        raise ValueError(f"kind 必須是 sp 或 table，收到：{req.kind!r}")

    object_name = (req.object_name or "").strip()
    asked = parse(object_name)

    matched: List[LocatedDatabase] = []
    unindexed: List[LocatedDatabase] = []
    indexes_consulted = 0

    for row in sql_cache_store.list_caches():
        try:
            identity = sql_cache_store.CacheIdentity.of(row.server, row.database)
        except ValueError:
            # A file whose name no SQL Cache Identity writes, and whose Scan
            # Record names no server (see list_caches()): no identity to report
            # a caller could match against a Declared Database Dependency, so
            # it is neither counted nor listed — not a cache this endpoint can
            # answer for, in either direction.
            continue
        indexes_consulted += 1
        index = sql_cache_store.load_object_location_index(identity)
        if index is None:
            unindexed.append(LocatedDatabase(server=identity.server, database=identity.database))
            continue
        matched.extend(_located_rows(index, kind, asked))
        # else: a fresh index that does not hold the name — pruned, appears in neither list.

    matched_databases = {(row.server, row.database) for row in matched}
    return LocateObjectResponse(
        object_name=object_name,
        kind=kind,
        matched=matched,
        unindexed=[row for row in unindexed if (row.server, row.database) not in matched_databases],
        indexes_consulted=indexes_consulted,
    )


def _located_rows(
    index: sql_cache_store.ObjectLocationIndex, kind: str, asked: ObjectName
) -> List[LocatedDatabase]:
    """The rows one fresh index gives for a name, under the two-bucket rule."""
    bare_bucket, full_bucket = index.buckets(kind)
    name_key = bare_key(asked)
    if name_key not in bare_bucket:
        return []
    own_database = part_key(index.database)
    keys = sorted(
        (located for located in map(_full_key_parts, full_bucket) if located.name == name_key),
        key=full_key,
    )
    if asked.database:
        # A Database that the name states answers for itself: the fallback relaxes the
        # schema and never the Database, so `PUR.dbo.Users` does not merge into `Response.dbo.Users`.
        keys = [located for located in keys if located.database == part_key(asked.database)]
    schema_fell_back = False
    if asked.schema:
        # The name states a schema: the full bucket answers. A name that states no
        # Database takes the Database of the index that is asked.
        asked_key = full_key(
            ObjectName("", asked.database or index.database, asked.schema, asked.name)
        )
        exact = [located for located in keys if full_key(located) == asked_key]
        schema_fell_back = not exact
        keys = exact or keys
    if not keys and not asked.database:
        # The bare bucket holds the name but no full key does (a hand-edited index):
        # the cache still answers, with no schema proven.
        keys = [ObjectName("", own_database, "", name_key)]
    rows = []
    for located in keys:
        stated = None
        if located.database != own_database:
            # The index keeps casefolded keys; a caller that typed the Database gets it back as typed.
            stated = asked.database if part_key(asked.database) == located.database else located.database
        unproven = schema_fell_back or not located.schema
        rows.append(
            LocatedDatabase(
                server=index.server,
                database=index.database,
                schema=located.schema,
                stated_database=stated,
                risk_flags=[UNPROVEN_SCHEMA] if unproven else [],
            )
        )
    return rows


def _full_key_parts(key: str) -> ObjectName:
    """Split one full key of an Object Location Index back into its three parts."""
    database, schema, name = key.split(".", 2)
    return ObjectName("", database, schema, name)


def flow_chain(
    req: FlowChainRequest, evidence_source: EvidenceSource = evidence_for_scope,
    *, scan_store: ScanStore | None = None, cache_store: CacheStore | None = None,
) -> FlowChainResponse:
    """組出「關係鏈」候選清單（純靜態組裝，見 flow_chain_builder.py，無 AI 判斷）。

    request context（請求共用上下文）統一準備掃描與證據範圍。
    本處理器建立自己的跳過回應，並將未指定主機的同名多主機資料庫視為未掃描。
    """
    context = build_request_context(
        req,
        scan_store=scan_store if scan_store is not None else RealScanStore(),
        cache_store=cache_store if cache_store is not None else RealCacheStore(),
    )
    if isinstance(context, Skipped):
        return FlowChainResponse(direction=req.direction, skipped=True)
    scans, scan, root = context.scans, context.scan, context.root
    sql_cache_identity = context.scope.sql_cache_identity
    scope = context.scope

    if req.direction == "backward":
        if req.database:
            _require_sql_execution_graph(req.database, sql_cache_identity)
        evidence = evidence_source(scope, scans, scan, root, refresh=req.refresh)
        rated_invocations: List[DbInvocation] = evidence.rated_invocations if req.database else []
        execution_graph: Dict[str, object] = evidence.graph if req.database else {}
        execution_paths = evidence.paths_of(rated_invocations)
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
            graph=execution_graph,
            invocations=rated_invocations,
            database=req.database or "",
            sql_cache_identity=sql_cache_identity,
            execution_paths=execution_paths,
        )
        return FlowChainResponse(
            direction="backward",
            backward_chains=chains,
            diagnostics=diagnostics,
            source_root=str(root),
        )

    # direction == "forward"（預設）
    # Same program resolution as /analyze: several screens of one name merge into one scope.
    matched_files, resolutions = _program_resolutions_for_names([req.program_name], scan)
    if not matched_files:
        return FlowChainResponse(direction="forward", forward_chain=None, source_root=str(root))

    def owns_file(file_path: str) -> bool:
        return any(resolution.owns_file(file_path) for resolution in resolutions)

    def owns_action(file_path: str, method_name: str) -> bool:
        return any(resolution.owns_action(file_path, method_name) for resolution in resolutions)

    rated_invocations: List[DbInvocation] = []
    execution_graph: Dict[str, object] = {}
    forward_execution_paths: List[dict] = []
    if req.database:
        _require_sql_execution_graph(req.database, sql_cache_identity)
        evidence = evidence_source(
            scope, scans, scan, root, needed_files=matched_files, refresh=req.refresh
        )
        owned = _invocation_owner(resolutions, scan, root)
        rated_invocations = [i for i in evidence.rated_invocations if owned(i)]
        execution_graph = evidence.graph
        forward_execution_paths = evidence.paths_of(rated_invocations)

    forward = flow_chain_builder.build_forward_chain(
        scan,
        req.anchor_method,
        owns_file=owns_file,
        owns_action=owns_action,
        graph=execution_graph,
        invocations=rated_invocations,
        execution_paths=forward_execution_paths,
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
    # load_sp_catalog() 在它自己的呼叫點用 sql_cache_store.find_cache_identity() 從磁碟找。
    #
    # `database` here is frequently a system id (a whole-system /refresh's
    # `req.system`, e.g. "Y-Docs_TTPUR"), not any one real SQL database --
    # `load_sp_catalog(database)` alone then always comes back empty, so
    # every call into that system's real databases (PUR, Response, ...)
    # would misreport not_in_resolved_catalog regardless of whether those
    # databases were ever scanned. `_referenced_databases` names the real
    # databases the scans' own connection strings resolve to; each is loaded
    # and merged in alongside `database` so a call is checked against its
    # own database's catalog.
    #
    # An empty `database` is a deliberate signal from registry-only wrapper-
    # contract acceptance (reclassify_cached_scans) that database evidence
    # stays unresolved on purpose -- it must touch no SQL cache at all, so
    # cross-database discovery is skipped for it too, exactly like the old
    # single `load_sp_catalog("")` call it replaces.
    scans = list(scans)
    if database:
        catalog_databases = dict.fromkeys(_referenced_databases(scans))
        catalog_databases.setdefault(database, None)
        catalog = SpCatalog.merged(load_sp_catalog(name) for name in catalog_databases)
    else:
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
        # ADR-0029 / Observed Call Evidence (ticket 04): one index per scan, built before
        # any of this scan's per-file gateways, so a Local Implementer's own method still
        # counts even when it lives in a different file than the call being rated.
        observed_call_evidence_index = build_observed_call_evidence_index(
            raw_by_file, contract_registry
        )
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
                observed_call_evidence_index=observed_call_evidence_index,
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
    # `review_candidate` answers "is the wrapper classification itself ambiguous"
    # -- it says nothing about whether the resolved database has been scanned.
    # `not_in_resolved_catalog` is the one evidence_reason `impact_orch.refresh_cli`
    # already assumes appears here regardless of `review_candidate` (see its own
    # `_needs_review`/`_print_uncataloged_database_hints`, which dedupe these by
    # (server, database) into one hint line rather than one row per call): a call
    # that resolves to exactly one procedure name through a Delegation Alias or a
    # Contract's own operation, with no overload tie, is never a review candidate,
    # but its database can still be one nobody has run `refresh_sql_cli` against.
    review_items = [
        item
        for item in observations
        if item["review_candidate"] or item["evidence_reason"] == "not_in_resolved_catalog"
    ]
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
        "ambiguous_implementation",
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


def _selector_names(selector: Any) -> List[str]:
    """Flatten a Contract Preflight selector (str / list / tuple / None) to
    the contract name list `contract_transaction.contracts` reports."""
    if isinstance(selector, str):
        return [selector] if selector.strip() else []
    if isinstance(selector, (list, tuple)):
        return [str(item) for item in selector if str(item).strip()]
    return []


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
    #
    # Each skip path below names the gate that actually stopped the commit,
    # so "not_required" keeps its literal meaning: nothing needed committing.
    # A refresh that never reaches a gate at all falls through unchanged.
    contract_transaction_summary: Dict[str, Any] = {"status": "not_required", "contracts": []}
    if partial:
        contract_transaction_summary = {"status": "program_scope", "contracts": []}
    elif not str(database or "").strip():
        contract_transaction_summary = {"status": "no_system_id", "contracts": []}
    elif preflight.failed:
        contract_transaction_summary = {"status": "preflight_failed", "contracts": []}
    elif preflight.onboarding_status in _ONBOARDING_STATUSES_ELIGIBLE_FOR_COMMIT:
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
            contract_transaction_summary["contracts"] = _selector_names(preflight.formal_selector)
        except ContractTransactionError as exc:
            contract_transaction_summary = {
                "status": "failed",
                "error_code": exc.code,
                "error": str(exc),
                "contracts": [],
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
        "framework_reports": getattr(scan, "framework_reports", []) or [],
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


class ReDecompileError(RuntimeError):
    """An explicit, named re-decompile request could not complete.

    Raised instead of guessing or partially committing: ``code`` names
    exactly which step stopped the attempt (sync, decompile, or accept), so
    a caller never mistakes a stopped attempt for a silent no-op.
    """

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def redecompile_wrapper_receiver(
    source: dict,
    receiver_type: str,
) -> dict:
    """Explicitly re-decompile one named external wrapper receiver type and
    commit its result as a registry entry.

    This is the maintainer bypass ADR-0005/0006 already describe --
    ``StaticAnalyzerHost.decompile_wrapper(..., rerun=True)`` forcing a fresh
    attempt past any cached one for that receiver's DLL only -- reached
    through an entry point that runs regardless of whether this system
    already has a valid ``wrapper_contract`` selector configured. It is
    deliberately not `refresh_source()`: that function's decompile-based
    onboarding only ever runs when a selector is unspecified (US2's own
    "valid selector never triggers decompilation" guarantee, which this
    function must not disturb), and its Contract Preflight short-circuits to
    "selected" without even looking at new proposals once a selector already
    resolves. Calling this function requires naming the receiver type
    explicitly; it never runs as a side effect of a bare, selector-less
    refresh.

    Contract acceptance for the result reuses `run_contract_preflight` with
    no selector, so a fresh proposal is evaluated the same way a from-scratch
    onboarding attempt would be: reused when its Contract Fingerprint matches
    an existing entry, created under the existing fingerprint-suffix
    collision convention otherwise (ADR-0006). The commit that follows never
    touches any system's catalog selector (`staged_selector=None`) -- only
    the registry gains the new entry; repointing a System's selector at it is
    a separate, explicit step.

    Needs no live database connection: syncing the checkout, scanning it, and
    decompiling the referenced DLL are all local operations, never a SQL
    Server round trip.
    """
    normalized_receiver = str(receiver_type or "").strip()
    if not normalized_receiver:
        raise ReDecompileError(
            "receiver_type_required",
            "receiver_type 不可為空：這個入口只接受明確命名一個 receiver type 的請求，"
            "不會退化成 selector-less 的整批重新掃描。",
        )

    try:
        roots = resolve_scan_roots(source, refresh=True)
    except (AzureFetchError, ValueError) as exc:
        raise ReDecompileError("checkout_sync_failed", str(exc)) from exc
    if not roots:
        raise ReDecompileError(
            "checkout_sync_failed", "resolve_scan_roots 未回傳任何可掃描的路徑。"
        )
    root = roots[0]

    scan = get_or_scan(root, refresh=True)
    external_sources = _external_wrapper_sources(scan)
    matched_receiver = next(
        (
            name
            for name in external_sources
            if name.casefold() == normalized_receiver.casefold()
        ),
        None,
    )
    if matched_receiver is None:
        raise ReDecompileError(
            "receiver_not_referenced",
            f"掃描結果中找不到外部 wrapper receiver：{normalized_receiver}",
        )

    csproj_path = _find_source_csproj(root, external_sources[matched_receiver])
    if csproj_path is None:
        raise ReDecompileError(
            "csproj_not_found",
            f"找不到 {matched_receiver} 對應、且唯一可判定的 .csproj。",
        )

    try:
        host = StaticAnalyzerHost.for_project(Path(__file__).resolve().parent.parent)
        host.ensure_ready()
    except StaticAnalyzerHostError as exc:
        raise ReDecompileError("decompiler_host_unavailable", str(exc)) from exc

    try:
        response = host.decompile_wrapper(csproj_path, matched_receiver, rerun=True)
    except StaticAnalyzerHostError as exc:
        raise ReDecompileError("decompiler_failed", str(exc)) from exc

    attempt = _decompilation_attempt_record(
        response, receiver_type=matched_receiver, csproj_path=csproj_path
    )

    proposals_raw = response.get("contract_proposals") or []
    if isinstance(proposals_raw, Mapping):
        proposals_raw = [proposals_raw]
    delegated_methods = response.get("delegated_methods")
    staged_proposals: list[dict[str, Any]] = []
    for proposal in proposals_raw:
        if not isinstance(proposal, Mapping):
            continue
        proposal_entry = dict(proposal)
        if not str(proposal_entry.get("evidence_kind") or "").strip():
            proposal_entry["evidence_kind"] = DECOMPILED_AUTO_EVIDENCE_KIND
        if delegated_methods:
            snapshot = proposal_entry.get("implementation_snapshot")
            if isinstance(snapshot, Mapping) and not snapshot.get("delegated_methods"):
                snapshot = dict(snapshot)
                snapshot["delegated_methods"] = list(delegated_methods)
                proposal_entry["implementation_snapshot"] = snapshot
        staged_proposals.append(proposal_entry)

    if not staged_proposals:
        raise ReDecompileError(
            "decompilation_incomplete",
            f"{matched_receiver} 的反編譯結果不完整，未產生任何可接受的 Contract 提案："
            f"{attempt.get('detail') or attempt.get('reasons')}",
        )

    scan.contract_proposals = staged_proposals
    registry = load_contract_registry()
    preflight = run_contract_preflight(
        [scan],
        selector=None,
        registry=registry,
        allow_onboarding=True,
    )
    if preflight.onboarding_status not in _ONBOARDING_STATUSES_ELIGIBLE_FOR_COMMIT:
        raise ReDecompileError(
            "contract_not_accepted",
            f"反編譯結果未能形成可接受的 Contract（onboarding_status="
            f"{preflight.onboarding_status!r}，reason={preflight.reason!r}）。",
        )

    try:
        transaction = commit_staged_contract_transaction(
            staged_registry=preflight.staged_registry or {"contracts": {}},
            trigger="manual_acceptance",
            staged_selector=None,
            system_id="",
            registry_path=CONTRACT_TRANSACTION_REGISTRY_PATH,
            catalog_path=CONTRACT_TRANSACTION_CATALOG_PATH,
            source_revision={
                "scan_root": str(root),
                "source_commit": cached_commit(root) or "",
                "receiver_type": matched_receiver,
            },
        )
    except ContractTransactionError as exc:
        raise ReDecompileError("commit_failed", str(exc)) from exc

    return {
        "receiver_type": matched_receiver,
        "csproj_path": str(csproj_path),
        "decompilation_attempt": attempt,
        "onboarding_status": preflight.onboarding_status,
        "contract_names": _selector_names(preflight.formal_selector),
        "contract_transaction": transaction,
    }


def refresh_sql_source(
    database: str,
    server: str,
    db_name: str,
    user_id: str = "",
    password: str = "",
    progress_callback: Callable[[str, int, int, str], None] | None = None,
) -> dict:
    """更新 SQL 快取指令：重新連線 SQL Server 撈取整庫 SP/View/Function 定義與
    資料表 Schema，覆寫本機落地快取（data/sql_cache/）。

    database：顯示／工單用簡稱，不參與快取鍵計算。
    server/db_name：實際連線目標，也是快取鍵的兩個組成，由呼叫端（catalog）提供；缺一時
    CacheIdentity.of() 會直接報錯，不嘗試連線。
    user_id/password：這台伺服器的掃描帳密覆寫，兩者都有值才生效（ADR-0010）。

    回傳 {database, procedures, views, functions, tables} 數量摘要；
    SQL Execution Graph 會與 object definitions 一起落地到 SQL cache。
    """
    from .sql_cache_store import CacheIdentity, get_or_dump

    data = get_or_dump(
        CacheIdentity.of(server, db_name),
        connection_server=server,
        refresh=True,
        user_id=user_id,
        password=password,
        progress_callback=progress_callback,
    )
    return {
        "database": data.get("database", database),
        "procedures": len(data.get("procedures", [])),
        "views": len(data.get("views", [])),
        "functions": len(data.get("functions", [])),
        "tables": len(data.get("tables", [])),
    }
