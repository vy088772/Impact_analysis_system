# service/reference_expander.py
"""
跨程式參照展開（無 AI）。

類似 VS Code Copilot「跟隨參照」（go-to-definition）自動把相關檔案拉進上下文：
使用者只點名了 A 程式，但 A 呼叫了定義在 B 程式（另一支 .cs/.aspx.cs）的方法，
這裡就沿著既有解析結果的 MethodInfo.calls，把「B 也被呼叫到」這件事找出來，
最多展開 depth 層，並回傳足以識別 + 擷取片段的定位資訊。

僅用整個掃描結果（ProjectScanResult.csharp_results）既有的靜態解析資料做名稱比對，
不重新掃描、不連 AI，可獨立驗證正確性。
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Set, Tuple

from code_analyzer.models import FileAnalysisResult


def _method_index(csharp_results: List[FileAnalysisResult]) -> Dict[str, List[Tuple[str, str]]]:
    """建立 method_name → [(file_path, class_name), ...] 的全域索引（跨整個掃描結果）。

    排除「方法名與所屬類別名相同」的項目：C# 建構子（如 `public Foo()`）在原始碼
    中沒有獨立的傳回型別，csharp_parser 的方法規則比對建構子時，偶爾會誤把類別名
    本身當成傳回型別、方法名仍取到類別名（例如 `public GetColumnIndex()` 被誤判成
    一個叫 `GetColumnIndex` 的方法）。這種「同名假方法」不是可展開的外部呼叫目標，
    若不濾除，`new GetColumnIndex()` 這類建構呼叫會被誤配到這個假方法，把該檔案
    標記為已展開（visited），導致同一支程式裡真正的呼叫（如
    `GetColumnIndexByFieldName`）反而被擠掉、展開不到。
    """
    index: Dict[str, List[Tuple[str, str]]] = {}
    for fr in csharp_results:
        for cls in fr.classes:
            for m in cls.methods:
                if m.name == cls.name:
                    continue
                index.setdefault(m.name, []).append((fr.file_path, cls.name))
    return index


def _calls_in_file(fr: FileAnalysisResult) -> List[Tuple[str, str, str]]:
    """攤平出這個檔案內所有方法呼叫的 (被呼叫方法名, 呼叫者方法名, 呼叫者類別名)。"""
    out: List[Tuple[str, str, str]] = []
    for cls in fr.classes:
        for m in cls.methods:
            for call in m.calls:
                out.append((call, m.name, cls.name))
    return out


def _own_method_names(fr: FileAnalysisResult) -> Dict[str, Set[str]]:
    """回傳 {類別名: {該類別自己的方法名, ...}}。

    用於判斷一個呼叫是否為「同類別內部呼叫」（例如 WebForms 常見的
    `BindSelCustomer()` 這種無限定子呼叫，其實就是呼叫 this 所屬類別自己
    的方法）。這類呼叫的定義本來就已經在起點程式的 code_snippets 裡，
    不該被當成「未解析、需跨檔展開」而拿全域同名方法比對——否則像
    `BindSelCustomer` 這種在多支程式間常見的複製貼上 helper 名稱，
    會被誤配到完全不相干的其他程式，把 max_programs 名額擠光，
    導致真正該展開的呼叫（如 CommonFunction.AlertMsg）反而展開不到。
    """
    return {cls.name: {m.name for m in cls.methods} for cls in fr.classes}


def _known_class_names(csharp_results: List[FileAnalysisResult]) -> Set[str]:
    """回傳整個掃描結果中所有已知類別名稱（用於判斷呼叫限定子是否為類別名）。"""
    return {cls.name for fr in csharp_results for cls in fr.classes}


def _split_call(call: str) -> Tuple[str, str]:
    """把 MethodInfo.calls 內的呼叫字串拆成 (限定子, 方法名)。無限定子時限定子為空字串。"""
    if "." in call:
        qualifier, name = call.rsplit(".", 1)
        return qualifier, name
    return "", call


def expand_related_programs(
    csharp_results: List[FileAnalysisResult],
    matched_files: List[FileAnalysisResult],
    depth: int = 1,
    max_programs: int = 10,
) -> List[dict]:
    """從 matched_files 出發，沿呼叫關係找出定義在「其他檔案」的方法，展開最多 depth 層。

    參數：
      csharp_results：整個 repo 的 C# 解析結果（全域索引來源）。
      matched_files ：使用者點名程式對應到的檔案（展開起點）。
      depth         ：展開層數（1 = 只找直接呼叫到的其他檔案）。
      max_programs  ：最多回傳幾個相關程式（避免無限展開撐爆 prompt）。

    回傳：[{"file", "class", "method", "called_by", "depth"}, ...]，依發現順序、去重
    （同一個 (檔案, 方法) 只列一次；不同方法即使來自同一個檔案，仍各自列出，
    因為它們是不同的程式碼片段/不同的上下文依據，如 CommonFunction.AlertMsg
    與 CommonFunction.OpenWindow 應分別列出，而不是同檔案只挑第一個發現的方法）。
    """
    if depth <= 0 or not matched_files:
        return []

    index = _method_index(csharp_results)
    known_classes = _known_class_names(csharp_results)
    by_path = {fr.file_path: fr for fr in csharp_results}
    start_files: Set[str] = {fr.file_path for fr in matched_files}
    visited_calls: Set[Tuple[str, str]] = set()
    seen_frontier_files: Set[str] = set(start_files)
    frontier: List[FileAnalysisResult] = list(matched_files)
    related: List[dict] = []

    for d in range(1, depth + 1):
        if len(related) >= max_programs:
            break
        next_frontier: List[FileAnalysisResult] = []
        for fr in frontier:
            own_by_class = _own_method_names(fr)
            for call, caller_method, caller_class in _calls_in_file(fr):
                if len(related) >= max_programs:
                    break
                qualifier, call_name = _split_call(call)

                # 無限定子呼叫若已是呼叫者自己類別的方法 → 本地呼叫，
                # 定義已在起點程式本身，不當作跨程式參照展開。
                if not qualifier and call_name in own_by_class.get(caller_class, set()):
                    continue

                candidates = index.get(call_name, [])
                if qualifier and qualifier in known_classes:
                    # 限定子恰為一個已知類別名（如 CommonFunction.AlertMsg 這種
                    # 靜態工具呼叫）→ 只取該類別的定義，避免同名方法在其他
                    # 不相干類別間誤配（如許多頁面各自複製貼上的同名 helper）。
                    candidates = [c for c in candidates if c[1] == qualifier]
                elif len(candidates) > 1:
                    # 限定子不是已知類別名（無限定子，或 obj.Xxx 這種實例變數呼叫，
                    # 例如 DB helper 的 obj.CreateTable(...)），只能靠「方法名」比對，
                    # 無法確定歸屬哪個類別。若此名稱在整個 repo 有多個同名定義
                    # （最典型如每支頁面各自的 private CreateTable() 建 DataTable），
                    # 這是巧合同名、而非同一個真正的呼叫目標；把它們全部展開只會
                    # 塞進大量不相干、又佔行數的片段。無法確定 → 直接跳過。
                    continue

                for target_file, target_class in candidates:
                    if target_file in start_files:
                        continue
                    key = (target_file, call_name)
                    if key in visited_calls:
                        continue
                    visited_calls.add(key)
                    related.append(
                        {
                            "file": target_file,
                            "class": target_class,
                            "method": call_name,
                            "called_by": f"{Path(fr.file_path).stem}.{caller_method}",
                            "depth": d,
                        }
                    )
                    target_fr = by_path.get(target_file)
                    if target_fr and target_file not in seen_frontier_files:
                        seen_frontier_files.add(target_file)
                        next_frontier.append(target_fr)
                    if len(related) >= max_programs:
                        break
            if len(related) >= max_programs:
                break
        frontier = next_frontier
        if not frontier:
            break

    return related[:max_programs]
