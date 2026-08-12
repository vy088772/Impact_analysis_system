# Legacy Comparison Boundary

label: wayfinder:grilling
parent: Graph/Gateway Spec Handoff
status: open
assignee: unassigned
blocked_by: none

## Question

在 legacy `dependencies` / `write_dependencies` 只作 transient comparison 的前提下，comparison 應由哪個 seam 觸發、保留哪些差異欄位、如何保證它不寫入或被正式 Graph/Path/lookup API 讀取？
