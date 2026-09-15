# 06 — Two Systems sharing one clone cannot reset it at once

**What to build:** An operator refreshes two Systems that share one repository, and neither sees a half-updated working tree. The catalog points both `Y-Docs_TTPUR` and `Y-DOCs_TTRDQ` at the same repository, and each scans different subdirectories, so one reset can land underneath the other's read.

The second refresh stops rather than waits. Both callers would fetch the same content, and a caller that waits cannot tell how long it will wait.

**Blocked by:** 02

**Status:** done

- [x] A lock is keyed on the clone directory, not on a System.
- [x] The lock file sits beside the clone directory, not inside it.
- [x] The cleaning step cannot delete a lock that a running refresh holds.
- [x] A refresh that finds the lock held returns a busy result immediately, and changes nothing.
- [x] A refresh never queues behind a held lock.
- [x] A lock older than thirty minutes counts as abandoned.
- [x] The next refresh takes over an abandoned lock.
- [x] A refresh releases its lock when it fails, as well as when it succeeds.

## Note

`CloneSynchroniser.synchronise()`（[code_analyzer/clone_synchroniser.py](code_analyzer/clone_synchroniser.py)）現在回傳一個
`SynchroniseResult`（`SYNCHRONISED` 或 `BUSY`），而不是回傳 `None`。

實作方式：
- 鎖檔案路徑是 `target.parent / f"{target.name}.lock"`——target 的兄弟檔案，鍵在目錄本身，不含
  System 資訊，也因此不受 `clean -fd`（只清 target 內部）影響。
- 用 `os.O_CREAT | os.O_EXCL` 原子建立鎖檔案；建立失敗代表鎖被握著。鎖齡（檔案 mtime）超過
  `ABANDONED_LOCK_SECONDS`（30 分鐘）就視為棄置並接手，否則立刻回傳 `BUSY`，不等待、不重試。
- 鎖檔案內容是一個隨機 token（`uuid.uuid4().hex`），不是先前草稿版本寫的 pid/時間戳。這不是
  裝飾——`_release_lock()` 釋放前會比對鎖檔案目前的內容跟自己拿到的 token 是否一致，一致才刪除。
  這是為了處理「這次 refresh 跑得比 30 分鐘還久，鎖已經被下一次 refresh 當成棄置接手」的情況：
  舊的一方在 `finally` 釋放鎖時，若不比對就直接刪，刪掉的會是接手者正在用的鎖，讓第三次 refresh
  又能同時跑起來，違背鎖原本要擋的事。
- 鎖檔案建立後若寫入或關閉失敗，會先把剛建立的檔案刪掉再往外拋例外，不留下一個要等 30 分鐘
  逾時才會被清掉的孤兒鎖檔案。
- 鎖的釋放包在 `try/finally` 裡，`synchronise()` 內部不論成功或拋出 `SynchroniseError` 都會釋放
  （釋放的前提是上面說的 token 比對）。

呼叫端 `AzureDevOpsFetcher.fetch()`（[code_analyzer/azure_fetcher.py](code_analyzer/azure_fetcher.py)）目前仍未讀取這個回傳值——
它是本票（ticket 06）刻意畫的邊界：這張票只保證 `CloneSynchroniser` 這一層的鎖語意正確，
沒有要求把「busy」往上傳到 `AzureDevOpsFetcher`、`/refresh` API 或 `refresh_cli`。若之後需要
讓使用者在 API 層看到「忙碌中，請稍後再試」，需要開一張新票決定要接到哪一層、用什麼形狀
回報。

跑過兩軸 code review（`/code-review`）：Standards 軸沒有硬性違規，Spec 軸抓到兩個真的問題並已修正——
（1）鎖檔案寫入失敗會留下孤兒鎖，（2）釋放鎖沒有比對持有人就直接刪，會誤刪接手者的鎖；也指出
「clean -fd 刪不到鎖」原本只有結構保證、沒有直接測試，已補上直接呼叫 `_clean()` 的測試。

測試在 [tests/test_clone_synchroniser.py](tests/test_clone_synchroniser.py) 的「Ticket 06」區塊，共 10 個，涵蓋：
成功後鎖被釋放、鎖檔案位置、`clean -fd` 直接證明碰不到鎖、忙碌時不改動任何狀態、逾時鎖被接手、
未逾時的鎖不被接手、寫入失敗不留孤兒鎖、釋放不誤刪接手者的鎖、失敗路徑也釋放鎖、首次 clone
也釋放鎖。全部通過；同時跑過 `test_azure_fetcher.py` 與全專案測試，確認沒有引入新的失敗（既有
的 12 個失敗與 2 個因缺 SQL Server ODBC 驅動而收集失敗的測試，在改動前就已存在，與本票無關）。
