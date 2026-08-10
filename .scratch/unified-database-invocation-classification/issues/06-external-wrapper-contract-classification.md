# 06 — External Wrapper Contract Classification

**What to build:** 讓 unavailable external wrapper 在有可靠語意來源時可以參與 `Database Invocation` 分類，同時嚴格區分 source-backed evidence、verified implementation snapshot、`wrapper_contract` selector 與 procedure proof。外部 contract 應是可重用的 semantics selector，不是 observed method inventory。

**Blocked by:** 03 — Source-Backed Overload and Method Semantics; 05 — Adapter and Fill Sink Parity; existing `external-wrapper-refresh-reconciliation` 01 — Canonical Wrapper Reconciliation Boundary; existing `external-wrapper-refresh-reconciliation` 05 — Review-Only External Contract Proposals.

**Status:** ready-for-agent

- [ ] Local source implementation 或帶有 exact external assembly identity 的 verified implementation snapshot，會優先於外部 `wrapper_contract` selector。
- [ ] unavailable wrapper 只有在 matching selected contract 提供 receiver、method、mode 與 terminal sink semantics 時，才可貢獻 stored-procedure 或 inline invocation classification。
- [ ] `wrapper_contract` 本身不能證明 procedure target、connection source、Catalog match 或 SQL Execution Graph relationship；這些 facts 必須由其他 evidence 提供。
- [ ] new receiver、missing method、conflicting semantics 與 ambiguous contract 會產生 review candidate 與 unresolved reason，不會依 registry order、method name 或 frequency 自動選擇。
- [ ] reflection-only metadata、arbitrary DLL discovery、decompilation 或 name-only observation 不會建立 active contract。
- [ ] equivalent receiver type 的既有 contract 可以被 deterministic reuse；valid selector 不會因觀察到新 method 就自動覆寫或擴充。
