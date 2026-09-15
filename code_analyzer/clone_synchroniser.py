# code_analyzer/clone_synchroniser.py
"""通用的 git clone 同步機制。

只認得 git 操作本身（clone、fetch、reset、clean），不認得 Azure DevOps、
PAT、System 或 catalog。呼叫端保證：呼叫 synchronise() 之後，target 目錄
的內容等於 remote_url 上 branch 分支的內容。

同步序列固定：fetch、reset --hard 到遠端追蹤分支、clean 掉未追蹤的檔案與
目錄。這個序列每次都跑，從不先檢查工作目錄是否乾淨——一條路徑處理乾淨與
髒污兩種狀況，行為才容易預測。

每次成功的 synchronise() 都在 target 目錄裡寫下 `meta.json`：宣告
（settings、catalog）講的是意圖，這個檔案講的是事實——clone 目前實際停在
哪個分支、哪個 commit、上一次成功 refresh 是何時。見 ADR-0023。
"""

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class SynchroniseError(Exception):
    """同步 clone 失敗。訊息可能含有 remote_url 中的機密資訊，呼叫端需自行過濾。"""
    pass


class CloneSynchroniser:
    """讓一個目標目錄的內容等於某個遠端分支的內容。"""

    META_FILENAME = 'meta.json'

    def synchronise(self, target: Path, remote_url: str, branch: str) -> None:
        """同步 target 目錄至 remote_url 的 branch 分支。

        target 尚未 clone 過時執行 clone；已存在時執行
        fetch、reset --hard、clean 這個固定序列。

        成功後一律在 target 寫下 meta.json，記錄 branch、目前的 commit、
        與這次成功 refresh 的時間。若 target 已 clone 過但 meta.json 遺失
        （例如上一次 refresh 中途失敗，或這是一個尚未被本機制接手的舊
        clone），先問 git 這個 clone 目前停在哪個分支，重建一份時間欄位為
        unknown 的 meta.json——這個重建本身不觸發重新 clone，也不代表
        refresh 已經完成；接下來仍照常跑 fetch/reset/clean，成功後再用
        本次已知的 branch、新 commit、目前時間覆寫過去。
        """
        target = Path(target)

        if self.is_cloned(target):
            if not self._meta_path(target).exists():
                self._rebuild_meta(target)
            self._fetch(target, remote_url)
            self._reset_hard(target, branch)
            self._clean(target)
        else:
            target.mkdir(parents=True, exist_ok=True)
            self._clone(target, remote_url, branch)

        self._write_meta(target, branch=branch, commit=self._current_commit(target),
                          refreshed_at=_now_iso())

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
    ) -> str:
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
        return self._run(cmd)

    @staticmethod
    def _run(cmd: list) -> str:
        """執行外部 git 指令，回傳 stdout；失敗時拋出 SynchroniseError（訊息未過濾機密資訊）。"""
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

        return result.stdout

    # ------------------------------------------------------------------
    # meta.json
    # ------------------------------------------------------------------

    def _meta_path(self, target: Path) -> Path:
        return Path(target) / self.META_FILENAME

    def _rebuild_meta(self, target: Path) -> None:
        """meta.json 遺失時的自救：問 git 這個 clone 目前停在哪個分支與
        commit，寫回一份時間欄位為 unknown 的 meta.json。這份紀錄只反映
        呼叫當下、尚未被這次 refresh 觸碰過的狀態；若接下來的 fetch/reset
        失敗，目錄裡至少留下這份誠實的紀錄，而不是完全沒有 meta.json。"""
        branch = self._current_branch(target)
        commit = self._current_commit(target)
        self._write_meta(target, branch=branch, commit=commit, refreshed_at=None)

    def _current_branch(self, target: Path) -> str:
        """問 git 這個 clone 目前檢出的分支名稱。"""
        return self._git(target, ['rev-parse', '--abbrev-ref', 'HEAD']).strip()

    def _current_commit(self, target: Path) -> str:
        """問 git 這個 clone 目前的 commit hash。"""
        return self._git(target, ['rev-parse', 'HEAD']).strip()

    def _write_meta(self, target: Path, branch: str, commit: str,
                     refreshed_at: Optional[str]) -> None:
        """寫下 meta.json。refreshed_at 為 None 時序列化成 JSON 的 null——
        這是「時間未知」的明確值，跟欄位整個不存在是兩回事，也跟一個真正
        的時間字串不會混在一起。"""
        meta = {'branch': branch, 'commit': commit, 'refreshed_at': refreshed_at}
        self._meta_path(target).write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + '\n', encoding='utf-8'
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
