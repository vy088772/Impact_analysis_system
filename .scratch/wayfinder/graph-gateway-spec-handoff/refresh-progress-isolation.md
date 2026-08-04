# Refresh Progress Isolation

label: wayfinder:grilling
parent: Graph/Gateway Spec Handoff
status: open
assignee: unassigned
blocked_by: none

## Question

既然 SQL refresh progress/status 保留為獨立 operational add-on，它的 ownership、文件位置、測試責任與 Graph/Gateway migration 的 release gate 應如何分離，避免它既被誤當成核心 spec 又沒有人維護？
