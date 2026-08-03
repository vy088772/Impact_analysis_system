# 11 — 導入共用 Path Selection Loop

**What to build:** deterministic mode 與 agentic mode 在 discovery 後共用同一個 Path Selection Loop，讓 LLM 以 `answer | expand | clarify` 選擇或擴展路徑，並只用 selected evidence 產生最終答案。

**Blocked by:** 10 — 提供 Exact Path Evidence API

**Status:** ready-for-agent

- [ ] 兩種模式使用同一 coordinator 與結構化 decision contract。
- [ ] expand 最多三輪，重複 path 不重抓 evidence 且不消耗輪次。
- [ ] invalid ID 只允許一次修正，第二次失敗轉為 clarify。
- [ ] 最終 context 只包含 selected Path Evidence，並區分 verified facts 與 unresolved uncertainty。