# 06 — `refresh_cli` Flags Uncataloged Databases With an Actionable Hint

**Repo:** `llamaindex-spec-rag`
**Spec:** `Impact_analysis_system/.scratch/database-identity-decoupled-from-system/spec.md`
**ADR:** `docs/adr/0002-new-database-scanning-is-explicit.md`

**What to build:** This is the original ask that started this whole effort: `refresh_cli`'s unresolved summary tells an analyst "this database is real, it just hasn't been scanned yet" instead of lumping it in with genuine static-analysis gaps — and tells them exactly what command fixes it.

**Blocked by:** 03 (the `not_in_resolved_catalog` reason must actually be reachable and correct), 05 (the suggested command must actually work as suggested)

**Status:** done

- [x] `refresh_cli`'s unresolved-results summary buckets `not_in_resolved_catalog` results separately from other unresolved reasons.
- [x] For each distinct uncataloged database, it prints "其中 N 筆為「資料庫未建檔」，refresh_sql_cli 建立 `<database>`" — deduplicated once per database regardless of how many invocations hit it (verified with a case where 3+ calls hit the same uncataloged database and only one hint line appears, with N reflecting the true call count).
- [x] Running `refresh_cli STC` today's way (before any of tickets 01/02/03/04/05 land) is unaffected for reasons other than `not_in_resolved_catalog`.
- [x] Nothing in `refresh_cli` triggers `refresh_sql_cli` or any live SQL scan automatically upon discovering an uncataloged database — the hint is informational only.
- [x] `tests/test_refresh_cli.py` gains cases for: the bucketed message text, deduplication across multiple invocations of the same database, and confirmation that no scan is triggered as a side effect of printing the hint.

## Comments

2026-08-19 實作完成，commit `063353b`（`llamaindex-spec-rag`，branch `spec_extend_20260701`）。

**這一桶讀的是哪個欄位**：`not_in_resolved_catalog` 是 gateway 掛在 `DbInvocation.reason`
上的原因碼，到 `/refresh` 回應裡是 review item 的 `evidence_reason`（不是
`unresolved_reason`／`classification_reason`，那三個 `_review_projection` 另外讀）。
新的 `_uncataloged_database_calls()` 就以 `evidence_reason` 分桶，用每筆的 `database`
當去重鍵、累加 `calls` 當 N，所以同一個資料庫被幾通呼叫打到都只印一行，N 是真實筆數。
輸出接在 `wrapper summary:` 那一行之後，「其中」指的就是同一行的 unresolved 數。

**提示只印資料庫名稱，沒有伺服器**：review item 的欄位是
`wrapper_observation_fields()`（`csharp_analysis_gateway.py`）產的那一包，裡面有
`database` 但沒有 `server`——`server` 只活在 `DbInvocation`／`connection_source`
那一層，沒有被投影到 review item 上。所以提示文字照 spec 與 ADR-0002 的原文只帶
`<database>`；分析師實際要跑的是
`refresh_sql_cli --server <server> --database <database>`，或直接給 system_id。
真的要讓提示印出完整可貼上的指令，得先讓 Impact 端把 `server` 投影進 review item，
那是另一張票的範圍，這裡沒做。

**沒有自動掃描**：`refresh_cli` 完全沒有引用 `refresh_sql_cli`，也沒有呼叫
`rag_client.refresh_sql`／`refresh_sql_database`。
`test_refresh_cli_hint_does_not_trigger_a_live_scan` 把那兩個函式換成會 raise 的樁，
再跑一次完整的 `main()`，印出提示而不炸，就是這條保證。

**測試**：`tests/test_refresh_cli.py` 新增四筆——訊息文字、去重（3 通呼叫打同一個
資料庫只印一行且 N=3，另一個資料庫自成一行）、不觸發掃描、以及
`connection_source_unresolved` 不會被誤歸到這一桶。全套 112 passed / 2 failed，
那 2 筆在這次改動之前就是紅的，與本票無關：
`test_path_evidence_wiring.py::test_refresh_client_uses_catalog_contract_without_discovery_request`
（本機 catalog 的 `Y-Docs_TTPUR.wrapper_contract` 是空字串）與
`test_source_resolver_databases.py::test_the_shipped_catalog_declares_databases_as_a_list`
（本機 `system_catalog.json` 的 STC 現在宣告 `['PUR', 'STC', 'SysErrorRecord']`，
測試期待 `['STC', 'SysErrorRecord']`）。後者是本機 catalog 資料漂移，不是程式問題，
但值得有人確認 STC 該不該依賴 `PUR`。

**留給 `/domain-modeling` 的後續**：「資料庫未建檔」在 `CONTEXT.md` 沒有對應詞條
（只有 **Database**／**Shared Database**）。ADR-0002 的原文目前是唯一的措辭來源。
