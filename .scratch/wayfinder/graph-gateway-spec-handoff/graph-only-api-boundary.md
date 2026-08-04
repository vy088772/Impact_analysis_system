# Graph-Only API Boundary

label: wayfinder:grilling
parent: Graph/Gateway Spec Handoff
status: open
assignee: unassigned
blocked_by: none

## Question

哪些 endpoint 與 service operation 必須要求 resolved database 及 `sql_execution_graph` 並 fail fast？純 C# facts、unresolved candidate 與 refresh 前的 diagnostics 在 graph 缺失時各自允許回傳到什麼程度？
