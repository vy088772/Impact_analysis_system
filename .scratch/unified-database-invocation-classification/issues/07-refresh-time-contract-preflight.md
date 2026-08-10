# 07 — Refresh-Time Contract Preflight

**What to build:** 讓一次 `refresh_cli` 在同一個 source snapshot 上完成 raw analysis、Contract Preflight、staged contract interpretation、formal `Database Invocation` classification 與 wrapper reconciliation；不需要先執行獨立 discovery command 才得到正式分類結果。

**Blocked by:** 06 — External Wrapper Contract Classification; existing `external-wrapper-refresh-reconciliation` 02 — Full Refresh Wrapper Reconciliation.

**Status:** ready-for-agent

- [ ] refresh 只執行一次 raw source analysis；Preflight、formal classification 與 reconciliation 共用同一批 raw facts，不進行第二次 filesystem scan。
- [ ] missing、`null`、blank string、empty array、all-blank array、invalid string 與 partially invalid array 都會被一致正規化為 unspecified，並保留原始 invalid selector diagnostics。
- [ ] valid string 或 valid array selector 會成為 explicit candidate set；formal classification 不會 fallback 到 selector 以外的 contract，也不會自動新增或覆寫 contract。
- [ ] selector 未指定時，只有完整且可驗證的 source-backed 或 exact external implementation evidence 能產生 staged contract；incomplete、conflicting、ambiguous 或 name-only proposal 會留在 review/unresolved。
- [ ] 一個完整 proposal 可形成單一 selector，多個完整 proposals 形成 deterministic candidate set；沒有完整 proposal 時，受影響 wrapper 會是 `unresolved` 並帶有 `contract_preflight_failed`，不影響無關 direct 或 inline invocation。
- [ ] refresh summary 會同時呈現 classification status、invocation mode、sink、target、connection source 與 unresolved reason。
