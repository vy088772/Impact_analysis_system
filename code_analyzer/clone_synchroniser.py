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
哪個分支、哪個 commit、上一次成功 refresh 是何時。宣告的 branch 才有決定
權：當它跟 meta.json 記錄的 branch 不同，代表這個 clone 停在錯的分支上，
synchronise() 整個刪掉 target 重新 clone，不嘗試用 fetch 硬湊。見
ADR-0023。

一把鎖守著每個 target 目錄：鎖認的是目錄本身，不是哪個 System——一個
repository 可以被兩個 System 同時指到同一個 target，鎖必須擋住兩邊同時
refresh 同一個目錄，而不是分別記在各自的 System 上。鎖檔案放在 target
「旁邊」（target 的兄弟檔案），不是 target 裡面：clean -fd 只清 target
內部，鎖放外面才不會被自己保護的那次 refresh 清掉。找到鎖已被握住時，
synchronise() 立刻回傳 SynchroniseResult.BUSY，不做任何改動，也不等待、
不重試——兩邊要抓的內容相同，等待也不會等出更好的結果，只會不知道要等
多久。超過 ABANDONED_LOCK_SECONDS（30 分鐘）沒被釋放的鎖視為被棄置（多半
是前一次 refresh 的行程當掉），下一次 refresh 直接接手。鎖在失敗與成功
兩種結尾都會釋放，且只釋放自己拿到的那一份——見 _release_lock，這是為了
「這次 refresh 跑得比逾時還久、鎖已經被下一次接手」的情況：舊的一方
不能把接手者正在用的鎖也一併刪掉。見 ADR-0023。
"""

import json
import os
import shutil
import subprocess
import time
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional


class SynchroniseError(Exception):
    """同步 clone 失敗。訊息可能含有 remote_url 中的機密資訊，呼叫端需自行過濾。"""
    pass


class SynchroniseResult(Enum):
    """synchronise() 的結果。BUSY 不是錯誤——目錄的鎖被另一次 refresh 握著，
    這次呼叫沒有做任何事，呼叫端可以直接再問一次，不必當成例外處理。"""
    SYNCHRONISED = 'synchronised'
    BUSY = 'busy'


class CloneSynchroniser:
    """讓一個目標目錄的內容等於某個遠端分支的內容。"""

    META_FILENAME = 'meta.json'
    LOCK_SUFFIX = '.lock'
    ABANDONED_LOCK_SECONDS = 30 * 60

    def synchronise(self, target: Path, remote_url: str, branch: str) -> SynchroniseResult:
        """同步 target 目錄至 remote_url 的 branch 分支。

        呼叫一開始先抓 target 目錄的鎖。抓不到（鎖被另一次 refresh 握著，
        且未逾時）就立刻回傳 SynchroniseResult.BUSY，之後的步驟一概不做，
        target 目錄維持原狀；抓到之後才進入下面描述的同步序列，最後不論
        成功或拋出例外都會釋放鎖（見 _acquire_lock/_release_lock）。

        branch 是宣告的分支（settings、catalog 講的意圖）。target 尚未
        clone 過時執行 clone；已存在時，先比對這個宣告的 branch 跟
        meta.json 記錄的 branch：兩者相同才執行 fetch、reset --hard、
        clean 這個固定序列；兩者不同就整個刪掉 target 目錄，改當成
        「尚未 clone 過」重新 clone 宣告的 branch——因為 clone 是 shallow
        加 single-branch，fetch 設定只認得 clone 當初指定的那個分支，換
        分支不是 fetch 能做到的事，見 ADR-0023。

        成功後一律在 target 寫下 meta.json，記錄 branch、目前的 commit、
        與這次成功 refresh 的時間。若 target 已 clone 過但 meta.json 遺失
        （例如上一次 refresh 中途失敗，或這是一個尚未被本機制接手的舊
        clone），先問 git 這個 clone 目前停在哪個分支，重建一份時間欄位為
        unknown 的 meta.json——這個重建本身不觸發重新 clone，也不代表
        refresh 已經完成；重建出來的 branch 接下來仍會拿去跟宣告的 branch
        比對，遺失 meta.json 本身不等於分支不符。比對通過後仍照常跑
        fetch/reset/clean，成功後再用本次已知的 branch、新 commit、目前
        時間覆寫過去。
        """
        target = Path(target)
        lock_path = self._lock_path(target)

        token = self._acquire_lock(lock_path)
        if token is None:
            return SynchroniseResult.BUSY

        try:
            if self.is_cloned(target):
                if not self._meta_path(target).exists():
                    self._rebuild_meta(target)
                if self._recorded_branch(target) != branch:
                    shutil.rmtree(target)
                    self._clone_fresh(target, remote_url, branch)
                else:
                    self._fetch(target, remote_url)
                    self._reset_hard(target, branch)
                    self._clean(target)
            else:
                self._clone_fresh(target, remote_url, branch)

            self._write_meta(target, branch=branch, commit=self._current_commit(target),
                              refreshed_at=_now_iso())
        finally:
            self._release_lock(lock_path, token)

        return SynchroniseResult.SYNCHRONISED

    @staticmethod
    def is_cloned(target: Path) -> bool:
        """判斷 target 目錄是否已 clone 過（是否含 .git）。"""
        return (Path(target) / '.git').exists()

    # ------------------------------------------------------------------
    # 內部方法
    # ------------------------------------------------------------------

    def _clone_fresh(self, target: Path, remote_url: str, branch: str) -> None:
        """在一個保證不含既有內容的 target 上建立全新 clone。呼叫端須自行
        保證 target 尚未存在或已清空——沒有 clone 過的第一次同步，以及
        branch 不符、target 已被整個刪掉之後的重新 clone，都走這條路。"""
        target.mkdir(parents=True, exist_ok=True)
        self._clone(target, remote_url, branch)

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
    # 目錄鎖
    # ------------------------------------------------------------------

    def _lock_path(self, target: Path) -> Path:
        """鎖檔案的路徑：target 的兄弟檔案，檔名是 target 目錄名加上
        LOCK_SUFFIX。放在 target 外面，clean -fd（只清 target 內部）就
        絕對碰不到它。"""
        target = Path(target)
        return target.parent / f'{target.name}{self.LOCK_SUFFIX}'

    def _acquire_lock(self, lock_path: Path) -> Optional[str]:
        """嘗試抓 target 目錄的鎖，抓到就回傳這次持有的 token，抓不到回傳
        None。

        鎖檔案用 O_CREAT|O_EXCL 建立，這個系統呼叫本身是原子的，兩個
        行程同時搶同一個鎖檔案時只有一個會成功。第一次搶輸了，代表鎖被
        握著（可能是另一次還在跑的 refresh，也可能是逾時被棄置），此時
        看鎖檔案的年紀：超過 ABANDONED_LOCK_SECONDS 就刪掉重搶一次，接手
        這把被棄置的鎖；沒超過就回傳 None，讓呼叫端當成 BUSY，不等待、
        不重試。

        每次成功建立都寫入一個新產生的 token 當內容，讓 _release_lock 只
        釋放「確實還是自己的」那一份——見它的說明。"""
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        token = uuid.uuid4().hex

        if self._create_lock_file(lock_path, token):
            return token

        if not self._lock_is_abandoned(lock_path):
            return None

        lock_path.unlink(missing_ok=True)
        return token if self._create_lock_file(lock_path, token) else None

    @staticmethod
    def _create_lock_file(lock_path: Path, token: str) -> bool:
        """用 O_EXCL 原子建立鎖檔案，內容寫入 token；已存在就回傳 False，
        不覆寫、不拋例外。建立之後任何失敗（寫入或關閉檔案）都先把這個
        檔案刪掉再往外拋例外——鎖不會在半途留下一個沒有人管、要等 30
        分鐘逾時才會被清掉的孤兒檔案。"""
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False
        try:
            try:
                os.write(fd, token.encode('utf-8'))
            finally:
                os.close(fd)
        except OSError:
            lock_path.unlink(missing_ok=True)
            raise
        return True

    def _lock_is_abandoned(self, lock_path: Path) -> bool:
        """鎖檔案的最後修改時間距今是否已超過 ABANDONED_LOCK_SECONDS。
        檔案在檢查的當下剛好消失（另一次 refresh 剛釋放），視為可以重搶，
        不當成「仍被握著」。"""
        try:
            age_seconds = time.time() - lock_path.stat().st_mtime
        except FileNotFoundError:
            return True
        return age_seconds > self.ABANDONED_LOCK_SECONDS

    @staticmethod
    def _release_lock(lock_path: Path, token: str) -> None:
        """釋放鎖，但只釋放「確實還是自己的」那一份：讀出鎖檔案目前的
        內容，跟自己當初拿到的 token 一致才刪除。

        一次 refresh 若跑得比 ABANDONED_LOCK_SECONDS 還久，它的鎖可能已
        經被下一次 refresh 當成棄置接手，鎖檔案裡的內容這時是對方的新
        token；呼叫端在 finally 走到這裡若不比對就直接刪，刪掉的會是
        接手者正在用的鎖，讓兩次 refresh 又同時跑起來，違背鎖原本要擋
        的事。讀不到檔案（已經被刪過）視為沒有自己的鎖可釋放。"""
        try:
            current_token = lock_path.read_text(encoding='utf-8')
        except FileNotFoundError:
            return
        if current_token == token:
            lock_path.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # meta.json
    # ------------------------------------------------------------------

    def _meta_path(self, target: Path) -> Path:
        return Path(target) / self.META_FILENAME

    def _recorded_branch(self, target: Path) -> Optional[str]:
        """讀出 meta.json 目前記錄的 branch。呼叫前必須先確保 meta.json
        存在（缺少時 synchronise() 已經呼叫過 _rebuild_meta()）。"""
        meta = json.loads(self._meta_path(target).read_text(encoding='utf-8'))
        return meta.get('branch')

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
