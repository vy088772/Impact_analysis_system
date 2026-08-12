# 07 — 建立 Adaptive Final Answer、Compact Inventory Table 與 Conversation Analysis State

**What to build:** 讓 final synthesis 依問題型態（單一 `Execution Path` 說明 vs. completeness 列舉）調整呈現方式，維持 answer-first 且最多約 3 個可見區塊；completeness 結果以 compact table 呈現並附上短人類可讀的 `Display Reference`（如 W1/W2）；同時保存對話回合的 inventory 投影，讓後續追問可依 `Display Reference` 或新 explicit identifier 解析範圍。

**Blocked by:** 06 — 建立 Grounded Final Context、Legacy Fallback 與 Specification vs Observed 分類

**Status:** ready-for-agent

- [ ] 一般問題（單一 path 或少量 finding）維持既有 `prompts/integrated_answer.md` 的 answer-first 呈現，不會因為新增的分類欄位（writer_mode、evidence_status、consistency status 等）被強制拆成過多固定區塊。
- [ ] completeness 查詢的回答以 Compact Inventory Table 呈現關鍵欄位（`Display Reference`、對象、writer_mode、evidence_status），完整 provenance、manifest 與 recovery 細節保留在內部 context，不佔用主要可見版面。
- [ ] 每筆呈現給使用者的 finding 都會被指派穩定的 `Display Reference`（如 W1、W2），內部 `finding_id`/`path_id` 不會直接暴露給使用者，但仍可用於 provenance/debug/API。
- [ ] 系統保存當次對話的 `Conversation Analysis State`（含最近一次 inventory 投影與其 `Display Reference` 對應），使用者以「第二筆」「W2 那個」等自然語言追問時可被 deterministic 解析回對應 finding，而不需要使用者提供內部 ID。
- [ ] 追問中出現新的明確 identifier（SP/table/system 名稱）時，該 identifier 優先於舊有對話 reference 決定範圍（Follow-up Scope Precedence）；範圍不明確時要求澄清而非臆測。
- [ ] contract tests 使用 fake finding/manifest fixtures 驗證 answer-first 呈現邊界、compact table 內容、display reference 穩定性與 follow-up 範圍解析，不依賴 live LLM 或特定 prompt 措辭。
