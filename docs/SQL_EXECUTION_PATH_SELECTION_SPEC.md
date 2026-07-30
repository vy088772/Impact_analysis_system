---
status: ready-for-agent
triage: ready-for-agent
---

# SQL Execution Path Selection

## Problem Statement

目前系統以 `dependencies`、`depends_on`、`depended_by` 表示 SQL 關係，但這些資料混合 SP、View、Function 與 Table，無法說明 DML 的執行順序、分支條件、寫入欄位或實際的 C# 入口。分析流程因此容易把大量完整 SP 與 C# 原始碼送給 LLM，造成 token 膨脹、雜訊與錯誤路徑選擇。

使用者需要先看到精簡且可辨識的 SQL 執行流程，讓 LLM 選擇最相關的 `path_id`，再只提供該路徑的精確證據；若第一條路徑不夠，LLM 應可有限次地要求擴展相鄰路徑。

## Solution

建立以 SQL AST 為唯一真實來源的 `sql_execution_graph`，取代現有 SQL cache 的 `dependencies` 與 `write_dependencies`。圖譜將 SQL module、DML、Table、View、Function、SP 呼叫及無法靜態解析的 dynamic SQL 都表示為明確型別的節點與關係。

在程式與系統範圍已確定後，模式 2 與模式 3 共用一個 Path Selection Loop：先提供精簡 Execution Path 摘要，LLM 只能回傳 `answer`、`expand` 或 `clarify`。選中的路徑才展開 C# 方法、SP、DML、View 與 UDF 定義；展開最多三輪，並以程式驗證回應與路徑 ID。

## User Stories

1. As a system analyst, I want to see compact SQL execution paths before source code, so that I can identify the relevant business flow quickly.
2. As a system analyst, I want each path to start at a C# entry method and end at one DML operation, so that I can trace a concrete effect.
3. As a system analyst, I want each path to show branch conditions, so that I can distinguish mutually exclusive business outcomes.
4. As a system analyst, I want each path to identify written tables and columns, so that I can assess data-change impact precisely.
5. As a system analyst, I want each path to identify read tables, so that I can understand prerequisites and source data.
6. As a system analyst, I want explicit nested SP calls in a path, so that indirect database effects are not hidden.
7. As a system analyst, I want View and UDF references to have distinct types, so that read-only modules are not confused with stored procedures or tables.
8. As a system analyst, I want dynamic SQL to be explicitly unresolved when static analysis cannot prove its target, so that the system never fabricates an impact.
9. As an LLM router, I want stable `path_id` values in the summary, so that I can request exact evidence without naming code heuristically.
10. As an LLM router, I want to return `expand`, so that I can obtain adjacent evidence when the first selected path is insufficient.
11. As an LLM router, I want to return `clarify`, so that users can resolve business ambiguity instead of receiving an unsupported answer.
12. As an LLM router, I want invalid or duplicate path selections to be handled deterministically, so that control flow remains bounded.
13. As an end user, I want the final answer to be grounded only in selected path evidence, so that irrelevant code does not distort the answer.
14. As an end user, I want the final answer to state unresolved dynamic-SQL or unexpanded-path uncertainty, so that I can assess confidence.
15. As an operator, I want SQL cache refresh to rebuild the execution graph, so that analysis always uses one current schema.
16. As an operator, I want old SQL caches to be rejected after the graph migration, so that legacy dependency data cannot silently affect answers.
17. As a developer, I want deterministic graph APIs separate from LLM orchestration, so that SQL analysis remains reproducible and testable.
18. As a developer, I want deterministic mode 2 and agentic mode 3 to share one path-selection seam, so that they cannot drift in evidence-selection behavior.
19. As a developer, I want table reverse lookup and backward-flow analysis to use the new graph, so that removal of legacy dependencies does not lose impact-analysis capability.
20. As a maintainer, I want fixtures for SQL branches, nested calls, CTEs, temp tables, Views, UDFs, and dynamic SQL, so that future analyzer changes remain safe.
21. As a maintainer, I want one CSharpAnalysisGateway to produce C# Flow and database invocations, so that wrapper detection does not become a second long-lived parser.
22. As a developer, I want direct SqlClient and source-available wrappers validated against an SP Catalog, so that custom database APIs are detected without manually maintaining every method name.
23. As a developer, I want ambiguous cross-database SP names to remain unresolved, so that an invocation is never attributed to the wrong database.
24. As an end user, I want a selected path to retrieve complete C# and SQL source from its scan snapshot, so that the final answer can cite the actual implementation.

## Implementation Decisions

- The SQL Execution Graph is the only persisted source for SQL relationship and execution-flow evidence. Legacy `dependencies`, `depends_on`, `depended_by`, and `write_dependencies` are removed.
- Database connectivity, SQL object retrieval, cache persistence, and schema retrieval remain in the existing Python-side SQL cache flow.
- Roslyn and ScriptDom source projects are packaged behind one versioned StaticAnalyzerHost with separate C# and SQL commands. Python integrates one process contract; generated DLL and build directories are deployment artifacts rather than committed source inputs.
- ScriptDom AST analysis becomes responsible for structured DML operations, ordering, branch conditions, CTE expansion, temp-table lineage, SP calls, View/UDF use, and dynamic-SQL markers.
- Graph nodes are typed as `stored_procedure`, `view`, `function`, `table`, `dml_operation`, or `unresolved_dynamic_sql`.
- Graph edges are typed as `calls`, `reads`, `writes`, `contains`, `uses`, or `unresolved`; each edge retains source location, branch context, and an evidence state.
- An Execution Path is a route from a C# entry method through zero or more stored procedures to one terminal DML operation. Multiple DML outcomes or branches produce distinct path IDs.
- The compact path summary includes only path ID, entry/method chain, SP chain, branch conditions, write effect, read tables, and risk flags. It excludes raw SQL, complete SP definitions, and C# source.
- Each program returns at most 20 summary paths, ordered by write effect, question-keyword relevance, then entry relevance.
- Selected Path Evidence contains only the entry and method chain, SPs on the selected chain, the selected DML nodes with full predicates, and directly used View/UDF definitions. Sibling branches and unrelated code require explicit expansion.
- The highest shared testable seam is a Path Selection Coordinator between program discovery and final answer generation. It accepts compact graph summaries, validates LLM decisions, retrieves selected evidence, and returns final evidence or a clarification request.
- Both deterministic mode 2 and agentic mode 3 invoke the same Path Selection Coordinator after system/program discovery. The existing agent continues to own discovery scope, not SQL path expansion.
- The LLM control contract is JSON with `action`, `path_ids`, `reason`, and `question`. Valid actions are `answer`, `expand`, and `clarify`.
- Repeated path IDs do not retrieve duplicate evidence and do not consume an iteration. Invalid output receives one deterministic correction response; a second invalid response ends in `clarify`.
- The coordinator permits at most three expansions. On the limit, the answer must separate verified facts from unresolved uncertainty.
- Dynamic SQL is represented as an explicit unresolved node. Expanding it returns only its construction and execution evidence; no target table, SP, or DML is inferred.
- The SQL cache version is incremented. Caches without a SQL Execution Graph are invalid and must be rebuilt using the SQL refresh command.
- `find_by_table` and backward flow reconstruction are migrated to graph queries and continue to resolve C# entry points from graph-backed SQL evidence.
- A CSharpAnalysisGateway is the single long-term producer of C# method Flow and evidence-rated database invocations. It combines Roslyn syntax analysis, ASPX event bindings, and database-scoped SP Catalog matching.
- Invocation evidence is `proven`, `likely`, or `unresolved`. Direct `SqlCommand` with `CommandType.StoredProcedure`, and source-available wrappers that reach the same sink with SP mode, are `proven` when the target exists in the resolved Catalog.
- Unknown database source may match a Catalog only when the SP name is globally unique; same-name candidates across multiple databases remain `unresolved`.
- Scan storage persists one complete source snapshot per file for the current scan root. Analysis records reference snapshot identity and source spans; path records do not duplicate C# source text. SQL storage continues to persist complete SQL module definitions.
- Only the latest source snapshot is retained. Refresh replaces it; Git is the source of historical comparison.
- The legacy regex detector is comparison-only during migration. It does not remain a second formal relationship source after the cutover gate passes.

## Testing Decisions

- Tests verify externally visible graph records, compact summaries, selected evidence, reverse lookups, and coordinator outcomes. They do not assert private visitor traversal or implementation-specific intermediate structures.
- Use a small fixed ScriptDom fixture suite as the primary analyzer seam. It must cover direct `UPDATE`, `INSERT ... SELECT`, `DELETE`, `IF/ELSE`, nested SP calls, CTEs, temp tables, Views, UDFs, and dynamic SQL.
- Assert that branch-specific DML produces distinct path IDs and correct branch predicates.
- Assert that dynamic SQL creates unresolved evidence and never creates guessed table or SP nodes.
- Exercise the Path Selection Coordinator with valid `answer`, valid `expand`, valid `clarify`, duplicate IDs, invalid IDs, and the three-expansion boundary.
- Verify exact Path Evidence does not include sibling branches or unrelated source unless an explicit expansion requests it.
- Add graph-backed behavior tests for table write lookup and backward reconstruction to C# entry methods.
- Run a real refreshed SQL cache smoke test to confirm persisted graph data supports the service boundary after cache reconstruction.
- Existing static-analysis and service-level test patterns remain the prior art; new tests should prefer their highest externally callable service or coordinator boundary.
- Compare legacy and Gateway invocations for representative systems and review only emitted differences. Require fixtures for direct SqlClient, source-available wrapper, variable branch, Dapper, EF, inline SQL, dynamic SQL, and ambiguous cross-database names before cutover.

## Out of Scope

- Runtime execution tracing, SQL Server query-plan analysis, and proving dynamic SQL targets at runtime.
- LLM inference inside the Impact Analysis service.
- Automatic migration or fallback reading of legacy dependency cache data.
- Indefinite operation of the legacy regex SP detector alongside the CSharpAnalysisGateway.
- Automatic inclusion of FK-expanded tables, sibling branches, or unrelated source code in selected evidence.
- Changes to system discovery rules beyond routing both existing modes through the shared path-selection phase.

## Further Notes

- This specification supersedes the legacy SQL dependency model described by the SQL cache implementation.
- Deployment requires restarting the Impact service before SQL cache refresh so the rebuilt cache uses the new analyzer.
- The available workspace does not expose an issue-tracker integration. This local specification is the publishable source until an issue tracker is connected; it is marked `ready-for-agent` for handoff.