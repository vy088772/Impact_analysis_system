# 05 — `refresh_sql_cli` Targets a Database Directly, Independent of System

**Repo:** `llamaindex-spec-rag`
**Spec:** `Impact_analysis_system/.scratch/database-identity-decoupled-from-system/spec.md`
**ADR:** `Impact_analysis_system/docs/adr/0010-scan-identity-independent-of-app-credentials.md`

**What to build:** A Database with no owning System (like `SysErrorRecord`) can be scanned without inventing a fake System for it. `refresh_sql_cli` accepts `(server, database)` directly, in addition to its existing `system_id` argument (which now resolves to every Database that System declares, via ticket 04's `SQLServerData.json`, and scans each). Scan-tool credentials stay independent of each application's own Web.config credentials, with an optional per-`(server, database)` override read from `SQLServerData.json`'s `uid`/`pwd` fields (blank → global identity).

**Blocked by:** 02 (cache-key format must match what `Impact_analysis_system` now writes/reads), 04 (`system_id` convenience mode needs `SQLServerData.json` to resolve a System's declared databases)

**Status:** done

- [x] `refresh_sql_cli` accepts a direct `(server, database)` target and triggers a scan against exactly that pair — no `system_id` or `system_catalog.json` entry required.
- [x] `refresh_sql_cli` still accepts a bare `system_id`; in that mode it resolves the System's `databases` list from `system_catalog.json`/`SQLServerData.json` and runs the same per-database scan for each entry in turn.
- [x] The cache-key string this command sends as `RefreshSqlRequest.database` is computed by the *same normalization rule* ticket 02 implements in `Impact_analysis_system` (domain-suffix append, instance-suffix strip) — verified with a shared example (`vmsystest07` → `vmsystest07.topmost.com.tw`) so the two repos' independently-computed keys actually match on disk.
- [x] Scanning reads the target database's `SQLServerData.json` entry for `uid`/`pwd` and connects with them only when both are non-blank; when either is blank it falls back to the existing global `DB_AUTH_MODE` identity.
- [x] Credentials are never read from or derived from any scanned application's Web.config.
- [ ] `SysErrorRecord` can be scanned end-to-end via `refresh_sql_cli` targeting `(vmsystest07.topmost.com.tw, SysErrorRecord)` directly. —— 指令路徑已驗到送出請求為止；實機連線待有 ODBC 驅動程式且連得到 vmsystest07 的機器上跑，見 Comments。
- [x] New `tests/test_refresh_sql_cli.py` covers: the direct `(server, database)` path, the `system_id`-resolves-to-multiple-databases path, and the credential-override-vs-fallback-to-global behavior — following `tests/test_refresh_cli.py`'s existing `monkeypatch`-based CLI-test pattern.

## Comments

2026-08-18 實作完成（除了「實機掃一次 SysErrorRecord」那一項，見下）。

**帳密放哪裡**：訪談時的回覆是「放 SQLServerData.json，以 server 分組，一組帳密，
底下掛多個 database」。實作照這個做，登錄檔改成
`{"servers": [{"server", "uid", "pwd", "databases": [...]}]}`；票 04 與 spec 原本寫的
「每筆 `{name, server, uid, pwd}`」已一併改成伺服器分組的寫法（ADR-0001／ADR-0010 同步）。
一台伺服器只需要寫一次位址與一組掃描身分。

**帳密怎麼送到連線那一端**：實際開連線的是 Impact，所以 `/refresh_sql` 請求多兩個
選填欄位 `db_user_id`／`db_password`（`RefreshSqlRequest`），一路傳到
`settings.build_database_config()`；兩者都有值才把 `auth_mode` 切成 `sql` 並用那組
帳密，缺一即沿用全域 `DB_AUTH_MODE`。Web.config 的 uid/pwd 只用來辨識「這通呼叫連的是
哪個資料庫」，永遠不拿來建掃描連線。`docs/openapi/openapi.json` 已重新匯出。

**送出的快取鍵**：`impact_orch/sql_cache_identity.py` 是票 02 那條正規化規則在呼叫端的
第二份實作（兩個 repo 是不同程序，不互相 import）。
`tests/test_sql_cache_identity.py` 直接拿 Impact 已落地的快取檔名對答案
（`vmsystest07` → `vmsystest07.topmost.com.tw__STC__dbo.json`），任一端改規則而另一端沒跟上就會紅。

**唯一沒打勾的那一項**（`SysErrorRecord` 實機掃一次）：本機沒有 ODBC Driver 17
（`tests/test_search_roles.py`／`test_sp_tables.py` 也因此無法 collect），連不到
vmsystest07。指令本身已驗到最後一步——
`python -m impact_orch.refresh_sql_cli --server vmsystest07.topmost.com.tw --database SysErrorRecord`
會解析出目標、送出請求，Impact 收下後在實際連線那一步失敗。要收尾請在裝有驅動程式且
連得到該台的機器上重啟 Impact 服務（新欄位需要重載）後重跑同一行，並確認掃描身分對
`SysErrorRecord` 有讀取權限（ADR-0010 的 Consequences）。

測試：spec-rag 全套 108 passed / 1 failed，該筆
（`test_path_evidence_wiring.py::test_refresh_client_uses_catalog_contract_without_discovery_request`）
在改動前後皆失敗，原因是本機 catalog 的 `Y-Docs_TTPUR.wrapper_contract` 是空字串。
Impact 全套 495 passed / 11 failed，同樣 11 筆在 HEAD 上就是紅的（external wrapper
contracts / MVC scan / formal output migration），與本票無關。
