# 04 — 串接 Bounded Path Selection、Selected Evidence 與 Analysis Manifest

**What to build:** 讓 UI-linked 與 non-UI `Execution Path` candidates 進入同一個 bounded `PathSelectionCoordinator`，由 LLM 只能在 deterministic candidate registry 中選擇或要求有限 expansion，並取得 selected path 的完整 evidence，附上獨立版本化的 Analysis Manifest。

**Blocked by:** 02 — 建立 Mandatory Discovery Dispatcher、Additive Merge 與 Completeness Query Routing；03 — 建立 UI-linked Handler-scoped Path Candidates 與 Canonical Object Identity

**Status:** ready-for-agent

- [ ] UI-linked 與 non-UI candidates 可在同一 selection contract 中被列出、比較與選擇，valid `path_id` 才能取得正式 path evidence。
- [ ] invalid `path_id`、重複 expansion、已拒絕 candidate 與 ambiguity decision 都會被 deterministic handling 限制，不會觸發任意 repository exploration 或無界 context growth。
- [ ] selected path 可取得與該 route 相關的 UI interaction、C# handler/method chain、SP/database invocation、SQL module/terminal DML 與可用的 specification support。
- [ ] unselected candidates 只提供 compact summary、provenance、rejection reason、unresolved signal 與 evidence gap，不會把其他 branch 的 raw source 帶入 selected context。
- [ ] selection contract tests 驗證 bounded answer、expand、clarify 行為與現有 expansion safety，不依賴 final natural-language prompt 的特定措辭。
- [ ] selected path evidence 回應附上 Analysis Manifest（`spec_revision`、`source_commit`、`sql_revision` 等獨立版本欄位）。
- [ ] manifest 內任兩個 artifact revision 不一致時，回應標示 Consistency Status，不會假設所有 artifact 都是同步版本。
