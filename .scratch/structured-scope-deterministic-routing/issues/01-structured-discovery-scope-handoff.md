# 01 — 建立 Structured DiscoveryScope Handoff

**What to build:** 讓 routing Agent 將原始問題與 initial RAG context 轉成可序列化、可驗證、可觀測的 `DiscoveryScope`，使後續流程讀取 declarative signals，而不是解析 Agent 的 free-form tool-call 行為。

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] 同一份 scope 可在不啟動 live LLM 的情況下完成 serialize、validate、normalize 與 round-trip，並保留 system、program、UI、SP、table、specification、confidence、provenance 與 ambiguity signals。
- [ ] malformed field type、未知 enum value、互相矛盾的 identifier metadata 會產生可辨識的 validation failure，不會靜默執行 discovery。
- [ ] 等價 identifier 會去重，但所有來源 provenance、原始 spelling 與 interpretation conflict 仍可被查閱。
- [ ] scope 能區分 explicit identifier、semantic candidate、requested discovery intent 與 deterministic result，且不把任何候選直接標記成 selected path 或 backend proof。
- [ ] contract tests 可使用 fake Agent output 驗證上述行為，不依賴 prompt wording、model vendor 或外部 repository。
