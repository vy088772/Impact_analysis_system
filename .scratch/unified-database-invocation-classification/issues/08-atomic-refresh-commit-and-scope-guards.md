# 08 — Atomic Refresh Commit and Scope Guards

**What to build:** 讓 staged contract registry 與 catalog selector 只在 formal classification 和 reconciliation 成功後，以可恢復的 cross-repository transaction 一起提交，並以 transaction manifest 與 `Analysis Manifest` 保留完整 revision provenance。任一檔案替換失敗、process 中斷、program-scoped refresh 或 cached reclassification 都要遵守相同的 onboarding 邊界。

**Blocked by:** 07 — Refresh-Time Contract Preflight; existing `external-wrapper-refresh-reconciliation` 06 — Explicit Contract Acceptance and Cached Reclassification.

**Status:** ready-for-agent

- [ ] registry 與 catalog selector 以 deterministic transaction identity、validated temporary artifacts 與 two-file logical atomic commit 更新，且只在 formal classification、wrapper reconciliation 與 post-commit validation 成功後替換 active files。
- [ ] replacement 前會寫入 transaction manifest，記錄 transaction identity、source/target repository revisions、staged artifact identities、previous file hashes、replacement order、commit progress、recovery location 與 final status。
- [ ] formal classification、wrapper reconciliation 或 post-commit validation 失敗時，active registry 與 active catalog 都保持 byte-for-byte unchanged；第二個檔案 replacement 失敗或 process 中斷時，recovery 只能回復舊 pair 或完成同一個新 pair，不得留下 mixed active state。
- [ ] 一個 complete contract 以 string selector 寫入，多個 complete contracts 以 deterministic sorted array 寫入；array order 不代表 precedence，且 registry 維持 append-only，不會為了 selector 更新而改寫既有 immutable contract。
- [ ] invalid selector 只有在整個 staged refresh 成功後才會被替換；失敗時原始 invalid value、diagnostics 與 staged comparison report 都保留，staged result 可供 review 而不會成為 active semantics。
- [ ] valid selector 定義 system 的 candidate boundary；沒有 valid selector 的 program-scoped refresh 不得從 partial source facts onboarding contract，必須使用既有 valid selector 或先完成 full-system onboarding refresh。
- [ ] `Analysis Manifest` 會記錄本次 run 使用的 `Contract Revision Reference`：contract fingerprint、signature schema revision、contract status、implementation snapshot、comparison report 與 system binding revision；歷史 manifest 的語意不可被後續 contract 更新改寫。
- [ ] contract-only acceptance 能使用 cached raw facts reclassify，更新 contract revision reference 而不重新掃描未變更的 C# source；source facts 改變時才需要新的 source refresh。
