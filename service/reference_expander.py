# service/reference_expander.py
"""
跨程式參照展開（無 AI）。

類似 VS Code Copilot「跟隨參照」（go-to-definition）自動把相關檔案拉進上下文：
使用者只點名了 A 程式，但 A 呼叫了定義在 B 程式（另一支 .cs/.aspx.cs）的方法，
這裡就沿著每個呼叫的 Bound Call Target（ADR-0044），把「B 也被呼叫到」這件事
找出來，最多展開 depth 層，並回傳足以識別 + 擷取片段的定位資訊。

呼叫邊與正向 flow chain 是同一份（flow_chain_builder.bound_call_edges）：
analyzer host 以 semantic model 綁定每個呼叫，介面方法依 Local Implementer
規則解析到實作類別。這裡不再比對呼叫文字裡的方法名稱，所以介面與實作同名、
或兩個類別各有同名方法時，一個呼叫只會列出它真正呼叫到的那一個方法。
沒有 Bound Call Target 的呼叫不產生任何項目。

只用整個掃描結果（ProjectScanResult）既有的靜態解析資料，不重新掃描、
不連 AI，可獨立驗證正確性。
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, List, NamedTuple, Set, Tuple

from code_analyzer.models import FileAnalysisResult
from code_analyzer.project_scanner import ProjectScanResult

from .call_graph_nodes import MethodNodes
from .flow_chain_builder import bound_call_edges


class _Declaration(NamedTuple):
    """One declaration of a call graph node: the file, the class and the method."""

    file_path: str
    class_name: str
    method_name: str


class _Caller(NamedTuple):
    """One node to walk, and the file and the method that `called_by` names for its calls."""

    node: str
    file_path: str
    method_name: str


def _declarations(
    csharp_results: List[FileAnalysisResult], nodes: MethodNodes
) -> Dict[str, List[_Declaration]]:
    """node（`MethodSourceSpan.node`）-> [(宣告它的檔案, 類別名, 方法名), ...]。

    節點是綁定後的方法符號（ADR-0044），所以一個節點只有一個宣告；同一個檔案被兩個
    掃描結果列到時，才會重複，這裡只留一筆。
    """
    declared: Dict[str, List[_Declaration]] = {}
    for fr in csharp_results:
        for span in nodes.spans_of(fr.file_path):
            entries = declared.setdefault(span.node, [])
            declaration = _Declaration(fr.file_path, span.class_name, span.method_name)
            if declaration not in entries:
                entries.append(declaration)
    return declared


def expand_related_programs(
    scan: ProjectScanResult,
    matched_files: List[FileAnalysisResult],
    *,
    owns_action: Callable[[str, str], bool] = lambda file_path, method_name: True,
    depth: int = 1,
    max_programs: int = 10,
) -> List[dict]:
    """從 matched_files 出發，沿 Bound Call Target 找出定義在「其他檔案」的方法，展開最多 depth 層。

    參數：
      scan         ：整個掃描根目錄的掃描結果（呼叫邊與方法宣告的來源）。
      matched_files：使用者點名程式對應到的檔案（展開起點）。
      owns_action  ：這支程式是否擁有某檔案裡的某個方法；只有它擁有的方法是起點
                     （MVC Program Screen 只擁有自己的 action，見 ADR-0019；
                     WebForms 程式擁有檔案內所有方法）。
      depth        ：展開層數（1 = 只找起點方法直接呼叫到的其他檔案）。
      max_programs ：最多回傳幾個相關程式（避免無限展開撐爆 prompt）。

    每一層只沿「被呼叫到的方法」繼續展開，不展開被呼叫檔案裡的其他方法
    （ADR-0044）。呼叫到同一檔案（或起點檔案）裡的方法屬於程式內部呼叫：不列出、
    不佔層數，但會在同一層繼續沿它的呼叫走下去。

    回傳：[{"file", "class", "method", "called_by", "depth"}, ...]，依發現順序、去重
    （同一個 (檔案, 節點) 只列一次；同一個檔案的不同方法仍各自列出，因為它們是
    不同的程式碼片段，如 CommonFunction.AlertMsg 與 CommonFunction.OpenWindow）。
    `called_by` 是呼叫者所在檔案的檔名（不含最後一個副檔名）加方法名。
    """
    if depth <= 0 or not matched_files:
        return []

    edges = bound_call_edges(scan)
    nodes = MethodNodes(scan)
    declared = _declarations(scan.csharp_results, nodes)
    start_files: Set[str] = {fr.file_path for fr in matched_files}

    frontier: List[_Caller] = []
    # 已排進 frontier 或 queue 的節點；每個節點只走一次。
    queued_nodes: Set[str] = set()
    for fr in matched_files:
        for span in nodes.spans_of(fr.file_path):
            if span.node not in queued_nodes and owns_action(fr.file_path, span.method_name):
                queued_nodes.add(span.node)
                frontier.append(_Caller(span.node, fr.file_path, span.method_name))

    # 已列進結果的 (檔案, 節點)。
    reported: Set[Tuple[str, str]] = set()
    related: List[dict] = []
    for d in range(1, depth + 1):
        next_frontier: List[_Caller] = []
        # 程式內部呼叫會在同一層加進 queue 繼續走。
        queue = list(frontier)
        while queue:
            node, caller_file, caller_method = queue.pop(0)
            for target in edges.get(node, []):
                for target_file, target_class, target_method in declared.get(target, []):
                    if target_file == caller_file or target_file in start_files:
                        if target not in queued_nodes:
                            queued_nodes.add(target)
                            queue.append(_Caller(target, target_file, target_method))
                        continue
                    if (target_file, target) in reported:
                        continue
                    reported.add((target_file, target))
                    related.append(
                        {
                            "file": target_file,
                            "class": target_class,
                            "method": target_method,
                            "called_by": f"{Path(caller_file).stem}.{caller_method}",
                            "depth": d,
                        }
                    )
                    if len(related) >= max_programs:
                        return related
                    if target not in queued_nodes:
                        queued_nodes.add(target)
                        next_frontier.append(_Caller(target, target_file, target_method))
        frontier = next_frontier
        if not frontier:
            break

    return related
