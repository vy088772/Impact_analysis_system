# 11 — Selector Fail-Closed for Receiver-Bound Contracts

**What to fix:** 修正 external wrapper reconciliation 在缺少有效 system selector 時，仍透過 `Receiver Implementation Binding` 對整個 external contract registry 做 fallback selection 的規格違反。

**Follow-up from:** `/code-review` 對 issue 01–10 的 Spec 軸審查；這是標記 unified classifier 完成前必須修正的 blocking finding。

**Status:** resolved

## Problem

`CSharpAnalysisGateway.reconcile_wrapper` 目前在沒有明確 `wrapper_contract` selector 時，若 raw fact 含有 `implementation_identity` 與 `assembly_identity`，會呼叫 `_contracts_by_implementation_identity(binding)`。該 helper 會掃描整個 external-wrapper-contracts registry；當恰好只有一個 receiver type 相符的 contract 時，reconciliation 會產生 `auto_receiver_type` / `auto_selected`，後續 invocation classification 可能把它當成正式 selected contract，進而得到 `proven` stored-procedure evidence 並加入 `Execution Path`。

這違反 unified classifier spec 的 selector boundary：

- 有效 selector 定義 formal classification 的 candidate boundary；不得從 registry-wide receiver match、其他 system binding 或 selector 外的 contract fallback。
- 沒有 selector 時，完整 source/DLL evidence 只能形成 staged candidate；在 system binding 與 registry transaction commit 前，candidate 不是 active contract。
- contract 不得由 receiver type、class name 或 registry order 自動選出。

## Acceptance Criteria

- [x] 沒有有效 selector 時，即使 `Receiver Implementation Binding` 同時含有 concrete `implementation_identity`、`assembly_identity`，且 registry 中只有一個 receiver match，也不得選取該 contract。
- [x] 上述情境的 Gateway reconciliation 必須維持 unresolved/review-candidate，`active_contract` 為 false，不得回傳 `auto_selected`、`auto_receiver_type`、contract name、contract mode 或 contract sink 作為正式分類結果。
- [x] 沒有 selector 的 external wrapper 不得僅因 registry-wide receiver match 而產生 `InvocationEvidence.PROVEN`，也不得因此加入正式 `Execution Path` graph join；應保留 documented unresolved reason/provenance。
- [x] 有效 string selector 與有效 array selector 的既有 explicit classification 行為不變；selector 以外的 registry contract 仍不可被考慮，array order 仍不代表優先順序。
- [x] Contract preflight 仍可在完整 source/DLL evidence 下建立 staged candidate，但 candidate 只有在 system binding 與 registry transaction 成功 commit 後，才可作為後續正式 classification 的 active selector；不因本修正重新引入 registry-wide auto-selection。
- [x] 新增或修改 Gateway 外部行為測試，實際帶入 implementation binding 與 matching registry，鎖住「無 selector 仍 unresolved」的 regression；測試不得只覆蓋 bare receiver type。
- [x] 更新 `tests/test_exact_path_evidence.py` 中把 `auto_selected` 當作合法 proven classification 的 fixture，改用有效 explicit selector，或改為驗證 unresolved evidence；測試不得再替禁止的 auto-selection 狀態背書。

## Scope Guidance

- 主要修正面：`code_analyzer/csharp_analysis_gateway.py` 的 `reconcile_wrapper` 與 `_contracts_by_implementation_identity` selection path。
- 保留 `Receiver Implementation Binding` 作為 evidence/provenance；不要把 receiver/assembly identity 重新當成 contract identity 或 implicit selector。
- 不要把本票擴大成 `reconcile_wrapper` 的 dispatch 重構、contract identity value object，或 registry payload normalizer consolidation；那些是 Standards 軸的非 blocking code smells。
- 不要處理與本功能無關的 whitespace-only diff。

## Verification

至少執行：

```text
.venv/bin/python -m pytest tests/test_csharp_analysis_gateway.py tests/test_exact_path_evidence.py tests/test_refresh_contract_preflight.py tests/test_program_refresh.py
```

完成條件是 focused suite 通過，且新增 regression test 能在修正前重現 review 指出的 registry-wide fallback、修正後確認 fail-closed。

## Comments

Removed the registry-wide `_contracts_by_implementation_identity` fallback from
`CSharpAnalysisGateway.reconcile_wrapper`. A valid explicit system selector is
now the only contract-selection source; receiver implementation binding remains
available as provenance and identity evidence, but cannot activate a contract by
itself. The runtime `auto_selected` status path was removed as unreachable after
the selector change.

Added Gateway coverage for a concrete implementation/assembly binding that
matches a registry contract without a selector. The invocation remains
unresolved/review-only, retains its raw stored-procedure mode separately from
`Evidence Status`, and produces only an unconfirmed diagnostic path even when a
matching stored procedure and terminal DML node exist. Updated the older binding
test and path-evidence fixture so they no longer bless implicit auto-selection;
the path fixture now represents an explicit selector.

Focused verification passed with 209 tests. The full suite excluding the two
tests that require the unavailable local SQL Server ODBC driver passed 325 tests;
two unrelated pre-existing tests still fail because of a dependency-graph JSON
schema expectation and a hard-coded Windows path. The required two-axis review
found no documented-standard violation or blocking spec issue.
