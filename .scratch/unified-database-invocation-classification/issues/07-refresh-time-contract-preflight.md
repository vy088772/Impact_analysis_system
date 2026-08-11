# 07 — Refresh-Time Contract Preflight

**What to build:** 讓一次 `refresh_cli` 在 `git pull` 後的同一個 source snapshot 上完成 raw analysis、`Receiver Implementation Binding`、Contract Preflight、staged contract interpretation、formal `Database Invocation` classification 與 wrapper reconciliation；不需要先執行獨立 discovery command 才得到正式分類結果，且 contract 選擇只能服從明確的 system boundary。

**Blocked by:** 06 — External Wrapper Contract Classification; existing `external-wrapper-refresh-reconciliation` 02 — Full Refresh Wrapper Reconciliation.

**Status:** ready-for-agent

- [ ] refresh 只執行一次 raw source analysis；Preflight、formal classification 與 reconciliation 共用同一批 raw facts、current source snapshots 與 verified implementation evidence，不進行第二次 filesystem scan。
- [ ] `missing`、`null`、blank string、empty array、all-blank array、invalid string 與 partially invalid array 都會被一致正規化為 unspecified，並保留原始 invalid selector diagnostics；missing named contract 或 array member 不會被部分套用。
- [ ] valid string 或 valid array selector 會成為 explicit `Selector Candidate Boundary`；formal classification 不會 fallback 到 selector 以外的 registry entry、另一個 system binding、same-named contract 或 `auto_select` inference，也不會自動新增或覆寫 contract。
- [ ] selector 未指定時，只有完整且可驗證的 source-backed 或 exact external implementation evidence，且通過完整 `Database Behavior Surface`、single-revision 與 fingerprint comparison，才能產生 staged contract；incomplete、conflicting、ambiguous 或 name-only proposal 會留在 review/unresolved。
- [ ] preflight 可依完整 `Contract Behavior Signature` 與 `Contract Fingerprint` deterministic reuse 既有 contract；一個完整 proposal 可形成單一 selector，多個完整 proposals 形成 deterministically sorted candidate set，array order 不代表 precedence。
- [ ] 沒有完整 proposal 時，staged registry/catalog 不會被套用；受影響 wrapper 會是 `unresolved` 並帶有 `contract_preflight_failed`，不影響無關 direct 或 inline invocation。
- [ ] preflight 會分開輸出 contract onboarding lifecycle status、wrapper classification status 與 `Evidence Status`，並讓 staged result 可在 commit 前 review。
- [ ] refresh summary 會同時呈現 classification status、invocation mode、sink、target、connection source、contract reference 與 unresolved reason。
