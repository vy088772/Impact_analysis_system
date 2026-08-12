---
status: ready-for-agent
triage: ready-for-agent
---

# Graph and Gateway Contract Handoff

## Problem Statement

The Graph/Gateway migration has working analysis components, but several boundaries still allow two interpretations of the same evidence. Legacy SQL dependency dictionaries can still be emitted by the SQL dump path, graph-dependent service operations can still reach compatibility behavior when a graph is absent, and a `likely` C# invocation can lose its uncertainty when it crosses into reverse lookup or path output. These ambiguities make it possible for a caller to receive an apparently confirmed relationship that the analyzers never proved.

The SQL Execution Graph and the CSharpAnalysisGateway are intended to be the authoritative sources for their respective relationship facts. Operators and downstream agents need a contract that states exactly when a relationship result is available, how uncertainty is carried, which migration data is review-only, and whether SQL refresh progress is part of the migration acceptance decision.

## Solution

Tighten the existing Graph/Gateway boundaries around four decisions:

1. Legacy `dependencies`, `write_dependencies`, `depends_on`, and `depended_by` data is transient comparison input only. It is not persisted as formal SQL relationship data and is never read by a formal graph, path, reverse-lookup, or flow consumer.
2. Every formal SQL relationship operation requires a resolved database and a valid SQL Execution Graph. Missing or invalid graph state fails fast. Source-only C# facts remain available when the caller does not request graph-backed analysis.
3. `proven`, `likely`, and `unresolved` evidence remains visible across service and API boundaries. `likely` records include their reason, database attribution state, caller, and source span, but only `proven` evidence can create a formal relationship.
4. SQL refresh progress and status remain a separately owned operational add-on. They are documented and tested independently and do not become a Graph/Gateway migration release gate.

This handoff clarifies the current modules and contracts; it does not introduce another parser or redesign the SQL Execution Graph, Path Selection, wrapper discovery, or source snapshot model.

## User Stories

1. As a system analyst, I want SQL relationship answers to come from one typed SQL Execution Graph, so that old untyped dependency data cannot change an impact result silently.
2. As a system analyst, I want a missing SQL graph to be reported explicitly, so that I know to refresh the database cache instead of receiving an incomplete relationship answer.
3. As a system analyst, I want source-only C# method Flow and invocation facts to remain available without a SQL graph, so that code inspection is still useful before SQL refresh.
4. As a system analyst, I want graph-backed Execution Paths to require the graph, so that a path never falls back to a legacy SP or dependency relation.
5. As a system analyst, I want SP reverse lookup to identify whether a match is proven or only a candidate, so that I do not treat a name-only match as a confirmed call.
6. As a system analyst, I want table reverse lookup and backward flow to use graph-backed SQL lineage, so that indirect writes and nested stored procedures are based on typed operations rather than text guesses.
7. As a system analyst, I want likely invocations to remain visible with an explanation, so that useful leads are not discarded while uncertainty is still honest.
8. As a system analyst, I want an unresolved invocation to retain its caller and source location, so that I can inspect dynamic SQL or an unavailable wrapper manually.
9. As a system analyst, I want an inferred database candidate to be distinguishable from a database resolved from the source connection, so that cross-database attribution is not overstated.
10. As a developer, I want one evidence contract from `CSharpAnalysisGateway` through reverse lookup and path output, so that each boundary preserves the same meaning for `proven`, `likely`, and `unresolved`.
11. As a developer, I want only proven invocations to create formal graph relationships, so that candidate evidence cannot affect confirmed path, table, or SP counts.
12. As a developer, I want legacy-versus-Gateway comparison to have one explicit seam, so that migration review does not become a second runtime relationship engine.
13. As a maintainer, I want comparison reports to show dropped, new, confidence-changed, and unresolved differences, so that migration review focuses on disagreement and not every call site.
14. As an operator, I want graph-less or stale SQL caches rejected by the same cache contract, so that every graph-backed API sees the same readiness state.
15. As an operator, I want SQL refresh progress to remain available while the refresh is running, so that a long database rebuild can be observed without changing analysis semantics.
16. As an operator, I want refresh progress failures and graph readiness failures to be distinguishable, so that operational troubleshooting does not become confused with evidence quality.
17. As a maintainer, I want refresh progress tests to run independently of Graph/Gateway acceptance tests, so that an operational regression does not block evidence-contract verification and vice versa.
18. As a release owner, I want the migration gate to evaluate graph correctness and Gateway evidence separately from progress polling, so that optional observability does not become an accidental dependency of formal analysis.
19. As a downstream RAG coordinator, I want stable machine-readable evidence and error fields, so that it can explain uncertainty or request a refresh without interpreting localized message text.
20. As a future implementation agent, I want the existing seams and out-of-scope areas named, so that this contract can be implemented without reopening the entire migration design.

## Implementation Decisions

- The SQL Execution Graph is the only persisted source of SQL relationship, lineage, reverse-lookup, and execution-flow evidence. Its typed nodes, typed relationships, branch context, DML order, and explicit unresolved dynamic-SQL nodes remain the formal model.
- SQL cache persistence contains the graph and the SQL object data required by existing graph-backed consumers, but does not persist legacy `dependencies`, `write_dependencies`, `depends_on`, or `depended_by` relationship dictionaries. The cache version and validation rules continue to reject graph-less or stale payloads.
- If the SQL extraction path still computes legacy-shaped data during migration, that data lives only long enough to feed the migration comparison seam. It is not added to the persisted cache, `ProjectScanResult` formal relation fields, graph query inputs, path builders, reverse lookup results, or flow-chain results.
- `compare_legacy_gateway` and its scan-level adapter are the only comparison seams. Their output is a review-oriented report containing stable identities, caller and source information, legacy and Gateway records, evidence, reasons, source kind, and the categories `dropped`, `new`, `confidence_changed`, and `unresolved`. A saved Markdown or JSON report is a migration review artifact, not a cache and not a relationship source.
- Formal consumers must not implement a legacy fallback. This includes Execution Path construction and evidence expansion, SP reverse lookup, graph-backed table reverse lookup, forward and backward flow reconstruction, dependency fetches, and any other operation that claims a SQL relationship.
- A graph-dependent operation requires both a non-empty resolved database key and a valid cache whose SQL Execution Graph is present, version-compatible, and scoped to that database. The service checks this precondition before returning formal relationship data.
- The service uses one typed graph-required failure for missing, stale, invalid, or database-mismatched graph state. The API exposes missing request identity as HTTP 400 and unavailable graph state as HTTP 409 with a machine-readable code such as `sql_execution_graph_required`, the requested database, and the action to rebuild the cache. Localized messages are explanatory only.
- `cache_only` may still report that a source scan is unavailable, but it must not conceal a missing graph once a formal relationship operation has begun. A skipped source scan and an unavailable SQL graph are different states.
- Source-only operations may run without a SQL graph. They include C# source scanning, method Flow, raw Roslyn or StaticAnalyzerHost facts, source spans, and direct inline-SQL facts. They must not label a database relationship as proven when the graph prerequisite is absent.
- `/analyze` may return source-only C# facts when no database-backed analysis is requested. Its graph-backed fields are empty or explicitly marked unavailable in that mode. If a database is supplied and the request asks for Execution Paths or other graph-backed enrichment, a missing graph is a failed precondition rather than a silent compatibility result.
- `/path_evidence`, `/find_by_sp`, formal `/find_by_table`, forward or backward `/flow_chain`, and other graph-backed relationship operations require the same graph precondition. Their existing domain-specific not-found behavior remains distinct from graph readiness errors.
- `CSharpAnalysisGateway` remains the single C# evidence-rating boundary. `DbInvocation` and every downstream response derived from it preserve the evidence level, machine-readable reason, caller identity, source span, branch context, procedure identity, and source snapshot identity when available.
- Database attribution has two separate meanings. `database` is populated only from a resolved connection or other trusted source. A database inferred from catalog uniqueness is not a resolved attribution; it is exposed through `database_candidates` or an equivalent explicit candidate field and remains marked `likely`.
- `proven` means that the invocation target and its database scope are supported by the applicable catalog and sink rules. `likely` means that a useful candidate exists but a required attribution or sink fact is incomplete. `unresolved` means that the target or attribution cannot be established. Reason values are stable machine-readable codes such as `unique_across_catalogs`, `not_in_resolved_catalog`, `dynamic_command_text`, `wrapper_source_unavailable`, or `ambiguous_cross_database`.
- `likely` and `unresolved` records may remain visible as candidates or diagnostics in Gateway, SP reverse lookup, table or flow responses, path summaries, and migration reports. Every returned record must carry its evidence and reason; existing compact fields such as program and file remain additive-compatible.
- Only `proven` records may create formal `calls`, `reads`, `writes`, access matches, confirmed SP matches, or confirmed Execution Paths. A candidate record must never increment a confirmed relationship count or be rendered as a confirmed relation merely because it has a unique catalog candidate.
- When a response mixes formal matches and candidates, the response must make the distinction machine-readable. At minimum, `SPMatchProgram`, table matches, path records, and flow entries expose evidence, reason, database attribution, and caller/source information. Existing program/file and path identity fields remain available for clients that already use them.
- `likely` path candidates may be retained for review if the existing response shape requires them, but they are risk-bearing candidates rather than formal paths. They must carry a visible likely indicator and must not become the source of downstream table or write relationships.
- The Gateway, SQL Execution Graph, and StaticAnalyzerHost retain their existing ownership boundaries. This contract changes how their outputs are admitted and represented at service boundaries; it does not add a parser or move analysis responsibility between them.
- `refresh_progress` owns the bounded, thread-safe in-memory job state and the refresh status API. It reports operational stages, counts, completion, and failure for SQL refresh, but it does not decide cache validity, evidence level, relationship provenance, or release acceptance.
- The refresh status endpoint remains an independent operational interface. Its job lifecycle may be tested and documented alongside refresh operations, while Graph/Gateway acceptance is evaluated from rebuilt cache contents and deterministic service results.
- The Graph/Gateway migration gate requires representative comparison fixtures to show that existing detections are either `proven` Gateway records or explicit `unresolved` records with reasons, that no inline SQL or ordinary method becomes falsely `proven`, and that no formal consumer reads legacy comparison data. Progress polling is not a condition of this gate.

## Testing Decisions

- Tests assert externally observable contracts: returned evidence, reason, database attribution, source identity, graph-required failures, persisted cache shape, formal relationship counts, comparison categories, and refresh job states. They do not assert private visitor traversal, regex ordering, or incidental helper calls.
- The primary service-level seam for graph availability accepts a synthetic cache state and exercises graph-dependent operations through their public service entry points. Tests cover a valid graph, a missing graph, a graph-less legacy payload, a stale cache version, and a database identity mismatch.
- Graphless tests assert fail-fast behavior for path creation, path evidence, SP reverse lookup, formal table reverse lookup, forward flow, backward flow, and other formal relationship consumers. They also assert that legacy dependency dictionaries cannot produce a result when the graph is absent.
- Source-only tests assert that C# scanning, Method Flow, raw invocation facts, source spans, and direct inline-SQL facts remain callable without a SQL graph. They assert that these responses do not claim a proven SQL relationship.
- API boundary tests assert that missing database identity is a client error, unavailable graph state is a graph-readiness conflict with a stable machine-readable code, and a genuine path-not-found response is not confused with graph absence.
- `CSharpAnalysisGateway` remains the highest evidence-rating seam. Synthetic raw invocation records and a synthetic database-scoped SP Catalog cover direct SqlClient, source-available wrappers, Dapper, Entity Framework, branch-assigned names, inline SQL, dynamic command text, unavailable wrapper source, unique unknown-database candidates, and ambiguous cross-database names.
- Gateway tests assert that a `likely` record keeps its reason and candidate database information without pretending that the database source was resolved. They also assert that `proven` requires the applicable catalog and sink evidence.
- Response-contract tests pass Gateway records through SP reverse lookup, table or flow output, and path construction. They assert that evidence, reason, database attribution, caller, and source span survive every boundary and that only `proven` records enter formal relationship collections or counts.
- `compare_legacy_gateway` remains the migration comparison seam. Tests assert deterministic `dropped`, `new`, `confidence_changed`, and `unresolved` categories, preservation of legacy and Gateway evidence fields, and stable sorting. A legacy-only record must not appear in graph queries or formal lookup results.
- Cache tests assert that a refreshed payload contains the SQL Execution Graph as the formal relationship model, that legacy relationship dictionaries are not persisted, and that graph-less or stale payloads are rejected rather than read through a fallback.
- Refresh progress tests remain separate and cover job creation, stage updates, completion, failure, unknown job IDs, and bounded cleanup. API tests cover the status endpoint independently from graph and evidence tests.
- The existing direct-script and pytest-compatible test patterns are prior art. Fast deterministic fixtures are preferred; a real analyzer-host or rebuilt-cache smoke test is added only where it verifies the process contract rather than a private implementation detail.
- Acceptance is complete only when the formal consumers have no reachable legacy fallback, candidate evidence is visibly non-confirmed at every boundary, and progress tests can be removed from the migration test command without weakening Graph/Gateway acceptance.

## Out of Scope

- Rebuilding the SQL AST model, changing SQL lineage semantics, or redesigning Path Selection.
- Improving wrapper discovery, adding new Roslyn semantic analysis, changing StaticAnalyzerHost commands, or changing source snapshot storage.
- Runtime tracing, reflection-based proof, execution-plan analysis, or guessing dynamic SQL targets.
- A full legacy detector cutover across every representative system. This spec defines the comparison and admission contract needed before that cutover.
- Automatic migration of old SQL caches or fallback reads from legacy dependency dictionaries.
- Removing every historical mention of legacy fields from older operational manuals in the same change. Documentation needed for the new contract may be updated, but unrelated manual cleanup is separate.
- Making refresh progress, polling frequency, job retention, SSE, WebSocket streaming, or terminal rendering part of Graph/Gateway evidence semantics or the migration release gate.
- Adding AI inference to the Impact Analysis service or changing downstream RAG orchestration beyond consuming the explicit contract fields.
- Reworking cache-only source-scan skip behavior except where it must not hide a graph-required failure for a formal relationship request.

## Further Notes

- This specification refines and connects the existing CSharpAnalysisGateway, SQL Execution Graph, StaticAnalyzerHost, migration report, and refresh progress decisions. It is intentionally narrower than a full migration plan.
- The implementation should preserve existing public fields where possible and add evidence metadata rather than forcing downstream clients to reconstruct confidence from localized messages.
- The migration report is useful for human review and cutover evidence, but it is never a competing source of truth. The graph and Gateway outputs remain the only formal sources.
- A completed SQL refresh should make the rebuilt graph available for subsequent formal requests. Progress completion is an operational signal; formal readiness is verified by cache validation at the service boundary.
- This local Markdown document is the publishable tracker fallback for the current workspace and is marked `ready-for-agent` for implementation handoff.
