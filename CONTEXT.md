# Impact Analysis Domain Context

This context defines the SQL execution-analysis vocabulary used to trace application actions through stored procedures to database effects.

## SQL Execution Analysis

**SQL Cache Identity**:
The normalized `(server, database, schema)` triple that names one SQL cache, independent of any System. The server part drops a named-instance suffix, gains the internal domain when it has none, and is lowercased, so one host never holds two identities. A Database shared by many Systems has exactly one identity, and so exactly one cache. See [ADR-0009](docs/adr/0009-sql-cache-identity-decoupled-from-system.md).
_Avoid_: system_id cache key, per-System cache, database name alone

**Object Location Index**:
The record of every object name one SQL cache can answer for, carried beside that cache under the same SQL Cache Identity. It holds the union of the declared object names and the SQL Execution Graph node names, so a table reached only inside a stored-procedure body stays findable. An index that reports no match is an authoritative negative: the reader skips that cache without opening it. An index that disagrees with the version of the cache it describes counts as absent, and the reader falls back to reading the whole cache — a stale index makes a search slow, never wrong.
_Avoid_: name list, cache summary, object catalog

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

**Resolved Connection Source**:
The `{server, database}` shape a `connection_sources` entry takes once the Web.config connection-string resolver has worked it out — it names the physical target the connection really opens, and carries a server so it can drive a cache lookup. See [ADR-0008](docs/adr/0008-web-config-connection-string-resolution.md).
_Avoid_: connection info, connection dict, resolved database

**Legacy Connection Label**:
The bare-string shape a `connection_sources` entry still carries when it was written by a scan that predates the Web.config connection-string resolver. It names nothing beyond an old system_id-shaped guess — no server, no proof it points at a real database — and is always replaced by a Resolved Connection Source the next time its file is re-scanned.
_Avoid_: unresolved label, plain string, legacy string

**Scan Record**:
The record that one SQL Cache Identity was actually scanned, and when — written beside the scan results at save time. It is the only record that a scan happened; the caller's Database Registry records which Databases *should* exist, never whether any were scanned, so the two are read separately and can never disagree. See `llamaindex-spec-rag`'s [ADR-0005](../llamaindex-spec-rag/docs/adr/0005-registry-records-intent-cache-metadata-records-fact.md).

**Uncataloged Database**:
A resolved connection target whose database is identified but has no matching SP Catalog scan yet — its SQL Cache Identity names no cache on disk. Distinct from a connection target that cannot be identified at all — the two are never reported under the same reason. `llamaindex-spec-rag`'s `CONTEXT.md` carries the same concept under the same name, viewed from `refresh_cli`'s unresolved-summary layer instead of this gateway's classification layer. See [ADR-0009](docs/adr/0009-sql-cache-identity-decoupled-from-system.md).
_Avoid_: unresolved database, unknown database

**Database Invocation**:
An evidence-rated C# data-access call that represents stored-procedure execution, inline SQL execution, or an unresolved database operation, regardless of whether it crosses direct ADO.NET, a local wrapper, an external wrapper, Dapper, or Entity Framework.
_Avoid_: assumed SP call

**Evidence Status**:
The confidence state of a Database Invocation: `proven`, `likely`, `unresolved`, or `not_applicable`. It rates the available execution and target evidence independently from contract selection status. `not_applicable` marks an invocation with no database evidence to rate. This concept shares its name with, but is unrelated to, `llamaindex-spec-rag`'s per-path/query Evidence Status; see [ADR-0007](docs/adr/0007-evidence-status-name-collision-with-llamaindex-spec-rag.md).
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