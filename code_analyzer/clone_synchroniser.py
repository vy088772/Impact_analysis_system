# code_analyzer/clone_synchroniser.py
"""通用的 git clone 同步機制。

只認得 git 操作本身（clone、fetch、reset、clean），不認得 Azure DevOps、
PAT、System 或 catalog。呼叫端保證：呼叫 synchronise() 之後，target 目錄
的內容等於 remote_url 上 branch 分支的內容。

同步序列固定：fetch、reset --hard 到遠端追蹤分支、clean 掉未追蹤的檔案與
目錄。這個序列每次都跑，從不先檢查工作目錄是否乾淨——一條路徑處理乾淨與
髒污兩種狀況，行為才容易預測。
"""

import subprocess
from pathlib import Path


class SynchroniseError(Exception):
    """同步 clone 失敗。訊息可能含有 remote_url 中的機密資訊，呼叫端需自行過濾。"""
    pass


class CloneSynchroniser:
    """讓一個目標目錄的內容等於某個遠端分支的內容。"""

    def synchronise(self, target: Path, remote_url: str, branch: str) -> None:
        """同步 target 目錄至 remote_url 的 branch 分支。

        target 尚未 clone 過時執行 clone；已存在時執行
        fetch、reset --hard、clean 這個固定序列。
        """
        target = Path(target)

        if self.is_cloned(target):
            self._fetch(target, remote_url)
            self._reset_hard(target, branch)
            self._clean(target)
        else:
            target.mkdir(parents=True, exist_ok=True)
            self._clone(target, remote_url, branch)

    @staticmethod
    def is_cloned(target: Path) -> bool:
        """判斷 target 目錄是否已 clone 過（是否含 .git）。"""
        return (Path(target) / '.git').exists()

    # ------------------------------------------------------------------
    # 內部方法
    # ------------------------------------------------------------------

    def _clone(self, target: Path, remote_url: str, branch: str) -> None:
        self._git(None, [
            'clone',
            '--branch', branch,
            '--single-branch',
            '--depth', '1',
            remote_url,
            str(target),
        ], with_no_credential_helper=True, pin_line_endings=True)

    def _fetch(self, target: Path, remote_url: str) -> None:
        # 既有 clone 的 origin URL 可能沒有內嵌憑證（或內嵌的憑證已過期），
        # 先用目前的 remote_url 重新寫入，才不必依賴本機 Git Credential Manager。
        self._git(target, ['remote', 'set-url', 'origin', remote_url])
        self._git(
            target,
            ['fetch', 'origin', '--depth', '1'],
            with_no_credential_helper=True,
            pin_line_endings=True,
        )

    def _reset_hard(self, target: Path, branch: str) -> None:
        self._git(target, ['reset', '--hard', f'origin/{branch}'], pin_line_endings=True)

    def _clean(self, target: Path) -> None:
        self._git(target, ['clean', '-fd'])

    def _git(
        self,
        target,
        args: list,
        with_no_credential_helper: bool = False,
        pin_line_endings: bool = False,
    ) -> None:
        cmd = ['git']
        if with_no_credential_helper:
            cmd += ['-c', 'credential.helper=']
        if pin_line_endings:
            # 每個會寫入工作目錄的指令都在指令本身關閉換行轉換，理由與上面的
            # credential.helper 相同：refresh 的行為不可依賴執行機器本身的
            # git 設定。用 -c 傳入、不寫進 clone 自己的 git config。
            cmd += ['-c', 'core.autocrlf=false']
        if target is not None:
            cmd += ['-C', str(target)]
        cmd += args
        self._run(cmd)

    @staticmethod
    def _run(cmd: list) -> None:
        """執行外部 git 指令，失敗時拋出 SynchroniseError（訊息未過濾機密資訊）。"""
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
            )
        except FileNotFoundError:
            raise SynchroniseError("找不到 git 指令，請確認 Git 已安裝並加入 PATH")
        except subprocess.TimeoutExpired:
            raise SynchroniseError("git 操作逾時（超過 300 秒）")

        if result.returncode != 0:
            stderr = result.stderr or ''
            raise SynchroniseError(f"git 操作失敗（exit {result.returncode}）\n{stderr}")
