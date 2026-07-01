# code_analyzer/azure_fetcher.py
"""
Azure DevOps 程式碼擷取器
使用 git clone（含 PAT 驗證）將 Azure Repos 的程式碼下載至本機目錄
"""

import subprocess
import shutil
import tempfile
from pathlib import Path
from urllib.parse import quote


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
                 branch: str = 'main', clone_dir: str = ''):
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

    # ------------------------------------------------------------------
    # 公開方法
    # ------------------------------------------------------------------

    def fetch(self, update: bool = True) -> Path:
        """
        Clone 或更新程式碼，回傳本機路徑。

        - 若 clone_dir 已存在且含 .git：
            update=True  → 執行 git pull（更新）。
            update=False → 直接沿用現有 clone（不連線、不更新）。
        - 若 clone_dir 為空，建立暫存目錄後 clone。
        - 回傳 clone 根目錄的 Path 物件。
        """
        target = self._resolve_target()

        if (target / '.git').exists():
            if update:
                print(f"📂 目錄已存在，執行 git pull：{target}")
                self._git_pull(target)
            else:
                print(f"📂 已存在 clone，沿用（未更新）：{target}")
        else:
            print(f"⬇️  開始 clone：{self._safe_url()}")
            print(f"   分支：{self.branch}")
            print(f"   目標：{target}")
            self._git_clone(target)
            print(f"✅ Clone 完成：{target}")

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

    def _git_clone(self, target: Path):
        """執行 git clone"""
        cmd = [
            'git', 'clone',
            '--branch', self.branch,
            '--single-branch',
            '--depth', '1',          # shallow clone，加速下載
            self._build_clone_url(),
            str(target)
        ]
        self._run(cmd)

    def _git_pull(self, target: Path):
        """在現有目錄執行 git pull"""
        cmd = ['git', '-C', str(target), 'pull', '--ff-only']
        self._run(cmd)
        print("✅ git pull 完成")

    @staticmethod
    def _run(cmd: list):
        """執行外部命令，失敗時拋出 AzureFetchError"""
        # 隱藏命令列輸出中的 PAT（替換含 @ 的 URL 片段）
        display_cmd = [
            part if '@' not in part else part.split('@')[-1]
            for part in cmd
        ]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300
            )
        except FileNotFoundError:
            raise AzureFetchError(
                "找不到 git 指令，請確認 Git 已安裝並加入 PATH"
            )
        except subprocess.TimeoutExpired:
            raise AzureFetchError("git 操作逾時（超過 300 秒）")

        if result.returncode != 0:
            # 過濾錯誤訊息中可能洩漏的 PAT
            stderr = result.stderr or ''
            raise AzureFetchError(
                f"git 操作失敗（exit {result.returncode}）\n{_mask_pat(stderr)}"
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
