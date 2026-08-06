# 03 — 建立 UI-linked Handler-scoped Path Candidates 與 Canonical Object Identity

**What to build:** 將 UI interaction discovery 的結果與 source-backed handler、C# reachability、database invocation 及 SQL path facts 依 Canonical Object Identity 正規化後 join 起來，產生可選的 handler-scoped candidates；UI operation identity 與 backend path identity 必須分離。

**Blocked by:** 02 — 建立 Mandatory Discovery Dispatcher 與 Additive Merge

**Status:** ready-for-agent

- [ ] 每個可辨識的 UI operation 都保留穩定且可追溯的 `interaction_id`，query、save、delete、cancel 與 row command 不會只以 shared method name 表示。
- [ ] 每個 proven handler-scoped route 都保留穩定的 `path_id`，並帶有 page、event、handler、reachable methods、database invocation 與 SQL relationship provenance。
- [ ] PUR/TTPUR query 與 row-delete 即使共用 `BindData()`、SP、table 或 downstream sink，仍會產生不同 interaction/path candidates，不會因 shared downstream node 被合併。
- [ ] 同名 handler 出現在不同 page 或 system 時，page pairing、source identity 與 system provenance 會維持 candidates 分離。
- [ ] 沒有 proven server/API mapping 的 UI interaction 會保留為 `unresolved` UI evidence，不會被命名相似度或 Agent confidence 提升成 C# 或 SQL relation。
- [ ] dynamic SQL、unresolved API target、missing source 或低信心 invocation 會保留 rated uncertainty，且只有 source-backed facts 才能進入正式 path candidate。
- [ ] SP、table 與 program 等 backend identifier 在 join 前先正規化為 Canonical Object Identity，跨 schema 或跨 system 的同名 object 不會被誤判為同一實體。
- [ ] 無法唯一決定 canonical identity 的 identifier（跨 unrelated systems 同名）會回報為 `ambiguous`，並列出所有候選來源與 provenance，不會任意選擇其中一個。
