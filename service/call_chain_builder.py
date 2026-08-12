# service/call_chain_builder.py
"""
方法呼叫鏈建構（S3，無 AI）。

從 C# 解析結果的 MethodInfo.calls 建立「程式內部」的呼叫鏈：
僅串接目標為「同一程式所定義之方法」的呼叫，過濾框架/函式庫呼叫，
產出 List[List[str]]（每條為 A → B → C 的方法名路徑）。
"""
from __future__ import annotations

from typing import Dict, List, Set

from code_analyzer.models import FileAnalysisResult


def _known_methods(files: List[FileAnalysisResult]) -> Dict[str, List[str]]:
    """建立 method_name → 內部被呼叫的 method_name 清單（鄰接表）。

    同名方法（多載/跨類別）合併其呼叫目標。
    """
    names: Set[str] = set()
    for fr in files:
        for cls in fr.classes:
            for m in cls.methods:
                names.add(m.name)

    adj: Dict[str, List[str]] = {}
    for fr in files:
        for cls in fr.classes:
            for m in cls.methods:
                targets = adj.setdefault(m.name, [])
                for call in m.calls:
                    if call in names and call != m.name and call not in targets:
                        targets.append(call)
    return adj


def build_call_chains(
    files: List[FileAnalysisResult],
    max_depth: int = 4,
    max_chains: int = 30,
) -> List[List[str]]:
    """建立程式內部呼叫鏈。

    回傳的每條鏈長度 >= 2（至少包含一個內部呼叫）。
    具循環防護與深度上限，避免無限展開。
    """
    adj = _known_methods(files)
    if not adj:
        return []

    chains: List[List[str]] = []

    def dfs(node: str, path: List[str], visited: Set[str]) -> None:
        if len(chains) >= max_chains:
            return
        children = [c for c in adj.get(node, []) if c not in visited]
        if not children or len(path) >= max_depth:
            if len(path) >= 2:
                chains.append(list(path))
            return
        for child in children:
            if len(chains) >= max_chains:
                return
            dfs(child, path + [child], visited | {child})

    for start in adj:
        if len(chains) >= max_chains:
            break
        # 僅由「會呼叫內部方法」的起點展開
        if adj.get(start):
            dfs(start, [start], {start})

    # 去重（相同路徑只保留一次，保序）
    seen: Set[tuple] = set()
    unique: List[List[str]] = []
    for ch in chains:
        key = tuple(ch)
        if key not in seen:
            seen.add(key)
            unique.append(ch)
    return unique[:max_chains]
