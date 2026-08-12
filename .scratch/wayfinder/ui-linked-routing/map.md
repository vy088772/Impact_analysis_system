---
labels: wayfinder:map
status: ready-for-agent
triage: ready-for-agent
tracker: local-markdown
---

# UI-linked Impact Analysis Routing

## Destination

把 UI interaction、specification、C# method Flow、SQL Execution Graph、Execution Path 與 final Path Evidence 收斂成一份可交接的跨 repository routing spec，供後續 implementation 使用。

## Domain

跨 `llamaindex-spec-rag` 與 `Impact_analysis_system` 的 UI-linked impact analysis。Canonical scenario 是 PUR/TTPUR 的 query 與 row delete，特別驗證兩個 UI entrance 共用 `BindData()` 時仍保留不同 interaction 與 path identity。

## Published Spec

- [Impact Analysis Routing and UI-linked Evidence](../../../../llamaindex-spec-rag/IMPACT_ANALYSIS_ROUTING_SPEC.md) - ready-for-agent

## Resolved Decisions

- RAG、exact SP／table lookup、specification lookup 與 UI discovery 並行收集後合併。
- Agent 輸出結構化 `DiscoveryScope`；deterministic layer 建立 bounded candidates，LLM 只選擇或有限展開 valid `path_id`。
- `interaction_id` 與 `path_id` 分離；UI handler 以 handler-scoped mapping 對接 Execution Path。
- frontend interaction 沒有可證明 backend mapping 時保留 UI-only／`unresolved` evidence，不允許 LLM 猜測 C#／SQL。
- selected path 送完整 source-backed evidence；其他候選只送 compact summary、rejection reason 與 unresolved signals。
- `Impact_analysis_system` 產 deterministic evidence；`llamaindex-spec-rag` 負責 routing、LLM selection 與 final synthesis。
- `select_relevant()` 與 `get_flow_chains()` 暫不退役，直到新 UI-to-path contract 與 PUR regression tests 完成。

## Implementation Handoff

- `WF-01`：定義 DiscoveryScope、UI Interaction Evidence、candidate、status 與 provenance contract。
- `WF-02`：建立 UI anchor 到 handler-scoped Execution Path 的 deterministic join。
- `WF-03`：決定 `/flow_chain`、`/analyze`、`/path_evidence` 的 additive reuse 或 join endpoint。
- `WF-04`：把 structured DiscoveryScope 接入 RAG／exact／UI discovery orchestration。
- `WF-05`：把 UI-linked candidates 接入既有 Path Selection Coordinator。
- `WF-06`：組裝 selected UI、spec、C#、SQL evidence 與 alternative summaries。
- `WF-07`：建立 PUR/TTPUR query、row delete、shared `BindData()` 與 UI-only contract tests。
- `WF-08`：定義既有 `get_flow_chains()` fallback 與遷移策略。
- `WF-09`：定義 cache snapshot、source hash、path identity 與 refresh operations contract。

## Tracker Status

目前 workspace 沒有可用的 authenticated issue-tracker publish integration，因此此 map 與 linked spec 是 local Markdown tracker fallback，並套用 `ready-for-agent` triage metadata。取得 tracker access 後，應將 linked spec 發布為一個跨 repository architecture issue，並套用 `ready-for-agent` label。
