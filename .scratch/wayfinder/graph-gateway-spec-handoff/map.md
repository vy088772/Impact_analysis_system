# Graph/Gateway Spec Handoff

labels: wayfinder:map
status: ready-for-agent
tracker: local-markdown

spec: ../../../docs/GRAPH_GATEWAY_CONTRACT_SPEC.md

## Destination

把本次 code review 暴露的 Graph/Gateway 契約決策收斂成可交接的路線：實作者能依三份 spec 修正或保留現況，且不再需要猜測 legacy data、graph availability、evidence 分級或 refresh progress 的邊界。

## Notes

- Domain: `Impact_analysis_system` 的 C# Analysis Gateway、SQL Execution Graph 與 migration contract。
- Skills for ticket sessions: `grilling`, `domain-modeling`；需要檢查實作時沿用 `code-review` 的兩軸觀點。
- Scope: 只處理本次 review findings，不重新規劃完整 end-to-end migration。
- Charting direction selected by the user: legacy data 只作 transient comparison；graph-dependent API 沒有 graph 時 fail fast；`likely` 對外保留且明示 evidence；refresh progress 保留為獨立 operational add-on。
- Local tracker fallback：workspace 沒有 issue-tracker 文件，因此以此目錄的 Markdown 檔案作為 map 與 child issues。

## Published Spec

- [Graph and Gateway Contract Handoff](../../../docs/GRAPH_GATEWAY_CONTRACT_SPEC.md) - ready-for-agent

## Resolved Decisions

<!-- Closed child tickets are appended here after resolution. Open tickets are discovered from this directory. -->

## Handoff Summary

- [legacy-comparison-boundary.md](legacy-comparison-boundary.md): legacy dependency structures are transient comparison input only; `compare_legacy_gateway` is the review seam and its output is never formal relationship data.
- [graph-only-api-boundary.md](graph-only-api-boundary.md): graph-backed path, reverse lookup, table, and flow operations require a valid database-scoped SQL Execution Graph and fail fast; source-only C# facts remain available independently.
- [likely-evidence-contract.md](likely-evidence-contract.md): `likely` remains visible with evidence, reason, explicit database attribution state, caller, and source fields; only `proven` creates formal relationships.
- [refresh-progress-isolation.md](refresh-progress-isolation.md): refresh progress/status remains separately owned, documented, and tested as an operational add-on outside the Graph/Gateway migration gate.

## Out of scope

- 直接修改 production implementation、補測試或執行完整 cutover；本 map 只產生決策，完成後交給 implementation planning。
- 重新設計未被本次 review 觸及的 Path Selection、SQL lineage、wrapper discovery 或 source snapshot 功能。
- 把 refresh progress 變成 Graph/Gateway migration 的必要 contract；它保留，但作為獨立 operational add-on。
