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


def ensure_repo(source: dict, refresh: bool = False) -> Path:
    """
    確保來源程式碼已存在於 data/，回傳要掃描的路徑。

    參數：
      source ：{project, repo, branch, path}。repo 不可為空（不讀取本機路徑）。
      refresh：True → 已存在時執行 git pull 取得最新；False → 沿用現有 clone。

    回傳：要掃描的本機路徑（若 source.path 非空則為其子資料夾）。
    """
    project = (source or {}).get("project", "")
    repo = (source or {}).get("repo", "")
    branch = (source or {}).get("branch", "")
    sub_path = (source or {}).get("path", "")

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
    repo_root = fetcher.fetch(update=refresh)

    if sub_path:
        sub = repo_root / sub_path
        if sub.exists():
            return sub
    return repo_root
