# code_analyzer/azure_fetcher.py
"""
Azure DevOps 程式碼擷取器
使用 git clone（含 PAT 驗證）將 Azure Repos 的程式碼下載至本機目錄
"""

import shutil
import tempfile
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from code_analyzer.clone_synchroniser import CloneSynchroniser, SynchroniseError, SynchroniseResult


class AzureFetchError(Exception):
    """Azure DevOps 擷取錯誤"""
    pass


class AzureDevOpsFetcher:
    """
    從 Azure DevOps Repos 取得程式碼

    所需設定（建議寫在 .env）：
        AZURE_DEVOPS_ORG       - 組織名稱，例如 mycompany
        AZURE_DEVOPS_PROJECT   - 專案名稱，例如 MyProject
        AZURE_DEVOPS_REPO      - 儲存庫名稱，例如 MyRepo
        AZURE_DEVOPS_PAT       - Personal Access Token（需要 Code: Read 權限）
        AZURE_DEVOPS_BRANCH    - 分支，預設 main
        AZURE_DEVOPS_CLONE_DIR - 指定 clone 目標目錄（留空使用暫存目錄）
    """

    def __init__(self, org: str, project: str, repo: str, pat: str,
                 branch: str = 'main', clone_dir: str = '',
                 synchroniser: Optional[CloneSynchroniser] = None):
        if not all([org, project, repo, pat]):
            raise AzureFetchError(
                "缺少必要設定：AZURE_DEVOPS_ORG、AZURE_DEVOPS_PROJECT、"
                "AZURE_DEVOPS_REPO、AZURE_DEVOPS_PAT 均不可為空"
            )
        self.org = org
        self.project = project
        self.repo = repo
        self.pat = pat
        self.branch = branch
        self.clone_dir = clone_dir
        self._temp_dir = None   # 若使用暫存目錄，記錄以便清理
        self._synchroniser = synchroniser or CloneSynchroniser()

    # ------------------------------------------------------------------
    # 公開方法
    # ------------------------------------------------------------------

    def fetch(self, update: bool = True) -> Path:
        """
        Clone 或同步程式碼，回傳本機路徑。

        - 若 clone_dir 已存在且含 .git：
            update=True  → 交由同步器執行 fetch、reset --hard、clean。
            update=False → 直接沿用現有 clone（不連線、不更新）。
        - 若 clone_dir 為空或尚未 clone 過，一律交由同步器建立 clone。
        - 若同步器回傳忙碌（目錄的鎖被另一次 refresh 握著），拋出
          AzureFetchError 告知忙碌，不宣稱同步已完成、也不回傳 target——
          呼叫端據此知道要重試，而不是把一個沒發生的更新當成已經發生。
        - 回傳 clone 根目錄的 Path 物件。
        """
        target = self._resolve_target()
        already_cloned = self._synchroniser.is_cloned(target)

        if already_cloned and not update:
            print(f"📂 已存在 clone，沿用（未更新）：{target}")
            return target

        if already_cloned:
            print(f"🔄 目錄已存在，執行同步：{target}")
        else:
            print(f"⬇️  開始 clone：{self._safe_url()}")
            print(f"   分支：{self.branch}")
            print(f"   目標：{target}")

        try:
            result = self._synchroniser.synchronise(target, self._build_clone_url(), self.branch)
        except SynchroniseError as exc:
            raise AzureFetchError(_mask_pat(str(exc))) from exc

        if result is SynchroniseResult.BUSY:
            raise AzureFetchError(
                f"⏳ 同步忙碌中：另一個 refresh 正在使用這個目錄，請稍後再試：{target}"
            )

        print(f"✅ 同步完成：{target}")
        return target

    def cleanup(self):
        """刪除暫存目錄（僅當使用自動暫存目錄時有效）"""
        if self._temp_dir and Path(self._temp_dir).exists():
            shutil.rmtree(self._temp_dir, ignore_errors=True)
            print(f"🗑️  已清除暫存目錄：{self._temp_dir}")
            self._temp_dir = None

    # ------------------------------------------------------------------
    # 內部方法
    # ------------------------------------------------------------------

    def _resolve_target(self) -> Path:
        """決定 clone 目標目錄"""
        if self.clone_dir:
            target = Path(self.clone_dir)
            target.mkdir(parents=True, exist_ok=True)
            return target
        else:
            self._temp_dir = tempfile.mkdtemp(prefix=f"ias_{self.repo}_")
            return Path(self._temp_dir)

    def _build_clone_url(self) -> str:
        """建立含 PAT 的 HTTPS clone URL（PAT 作為密碼）"""
        encoded_pat = quote(self.pat, safe='')
        project_encoded = quote(self.project, safe='')
        repo_encoded = quote(self.repo, safe='')
        return (
            f"https://:{encoded_pat}@dev.azure.com"
            f"/{self.org}/{project_encoded}/_git/{repo_encoded}"
        )

    def _safe_url(self) -> str:
        """顯示用 URL（隱藏 PAT）"""
        project_encoded = quote(self.project, safe='')
        repo_encoded = quote(self.repo, safe='')
        return (
            f"https://***@dev.azure.com"
            f"/{self.org}/{project_encoded}/_git/{repo_encoded}"
        )


def _mask_pat(text: str) -> str:
    """將 URL 中的 PAT 替換為 *** 以避免洩漏"""
    import re
    return re.sub(r'https?://[^@\s]*@', 'https://***@', text)


# ------------------------------------------------------------------
# 便利函式
# ------------------------------------------------------------------

def fetch_from_settings() -> Path:
    """
    從 config.settings 讀取 Azure DevOps 設定並 clone 程式碼。
    回傳 clone 根目錄的 Path 物件。
    """
    from config.settings import settings

    fetcher = AzureDevOpsFetcher(
        org=settings.AZURE_DEVOPS_ORG,
        project=settings.AZURE_DEVOPS_PROJECT,
        repo=settings.AZURE_DEVOPS_REPO,
        pat=settings.AZURE_DEVOPS_PAT,
        branch=settings.AZURE_DEVOPS_BRANCH,
        clone_dir=settings.AZURE_DEVOPS_CLONE_DIR,
    )
    return fetcher.fetch()
