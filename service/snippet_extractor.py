# service/snippet_extractor.py
"""
程式碼片段擷取（S2b，無 AI）。

依 C# 解析結果中的方法位置（CodeLocation.line_number + MethodInfo.line_count），
從原始檔讀出對應的程式碼片段，供後續 AI 整合上下文使用。

對於沒有方法位置資訊的檔案（如 .aspx / .vue 樣板），退回擷取檔案開頭片段。
"""
from __future__ import annotations

from pathlib import Path
from typing import List

from code_analyzer.models import FileAnalysisResult

from .schemas import CodeSnippet

# 編碼嘗試順序（企業舊專案常見 cp950）
_ENCODINGS = ("utf-8-sig", "utf-8", "cp950", "latin-1")


def _read_lines(file_path: Path) -> List[str]:
    """讀檔為行清單，依序嘗試多種編碼。失敗回傳空清單。"""
    for enc in _ENCODINGS:
        try:
            return file_path.read_text(encoding=enc).splitlines()
        except (UnicodeDecodeError, OSError):
            continue
    return []


def _join_non_blank_lines(lines: List[str]) -> str:
    """組裝片段時移除空白行，但保留程式碼行原有的縮排。"""
    return "\n".join(line for line in lines if line.strip())


def _rel(file_path: str, root: Path) -> str:
    try:
        return str(Path(file_path).resolve().relative_to(root.resolve()))
    except Exception:
        return file_path


def extract_snippets(
    result: FileAnalysisResult,
    root: Path,
    max_snippets: int = 20,
    max_lines_per_snippet: int = 600,
    head_lines: int = 40,
    method_filter: set[str] | None = None,
) -> List[CodeSnippet]:
    """
    從單一檔案的解析結果擷取程式碼片段。

    參數：
      result               ：C# 檔案解析結果（含 classes/methods 與位置）。
      root                 ：repo 根目錄，用於產生相對路徑。
      max_snippets         ：最多回傳幾個片段。
      max_lines_per_snippet：單一方法片段的行數上限（避免過長）。
      head_lines           ：無方法位置時，擷取檔案開頭的行數。
      method_filter        ：若指定，只擷取這些方法名（用於跨程式展開時只拿
                             實際被呼叫到的單一方法，控制篇幅）。
    """
    file_path = Path(result.file_path)
    lines = _read_lines(file_path)
    if not lines:
        return []

    rel_path = _rel(result.file_path, root)
    total = len(lines)
    snippets: List[CodeSnippet] = []

    # 1) 依方法位置擷取
    for cls in result.classes:
        for method in cls.methods:
            if len(snippets) >= max_snippets:
                break
            if method_filter is not None and method.name not in method_filter:
                continue
            loc = getattr(method, "location", None)
            if not loc or not getattr(loc, "line_number", 0):
                continue
            start = max(1, int(loc.line_number))
            span = max(1, int(getattr(method, "line_count", 0) or 1))
            end = min(total, start + min(span, max_lines_per_snippet) - 1)
            text = _join_non_blank_lines(lines[start - 1:end])
            if not text.strip():
                continue
            snippets.append(
                CodeSnippet(
                    file=rel_path,
                    label=f"{cls.name}.{method.name}",
                    lines=f"{start}-{end}",
                    text=text,
                )
            )
        if len(snippets) >= max_snippets:
            break

    # 2) 無方法位置 → 退回檔案開頭片段
    if not snippets:
        end = min(total, head_lines)
        text = _join_non_blank_lines(lines[:end])
        if text.strip():
            snippets.append(
                CodeSnippet(
                    file=rel_path,
                    label="file head",
                    lines=f"1-{end}",
                    text=text,
                )
            )

    return snippets
