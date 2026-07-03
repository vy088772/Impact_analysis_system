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
from pathlib import Path
from typing import Dict, List, Tuple

from config.settings import settings
from code_analyzer.azure_fetcher import AzureDevOpsFetcher, AzureFetchError
from code_analyzer.project_scanner import ProjectScanner, ProjectScanResult

from .schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    ProgramAnalysis,
)
from .snippet_extractor import extract_snippets
from .call_chain_builder import build_call_chains
from .fk_resolver import resolve_fk_related
from .sp_fetcher import fetch_sp_definitions
from .reference_expander import expand_related_programs
from .repo_manager import ensure_repo
from .scan_store import get_or_scan

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

def resolve_source(req: AnalyzeRequest) -> Path:
    """
    解析請求來源 → 回傳要掃描的本機路徑（一律位於 data/repos 之下）。

    - 透過 repo_manager 確保程式碼已 clone 至 data/；不讀取任意本機路徑。
    - req.refresh=True 時，已存在的 clone 會先 git pull 取得最新。
    - source.path 非空且存在 → 限定在該子資料夾（區分同 repo 多系統）。
    """
    return ensure_repo(
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


# ─────────────────────────────────────────────────────────────────────────────
# 主分析
# ─────────────────────────────────────────────────────────────────────────────

def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    """依 program_names 過濾掃描結果，組成回應（純靜態，無 AI）。"""
    root = resolve_source(req)
    scan = _get_scan(root, refresh=getattr(req, "refresh", False))

    programs: List[ProgramAnalysis] = []
    not_found: List[str] = []

    for raw_name in req.program_names:
        program_base = _normalize_program(raw_name)

        # 1) 比對 C# 解析結果（取得檔案、框架、方法）
        matched_files = [
            r for r in scan.csharp_results if _file_matches(r.file_path, program_base)
        ]

        # 2) 比對 SP / Table 關聯
        sp_names: List[str] = []
        for rel in scan.sp_relations:
            if _file_matches(rel.csharp_file, program_base) and rel.sp_name not in sp_names:
                sp_names.append(rel.sp_name)

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
            )

        # SP 完整定義（選用，需 DB 連線；讓 AI 看得到 SP 實際邏輯）
        sp_definitions: List[Dict] = []
        if req.include_sp_defs and sp_names:
            sp_definitions = fetch_sp_definitions(
                sp_names,
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
                related_programs=related_programs,
                view_layer=view_layer,
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


def refresh_source(source: dict) -> dict:
    """更新指令：git pull 取得最新程式碼並重新解析，覆寫快取。

    回傳 {source_root, files} 摘要。
    """
    root = ensure_repo(source, refresh=True)
    scan = get_or_scan(root, refresh=True)
    return {
        "source_root": str(root),
        "files": len(scan.csharp_results),
        "sp_relations": len(scan.sp_relations),
        "table_relations": len(scan.table_relations),
    }
