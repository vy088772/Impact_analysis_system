---
status: ready-for-agent
triage: ready-for-agent
---

# Unified Database Invocation Classification

## Problem Statement

The C# analysis currently starts from wrapper method names. This is too narrow for real application code.

A system can call a database through many methods. Examples include `CreateTable`, `CreateDataSet`, `CreateReader`, `ExeProcRead`, `ExeProcNon`, direct `SqlClient`, Dapper, and Entity Framework. The same method name can also have several overloads with different database semantics.

The analysis must first identify the `Database Invocation`. It must then determine the `Execution Path` and its `Path Evidence`.

The following facts are different facts and must not be merged:

- `connection source` identifies the database connection, such as STC.
- `method semantics` identifies how an implementation creates and executes a command.
- `invocation mode` identifies whether the call executes a stored procedure or inline SQL.
- `command text` identifies a procedure name or SQL text.
- `terminal sink` identifies the ADO.NET operation that executes the command.
- `SP Catalog` validates a stored-procedure target for one database.
- `Evidence Status` identifies whether the result is proven, likely, or unresolved.

The current variable-assignment helper can find several procedure-shaped string values before a call. It does not select an overload, preserve branch predicates, identify `CommandType`, identify the terminal sink, or classify literal SQL. A file-level `SQL_PATTERNS` match also does not prove that a string belongs to a database call.

This causes several risks:

- An inline `EXEC` string can be promoted to a stored-procedure invocation.
- A string that starts with `sp` or `usp` can be treated as a stored procedure even when `CommandType` is `Text`.
- A `CreateReader` call can be confused with a stored-procedure wrapper because it has a database-like receiver.
- A `CreateTable` overload with explicit `SP` mode can be treated the same as an overload with default `Text` mode.
- A branch can lose one procedure target or lose the condition that selects it.
- `SqlDataAdapter.Fill` can be incorrectly recorded as `ExecuteReader`.
- A procedure can be matched against a global catalog instead of the catalog for its resolved connection source.
- `wrapper_contract` can become an inventory of observed methods instead of a selector for opaque external semantics.

## Solution

Make `CSharpAnalysisGateway` the single high-level seam for C# `Database Invocation` production and evidence rating.

The Gateway consumes raw facts from the C# analyzer, current source snapshots, connection-source facts, external contract semantics when required, and the database-scoped `SP Catalog`. It returns evidence-rated `Database Invocation` records that can join to the SQL Execution Graph and form an `Execution Path`.

The classification flow is:

1. Identify a data-access call from typed raw facts.
2. Resolve the receiver type, method identity, overload arity, and parameter types when available.
3. Resolve the method implementation or an accepted external contract.
4. Determine the method semantics and terminal sink.
5. Resolve a literal or finite branch-assigned command text value.
6. Determine the actual invocation mode from `CommandType` or explicit call-site mode.
7. Parse SQL text for inline SQL and embedded `EXEC` targets without changing the invocation mode.
8. Resolve the connection source of the receiver.
9. Validate a stored-procedure target against the resolved database-scoped `SP Catalog`.
10. Preserve branch context, source spans, provenance, and an `Evidence Status`.

`refresh_cli` is the operational orchestrator for the complete workflow. After `git pull`, it performs one raw source analysis, then runs a source contract preflight over the raw facts, current source snapshots, and verified external implementation evidence. The preflight creates an in-memory staged registry and catalog selector before formal classification; it does not perform a second filesystem scan. Formal source scan/classification and wrapper reconciliation consume that staged view and emit `proven`, `likely`, and `unresolved` results. Only after formal classification and reconciliation succeed does the workflow commit the staged contract registry and catalog selector through a two-file atomic commit protocol.

The selector is normalized before preflight. A missing field, `null`, an empty or whitespace-only string, an empty array, or an array containing only blank values means that no contract is selected. A non-empty string selects one contract. A non-empty array selects an explicit candidate set. If a named contract is missing from `external_wrapper_contracts.json`, a string selector is treated as unspecified for preflight; if any member of an array is missing, the whole array is treated as unspecified. The original invalid selector remains in diagnostics and is replaced only by a successful staged commit. An existing valid selector prevents automatic contract creation or overwrite: formal classification uses the specified contract or candidate set, and does not fall back to contracts outside that set.

When no valid selector is present, preflight may add or reuse contracts only when source evidence or a verified implementation snapshot for an exact external assembly identity establishes complete receiver, method, mode, and sink semantics. Incomplete, conflicting, ambiguous, or name-only observations remain review candidates and do not enter the active staged registry. One complete contract is written as a string selector; multiple complete contracts are written as a deterministically sorted array. If preflight cannot produce a complete unique proposal, formal classification still proceeds for unaffected invocations and affected external wrappers remain `unresolved` with a `contract_preflight_failed` reason.

A normal source refresh runs this classification as part of the same analysis operation. A separate external-wrapper discovery command is not required to obtain `Database Invocation` results. The optional discovery command remains a read-only audit view of the shared classifier.

## User Stories

1. As a system analyst, I want every supported data-access call to produce one common `Database Invocation` shape, so that different libraries and wrapper methods can enter the same `Execution Path` model.
2. As a system analyst, I want the connection source to remain separate from invocation mode, so that a connection such as STC is not confused with stored-procedure or inline-SQL semantics.
3. As a system analyst, I want a source implementation to determine `CommandType` semantics, so that the analyzer does not infer behavior from a method name or a procedure prefix.
4. As a system analyst, I want method overload identity to include receiver type, method name, arity, and available parameter types, so that overloads with different semantics remain separate.
5. As a system analyst, I want an unresolved overload to remain unresolved, so that the analyzer does not select an overload by registry order or method name.
6. As a system analyst, I want a method with fixed `CommandType.Text` semantics to remain `inline_sql`, so that a procedure-shaped string does not become a stored-procedure invocation.
7. As a system analyst, I want a method with fixed `CommandType.StoredProcedure` semantics to produce a stored-procedure invocation when its target is valid, so that explicit source evidence is used directly.
8. As a system analyst, I want a call-site mode method to use the explicit call-site mode, so that a value such as `SP` selects stored-procedure execution only for that call.
9. As a system analyst, I want a call-site value other than `SP` to retain `CommandType.Text`, so that the default execution mode is not silently promoted.
10. As a system analyst, I want a literal `EXEC` string to remain inline SQL, so that SQL text and `CommandType.StoredProcedure` are not merged.
11. As a system analyst, I want an inline `EXEC` target to be extracted as separate target evidence, so that the SQL Execution Graph can validate the embedded procedure without changing the invocation mode.
12. As a system analyst, I want `SELECT`, `INSERT`, `UPDATE`, `DELETE`, and similar statement text to be classified as inline SQL, so that common SQL operations enter the correct evidence path.
13. As a system analyst, I want a bare procedure-shaped string without explicit stored-procedure evidence to remain unresolved or inline according to the implementation semantics, so that `sp` and `usp` prefixes are not proof.
14. As a system analyst, I want a resolved `CommandType.Text` implementation to override a procedure prefix, so that a name such as `spSelMasterQryV2` is not treated as an SP when the command executes as text.
15. As a system analyst, I want an exact Catalog match to validate a target, so that a candidate name is not accepted only because it looks like an SP name.
16. As a system analyst, I want Catalog matching to use the resolved connection source, so that the same procedure name in different databases does not create a false cross-database relationship.
17. As a system analyst, I want unresolved connection identity to remain visible, so that a unique cross-Catalog candidate can be marked `likely` and an ambiguous candidate can remain `unresolved`.
18. As a system analyst, I want a literal command text to be retained with its source span, so that the `Path Evidence` can show the exact call-site value.
19. As a system analyst, I want a variable command text to be resolved when it has a finite set of literal assignments, so that common branch-based code is not discarded.
20. As a system analyst, I want each finite variable value to retain its branch predicate, so that each value forms a separate and explainable `Execution Path`.
21. As a system analyst, I want both the default assignment and conditional reassignment to be retained, so that the default business path is not hidden by the last textual assignment.
22. As a system analyst, I want a dynamic string expression to remain `Unresolved Dynamic SQL`, so that the analyzer does not fabricate a procedure, table, or DML target.
23. As a system analyst, I want an ordinary UI helper call without a command-text argument to produce no `Database Invocation`, so that methods such as alert and script helpers do not create SQL evidence.
24. As a system analyst, I want a class that contains both UI helpers and database calls to be analyzed per invocation, so that class-level exclusion does not hide real database operations.
25. As a system analyst, I want `CreateReader` with a literal SELECT statement to remain inline SQL, so that read queries are not reported as stored-procedure calls.
26. As a system analyst, I want `CreateTable` and `CreateDataSet` overloads without an explicit SP mode to use their source-defined default mode, so that default `Text` behavior is preserved.
27. As a system analyst, I want `CreateTable` and `CreateDataSet` overloads with explicit SP mode to produce stored-procedure evidence only when the mode selects SP, so that call-site semantics remain precise.
28. As a system analyst, I want `ExeProcRead` and `ExeProcNon` to use their fixed stored-procedure implementation semantics, so that their calls do not need a method-name heuristic.
29. As a system analyst, I want the terminal sink to be retained, so that `ExecuteReader`, `ExecuteScalar`, `ExecuteNonQuery`, and `Fill` have distinct evidence.
30. As a system analyst, I want `SqlDataAdapter.Fill` to be a first-class terminal sink, so that a DataSet or DataTable operation is not incorrectly recorded as `ExecuteReader`.
31. As a system analyst, I want source-backed wrapper implementation evidence to be stronger than an external contract selector, so that local implementation facts control classification when they are available.
32. As a system analyst, I want a verified implementation snapshot from an exact external assembly identity to be usable as source-backed evidence, so that available Metadata as Source can explain a library boundary without inventing caller source.
33. As a system analyst, I want an unavailable external implementation to require a matching contract before it contributes stored-procedure evidence, so that an opaque DLL boundary is not treated as proof.
34. As a system maintainer, I want `wrapper_contract` to remain a selector for reusable external semantics, so that observed method inventory stays in raw observations and review output.
35. As a system maintainer, I want a new receiver or method to produce a review candidate instead of an active contract entry, so that refresh cannot silently change evidence semantics.
36. As a system maintainer, I want the existing contract for an equivalent receiver type to be reused, so that refresh does not create duplicate contracts for the same library.
37. As a system operator, I want one refresh command to produce the current `Database Invocation` classification, so that I do not need a separate discovery command for the same source snapshot.
38. As a system operator, I want the refresh result to show classification status, invocation mode, sink, target, connection source, and unresolved reasons, so that review does not require reading raw logs.
39. As a system operator, I want refresh to report incomplete external contract evidence without applying it, so that a source update cannot silently modify registry or catalog semantics.
40. As a system maintainer, I want explicit contract acceptance to reclassify cached raw facts without rescanning unchanged C# source, so that semantic maintenance is fast and deterministic.
41. As a developer, I want the C# analyzer to expose method identity, argument facts, branch context, and source spans, so that the Gateway can classify calls without a second regex evidence source.
42. As a developer, I want the SQL Execution Graph to receive typed invocation facts, so that graph relationships remain distinct from generic call-chain output.
43. As a developer, I want each `Execution Path` to retain the C# predicate and SQL target evidence that selected it, so that reverse lookup can explain why a path exists.
44. As a maintainer, I want legacy regex results to remain comparison-only during migration, so that the Gateway remains the single formal source of `Database Invocation` facts.
45. As a maintainer, I want focused fixtures for fixed mode, call-site mode, inline `EXEC`, branch assignments, overloads, and `Fill`, so that changes to classification semantics are detected before refresh output changes.
46. As a system operator, I want `refresh_cli` to run contract preflight before formal classification, so that one refresh produces both current source evidence and the contract view required to interpret opaque wrappers.
47. As a system maintainer, I want blank, null, and empty-array selectors normalized as unspecified, so that equivalent catalog states follow one deterministic onboarding path.
48. As a system maintainer, I want a valid existing selector to prevent automatic contract creation or overwrite, so that an explicitly chosen contract remains authoritative for formal external-wrapper classification.
49. As a system operator, I want a missing named contract to be treated as an unspecified selector with diagnostics, so that a stale catalog selector can be repaired by a successful preflight instead of blocking unrelated source analysis.
50. As a system maintainer, I want an array selector to represent an explicit contract candidate set, so that multiple reusable contracts can serve one system without using array order as priority.
51. As a system maintainer, I want a partially invalid selector array to be treated as unspecified as a whole, so that the same catalog does not have environment-dependent partial semantics.
52. As a system maintainer, I want complete source or exact external implementation evidence to be required before automatic contract onboarding, so that method names and incomplete DLL metadata cannot become active semantics.
53. As a system operator, I want incomplete or ambiguous preflight proposals to leave configuration unchanged while affected invocations remain unresolved, so that one opaque wrapper does not hide usable direct SQL evidence.
54. As a system operator, I want registry and catalog updates to commit atomically only after formal classification and reconciliation succeed, so that a failed refresh cannot leave a half-applied contract selection.
55. As a system maintainer, I want program-scoped refresh to require an existing valid selector or a completed full-system onboarding refresh, so that partial source facts cannot generate an incomplete contract set.

## Implementation Decisions

- The highest implementation and testing seam is the existing `CSharpAnalysisGateway`. No second high-level classifier is introduced in the CLI or in the legacy parser.
- `StaticAnalyzerHost` remains the raw-fact producer. It must expose enough facts for the Gateway to classify a call: receiver identity, receiver type when known, method identity, overload arity, available parameter types, argument expressions, literal values, branch context, source span, and connection-related construction facts.
- The Gateway owns the transition from raw facts to `Database Invocation`, `Evidence Status`, and provenance. Private helpers may extract facts, but callers do not treat private helper output as the formal evidence contract.
- `CSharpParser` and `SQL_PATTERNS` remain migration or comparison inputs only. A file-level SQL-like string match cannot create a formal `Database Invocation` without a call-site and execution-sink path.
- A `Database Invocation` records at least the receiver identity, method identity, method semantics, invocation mode, command-text kind, resolved command text or candidates, optional embedded procedure target, connection source, terminal sink, branch context, source span, provenance, and `Evidence Status`.
- `connection source` and `invocation mode` are separate fields. The first identifies the database source. The second identifies `stored_procedure`, `inline_sql`, or an unresolved mode. `call_site` describes method semantics; it is not the final invocation mode.
- Method semantics are classified as fixed stored procedure, fixed inline SQL, call-site selected, or unresolved. The implementation must use source `CommandType` assignments when the implementation is available.
- Overload selection uses receiver type, method name, arity, and available parameter types. If the available facts cannot select one implementation, the result retains all candidates and remains unresolved.
- A source-backed fixed `CommandType.Text` method is always classified as `inline_sql`, including when the command text starts with `sp` or `usp` or contains an SP name.
- A source-backed fixed `CommandType.StoredProcedure` method is classified as `stored_procedure` when the command text target is finite and the terminal sink is known.
- A source-backed call-site method is classified as `stored_procedure` only when the call-site mode selects stored-procedure execution. For the known SQLObject pattern, the `SP` mode value selects stored-procedure execution and the default path remains `Text`.
- The default `SqlCommand` mode is treated as `Text` when the implementation does not assign `CommandType.StoredProcedure`. The analyzer must not infer SP mode from a name prefix.
- Command text classification parses the leading SQL statement after whitespace and comments. `EXEC` and `EXECUTE` inside a `Text` command are inline SQL. Their procedure target is recorded as embedded target evidence and does not change the invocation mode.
- A bare command string without a resolved implementation or explicit stored-procedure mode is not proven by its name. A prefix such as `sp`, `usp`, or `proc` is a weak candidate hint only.
- Literal command text is resolved directly. A variable is resolved when the bounded source analysis finds a finite set of literal assignments before the call. Each candidate retains its branch context and source provenance.
- The variable-assignment result must not be reduced to the last textual assignment. The default value and conditional values must remain available for separate `Execution Path` candidates.
- Dynamic concatenation, external input, unbounded data flow, unknown method arguments, and ambiguous assignments remain `Unresolved Dynamic SQL` or unresolved command text. The analyzer records the reason and source span.
- Database source resolution follows receiver construction and constructor arguments where the source facts support it. Configuration expressions are normalized through the existing connection-source model. A missing or ambiguous source remains unresolved.
- The `SP Catalog` is scoped to the resolved database source. A normalized schema and procedure identity must match the selected Catalog before stored-procedure evidence is promoted.
- A stored-procedure invocation is `proven` only when the mode is stored procedure, the implementation or accepted contract establishes a terminal sink, the target is finite, the connection source is resolved, and the target exists in the matching `SP Catalog`.
- A candidate can be `likely` when the mode, sink, and target are strong but database attribution is unresolved and the target is unique across the known Catalogs. A target with cross-database ambiguity remains `unresolved`.
- Inline SQL is recorded as an inline `Database Invocation`. An embedded `EXEC` target is validated separately and must not be represented as a stored-procedure mode solely because the SQL text contains `EXEC`.
- The terminal sink vocabulary includes `ExecuteNonQuery`, `ExecuteReader`, `ExecuteScalar`, and `Fill`. `Fill` is a first-class adapter sink. It is not silently renamed to `ExecuteReader`.
- The SQLObject implementation supplied for this effort defines the required source-backed examples: text-mode reader calls, text-mode scalar calls, text-mode edit calls, adapter-based table and dataset calls, call-site SP table and dataset calls, fixed stored-procedure reader calls, and fixed stored-procedure non-query calls.
- A trusted implementation snapshot from exact external assembly metadata may provide source-backed semantics when its assembly identity and method identity are recorded. The snapshot is evidence for the library boundary, not a replacement for the caller source snapshot.
- A verified implementation snapshot from exact external assembly metadata may provide source-backed semantics when its assembly identity and method identity are recorded. Reflection-only metadata, arbitrary DLL discovery, or decompilation is insufficient to create an active contract.
- An unavailable external wrapper uses `wrapper_contract` only when a matching selected contract supplies its receiver, method, mode, and sink semantics. A selected contract does not by itself prove a procedure target or database identity. Source-backed implementation evidence remains stronger than an external selector; a conflict is retained as unresolved conflict evidence rather than silently overwritten.
- The `wrapper_contract` field remains a system selector for reusable semantics. It accepts a backward-compatible string for one contract or an array for multiple explicit candidates. Array order has no priority meaning; matching more than one candidate is ambiguous. It is not populated with every observed receiver and method.
- Contract preflight runs after `git pull` and before formal source classification. It consumes the one raw analyzer result and produces staged registry/catalog values in memory. A preflight proposal may reuse an equivalent existing receiver contract, add a deterministic new contract when semantics are complete, or report a review candidate when evidence is incomplete, conflicting, or ambiguous.
- Selector precedence is explicit and fail-closed. A valid non-empty selector string or array is used for formal classification and prevents automatic contract creation or overwrite. A missing contract name makes a string selector behave as unspecified; any missing member makes an array selector behave as unspecified. The original invalid value remains diagnostic until a successful commit replaces it.
- When no valid selector is present, one complete contract is serialized as a string selector and multiple complete contracts as a deterministically sorted array. If no complete proposal is available, the selector remains unchanged and affected external wrappers are unresolved with `contract_preflight_failed`.
- Ordinary refresh performs raw source analysis, contract preflight, formal invocation classification, and reconciliation in one operation. It does not require a separate discovery command to classify the current source. A program-scoped refresh cannot perform onboarding without an existing valid selector or a prior completed full-system onboarding refresh.
- Registry and catalog changes are staged in memory and committed only after formal source classification and wrapper reconciliation succeed. The commit is a logical two-file atomic transaction: temporary validated files, deterministic transaction identity, replacement of both targets, and rollback/recovery if the second replacement fails. A failed refresh leaves both active files byte-for-byte unchanged.
- The optional external-wrapper discovery command consumes the same Gateway classification service. It does not implement a separate mode, sink, overload, SQL-text, or Catalog rule.
- Refresh responses expose additive machine-readable fields for method semantics, invocation mode, command-text candidates, embedded targets, sink, connection source, branch context, Evidence Status, provenance, and unresolved reasons.
- The SQL Execution Graph remains the formal source of SQL relationship and lineage evidence. C# invocation classification supplies the typed entry edge and evidence required to join an `Execution Path`.
- The implementation remains deterministic. It does not use an LLM, runtime execution, reflection, global procedure-name matching, or semantic similarity between unrelated contracts.
- Cache invalidation must change when the raw invocation schema or classification semantics change. Contract-only changes reclassify compatible cached facts without rescanning source.

## Testing Decisions

- Tests assert external behavior at the `CSharpAnalysisGateway` seam. They assert `Database Invocation` records, invocation mode, method semantics, sink, target, connection source, branch context, Evidence Status, provenance, and unresolved reasons.
- Tests do not assert private helper names, regex order, visitor traversal order, or the number of intermediate syntax nodes. A helper such as a variable-assignment extractor is tested only through the Gateway behavior that it enables.
- Gateway fixtures provide a synthetic current source snapshot, raw analyzer facts, connection-source mappings, external contract definitions when needed, and database-scoped SP Catalog data.
- A source-backed SQLObject fixture covers fixed inline SQL methods, fixed stored-procedure methods, call-site methods, adapter `Fill`, overload identity, and default `Text` behavior.
- A branch fixture covers a default procedure name and a conditional procedure name assigned to the same variable. The assertions require two invocation candidates, two branch contexts, and no loss of the default path.
- A literal SQL fixture covers a `CreateReader` call with a SELECT statement and verifies inline classification and the absence of stored-procedure evidence.
- An inline EXEC fixture verifies inline mode, embedded procedure target extraction, and separate Catalog validation. It must not produce stored-procedure mode from the EXEC text alone.
- A call-site fixture verifies that an explicit SP mode produces stored-procedure classification and that the same method without SP mode remains text mode.
- A prefix fixture verifies that a procedure-shaped name does not become stored procedure when source semantics are `Text` or when no stored-procedure evidence exists.
- Fixed stored-procedure fixtures verify reader and non-query sinks and require a matching database-scoped Catalog entry before `proven` evidence is returned.
- Adapter fixtures verify that `Fill` is retained as its own terminal sink and is not reported as `ExecuteReader`.
- An overload fixture verifies that methods with the same name but different argument counts or types can have different semantics. Ambiguous overloads must remain unresolved.
- A dynamic-expression fixture verifies `Unresolved Dynamic SQL`, preserved source span, and an explicit unresolved reason.
- A UI fixture includes alert and script helper calls in the same class as a real database call. The UI helpers must not produce `Database Invocation` records, while the real database call must remain visible.
- A connection fixture verifies resolved source, missing source, unique unknown-database candidates, and same-name procedures in multiple Catalogs.
- An external-boundary fixture verifies source-backed implementation evidence, exact assembly metadata evidence when available, contract-required unresolved behavior when unavailable, and the separation between contract selection and procedure proof.
- Refresh-service tests verify the ordered workflow: one raw source analysis, contract preflight, formal classification using the staged registry/catalog, wrapper reconciliation, and final summary without a mandatory second discovery request. They verify that a valid selector performs no automatic contract creation, while an unspecified selector can stage only complete source/DLL-backed contracts.
- Refresh-service tests verify selector normalization for missing, null, blank, empty-array, invalid-string, invalid-array, valid-string, and valid-array values. They verify that an invalid selector can be replaced only after successful formal classification and reconciliation, while a failed preflight preserves the original invalid value.
- Refresh-service tests verify that one complete proposal writes a string selector, multiple complete proposals write a deterministically sorted array, array order is not precedence, and a partially invalid selector array is not partially applied.
- Refresh-service tests verify the two-file atomic commit and rollback behavior, including a failure between registry and catalog replacement. Both active files must remain unchanged after failure.
- Program-refresh tests verify that a system without a valid selector cannot onboard contracts from a partial program refresh and must complete a full-system onboarding refresh first.
- Cached reclassification tests verify that a contract change updates classification from raw facts without a new C# scan, while a source change requires a new refresh.
- SQL Execution Graph integration tests verify that proven invocation records can join to the correct SQL module and form an `Execution Path`, while inline SQL and unresolved targets retain their documented evidence status.
- Regression tests compare the Gateway result with the legacy parser during migration. Differences are reported for review; legacy output is not merged into the formal evidence result.
- The focused suite must run without a live SQL Server, live external repository, LLM service, or runtime invocation. One end-to-end smoke test may use the real StaticAnalyzerHost to verify typed receiver and branch facts.

## Out of Scope

- Inferring stored-procedure mode from method names, `sp` or `usp` prefixes, or a global name match.
- Treating an inline `EXEC` statement as `CommandType.StoredProcedure`.
- Treating a selected `wrapper_contract` as proof of a procedure target, connection source, or SQL graph relationship.
- Automatically adding observed methods to an active external contract when a valid selector exists, or when source/DLL evidence is incomplete, conflicting, or ambiguous.
- Automatically writing the external contract registry or system catalog before formal classification and reconciliation succeed.
- Treating `wrapper_contract` array order as contract precedence, or silently applying only the valid subset of a partially invalid array.
- Full Roslyn semantic compilation for every legacy project and every external dependency.
- Runtime execution tracing, reflection, runtime configuration evaluation, and values assembled only outside the available source facts.
- Unbounded interprocedural data flow, arbitrary alias analysis, or complete path-sensitive symbolic execution.
- Downloading or decompiling an arbitrary external DLL as an automatic refresh side effect. An implementation snapshot must be supplied and associated with an exact artifact identity before it can provide source-backed semantics.
- Replacing the SQL Execution Graph as the source of SQL relationships, lineage, reverse lookup, or terminal DML evidence.
- Treating an inline SQL target extracted from `EXEC` as a stored-procedure mode relationship without the corresponding SQL Execution Graph and Catalog evidence.
- Historical source snapshots and historical contract versions beyond the existing Git and artifact revision model.
- Removing the legacy parser immediately. It remains available for bounded migration comparison until the Gateway cutover criteria are met.

## Further Notes

The central design rule is simple: classify the `Database Invocation` before classifying the wrapper. A wrapper is only one possible implementation boundary for a database call.

For the SQLObject examples, the source implementation is the decisive evidence. Reader, scalar, edit, table, and dataset methods that leave `CommandType` at its default are inline SQL. The methods that explicitly set `CommandType.StoredProcedure` are stored-procedure methods. The methods that set it only when the call site supplies SP mode are call-site methods.

A branch such as a default procedure name followed by a conditional reassignment must produce separate invocation candidates. The candidate names alone are not enough for an exact `Execution Path`; the branch predicate is part of the required `Path Evidence`.

The existing CSharpAnalysisGateway specification and the C# analysis gateway ADR define the architectural boundary. This spec adds the unified command-text, overload, adapter-sink, and branch-resolution detail needed to apply that boundary to the wider set of data-access calls.

The intended operational flow is:

```text
refresh_cli
	-> git pull and source-root resolution
	-> one raw source analysis
	-> source/DLL contract preflight
	-> staged external_wrapper_contracts + wrapper_contract selector
	-> formal source classification
	-> wrapper observations/reconciliation
	-> proven / likely / unresolved output
	-> atomic registry/catalog commit on success
```

The staged configuration is an interpretation aid, not evidence by itself. A selected or generated contract still has to provide method semantics and a terminal sink, while procedure proof still requires command mode, connection source, and the database-scoped SP Catalog.

This spec is published in the local Markdown issue tracker with `ready-for-agent` triage metadata.
