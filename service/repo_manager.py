# service/repo_manager.py
"""
程式碼來源管理（clone 進 data/，不讀取任意本機路徑）。

設計原則：
  - 每個系統的程式碼一律放在 AZURE_CLONE_ROOT/<project>__<repo> 之下。
  - 第一次分析時若該目錄不存在 → 從 Azure DevOps clone。
  - 之後直接沿用已 clone 的副本，**不**自動 git pull。
  - 只有在「更新指令」（refresh=True）時才 git pull 取得最新程式碼。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Union

from config.settings import settings
from code_analyzer.azure_fetcher import AzureDevOpsFetcher


def _safe_dirname(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", text or "").strip("_") or "default"


def repo_dir(project: str, repo: str) -> Path:
    """回傳某 project/repo 的本機 clone 根目錄（不保證已存在）。

    採巢狀結構 data/repos/<project>/<repo>，對應 Azure DevOps 的
    org/project/_git/repo 階層，方便瀏覽與依 project 分組。
    """
    return Path(settings.AZURE_CLONE_ROOT) / _safe_dirname(project) / _safe_dirname(repo)


def is_cloned(project: str, repo: str) -> bool:
    """判斷該 repo 是否已 clone 至 data/。"""
    return (repo_dir(project, repo) / ".git").exists()


def _clone_or_pull(source: dict, refresh: bool = False) -> Path:
    """確保 repo 已 clone 至 data/（或視 refresh 執行 git pull），回傳 repo 根目錄。"""
    project = (source or {}).get("project", "")
    repo = (source or {}).get("repo", "")
    branch = (source or {}).get("branch", "")

    if not repo:
        raise ValueError(
            "source.repo 為空：本系統未在 catalog 設定 Azure repo，"
            "無法定位程式碼（已停用讀取本機任意路徑）。"
        )

    org = settings.AZURE_DEVOPS_ORG
    pat = settings.AZURE_DEVOPS_PAT
    if not (org and pat):
        raise ValueError("缺少 AZURE_DEVOPS_ORG / AZURE_DEVOPS_PAT，請寫入 Impact 服務的 .env")

    target = repo_dir(project, repo)
    target.parent.mkdir(parents=True, exist_ok=True)

    fetcher = AzureDevOpsFetcher(
        org=org,
        project=project,
        repo=repo,
        pat=pat,
        branch=branch or settings.AZURE_DEVOPS_BRANCH or "main",
        clone_dir=str(target),
    )
    # 已存在且非 refresh → 沿用，不 pull；不存在 → clone；refresh → pull
    return fetcher.fetch(update=refresh)


def ensure_repo(source: dict, refresh: bool = False) -> Path:
    """
    確保來源程式碼已存在於 data/，回傳要掃描的路徑。

    參數：
      source ：{project, repo, branch, path}。repo 不可為空（不讀取本機路徑）。
              path 若為多個子資料夾清單，僅回傳第一個存在的子資料夾（單一路徑版，
              向下相容既有呼叫端）；需要一次掃描多個子資料夾時請改用
              resolve_scan_roots()。
      refresh：True → 已存在時執行 git pull 取得最新；False → 沿用現有 clone。

    回傳：要掃描的本機路徑（若 source.path 非空則為其子資料夾）。
    """
    repo_root = _clone_or_pull(source, refresh)
    sub_path = (source or {}).get("path", "")
    if isinstance(sub_path, list):
        sub_path = sub_path[0] if sub_path else ""
    if sub_path:
        sub = repo_root / sub_path
        if sub.exists():
            return sub
    return repo_root


def resolve_scan_roots(source: dict, refresh: bool = False) -> List[Path]:
    """解析要掃描的（可能多個）本機路徑清單，必要時 clone/pull repo。

    source.path 可以是：
      - 空字串：回傳整個 repo 根目錄 [repo_root]。
      - 單一字串子資料夾：回傳該子資料夾（存在時）或 fallback 回 repo_root。
      - 多個子資料夾的清單：用於「同一套系統的功能拆成多個 VS 專案資料夾」的情境
        （例如 Y-Docs_TTPUR 除了 TTPUR/ 外，還有 ATV/、Notification/、Response/
        這些屬於同一系統的兄弟資料夾）；只回傳實際存在的子資料夾，其餘（如
        TaskSchedule_*、TTRDQ 等不屬於本系統的資料夾）不會被納入、也不會被掃描到。
    """
    repo_root = _clone_or_pull(source, refresh)
    sub_path = (source or {}).get("path", "")
    if not sub_path:
        return [repo_root]

    sub_paths = [sub_path] if isinstance(sub_path, str) else list(sub_path)
    roots: List[Path] = []
    for sp in sub_paths:
        if not sp:
            continue
        candidate = repo_root / sp
        if candidate.exists():
            roots.append(candidate)
    return roots or [repo_root]


def peek_scan_roots(source: dict) -> List[Path]:
    """在不觸發 clone/pull 的前提下，推算要掃描的本機路徑清單（僅用於檢查快取是否
    已存在，不保證 repo/子資料夾實際存在——呼叫端應自行以 Path.exists() 或
    scan_store.has_cache() 判斷）。邏輯與 resolve_scan_roots() 一致，但不連網路。
    """
    project = (source or {}).get("project", "")
    repo = (source or {}).get("repo", "")
    sub_path = (source or {}).get("path", "")
    repo_root = repo_dir(project, repo)
    if not sub_path:
        return [repo_root]

    sub_paths = [sub_path] if isinstance(sub_path, str) else list(sub_path)
    roots: List[Path] = []
    for sp in sub_paths:
        if not sp:
            continue
        candidate = repo_root / sp
        if candidate.exists():
            roots.append(candidate)
    return roots or [repo_root]
