---
status: ready-for-agent
triage: ready-for-agent
---

# Refresh-time External Wrapper Contract Reconciliation

## Problem Statement

目前的程式碼 refresh 會更新 source snapshot、Method Flow 與 raw Database Invocation，但 external wrapper 的盤點是另一個需要維護者手動執行的 read-only CLI。這造成同一批 source 可能被先 refresh、再 discovery，操作流程重複，也讓 wrapper contract 的更新與下一次 program-scoped refresh 之間缺少清楚的契約。

當 C# 呼叫一個 source 不可得的 wrapper 時，單靠 `receiver_type + wrapper_method` 只能知道觀察到一個呼叫，不能安全推導它是 stored procedure、inline SQL 或其他 sink。若 refresh 直接把新 method 加進 active contract，可能把錯誤的 `mode` 或 `sink` 當成 `proven` evidence，進而污染 Execution Path、Path Evidence 與 reverse lookup。

此外，`wrapper_contract` 是 system 對 reusable contract 的 selector，不是 wrapper method inventory。已存在的 `sqlobject` contract 應該被相同 receiver type 重用；未知 method 或未知 receiver type 則必須留下可審查的 Evidence Gap，而不是建立一個語義未經驗證的 active contract。

## Solution

讓 `refresh_cli` 成為完整的 contract onboarding 與 source classification orchestrator。它在同一次操作中完成 `git pull`、raw source analysis、source contract preflight、formal `Database Invocation` classification、wrapper observations/reconciliation，以及 `proven` / `likely` / `unresolved` 輸出。preflight 與 formal classification 重用同一份 raw analyzer result，不重複掃描檔案系統。

refresh 依下列順序執行：

1. 解析 system 的 source roots 並執行 `git pull`。
2. 執行一次 raw C# source analysis，保留 source snapshot、typed invocation facts、source spans 與 connection facts。
3. 正規化 `system_catalog.wrapper_contract`。缺欄位、`null`、空白字串、空 array、只有空白值的 array 都代表未指定。單一非空字串代表一個 explicit contract；非空 array 代表多個 explicit contract candidate。
4. 若 selector 指向不存在的 contract，將單一 invalid selector 或包含任一 missing name 的整個 array 視為未指定，但保留原始值與 `invalid_selected_contract` diagnostics。若 selector 有效，禁止建立或覆寫 contract，formal scan 只使用指定 contract 或指定 candidate set，不向集合外 fallback。
5. 對未指定 selector 執行 source/DLL contract preflight。preflight 只能從 local source 或帶有 exact external assembly identity 的 verified implementation snapshot 建立完整 method semantics；reflection-only metadata、method name 或不完整 DLL evidence 不得建立 active semantics。等價 receiver contract 會被重用；conflict、ambiguous、incomplete 或 name collision 只產生 review candidate。
6. 建立 in-memory staged registry 與 catalog selector。單一完整 contract 寫成 string；多個完整 contract 寫成 deterministic sorted array；array 順序不是優先級。若沒有完整 proposal，保留目前 selector，受影響 external wrapper 於 formal scan 中標示 `unresolved`。
7. 使用 staged registry/catalog 執行 formal source classification 與 wrapper reconciliation。source-backed implementation 優先於 external contract；valid explicit selector 或 candidate set 只限制 external contract 的選擇範圍。contract selector 不等於 procedure proof，仍須通過 mode、sink、connection source 與 SP Catalog evidence。
8. 輸出 method semantics、invocation mode、sink、target、connection source、proven / likely / unresolved、contract provenance 與 unresolved reasons。
9. 只有 formal classification 與 reconciliation 成功後，才以 logical two-file atomic commit 同步寫入 `external_wrapper_contracts.json` 與 `system_catalog.wrapper_contract`。任何 preflight、scan、reconciliation 或 commit failure 都保留兩份 active configuration 原狀。

`discover_external_wrappers` 保留為可選的 audit/report 入口，但重用同一套 reconciliation service。它不再是 refresh 後取得 wrapper classification 的必要第二階段，也不會擁有另一套 wrapper 語義規則。

## User Stories

1. As a system operator, I want one full code refresh to include external-wrapper reconciliation, so that I do not need to run a second discovery command for the same source snapshot.
2. As a system operator, I want the refresh response to report wrapper classification status, so that I can see whether each observed wrapper was source-backed, explicitly selected, auto-selected, ambiguous, or unresolved.
3. As a system operator, I want a program-scoped refresh to analyze only the selected program files, so that discovering wrapper facts never silently expands the operation into a full-system C# scan.
4. As a system operator, I want all scan roots to pass the current-cache preflight before a program-scoped refresh, so that the partial result is not built on a mixture of stale and current source snapshots.
5. As a system operator, I want a multi-root system to reconcile each root within its own source boundary, so that a wrapper in an unrelated sibling root is not silently treated as local source.
6. As a system analyst, I want a source-available wrapper to remain source-backed evidence, so that local wrapper implementations do not require an external contract merely because they use a custom method name.
7. As a system analyst, I want a wrapper whose implementation is unavailable to require a declared contract before it contributes stored-procedure evidence, so that a DLL boundary is never treated as proof by itself.
8. As a system analyst, I want a receiver type with exactly one auto-selectable contract to reuse that contract automatically, so that common libraries can be shared across systems without a per-system wrapper name table.
9. As a system analyst, I want an explicitly selected system contract to take precedence over receiver-type auto-selection, so that a system can resolve a known exception deterministically.
10. As a system analyst, I want an unknown receiver type to remain unresolved, so that a new library cannot be assigned semantics from an unrelated contract.
11. As a system analyst, I want a receiver type matching multiple contracts to remain ambiguous, so that the analyzer never chooses one contract by registry order or method-name similarity.
12. As a system analyst, I want an observed method missing from an otherwise matching contract to be reported as an unresolved method, so that the missing semantic declaration is visible for review.
13. As a system analyst, I want `CreateReader` with a literal SELECT statement to remain inline SQL, so that it is not reported as a stored-procedure invocation.
14. As a system analyst, I want a `call_site` wrapper method to be trusted as a stored-procedure call only when the call site explicitly selects SP mode, so that overloads and mode arguments are not guessed.
15. As a system analyst, I want stored-procedure wrapper candidates validated against the resolved database-scoped SP Catalog, so that a literal name is not promoted merely because it looks like an SP name.
16. As a system analyst, I want dynamic command text to remain unresolved, so that the system does not fabricate a procedure, table, or database target.
17. As a system analyst, I want every unresolved or ambiguous wrapper observation to retain receiver type, method, source span, scan root, and candidate contracts, so that I can recover the missing evidence without repeating broad investigation.
18. As a system maintainer, I want the existing `sqlobject` contract to be reused for `SQLObject`, so that refresh does not create duplicate contracts with competing names.
19. As a system maintainer, I want a newly observed method to produce a review candidate rather than an active contract entry, so that `mode` and `sink` are approved before they affect formal evidence.
20. As a system maintainer, I want the review candidate to distinguish an unknown method from an unknown receiver contract, so that the next registry change is narrowly scoped.
21. As a system maintainer, I want a valid existing selector to prevent automatic contract creation or overwrite, so that an explicitly chosen contract remains authoritative for formal external-wrapper classification.
22. As a system maintainer, I want an unspecified selector to allow only complete source/DLL-backed contract onboarding, so that ordinary refresh can repair missing semantics without promoting incomplete observations.
23. As a system maintainer, I want an accepted contract change to reclassify existing raw scan facts without rescanning C#, so that semantic registry maintenance is cheap and does not create unnecessary source churn.
24. As a system maintainer, I want source changes to remain the trigger for a new C# refresh, so that the distinction between source revision and contract revision stays explicit.
25. As a downstream RAG coordinator, I want `wrapper_contract` to be resolved from the system catalog and forwarded through refresh, analyze, and path-evidence requests, so that every entry point uses the same selector semantics.
26. As a downstream RAG coordinator, I want refresh results to be machine-readable, so that the coordinator can show review items without parsing localized log messages.
27. As a downstream RAG coordinator, I want active contract selection and wrapper evidence to remain separate, so that catalog routing cannot be mistaken for proof of a database operation.
28. As a system analyst, I want the same classification rules to be used by refresh, analyze, path evidence, reverse lookup, and the optional audit CLI, so that one wrapper observation cannot receive different meanings depending on the entry point.
29. As a system analyst, I want wrapper evidence to retain its Evidence Status independently from SQL Execution Graph readiness, so that a current code scan is not mistaken for a current SQL graph.
30. As an operator, I want wrapper reconciliation to complete without an available SQL database when only source facts are needed, so that source refresh remains useful even when SQL enrichment is unavailable.
31. As an operator, I want a missing or stale scan cache to remain a clear program-refresh precondition failure, so that wrapper reconciliation cannot reintroduce the old full-scan fallback.
32. As a system maintainer, I want the optional discovery CLI to report cache readiness separately from wrapper contract status, so that stale-cache operations are not misdiagnosed as registry defects.
33. As a system maintainer, I want the refresh summary to identify whether a result came from explicit selection, receiver auto-selection, or source resolution, so that provenance survives into later review.
34. As a system analyst, I want source snapshots and invocation spans to remain the evidence source for wrapper observations, so that the reconciliation report can be traced back to concrete code.
35. As a future implementation agent, I want the normal refresh path, explicit acceptance path, and optional audit path to share a documented contract, so that follow-up changes do not recreate competing discovery logic.
36. As a system operator, I want refresh to run `git pull`, one raw scan, preflight, formal scan, reconciliation, and output in one deterministic order, so that contract semantics are ready before invocation evidence is rated.
37. As a system maintainer, I want a missing named contract to behave like an unspecified selector, so that a stale catalog reference can be repaired without blocking unaffected invocations.
38. As a system maintainer, I want an array selector to represent an explicit contract set, so that multiple contracts can serve one system without array order becoming precedence.
39. As a system maintainer, I want an array with any missing contract name to be treated as invalid as a whole, so that partial configuration cannot create environment-dependent semantics.
40. As a system maintainer, I want one complete contract to serialize as a string and multiple complete contracts as a deterministic array, so that catalog format remains backward compatible and stable.
41. As a system analyst, I want incomplete, conflicting, or ambiguous preflight evidence to leave affected wrappers unresolved, so that the workflow remains useful for direct and source-backed invocations without guessing.
42. As a system operator, I want registry and catalog changes to commit atomically after successful reconciliation, so that a failed refresh cannot leave a half-applied selector.
43. As a system maintainer, I want a program-scoped refresh to require an existing valid selector or completed full-system onboarding, so that partial observations cannot generate an incomplete contract set.

## Implementation Decisions

- The `CSharpAnalysisGateway` remains the single high-level owner of wrapper classification and Evidence Status. It consumes raw StaticAnalyzerHost facts, source snapshot availability, the optional explicit contract, receiver-type registry candidates, and the database-scoped SP Catalog; it does not infer semantics from method names.
- `ProjectScanner` remains responsible for one source scan and for passing the complete current scan root as source context when analyzing selected C# files. Wrapper reconciliation consumes the resulting facts and does not invoke another C# analyzer pass.
- `refresh_source` orchestrates raw analysis, contract preflight, staged formal classification, reconciliation, and commit after a successful full update. For a partial update, unchanged raw invocation facts remain in the cache and selected files replace only their own records; contract onboarding is not allowed unless a valid selector already exists or a prior full-system onboarding refresh completed.
- `RefreshRequest` accepts a backward-compatible wrapper-contract selector represented as a string or array. The spec-rag refresh client resolves it from the system catalog when the caller has not supplied one, then normalizes blank/null/empty values as unspecified.
- `RefreshResponse` gains additive machine-readable wrapper summary fields. The response must expose observed wrapper groups, classification status, selected contract, selection source, receiver type, observed methods, candidate contract names, source provenance, and review reasons without requiring consumers to parse terminal text.
- Wrapper classification status is separate from `InvocationEvidence`. `source_wrapper`, `explicit_selected`, and `auto_selected` describe contract/source resolution; `proven`, `likely`, and `unresolved` describe the resulting Database Invocation evidence. One status must not be used as a substitute for the other.
- Source-wrapper resolution is bounded by the current scan root. In a multi-root system, each root is reconciled with its own source context. Cross-root source lookup, repository-wide dependency materialization, and DLL retrieval are not introduced by this feature.
- Contract selection precedence is source-backed implementation first, then a valid explicit selector or explicit selector array for unavailable external wrappers, then a unique `auto_select` receiver-type match from the staged registry when no selector is specified. Zero candidates produce an unresolved contract result. Multiple candidates produce an ambiguous result and retain all candidate contract names as Impact Provenance. An explicit selector array is a candidate set, not an ordered priority list.
- Selector normalization treats a missing field, `null`, blank string, empty array, or all-blank array as unspecified. A missing named contract makes a string selector unspecified for preflight. Any missing member makes an array selector invalid as a whole and therefore unspecified for preflight. The original invalid value remains in diagnostics until a successful commit replaces it.
- Contract receiver and method matching is normalized by the existing receiver and method identity rules. A matching receiver type alone is insufficient: the observed wrapper method must also exist in the selected contract, and the contract receiver declaration must match the observed receiver.
- `stored_procedure`, `inline_sql`, and `call_site` retain their existing meanings. An `inline_sql` method is excluded from stored-procedure invocation classification. A `call_site` method requires explicit call-site SP mode. The contract sink is descriptive of the downstream wrapper operation and is not itself a new wrapper method.
- A source-available wrapper is not converted into an external contract proposal merely because its name is absent from the registry. The source implementation is the stronger local evidence path; an external contract is for unavailable or opaque wrapper boundaries.
- Contract preflight may reuse an equivalent receiver contract or create a deterministic new contract only when local source or an exact-identity verified external implementation snapshot establishes receiver, method, mode, and sink semantics. Reflection-only metadata, method-name heuristics, and incomplete DLL facts remain review-only.
- An unavailable external wrapper with a new method or receiver type produces a review-only contract candidate when complete semantics are not available. The candidate records observed identity and provenance, but leaves `mode`, `sink`, and active trust unresolved.
- An observed method that is absent from an existing receiver contract produces an `unresolved_method` review item. It must not be appended automatically to the active contract, even when the receiver type uniquely selects that contract.
- The current `sqlobject` registry entry is reused when the receiver type is `SQLObject`. The feature must not create a second contract solely because a refresh observed another `SQLObject` call site.
- Normal refresh may stage and conditionally write the external wrapper registry and system catalog only when the selector is unspecified or invalid and preflight produces complete proposals. A valid existing selector prevents automatic contract creation and overwrite. This keeps the user's explicit contract choice authoritative while allowing safe onboarding for systems that have no usable selector.
- The staged proposal must be validated for registry schema, receiver/method consistency, allowed modes, sink values, deterministic names, and selector representation before formal classification. The refresh commit happens only after formal classification and reconciliation succeed. A separate explicit acceptance workflow remains available for incomplete/review-only proposals, deliberate contract edits, and registry-only changes.
- The registry and catalog update is a logical two-file atomic transaction. The implementation writes validated temporary files with one transaction identity, replaces both active files, and restores the previous bytes if the second replacement or post-commit validation fails. A failed transaction must not leave only one file updated.
- When a contract is accepted or edited without a source revision, the implementation reclassifies cached raw invocation facts instead of rescanning C#. The raw facts remain the durable input to reclassification; active contract semantics remain configuration rather than duplicated scan output.
- The optional `discover_external_wrappers` CLI becomes a thin read-only consumer of the shared reconciliation service. It may format a system-wide or root-scoped report, but it must not contain separate receiver matching, contract matching, or mode inference rules.
- Refresh-time wrapper reconciliation is deterministic and contains no LLM or runtime execution. It may report an Evidence Gap, but it cannot fill that gap with semantic retrieval, reflection, or guessed database objects.
- SQL refresh and SQL Execution Graph construction remain independent resources. A successful code refresh may return source-backed wrapper facts even when the SQL graph is missing or stale; graph-backed APIs retain their existing readiness and Evidence Status rules.
- Existing cache safety rules remain unchanged: program-scoped refresh requires a current cache for every scan root and fails closed on stale or missing cache. Wrapper reconciliation must not call the full-project scan as a fallback.
- Contract preflight is a full-system operation. A program-scoped refresh with no valid selector fails with a clear onboarding precondition and does not create a partial registry/catalog proposal.
- The contract is additive for existing consumers. Existing refresh counts, source-root fields, partial-refresh fields, and legacy relation aliases remain available while wrapper summary fields are introduced.

## Testing Decisions

- The highest testing seam is `CSharpAnalysisGateway`. Tests provide synthetic raw invocation facts, source availability, a synthetic contract registry, and a synthetic SP Catalog, then assert externally observable wrapper classification, Database Invocation evidence, provenance, and unresolved reasons. Tests do not assert Roslyn visitor order, regex internals, or private helper call sequences.
- Gateway fixtures cover a source-available wrapper, an unavailable external wrapper with an explicit contract, a unique receiver-type auto-selection, an unknown receiver type, multiple matching contracts, a matching receiver with a missing method, a receiver mismatch, and a dynamic command text.
- Gateway fixtures cover `SQLObject.CreateReader` with inline SELECT text and verify that it is not emitted as a stored-procedure invocation. They also cover `CreateTable` or `CreateDataSet` with explicit SP call-site mode and with non-SP mode, verifying that only the former can enter stored-procedure classification.
- Gateway tests verify that a literal stored-procedure candidate still requires a matching database-scoped SP Catalog entry, and that unresolved database attribution or ambiguous database names retain the existing `likely`/`unresolved` semantics.
- Gateway tests verify that contract selection source and candidate names are preserved as Impact Provenance and that contract-resolution status is not confused with `InvocationEvidence`.
- Refresh-service tests use the existing program-refresh seams to assert that full refresh invokes one scan and partial refresh invokes only selected-file analysis while returning wrapper summaries from the resulting cache. A spy or forbidden full-scan implementation must fail the test if partial reconciliation triggers a full analyzer.
- Refresh-service tests cover multi-root preflight. If any root is stale or missing, no selected-root update or reconciliation is allowed to proceed; the existing program-refresh error code and fail-closed behavior remain observable.
- Refresh-service tests cover unchanged files and removed files, verifying that their raw invocation facts and wrapper observations are retained or removed consistently with the selected-file cache replacement.
- API tests verify additive request/response behavior: the explicit wrapper selector is forwarded, catalog-resolved selection reaches the Impact boundary, and machine-readable wrapper status fields survive response-model serialization.
- Spec-rag client tests verify that refresh resolves `wrapper_contract` through the catalog when the caller leaves it empty, preserves an explicit override, and does not require a second discovery HTTP request.
- Reconciliation tests verify that changing only the contract registry reclassifies cached raw facts without invoking source scanning. A source content change must still require refresh before the new observation appears.
- Preflight tests verify valid selector reuse, missing selector onboarding, invalid string fallback, invalid array fallback, complete source/DLL evidence requirements, equivalent receiver reuse, conflict/name-collision rejection, string-versus-array selector serialization, and deterministic array ordering.
- Refresh transaction tests verify that formal classification uses the staged registry/catalog, that incomplete preflight leaves affected wrappers unresolved, and that a failure before or during the two-file commit preserves both active configuration files.
- Acceptance-workflow tests verify rejection of incomplete proposals, rejection of invalid modes or sinks, explicit application of a reviewed registry/catalog change, and cached reclassification without source rescanning. They also verify that existing `sqlobject` is reused rather than duplicated.
- Audit CLI tests verify that it consumes the shared classifier, reports stale/missing cache separately from wrapper unresolved status, and produces equivalent classification results to refresh for the same cache snapshot.
- One end-to-end smoke test may call the real StaticAnalyzerHost for typed receiver extraction and feed its raw result into the Gateway, following the existing Gateway test pattern. The majority of tests remain dependency-light and do not require a live Azure repository, SQL Server, or LLM.
- Test assertions focus on external behavior: evidence status, selected contract, unresolved reason, provenance, cache scope, response schema, and write/no-write behavior. Internal data structure layout is tested only where it is part of the documented machine-readable contract.

## Out of Scope

- Inferring `mode` or `sink` from a wrapper method name alone.
- Automatically adding a new method to an active external wrapper contract when a valid selector exists, or when source/DLL semantics are incomplete, conflicting, or ambiguous.
- Automatically changing a Git-tracked system catalog or contract registry before preflight, formal classification, and reconciliation have succeeded.
- Treating a partially valid selector array as a usable subset, or treating array order as contract precedence.
- Runtime execution tracing, reflection, decompiling DLLs, downloading unavailable wrapper source, or querying an external package registry.
- Cross-root or cross-repository source-wrapper resolution in the first implementation.
- Full Roslyn semantic compilation, runtime configuration evaluation, or proving values assembled dynamically outside the available source facts.
- Replacing the SQL Execution Graph, SQL cache refresh, database connection resolution, or SQL object discovery.
- Treating a successful source refresh, a selected wrapper contract, or an available scan cache as proof that a stored procedure, table, or DML target exists.
- Historical source snapshots or historical contract versions beyond the existing Git and artifact revision mechanisms.
- LLM-based wrapper classification, semantic similarity matching between unrelated contracts, or automatic user-facing impact conclusions from a review candidate.
- Removing the optional discovery CLI immediately; it remains a compatibility and audit entry point while the shared reconciliation service becomes the canonical implementation.

## Further Notes

- `wrapper_contract` is a selector for reusable semantics, not an inventory of every wrapper method observed in a system. The inventory belongs in raw scan observations and review output.
- `source_wrapper` and `external_wrapper` are different evidence paths. A local `SQLObject.cs` implementation can establish source-backed behavior; an unavailable DLL boundary cannot establish the same behavior without a matching contract.
- The existing `sqlobject` contract already covers `ExeProcNon`, `ExeProcRead`, `CreateReader`, `GetFirstValue`, `CreateTable`, and `CreateDataSet`. Its inline-SQL and call-site distinctions are part of this feature's acceptance criteria.
- The intended operational flow is one refresh followed by normal analysis. The audit CLI is for maintenance, registry changes, parser changes, cache-version changes, and explicit review, not a mandatory step in every update.
- The selected seam model follows the existing CSharpAnalysisGateway specification and the current `test_program_refresh` regression pattern. It deliberately avoids introducing a second formal evidence source in the discovery CLI.
- The intended refresh flow is `git pull -> one raw analysis -> source/DLL contract preflight -> staged registry/catalog -> formal source classification -> wrapper reconciliation -> proven/likely/unresolved output -> atomic commit`. A preflight proposal is configuration interpretation, not procedure proof; SP Catalog and connection-source evidence remain mandatory for `proven` stored-procedure results.
- `wrapper_contract` remains backward compatible as a string for one contract and uses an array only for multiple contracts. Empty and invalid values are diagnostic input to preflight, not a reason to silently select an unrelated registry entry. A successful preflight may replace an invalid selector; a failed workflow preserves it.
- This workspace does not currently expose an authenticated issue-tracker publishing integration or a usable GitHub CLI. This document therefore serves as the local Markdown tracker fallback and carries `ready-for-agent` triage metadata. Once tracker access is available, publish this document as one cross-repository architecture issue and apply the `ready-for-agent` label.