# 08 — 完成 Structured Routing Rollout 與 Unified Canonical Acceptance

**What to build:** 以可重現的 source snapshot、明確的 operational failure contract 與 PUR/TTPUR canonical scenario 驗收 structured routing，並建立受控的 structured-default／legacy-fallback rollout boundary；驗收範圍同時涵蓋單一 `Execution Path` 選擇與 completeness inventory／manifest／conversation 行為，確保兩者在同一 rollout 下不互相回歸。

**Blocked by:** 07 — 建立 Adaptive Final Answer、Compact Inventory Table 與 Conversation Analysis State

**Status:** ready-for-agent

- [ ] 相同 normalized scope 與相同 source snapshot 重複執行時，candidate identities、`interaction_id`、`path_id`、provenance 與 status 保持穩定且可比較。
- [ ] malformed scope、source-cache unavailable、stale snapshot、missing SQL graph 與 user ambiguity 會以不同 operational status 回報，不會全部折疊成 generic clarification 或 generic analysis failure。
- [ ] PUR/TTPUR canonical mixed scenario 同時包含 screen、query、row delete、shared `BindData()`、explicit SP/table hint 與 named system 時，所有 signals 都能抵達 bounded candidate set，且 query/delete candidates 保持分離。
- [ ] canonical scenario 能完成 selected path evidence 驗收，包含 UI interaction、handler、C# reachability、SP/SQL relation、terminal data effect、provenance 與未選 alternatives 的 summary/gap。
- [ ] structured routing 可被設為主要 mode，legacy routing 只能透過明確 fallback boundary 使用，並可觀測 fallback、scope validation、discovery 與 path-selection failure 類型。
- [ ] deterministic routing contract suite、既有 exact SP/table tests、既有 path-selection tests 與 canonical acceptance tests 在不依賴 live LLM 的情況下通過；live LLM smoke test 不得成為 correctness gate。
- [ ] completeness inventory、evidence recovery、spec-vs-observed 分類與 conversation follow-up 的 acceptance scenario 與既有 PUR/TTPUR canonical scenario 一起執行，兩者共用同一 structured-default rollout boundary，且互不回歸。
