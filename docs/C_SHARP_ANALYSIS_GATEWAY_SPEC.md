---
status: ready-for-agent
triage: ready-for-agent
---

# C# Analysis Gateway And SP Catalog Validation

## Problem Statement

The current C# static analysis can identify some stored procedure calls, but its primary wrapper-method detection relies on a manually maintained allowlist. Real ASP.NET applications access databases through direct SqlClient calls, custom wrappers, variable-assigned procedure names, Dapper, Entity Framework, and APIs whose implementations may live in another project or DLL. The current results therefore know a feature or method name but do not consistently establish what data access action it performs, under which branch, or against which database.

Maintaining every wrapper method manually is not feasible for a large codebase. At the same time, broad heuristics must not misclassify inline SQL, ordinary methods, or cross-database same-name procedures as confirmed stored procedure calls.

## Solution

Introduce one CSharpAnalysisGateway that produces source-derived Method Flow and evidence-rated Database Invocations. The gateway combines Roslyn Flow extraction, ASPX event bindings, database-source resolution, and a database-scoped SP Catalog assembled from refreshed SQL cache data.

The gateway automatically recognizes direct SqlClient use and source-available wrappers by following them to ADO.NET execution sinks. It validates literal or branch-assigned candidate procedure names against the resolved SP Catalog, retains complete source snapshots for later evidence expansion, and marks unresolved evidence explicitly rather than guessing. The existing regex detector is comparison-only during migration and is removed as a formal source after the cutover gate passes.

## User Stories

1. As a system analyst, I want C# method Flow to retain branch and call order, so that I can understand what a feature does rather than only which feature was found.
2. As a system analyst, I want ASPX event bindings to identify C# entry methods, so that a UI action can be traced into its database effects.
3. As a system analyst, I want a direct SqlClient stored procedure call to be recognized automatically, so that I do not need to register each call pattern manually.
4. As a system analyst, I want source-available database wrappers to be recognized automatically, so that custom APIs such as `CreateTable` and `ExeProcRead` do not require a permanent allowlist.
5. As a system analyst, I want wrapper calls to distinguish SP mode from plain SQL mode, so that `CreateTable("SELECT ...")` is not confused with a stored procedure invocation.
6. As a system analyst, I want reusable receiver-typed contracts for external wrappers, so that a method such as `ExeProcNon` is trusted only when one declared contract identifies its semantics.
7. As a system analyst, I want candidate procedure names checked against an SP Catalog for the correct database, so that a name-shaped string is not accepted without evidence.
8. As a system analyst, I want branch-assigned procedure names to produce separate candidate invocations, so that default and conditional business paths are both visible.
9. As a system analyst, I want Dapper and Entity Framework procedure patterns handled by the same invocation model, so that data-access libraries do not fragment the analysis.
10. As a system analyst, I want each Database Invocation to expose its evidence level, so that I can distinguish proven facts from candidates and unknowns.
11. As a system analyst, I want unresolved dynamic SQL to remain explicit, so that no table or stored procedure is fabricated by static analysis.
12. As a system analyst, I want same-name stored procedures in different databases to remain unresolved when connection identity is unknown, so that analysis never attributes an action to the wrong database.
13. As a developer, I want one gateway to own Method Flow and Database Invocation production, so that Roslyn, regex, wrapper rules, and catalog matching do not create competing sources of truth.
14. As a developer, I want the gateway output to integrate with the SQL Execution Graph, so that C# entry methods can form Execution Paths to terminal DML operations.
15. As a developer, I want Database Invocation records to reference complete source snapshots by identity and span, so that a selected Execution Path can retrieve actual source code.
16. As a developer, I want external wrapper boundaries omitted from local source materialization, so that path evidence contains real caller methods without fabricated DLL source.
17. As a developer, I want source code stored once per file snapshot, so that many paths can share evidence without duplicating large C# bodies.
18. As an operator, I want source snapshots to retain only the latest scan state, so that storage remains bounded and Git remains the history system.
19. As an operator, I want C# scan refresh to regenerate Flow and invocation evidence, so that cached analysis follows current source code.
20. As a maintainer, I want a legacy-versus-gateway difference report during migration, so that review focuses on real disagreement rather than every call site.
21. As a maintainer, I want representative systems to demonstrate parity before legacy detection is removed, so that migration does not silently regress working results.
22. As a final-answer LLM, I want selected Execution Paths to expose only the related C# source spans, so that reasoning uses grounded evidence without unrelated code.

## Implementation Decisions

- CSharpAnalysisGateway is the highest and only new analysis seam. It accepts current C# source snapshots, ASPX event bindings, and a database-scoped SP Catalog; it returns Method Flow and Database Invocation records.
- Roslyn and ScriptDom are source modules behind one versioned StaticAnalyzerHost. The Python service calls one process contract with separate C# and SQL commands and fails clearly when the host, .NET runtime, or contract version is unavailable.
- Roslyn syntax analysis supplies method declarations, invocation order, control-flow branches, assignments required for finite procedure-name resolution, and source spans. It does not need to build a full project Compilation to provide these facts.
- ASPX event binding remains a source of entry-method evidence and is joined with Roslyn method identities.
- The SP Catalog is generated from the refreshed SQL cache and uses normalized database, schema, and procedure identity.
- A direct SqlCommand invocation is `proven` when it explicitly sets `CommandType.StoredProcedure` and its procedure exists in the resolved database Catalog.
- A source-available wrapper invocation is `proven` when its reachable implementation establishes an ADO.NET stored-procedure sink and its call-site mode selects stored-procedure execution.
- An external wrapper invocation may use an explicitly selected contract, or a registry contract resolved by a genuine Receiver Implementation Binding (a receiver traced through construction and relevant assignments to a concrete implementation identity and assembly identity). A bare receiver type name alone, or a registry `auto_select` flag, cannot select a contract -- auto-select and receiver-name inference are removed from the contract domain and runtime path. In both cases the wrapper method and receiver type must match the contract. The contract supplies sink semantics; the literal procedure name must still match the resolved database-scoped SP Catalog.
- Implementation-binding selection additionally requires the matching contract to carry no onboarding-workflow `status`/`lifecycle` (i.e. it is a reviewed, statically-authored registry entry, not a legacy/accepted contract from the acceptance workflow, which always requires a fully explicit selector). Zero matches remain unresolved; multiple matches remain unresolved with the candidate contract names retained as provenance.
- A contract method with `inline_sql` mode, such as `SQLObject.CreateReader` or `GetFirstValue`, is omitted from stored procedure invocations. A `call_site` method, such as `CreateTable` or `CreateDataSet`, is trusted only when the call site explicitly selects stored-procedure mode.
- `ExecuteReader` in a contract is a sink label for a wrapper's downstream ADO.NET operation, not an implicitly recognized wrapper method. A library that genuinely exposes an external `ExecuteReader` helper must declare that method explicitly in the registry contract.
- A literal candidate that matches the resolved Catalog but lacks a complete sink chain is `likely`.
- Dynamic SQL, unresolved variables, unavailable wrapper source without a matching contract, and ambiguous cross-database names are `unresolved`. The gateway preserves source evidence but does not invent a target.
- Database-source resolution scopes Catalog matching. If no source can be resolved, a candidate is accepted only when unique across known Catalogs; same-name results in multiple databases stay unresolved.
- A branch assigning multiple finite procedure names creates separate Database Invocations with the relevant branch context.
- Complete C# source is stored once per current file snapshot, addressed by a content identity. Methods and invocations retain start/end source spans; Execution Paths only reference these records.
- External wrapper methods are retained as invocation metadata (`external_wrapper_method`, `wrapper_contract`, `wrapper_contract_source`, `wrapper_receiver_type`, and `wrapper_contract_candidates`) but are not required to have a local C# method span. Path evidence materializes only source methods that exist in the local snapshot.
- The optional `discover_external_wrappers` command is a read-only, cache-driven audit: it walks catalog systems, groups observed receiver/method pairs, and reports source wrappers, unique auto-selected contracts, ambiguous contracts, unknown receiver types, and methods missing from a matched contract. It includes source file, line, and span locations in JSON output. It never clones, pulls, creates a scan cache, or writes configuration. The normal `refresh_cli` path separately performs Contract Preflight after `git pull` and may atomically onboard complete source/DLL-backed semantics when no valid selector exists.
- The current scan root retains only its latest source snapshot. Refresh replaces the snapshot; historical code comparison belongs to Git.
- Existing regex detection runs only as migration comparison output. It must not be merged with Gateway output as a second formal relationship source.
- The migration cutover gate requires representative systems and fixtures to show existing direct detections as Gateway results or explicit unresolved cases, without false `proven` detections for inline SQL or ordinary methods.

## Testing Decisions

- Tests assert externally observable Method Flow, Database Invocation evidence, database attribution, source retrieval by span, and migration difference reports. They do not assert internal visitor traversal order or regex implementation details.
- The CSharpAnalysisGateway is the single highest testing seam. Tests provide a source snapshot, event bindings, and a synthetic SP Catalog, then assert returned records.
- Fixtures cover direct SqlClient with explicit CommandType, a source-available wrapper with stored-procedure mode, a wrapper with inline SQL mode, branch-assigned procedure names, Dapper, Entity Framework, dynamic SQL, unavailable wrapper source, and cross-database same-name procedures.
- Fixtures cover a reusable external contract, explicit and receiver-auto selection, ambiguous receiver matches, `call_site` SP mode, contract-scoped inline SQL exclusion, and typed receiver extraction from the StaticAnalyzerHost.
- Tests verify that direct SqlClient and confirmed wrapper calls are `proven` only when their resolved Catalog contains the named procedure.
- Tests verify that unique unknown-database candidates are `likely`, while ambiguous names across multiple Catalogs are `unresolved`.
- Tests verify that selected source references recover the complete containing method from a file snapshot without storing a duplicate copy per invocation or Execution Path.
- Migration tests compare legacy and Gateway results for representative systems, emitting only differences for review. The cutover gate rejects unexpected dropped confirmed calls and unexpected new false `proven` calls.
- Service-level smoke tests verify that refreshed scan data can join Gateway records to SQL Execution Graph paths and retrieve evidence for a selected path.

## Out of Scope

- Full Roslyn semantic Compilation for every legacy project and its dependency graph.
- Runtime execution tracing, reflection analysis, or proving values assembled from external configuration at runtime.
- Guessing a stored procedure, database, table, or DML target for dynamic SQL.
- Storing historical source snapshots in scan storage.
- Permanent operation of the legacy regex detector as a second formal source of Database Invocation facts.
- Replacing the existing framework, ASPX, or SQL cache responsibilities that are outside Method Flow and Database Invocation production.

## Further Notes

- This specification builds on the SQL Execution Graph and Execution Path decisions. The gateway provides the C# side of those paths; SQL analysis remains deterministic and independent.
- For a system-wide onboarding report in Windows PowerShell, run `$env:PYTHONIOENCODING='utf-8'; python -m tools.discover_external_wrappers` from the Impact project root. Use `--system <system_id>` for selected catalog systems, `--root <scan_root>` when catalog resolution is unavailable, and `--format json --output <path>` for machine-readable review. Only genuinely new or ambiguous external APIs require contract review.
- Existing wrapper configuration may remain temporarily as a migration aid for unavailable source, but it is not the long-term primary discovery mechanism.
- The available workspace does not expose an issue-tracker integration. This local specification is marked `ready-for-agent` for handoff until tracker publishing is available.