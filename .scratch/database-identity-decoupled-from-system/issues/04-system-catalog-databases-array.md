# 04 — System-to-Database Catalog Becomes Many-to-Many

**Repo:** `llamaindex-spec-rag`
**Spec:** `Impact_analysis_system/.scratch/database-identity-decoupled-from-system/spec.md`
**ADR:** `docs/adr/0001-system-to-database-is-many-to-many.md`

**What to build:** A System can declare dependence on more than one Database, and a Database with no owning System (like `SysErrorRecord`) becomes representable. `system_catalog.json`'s singular `database: {name, server}` object is replaced with a `databases: [...]` list of database names; a new `SQLServerData.json` becomes the sole registry of Databases, grouped by server (`{server, uid, pwd, databases}`), independent of any System.

**Blocked by:** None — can start immediately

**Status:** done

- [x] `system_catalog.json`'s per-system `database` field is replaced with `databases: [...]` (a list of database-name strings). `STC`'s entry becomes `databases: ["STC", "SysErrorRecord"]`.
- [x] A new `SQLServerData.json` lists every known Database under its server as a `{server, uid, pwd, databases}` record, at minimum `STC`, `PUR`, and `SysErrorRecord` (all on `vmsystest07.topmost.com.tw`, matching what ticket 01's resolution and the real Web.config content confirm).
- [x] `catalog_builder.py`'s existing manually-curated-field preservation (today covering the singular `database` field) is extended to preserve `databases` across a forced rebuild the same way — a rebuild never drops a System's declared database dependencies, and never invents one for a System that has none.
- [x] Every `SQLServerData.json` server entry carries `uid` and `pwd` alongside its `databases` list, blank by default — a blank pair means "scan with the global `DB_AUTH_MODE` identity" (ADR-0010). Ticket 05 is what reads them; this ticket only pins the shape.
- [x] `tests/test_catalog_builder_database.py`'s two existing cases (forced rebuild preserves the field; absent field stays absent) are extended to cover `databases` instead of `database`.

## Comments

`catalog_builder.py` 不需要改程式：合併邏輯的人工欄位保留是泛用的（`_AI_MANAGED_FIELDS`
以外的欄位一律沿用舊記錄），`databases` 因此自動被保留，也不會為沒宣告的系統憑空生出來。
測試改為鎖定 `databases`，把這個行為釘住。

Ticket 07（已 done）的 `_sql_cache_database()` 走 `resolve_db_source()` 讀舊的
`database.name`，換欄位會直接打斷 `Y-Docs_TTPUR` → `PUR` 的路由，所以本票一併把
`source_resolver` 遷到新格式：新增 `resolve_databases()` 與 `resolve_db_server()`，
`resolve_db_source()` 改由「`databases` 第一筆 + `SQLServerData.json` 查 server」組出。
對外回傳契約 `{server, name}` 不變，ticket 07 的測試（patch `resolve_db_source`）全數不受影響。

宣告多個依賴時取清單第一筆：spec 明確把 primary/owned 標記列為 out of scope，所以用宣告
順序代替。`STC` 的 `["STC", "SysErrorRecord"]` 第一筆仍是 `STC`，所有系統的既有路由行為不變。

`catalog/*.json` 被 `.gitignore` 的 `*.json` 排除，`SQLServerData.json` 與
`system_catalog.json` 一樣是本機資料檔、不進版控。讀這兩個檔的測試在檔案不存在時 skip。

已知的既有失敗（與本票無關）：`tests/test_path_evidence_wiring.py::test_refresh_client_uses_catalog_contract_without_discovery_request`
期待 `Y-Docs_TTPUR` 的 `wrapper_contract` 是 `sqlobject`，本機 catalog 標的是空字串。
改動前後皆失敗。

2026-08-18 修正：本票原本寫「`SQLServerData.json` 不放帳密，只有 `name` 與 `server`」，
與訪談時 Q9 的定案相反。當時的定案是 B：每組 `(server, database)` 登記自己的帳密，
兩者皆空白才退回全域身份（`config/settings.py` 的 `DB_AUTH_MODE`）。改用環境變數存放
是寫 spec 時擅自轉的彎，沒有問過人。

因此補上：`SQLServerData.json` 每筆多帶 `uid`/`pwd` 兩個欄位（預設空字串），
`tests/test_source_resolver_databases.py` 的 `test_the_shipped_registry_holds_no_credentials`
（原本把錯的決定釘死成綠燈）改成 `..._carries_optional_scan_credentials` 與
`..._leaves_scan_credentials_blank`。真正「讀帳密去連線」的行為屬於 ticket 05，本票只釘檔案形狀。
