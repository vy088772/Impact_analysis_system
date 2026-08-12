# 06 — 建立 Grounded Final Context、Legacy Fallback 與 Specification vs Observed 分類

**What to build:** 將 selected path evidence（或 completeness inventory）、selected UI/specification support、alternative summaries 與 uncertainty status 組成 grounded final context，並保留明確標示的 legacy Agent routing fallback，讓 migration 期間兩種結果可比較但不會被無 provenance 地混合；同時將每筆 finding 依規格與觀測證據分類。

**Blocked by:** 04 — 串接 Bounded Path Selection、Selected Evidence 與 Analysis Manifest；05 — 建立 Structured Writer/Reader Completeness Inventory 與 Bounded Evidence Recovery

**Status:** ready-for-agent

- [ ] final context 能區分 Agent interpretation、deterministic discovery result、source-backed path fact、partial/ambiguous/unresolved evidence 與 user clarification requirement。
- [ ] final answer 的 material conclusion 只可由 selected path 的完整 source-backed evidence 支持；unselected alternatives 仍以 summary、rejection reason 與 gap 呈現，不可透過名稱相似度補造 backend relation。
- [ ] selected UI interaction 與 specification support 在 evidence 可用時會跟隨 selected path 進入 context；missing specification 會顯示為 spec gap，不會抹除既有 C# 或 SQL evidence。
- [ ] legacy `get_flow_chains()` 或 Agent tool-call result 若被使用，會標記為 legacy/compatibility evidence，且未具備 `path_id` 時不會被宣稱為正式 `Execution Path` 或 structured mandatory-discovery result。
- [ ] structured 與 legacy mode 可在相同 deterministic fixture 上分別執行與比較，輸出會保留各自 provenance、coverage 差異與 fallback 使用狀態，不會靜默合併兩份 evidence。
- [ ] 每筆 finding 依證據分類為「規格提及且程式證實」「規格提及但目前無法驗證（Specification-indicated / Unverified）」或「程式證實但規格未載明（Observed but Undocumented）」三類之一。
- [ ] 缺乏證據時只會標記為 `unresolved`／`Evidence Gap`，不會被解讀為該 writer/reader/path 不存在（Negative Inference Prohibition）。
