# 08 — Atomic Refresh Commit and Scope Guards

**What to build:** 讓 staged contract registry 與 catalog selector 只在 formal classification 和 reconciliation 成功後一起提交，並在任一檔案替換失敗時維持兩個 active files 的原狀。Program-scoped refresh 與 cached reclassification 也要遵守相同的 onboarding 邊界。

**Blocked by:** 07 — Refresh-Time Contract Preflight; existing `external-wrapper-refresh-reconciliation` 06 — Explicit Contract Acceptance and Cached Reclassification.

**Status:** ready-for-agent

- [ ] registry 與 catalog selector 以 deterministic transaction identity、validated temporary files 與 two-file logical atomic commit 更新。
- [ ] formal classification、wrapper reconciliation 或 post-commit validation 失敗時，active registry 與 active catalog 都保持 byte-for-byte unchanged。
- [ ] 第二個檔案 replacement 失敗時能 rollback 或 recovery 第一個 replacement，並在 refresh 結果中保留明確 failure diagnostics。
- [ ] 一個 complete contract 以 string selector 寫入，多個 complete contracts 以 deterministic sorted array 寫入；array order 不代表 precedence。
- [ ] invalid selector 只有在整個 staged refresh 成功後才會被替換；失敗時原始 invalid value 與 diagnostics 都保留。
- [ ] 沒有 valid selector 的 program-scoped refresh 不得從 partial source facts onboarding contract；contract-only acceptance 能使用 cached raw facts reclassify，而不重新掃描未變更的 C# source。
