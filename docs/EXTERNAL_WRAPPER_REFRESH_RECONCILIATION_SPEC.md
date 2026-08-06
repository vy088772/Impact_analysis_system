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

讓程式碼 refresh 在完成一次 C# scan 後，立即使用共用的 wrapper reconciliation service 對最新 raw Database Invocation 做分類，並將分類摘要、Evidence Status、contract provenance 與 review candidates 一起回傳。完整 refresh 與 program-scoped refresh 都沿用同一個 source-root source boundary；program-scoped refresh 仍只重建選定程式的 C# records，不因 wrapper reconciliation 而觸發整個 system 的 analyzer。

reconciliation 遵循下列順序：

1. source wrapper 若可在目前 scan root 的 source snapshot 中追蹤，保留為 source-backed evidence，不要求 external contract。
2. system 明確選定的 contract 優先使用；沒有明確 selector 時，才依 receiver type 尋找 `auto_select: true` 的 reusable contract。
3. receiver type 唯一對應既有 contract 時自動套用；零個候選或多個候選時保持 unresolved，並保留候選名稱作為 provenance。
4. contract method 的 `mode` 與 `sink` 必須來自 registry 或明確的 call-site evidence。`inline_sql` 不得被當成 stored procedure；`call_site` 只有在呼叫點明確選擇 stored-procedure mode 時才可作為 SP invocation。
5. 新 method 或新 receiver type 不會因名稱相似而自動加入 active contract。refresh 會產生 review candidate，接受後才可更新 contract registry；若需要變更 system selector，也必須透過明確的 acceptance workflow 更新 catalog。
6. contract 被接受或修改後，優先對已保存的 raw facts 重新分類，不重新執行 C# scan；只有 source 變更才需要新的 refresh。

`discover_external_wrappers` 保留為可選的 audit/report 入口，但改為重用同一套 reconciliation service。它不再是 refresh 後取得 wrapper classification 的必要第二階段，也不會擁有另一套 wrapper 語義規則。

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
21. As a system maintainer, I want normal refresh to avoid writing Git-tracked contract or catalog files, so that an ordinary source update cannot silently change analysis semantics.
22. As a system maintainer, I want an explicit acceptance workflow to apply a reviewed contract proposal, so that the registry and the system selector can be changed deliberately and audited.
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

## Implementation Decisions

- The `CSharpAnalysisGateway` remains the single high-level owner of wrapper classification and Evidence Status. It consumes raw StaticAnalyzerHost facts, source snapshot availability, the optional explicit contract, receiver-type registry candidates, and the database-scoped SP Catalog; it does not infer semantics from method names.
- `ProjectScanner` remains responsible for one source scan and for passing the complete current scan root as source context when analyzing selected C# files. Wrapper reconciliation consumes the resulting facts and does not invoke another C# analyzer pass.
- `refresh_source` orchestrates reconciliation after a successful full or program-scoped update. For a partial update, unchanged raw invocation facts remain in the cache and selected files replace only their own records; the response summarizes the logical cache state after the replacement.
- `RefreshRequest` accepts an optional wrapper-contract selector. The spec-rag refresh client resolves the selector from the system catalog when the caller has not supplied one, matching the existing behavior of analyze and path-evidence clients.
- `RefreshResponse` gains additive machine-readable wrapper summary fields. The response must expose observed wrapper groups, classification status, selected contract, selection source, receiver type, observed methods, candidate contract names, source provenance, and review reasons without requiring consumers to parse terminal text.
- Wrapper classification status is separate from `InvocationEvidence`. `source_wrapper`, `explicit_selected`, and `auto_selected` describe contract/source resolution; `proven`, `likely`, and `unresolved` describe the resulting Database Invocation evidence. One status must not be used as a substitute for the other.
- Source-wrapper resolution is bounded by the current scan root. In a multi-root system, each root is reconciled with its own source context. Cross-root source lookup, repository-wide dependency materialization, and DLL retrieval are not introduced by this feature.
- Contract selection precedence is explicit selector first, then unique `auto_select` receiver-type match. Zero candidates produce an unresolved contract result. Multiple candidates produce an ambiguous result and retain all candidate contract names as Impact Provenance.
- Contract receiver and method matching is normalized by the existing receiver and method identity rules. A matching receiver type alone is insufficient: the observed wrapper method must also exist in the selected contract, and the contract receiver declaration must match the observed receiver.
- `stored_procedure`, `inline_sql`, and `call_site` retain their existing meanings. An `inline_sql` method is excluded from stored-procedure invocation classification. A `call_site` method requires explicit call-site SP mode. The contract sink is descriptive of the downstream wrapper operation and is not itself a new wrapper method.
- A source-available wrapper is not converted into an external contract proposal merely because its name is absent from the registry. The source implementation is the stronger local evidence path; an external contract is for unavailable or opaque wrapper boundaries.
- An unavailable external wrapper with a new method or receiver type produces a review-only contract candidate. The candidate records observed identity and provenance, but leaves `mode`, `sink`, and active trust unresolved until a maintainer supplies and accepts the semantics.
- An observed method that is absent from an existing receiver contract produces an `unresolved_method` review item. It must not be appended automatically to the active contract, even when the receiver type uniquely selects that contract.
- The current `sqlobject` registry entry is reused when the receiver type is `SQLObject`. The feature must not create a second contract solely because a refresh observed another `SQLObject` call site.
- Normal refresh is read/write only for source repositories and scan cache. It does not modify the external wrapper registry or the system catalog. This prevents an ordinary source update from silently changing evidence semantics across repositories.
- A separate explicit acceptance workflow may apply a reviewed contract proposal and, when required, update the system catalog selector. Acceptance must validate registry schema, receiver/method consistency, allowed modes, sink values, and catalog selector existence before making active configuration changes. The workflow must produce a reviewable diff; it does not commit changes automatically.
- When a contract is accepted or edited without a source revision, the implementation reclassifies cached raw invocation facts instead of rescanning C#. The raw facts remain the durable input to reclassification; active contract semantics remain configuration rather than duplicated scan output.
- The optional `discover_external_wrappers` CLI becomes a thin read-only consumer of the shared reconciliation service. It may format a system-wide or root-scoped report, but it must not contain separate receiver matching, contract matching, or mode inference rules.
- Refresh-time wrapper reconciliation is deterministic and contains no LLM or runtime execution. It may report an Evidence Gap, but it cannot fill that gap with semantic retrieval, reflection, or guessed database objects.
- SQL refresh and SQL Execution Graph construction remain independent resources. A successful code refresh may return source-backed wrapper facts even when the SQL graph is missing or stale; graph-backed APIs retain their existing readiness and Evidence Status rules.
- Existing cache safety rules remain unchanged: program-scoped refresh requires a current cache for every scan root and fails closed on stale or missing cache. Wrapper reconciliation must not call the full-project scan as a fallback.
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
- Acceptance-workflow tests verify the default no-write behavior, rejection of incomplete proposals, rejection of invalid modes or sinks, and explicit application of a reviewed registry/catalog change. They also verify that existing `sqlobject` is reused rather than duplicated.
- Audit CLI tests verify that it consumes the shared classifier, reports stale/missing cache separately from wrapper unresolved status, and produces equivalent classification results to refresh for the same cache snapshot.
- One end-to-end smoke test may call the real StaticAnalyzerHost for typed receiver extraction and feed its raw result into the Gateway, following the existing Gateway test pattern. The majority of tests remain dependency-light and do not require a live Azure repository, SQL Server, or LLM.
- Test assertions focus on external behavior: evidence status, selected contract, unresolved reason, provenance, cache scope, response schema, and write/no-write behavior. Internal data structure layout is tested only where it is part of the documented machine-readable contract.

## Out of Scope

- Inferring `mode` or `sink` from a wrapper method name alone.
- Automatically adding a new method to an active external wrapper contract during an ordinary refresh.
- Automatically changing a Git-tracked system catalog or contract registry without an explicit acceptance action.
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
- This workspace does not currently expose an authenticated issue-tracker publishing integration or a usable GitHub CLI. This document therefore serves as the local Markdown tracker fallback and carries `ready-for-agent` triage metadata. Once tracker access is available, publish this document as one cross-repository architecture issue and apply the `ready-for-agent` label.