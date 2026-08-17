# Impact Analysis Domain Context

This context defines the SQL execution-analysis vocabulary used to trace application actions through stored procedures to database effects.

## SQL Execution Analysis

**SQL Execution Graph**:
A typed static graph of stored procedures, views, functions, tables, calls, and DML operations produced from SQL AST analysis. It is the sole source of SQL relationship and flow evidence.
_Avoid_: dependencies, depends_on, depended_by

**Execution Path**:
A traceable route from a C# entry method through zero or more stored-procedure calls to one terminal DML operation, identified by a stable `path_id`.
_Avoid_: generic dependency, flow chain

**Path Evidence**:
The smallest complete source set needed to justify one Execution Path: involved C# methods, SQL modules, DML operations, predicates, and referenced View/UDF definitions.
_Avoid_: full analysis context

**Unresolved Dynamic SQL**:
A graph operation known to execute dynamically constructed SQL but whose target object or DML effect cannot be proven statically.
_Avoid_: inferred table, guessed dependency

## C# Data Access Analysis

**CSharpAnalysisGateway**:
The single analysis boundary that turns C# and ASPX source into method Flow and evidence-rated database invocations using Roslyn and the system's SP Catalog.
_Avoid_: wrapper allowlist, regex SP detector

**SP Catalog**:
The normalized stored-procedure inventory for one refreshed database, used to validate a candidate invocation against its resolved database source.
_Avoid_: global SP-name match

**Database Invocation**:
An evidence-rated C# data-access call that represents stored-procedure execution, inline SQL execution, or an unresolved database operation, regardless of whether it crosses direct ADO.NET, a local wrapper, an external wrapper, Dapper, or Entity Framework.
_Avoid_: assumed SP call

**Evidence Status**:
The confidence state of a Database Invocation: `proven`, `likely`, or `unresolved`. It rates the available execution and target evidence independently from contract selection status.
_Avoid_: contract status, scan success

**Wrapper Contract Selector**:
The system-level choice of reusable semantics for an unavailable external wrapper. It may identify one contract or an explicit set of contracts; it is not an inventory of observed methods and does not prove a procedure target or database identity.
_Avoid_: wrapper method list, SP proof

**Wrapper Resolution Status**:
The categorical outcome of matching one wrapper invocation's Command Source to a Contract during reconciliation — for example `source_wrapper`, `explicit_selected`, `unresolved_contract`, `ambiguous_contract`, `receiver_mismatch`, `unresolved_method`, or `not_applicable`. It is independent of Evidence Status and does not itself rate database-target proof.
_Avoid_: classification status, wrapper status

**Contract Preflight**:
A preliminary evidence evaluation that determines whether source or verified external implementation facts can supply reusable wrapper semantics before formal Database Invocation classification. A preflight proposal is configuration interpretation, not procedure evidence.
_Avoid_: formal invocation evidence, runtime discovery

**Contract Lifecycle Status**:
The refresh/preflight disposition of a contract binding: `reused`, `created`, `preflight_failed`, `conflicted`, `selected`, or `not_required`. It describes how the contract was handled in the current refresh, not where its implementation evidence came from. Existing registry-to-invocation projections may also expose `accepted` or `legacy_unverified` for registry validation compatibility. The separate `evidence_kind` marker identifies provenance such as `decompiled_auto` and remains additive to this status.
_Avoid_: evidence provenance, Evidence Status

**Contract Transaction**:
The manifest-backed atomic replacement of the external wrapper registry and, when a selector changes, the system catalog, committed as one recoverable unit. Refresh-time onboarding and explicit contract acceptance are independent triggers that share this same commit; a crash mid-commit leaves a manifest that recovers to the same new pair rather than a mixed state.
_Avoid_: atomic commit, registry write, two-file write

**Command Source**:
The construct inside one wrapper method that supplies the method's command text and terminal sink. A method has a Command Source when a resolution rule recognizes its construct — today an explicit command object construction, or a data adapter construction taking a command text argument and a connection argument. A method that touches a database type but yields no Command Source is a visible gap, not a silent drop.
_Avoid_: SqlCommand construction, command builder

**Implementation Snapshot**:
A structured record of one receiver's public database operations (method identity, argument roles, effective command semantics, terminal sink) captured from local source, a verified external assembly, or a decompiled external assembly, submitted as a candidate for Contract Preflight.
_Avoid_: method inventory, observed call list

**Verified Implementation Snapshot**:
An Implementation Snapshot that has passed completeness validation — every relevant operation has a resolved body, mode, and sink, with a single exact assembly identity — and may therefore supply reusable wrapper semantics. Passing this bar does not itself prove a procedure target; it only qualifies the snapshot as evidence.
_Avoid_: draft snapshot, decompiled output

**Assembly Revision Boundary**:
The identity scope within which every method fact in one Implementation Snapshot must originate from the same exact external assembly (the same byte-identical DLL, hashed rather than assumed from name/version alone for unsigned or unversioned assemblies). Facts from two different revisions are never combined into one snapshot.
_Avoid_: assembly version, DLL name

**Semantic Binding Availability**:
The state of the Roslyn semantic model the analyzer built for one scanned project's own declarations: `available`, `unavailable_no_project_file`, or `unavailable_reference_resolution_failed`. Reported for every scanned project so a degraded, syntax-only analysis never looks like a confident one. Building the compilation and reporting this state does not itself change any classification result.
_Avoid_: compilation success, semantic model status