# 05 — 建立 Structured Writer/Reader Completeness Inventory 與 Bounded Evidence Recovery

**What to build:** 針對「列舉全部 writer/reader」類的 completeness 查詢，產生完整且去重的 `Writer Finding` 清單（含 direct/transitive writer mode、evidence status、canonical target 與 provenance），並在出現 `Evidence Gap` 時執行有限次 deterministic recovery，避免無界的 repository 探索。

**Blocked by:** 02 — 建立 Mandatory Discovery Dispatcher、Additive Merge 與 Completeness Query Routing；03 — 建立 UI-linked Handler-scoped Path Candidates 與 Canonical Object Identity

**Status:** ready-for-agent

- [ ] 針對已解析為單一 canonical object 的 table/SP，completeness 查詢會回傳所有已知 direct 與 transitive writer/reader，並以 `finding_id`（衍生自 canonical identity + program/path）去重，不因不同命名或不同來源重複列出同一實體。
- [ ] 每筆 `Writer Finding` 都保留 `writer_mode`（direct/transitive）與 `evidence_status`（proven/possible/unresolved）兩個正交分類，不會混用或以單一欄位互相取代。
- [ ] 找不到足夠 source evidence 支持某個候選 writer 時，該筆會維持 `unresolved` 並保留可查閱的 provenance 與嘗試紀錄，不會被排除在清單之外，也不會被升級為 proven。
- [ ] `Evidence Gap` 出現時，系統會執行有限次數的 deterministic recovery（例如重新解析 dynamic 呼叫、擴大 reachability 搜尋半徑），每次嘗試與其 recovery boundary 都可被觀測；超出 boundary 後停止並保留 gap 狀態，不會無限重試。
- [ ] recovery 成功時，finding 的 evidence_status 會被更新為 proven 並記錄成功的 recovery 依據；recovery 失敗不會被誤記為「已證實不存在」。
- [ ] contract tests 使用 fake source/graph fixtures 驗證去重、正交分類、recovery bounded 行為與 gap 保留，不依賴 live LLM 或外部服務。
