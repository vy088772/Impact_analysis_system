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
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Mapping, Tuple

from config.settings import settings
from code_analyzer.azure_fetcher import AzureDevOpsFetcher, AzureFetchError
from code_analyzer.csharp_analysis_gateway import (
    CSharpAnalysisGateway,
    DbInvocation,
    InvocationEvidence,
    SpCatalog,
    normalize_procedure_name,
)
from code_analyzer.project_scanner import ProjectScanner, ProjectScanResult

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
from .execution_path_builder import build_compact_execution_path_payload, build_execution_paths
from .graph_queries import query_table_accesses
from .reference_expander import expand_related_programs
from .repo_manager import repo_dir, resolve_scan_roots, peek_scan_roots
from .scan_store import get_or_scan, has_cache
from . import sql_cache_store
from . import flow_chain_builder


class PathEvidenceError(ValueError):
    """A path cannot be expanded from the current source or SQL snapshots."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code

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
    for s in scans:
        merged.total_files += s.total_files
        merged.scanned_files += s.scanned_files
        merged.failed_files += s.failed_files
        merged.csharp_results.extend(s.csharp_results)
        merged.source_snapshots.update(getattr(s, "source_snapshots", {}))
        merged.db_invocations.update(getattr(s, "db_invocations", {}))
        merged.connection_sources.update(getattr(s, "connection_sources", {}))
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


def _execution_path_context(
    req: AnalyzeRequest,
    scan: ProjectScanResult,
) -> Tuple[SpCatalog, Dict, str]:
    """Load the selected SQL graph and build its database-scoped SP catalog."""
    database_alias = str(getattr(req, "database", "") or "")
    cached = sql_cache_store.load_cached(database_alias, "dbo") if database_alias else None
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


def _require_sql_execution_graph(database: str) -> Tuple[Dict, Dict]:
    database = str(database or "").strip()
    if not database:
        raise ValueError(
            "database 不可為空；Gateway path analysis 需要指定 SQL execution graph cache。"
        )
    cached = sql_cache_store.load_cached(database, "dbo")
    graph = (cached or {}).get("sql_execution_graph") if cached else None
    if not cached or not graph:
        raise ValueError(
            f"SQL execution graph cache 不存在或版本已失效：{database}。"
            "請重新執行 refresh_sql_cli <system_id> 或 POST /refresh_sql。"
        )
    return cached, dict(graph)


def _execution_connection_sources(
    scan: ProjectScanResult,
    file_path: str,
    graph_database: str,
    database_aliases: Iterable[str] = (),
) -> Dict[str, str]:
    """Resolve raw connection expressions for one file into the selected graph scope."""
    file_key = str(Path(file_path).resolve())
    sources = dict(getattr(scan, "connection_sources", {}).get(file_key, {}) or {})

    if not graph_database:
        return sources

    # One /analyze request selects one SQL cache scope. A single legacy connection
    # label (such as "PUR") therefore resolves to that selected graph identity.
    # Multiple distinct labels are kept separate so one file cannot silently map
    # cross-database connections to the selected graph.
    known_databases = {
        value.strip().casefold()
        for value in (*database_aliases, graph_database)
        if value and value.strip()
    }
    source_values = {
        value.strip().casefold()
        for value in sources.values()
        if value and value.strip()
    }
    if not source_values:
        return sources
    if len(source_values) <= 1:
        return {expression: graph_database for expression in sources}
    return {
        expression: (
            graph_database
            if source.strip().casefold() in known_databases
            else source
        )
        for expression, source in sources.items()
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
    catalog, graph, graph_database = _execution_path_context(req, scan)
    rated_invocations = []
    raw_by_file = getattr(scan, "db_invocations", {})

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
        )
        relative_path = _rel(file_result.file_path, root)
        for invocation in gateway.resolve_direct_invocations(relative_path, raw_invocations):
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
    return {
        "class_name": invocation.class_name,
        "method_name": invocation.method_name,
        "database": invocation.database,
        "procedure_name": invocation.procedure_name,
        "evidence": invocation.evidence.value,
        "reason": invocation.reason,
        "source_span": {
            "relative_path": invocation.source.relative_path,
            "start_offset": invocation.source.start_offset,
            "end_offset": invocation.source.end_offset,
        },
        "procedure_schema": invocation.procedure_schema,
        "method_chain": list(invocation.method_chain),
        "method_class_chain": list(invocation.method_class_chain),
        "branch_context": list(invocation.branch_context),
        "source_snapshot_hash": invocation.source_snapshot_hash,
    }


def _build_program_execution_paths(
    req: AnalyzeRequest,
    scan: ProjectScanResult,
    matched_files: List,
    root: Path,
) -> Tuple[List[Dict], Dict[str, object]]:
    """Join one program's raw C# facts to the selected SQL execution graph."""
    if req.database:
        _require_sql_execution_graph(req.database)
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
    compact_payload = build_compact_execution_path_payload(paths)
    return paths, compact_payload


def get_path_evidence(req: PathEvidenceRequest) -> PathEvidenceResponse:
    """Expand one current Execution Path into source-backed, path-scoped evidence."""
    path_id = (req.path_id or "").strip()
    if not path_id:
        raise PathEvidenceError("invalid_path_id", "path_id 不可為空")

    roots = resolve_source(req)  # type: ignore[arg-type]
    if not roots:
        raise PathEvidenceError("source_not_found", "找不到 path evidence 的原始碼來源")
    scans = [_get_scan(root, refresh=req.refresh) for root in roots]
    scan = scans[0] if len(scans) == 1 else _merge_scans(scans)
    root = roots[0] if len(roots) == 1 else repo_dir(
        req.source.project if req.source else "",
        req.source.repo if req.source else "",
    )

    cached = sql_cache_store.load_cached(req.database, "dbo") if req.database else None
    graph = dict((cached or {}).get("sql_execution_graph") or {})
    if cached is None or not graph:
        raise PathEvidenceError(
            "sql_graph_cache_missing",
            "SQL execution graph cache 尚未建立，無法展開 path evidence",
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
    )


def _materialize_path_evidence(
    path: Mapping[str, object],
    invocation: DbInvocation,
    scan: ProjectScanResult,
    cached: Mapping[str, object],
    graph: Mapping[str, object],
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
    if operation is None and path.get("evidence") != "unresolved":
        raise PathEvidenceError("stale_path", f"terminal operation 已不存在：{operation_id}")

    operation_evidence: Dict = {}
    if operation is not None:
        operation_evidence = dict(operation)
        source_location = dict(operation.get("source") or {})
        operation_module_id = str(operation.get("module_id") or "")
        operation_module = module_objects.get(operation_module_id)
        if operation_module is not None and source_location:
            try:
                source_text = _slice_utf16(
                    str(operation_module.get("definition") or ""),
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

    return PathEvidenceResponse(
        path_id=str(path.get("path_id") or ""),
        entry_method=str(path.get("entry_method") or ""),
        method_chain=list(path.get("method_chain", []) or []),
        database=str(path.get("database") or ""),
        sp_chain=list(path.get("sp_chain", []) or []),
        conditions=list(path.get("conditions", []) or []),
        risk_flags=list(path.get("risk_flags", []) or []),
        evidence=str(path.get("evidence") or "unresolved"),
        unresolved_reason=str(path.get("unresolved_reason") or ""),
        unresolved_targets=list(path.get("unresolved_targets", []) or []),
        csharp_methods=csharp_methods,
        stored_procedures=stored_procedures,
        operations=[operation_evidence] if operation_evidence else [],
        views=views,
        functions=functions,
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
            if invocation.procedure_name and invocation.procedure_name not in sp_names:
                sp_names.append(invocation.procedure_name)
        database_invocations = [
            _serialize_db_invocation(invocation)
            for invocation in rated_invocations
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
        return str(Path(file_path).resolve().relative_to(root.resolve()))
    except Exception:
        return file_path


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
    seen_files: set = set()
    if not req.database:
        raise ValueError(
            "find_by_sp 需要 database 以載入 SQL execution graph；"
            "請提供 system_id 並先執行 refresh_sql_cli。"
        )
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
            or invocation.evidence == InvocationEvidence.UNRESOLVED
        ):
            continue
        csharp_file = _source_file_for_span(
            scan,
            root,
            invocation.source.relative_path,
        )
        if not csharp_file or csharp_file in seen_files:
            continue
        seen_files.add(csharp_file)
        matches.append(
            SPMatchProgram(
                program=_normalize_program(Path(csharp_file).name),
                file=_rel(csharp_file, root),
            )
        )

    return FindBySPResponse(sp_name=sp_name, matches=matches, source_root=str(root))


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
    for rel in scan.table_relations:
        if _normalize_table(rel.table_name) != table_norm:
            continue
        candidate = TableMatchProgram(
            program=_normalize_program(Path(rel.csharp_file).name),
            file=_rel(rel.csharp_file, root),
            # Inline C# SQL remains a direct source fact; SQL-module relationships
            # are queried from the Execution Graph below.
            access_type=rel.access_type,
        )
        _prefer_table_match(matches_by_file, candidate)

    # Stored-procedure access is joined through Gateway invocations and the graph.
    # Do not fall back to SQL dependency dictionaries or definition-text guesses.
    if req.database:
        _sql_cache, graph = _require_sql_execution_graph(req.database)
        rated_invocations, graph = _rated_execution_invocations(
            req,
            scan,
            list(scan.csharp_results),
            root,
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
            candidate = TableMatchProgram(
                program=_normalize_program(Path(csharp_file).name),
                file=_rel(csharp_file, root),
                via_sp=True,
                access_type=access_type,
                path_id=str(access_record.get("path_id") or ""),
                entry_method=str(access_record.get("entry_method") or ""),
                sp_chain=sp_chain,
                evidence=str(access_record.get("evidence") or "unresolved"),
                operation_type=operation_type,
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
        source_root=str(root),
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
            _cached, execution_graph = _require_sql_execution_graph(req.database)
            rated_invocations, execution_graph = _rated_execution_invocations(
                req,
                scan,
                list(scan.csharp_results),
                root,
            )
        chains = flow_chain_builder.build_backward_chains(
            scan,
            root,
            req.table_name,
            column_name=req.column_name or None,
            database_alias=database_alias,
            graph=execution_graph,
            invocations=rated_invocations,
        )
        return FlowChainResponse(direction="backward", backward_chains=chains, source_root=str(root))

    # direction == "forward"（預設）
    program_base = _normalize_program(req.program_name)
    matched_files = [r for r in scan.csharp_results if _file_matches(r.file_path, program_base)]
    if not matched_files:
        return FlowChainResponse(direction="forward", forward_chain=None, source_root=str(root))

    rated_invocations: List[DbInvocation] = []
    execution_graph: Dict[str, object] = {}
    if req.database:
        _cached, execution_graph = _require_sql_execution_graph(req.database)
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
    return FlowChainResponse(direction="forward", forward_chain=forward, source_root=str(root))


def refresh_source(source: dict) -> dict:
    """更新指令：git pull 取得最新程式碼並重新解析，覆寫快取。

    回傳 {source_root, files} 摘要。
    """
    roots = resolve_scan_roots(source, refresh=True)
    scans = [get_or_scan(r, refresh=True) for r in roots]
    scan = scans[0] if len(scans) == 1 else _merge_scans(scans)
    root = roots[0] if len(roots) == 1 else repo_dir(
        (source or {}).get("project", ""), (source or {}).get("repo", "")
    )
    database_invocation_count = len(scan.iter_formal_sp_invocations())
    inline_table_fact_count = len(scan.table_relations)
    return {
        "source_root": str(root),
        "files": len(scan.csharp_results),
        "database_invocations": database_invocation_count,
        "inline_table_facts": inline_table_fact_count,
        # Deprecated aliases retained for existing clients during migration.
        "sp_relations": database_invocation_count,
        "table_relations": inline_table_fact_count,
    }


def refresh_sql_source(
    database: str,
    server: str,
    db_name: str,
    schema: str = "dbo",
    progress_callback: Callable[[str, int, int, str], None] | None = None,
) -> dict:
    """更新 SQL 快取指令：重新連線 SQL Server 撈取整庫 SP/View/Function 定義與
    資料表 Schema，覆寫本機落地快取（data/sql_cache/）。

    database：快取鍵／顯示簡稱（通常是呼叫端的 system_id）。
    server/db_name：實際連線目標，由呼叫端（catalog）提供；缺一時
    get_or_dump()→SQLAnalyzer 會直接報錯，不嘗試連線。

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
