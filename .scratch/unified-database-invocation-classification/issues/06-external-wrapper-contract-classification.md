# 06 — External Wrapper Contract Classification

**What to build:** 讓 unavailable external wrapper 在有可靠語意來源時可以參與 `Database Invocation` 分類，同時以完整 `Database Behavior Surface` 建立可重用且不可變的 contract identity，嚴格區分 source-backed evidence、verified implementation snapshot、`wrapper_contract` selector 與 procedure proof。外部 contract 應是可重用的 semantics selector，不是 observed method inventory。

**Blocked by:** 03 — Source-Backed Overload and Method Semantics; 05 — Adapter and Fill Sink Parity; existing `external-wrapper-refresh-reconciliation` 01 — Canonical Wrapper Reconciliation Boundary; existing `external-wrapper-refresh-reconciliation` 05 — Review-Only External Contract Proposals.

**Status:** resolved

- [x] Local source implementation 或帶有 exact external assembly identity、assembly revision 與完整 Metadata as Source method bodies 的 verified implementation snapshot，會優先於外部 `wrapper_contract` selector；source/contract 衝突會保留雙方 provenance。
- [x] Snapshot 必須落在單一 `Assembly Revision Boundary`，並記錄 artifact identity、assembly identity、revision、`Behavior Surface Unit`、method/overload identity、argument roles、effective semantics、terminal sink 與完整 helper/inherited operation evidence；缺漏、混合 revision 或 incomplete metadata 只能產生 review/unresolved。
- [x] Contract comparison 覆蓋 class-level `Database Behavior Surface` 的所有 relevant public database operations 與 overload，包括 fixed/call-site mode、argument roles、connection behavior boundary、branch-scoped sinks；non-database utility 不會被誤判成遺漏的 database operation。
- [x] `Contract Behavior Signature` 以 canonical、normalized 形式保存 operation identity、overload arity/parameter identity、argument roles、effective command semantics、terminal sink 與 call-site/branch rules；source formatting、receiver name、assembly provenance 與 discovery order 不影響結果。
- [x] `Contract Fingerprint` 由 behavior signature 與 signature schema revision deterministic 產生；等價的完整 behavior 可 reuse，同一 receiver name 的不同 implementation 不能共用 fingerprint，behavior 改變時必須產生新的 immutable identity。
- [x] Active registry 採 append-only lifecycle；accepted contract 不得 in-place rewrite 或 delete，legacy contract 只能在 explicit binding 且明確標示未驗證時相容使用，歷史 `Analysis Manifest` 參照的 contract 不得變更語意。
- [x] unavailable wrapper 只有在 matching selected contract 提供 receiver implementation binding、method/overload、mode 與 terminal sink semantics 時，才可貢獻 stored-procedure 或 inline invocation classification。
- [x] `wrapper_contract` 本身不能證明 procedure target、connection source、Catalog match 或 SQL Execution Graph relationship；這些 facts 必須由其他 evidence 提供。
- [x] Local source semantics 優先於 selected external contract；若兩者衝突，輸出 `Source Contract Conflict` provenance，不得靜默覆寫 source 或 binding evidence。
- [x] new receiver、missing method/overload、incomplete surface、conflicting semantics 與 ambiguous contract 會產生 review candidate、comparison report 與 unresolved reason，不會依 registry order、method name 或 frequency 自動選擇。
- [x] 每次 onboarding comparison 都產生可追溯的 `Contract Comparison Report`，保留 compared snapshot identities、revision、signature version、fingerprint、method/overload differences、unresolved operations、conflict state 與 latest/history references。

**Implementation notes:** Added canonical behavior-surface signatures and SHA-256 contract fingerprints with exact implementation-boundary identity; verified single-revision snapshot validation; overload-aware method projections; append-only versioned acceptance with comparison-report history; explicit legacy compatibility lifecycle; concrete receiver binding; and source-versus-contract conflict provenance. Added focused Gateway/acceptance coverage for identity reuse, behavior changes, incomplete or conflicting snapshots, overloads, legacy binding, receiver binding, and durable provenance.
