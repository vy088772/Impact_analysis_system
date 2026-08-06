# 02 — 建立 Mandatory Discovery Dispatcher、Additive Merge 與 Completeness Query Routing

**What to build:** 讓 normalized `DiscoveryScope` 驅動 deterministic discovery，依問題中的 signals 執行所有適用的 RAG、exact SP/table、UI、program 與 specification discovery，並將結果以 provenance-preserving contract additive merge；同一 dispatcher 另外辨識「列舉全部 writer/reader」類的 completeness 意圖，路由到 completeness inventory 查詢，與既有 mandatory discovery 及 Execution Path 選擇並存。

**Blocked by:** 01 — 建立 Structured DiscoveryScope Handoff

**Status:** ready-for-agent

- [ ] 同時包含 screen、SP、table、system、program 或 specification intent 的問題，會完成所有適用的 mandatory discovery；任何一個 signal 都不會因另一個 route 被選中而消失。
- [ ] Agent 刻意漏填 explicit SP 或 table action，但原始問題含有明確 identifier 時，dispatcher 仍會執行對應 exact lookup，並記錄 deterministic recovery 或 interpretation conflict。
- [ ] RAG、exact lookup、UI、program 與 specification 結果 merge 後仍保留來源、confidence、access intent、spec gap 與 unresolved state，不會以單一較高分候選覆蓋其他 evidence。
- [ ] 同名 SP 或 table 跨 unrelated systems 時，未指定 system 的結果會是 `ambiguous` 並要求 clarification；明確指定 system 時可限制範圍，同時保留被排除候選的 provenance 或 summary。
- [ ] table 的 write-only intent 與一般 access intent 會產生不同 candidate policy，且兩者都能在 merged result 中被觀測。
- [ ] 問題被判定為 completeness 查詢（例如「哪些程式會寫入 X table」）時，dispatcher 會路由到 completeness inventory 查詢；此路由與既有 exact SP/table/UI discovery 並存，不會取代或跳過 mandatory discovery。
- [ ] completeness 路由與 Execution Path 選擇路由彼此獨立：選擇其中一種不會抑制另一種在同一 scope 下的可用性。
- [ ] contract tests 使用 fake discovery adapters 驗證 mandatory action completion、additive merge、ambiguity policy 與 completeness routing 判斷，不依賴 live LLM 或外部服務。
