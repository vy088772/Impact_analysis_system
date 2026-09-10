# Impact Analysis Domain Context

This context defines the SQL execution-analysis vocabulary used to trace application actions through stored procedures to database effects.

## SQL Execution Analysis

**SQL Cache Identity**:
The normalized `(server, database, schema)` triple that names one SQL cache, independent of any System. The server part drops a named-instance suffix, gains the internal domain when it has none, and is lowercased, so one host never holds two identities. A Database shared by many Systems has exactly one identity, and so exactly one cache. See [ADR-0009](docs/adr/0009-sql-cache-identity-decoupled-from-system.md).
_Avoid_: system_id cache key, per-System cache, database name alone

**Object Location Index**:
The record of every object name one SQL cache can answer for, carried beside that cache under the same SQL Cache Identity. It holds the union of the declared object names and the SQL Execution Graph node names, so a table reached only inside a stored-procedure body stays findable. An index that reports no match is an authoritative negative: the reader skips that cache without opening it. An index that disagrees with the version of the cache it describes counts as absent, and the reader falls back to reading the whole cache — a stale index makes a search slow, never wrong.
_Avoid_: name list, cache summary, object catalog

**Derived Execution Evidence**:
The full set of evidence-rated Database Invocations and the Execution Paths built from them, for one repository scan crossed with one SQL Cache Identity. It is independent of any object a question names — the name filters this evidence only at the end, and never scopes how the evidence is built. Its identity is the pair of repository scan and SQL Cache Identity it was derived from; either one changing invalidates it. See [ADR-0013](docs/adr/0013-derived-execution-evidence-computed-once-per-scope.md).
_Avoid_: cached results, invocation cache, precomputed paths

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

**Embedded Procedure Target**:
The stored procedure an inline SQL command text turns out to execute, rated against the SP Catalog for the invocation's resolved database. The text names it either with an explicit `EXEC`/`EXECUTE` or by being nothing but the procedure name, which T-SQL executes just the same; `target_source` keeps the two tellable apart. It is additional evidence beside the invocation, never a replacement for the `procedure_name` the call itself declared.
_Avoid_: inline SP call, exec target, promoted procedure

**Executed Procedure Name**:
Which stored procedure one Database Invocation runs, whichever field knows: the `procedure_name` the call declared, or a `proven` Embedded Procedure Target when the call declared none. A rating below `proven` answers nothing, because a candidate is not a call. It is the one question `/find_by_sp` asks of an invocation, so no caller has to remember to read two fields.
_Avoid_: effective procedure, resolved SP name, procedure_name fallback

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
A structured record of one receiver's public database operations (method identity, argument roles, Required Parameter Count, effective command semantics, terminal sink) captured from local source, a verified external assembly, or a decompiled external assembly, submitted as a candidate for Contract Preflight.
_Avoid_: method inventory, observed call list

**Required Parameter Count**:
How many arguments a caller must supply to one wrapper overload: its parameter count minus its trailing optional parameters. A call binds to an overload when this count is at or below the observed argument count and the overload's parameter count is at or above it. It is observed by the decompiler, never derived from a parameter list -- a derived count would claim every parameter is required and silently narrow which calls bind. An overload that reports no count is compared by exact argument count, the rule that predates this concept. See [ADR-0014](docs/adr/0014-required-parameter-count-joins-the-contract-behavior-signature.md).
_Avoid_: minimum arity, optional parameter count, method arity

**Mode Argument Carriage**:
Whether one wrapper overload has a parameter that could have received the call site's command-type mode argument. An overload declaring a `command_type` argument role carries the mode when that role sits inside the observed argument count and the parameter there is a string; an overload declaring no such role carries it only if some other string parameter, inside the observed count and not the command-text parameter, was free to take it. It breaks a tie between overloads that are otherwise indistinguishable by count alone, and only when exactly one overload survives -- zero or several leaves the tie reported as a tie.
_Avoid_: mode inference, command type guess

**Verified Implementation Snapshot**:
An Implementation Snapshot that has passed completeness validation — every relevant operation has a resolved body, mode, and sink, with a single exact assembly identity — and may therefore supply reusable wrapper semantics. Passing this bar does not itself prove a procedure target; it only qualifies the snapshot as evidence.
_Avoid_: draft snapshot, decompiled output

**Assembly Revision Boundary**:
The identity scope within which every method fact in one Implementation Snapshot must originate from the same exact external assembly (the same byte-identical DLL, hashed rather than assumed from name/version alone for unsigned or unversioned assemblies). Facts from two different revisions are never combined into one snapshot.
_Avoid_: assembly version, DLL name

**Semantic Binding Availability**:
The state of the Roslyn semantic model the analyzer built for one scanned project's own declarations: `available`, `unavailable_no_project_file`, or `unavailable_reference_resolution_failed`. Reported for every scanned project so a degraded, syntax-only analysis never looks like a confident one. It carries a `source_file_count`, because an SDK-style Project names none of its source files and the count is the only place a maintainer sees what the model actually holds. Building the compilation and reporting this state does not itself change any classification result.
_Avoid_: compilation success, semantic model status

**SDK-style Project**:
The project-file form every measured ASP.NET Core project uses, in which source files come from Implicit Globbing and references from package references resolved through Restore Assets. The old-style form names every source file and every reference instead. The project reader branches once on the form rather than asking which it is at every field, and the two never merge: an SDK-style project's own framework references already declare every built-in type, so `mscorlib` must not be added to it the way it still is to an old-style project.
_Avoid_: new csproj, modern project, netcore project

**Implicit Globbing**:
The rule by which an SDK-style Project's source files are discovered — every `.cs` file beneath the project directory, minus the ones a removal item names, and never one under `bin`, `obj`, or a dot-directory. The project file itself lists no source. A removal item excludes the files it names, so an excluded directory contributes no source at all.
_Avoid_: file discovery, source scan, compile items

**Restore Assets**:
The `obj/project.assets.json` one NuGet restore writes for one SDK-style Project, and the only place consulted for which assembly each package reference compiles against. A project already carrying assets is never restored again; a project carrying none is restored once. Nothing here guesses at a NuGet folder layout or hunts through a .NET installation. When two assemblies of one name arrive, the higher assembly version wins, which is the rule MSBuild's own conflict resolution follows — preferring the targeting pack unconditionally is wrong and produces CS1705.
_Avoid_: nuget cache, packages folder, project.json

**Declaring Receiver Type**:
The type one wrapper Contract is keyed on: the type that *declares* the invoked method, which for a local database context deriving from an external base class is that base, not the local subclass. It is reported beside a provenance saying how it was reached — `declaring_type` from the bound method symbol's containing type, `receiver_declaration` when the receiver's own declared type declares the method, `declaring_type_unresolved` when a receiver type resolved but inherits the method from a base this analysis cannot see, and blank when no receiver type resolved at all. The rule only ever walks *from* a receiver type the syntax already resolved; it never invents one where none was reported before.
_Avoid_: receiver class, wrapper class, declared type

## Web Application Analysis

**Program Screen**:
One View file together with the set of actions that serve it — the actions whose name equals the view name, plus the actions its View Anchors name. It is what a specification's program code resolves to inside a repository. The controller is a path used to reach those actions, never the unit of scope: one controller can hold several Program Screens, and one Program Screen never spans two controllers. In WebForms the same concept is one `.aspx` page and its code-behind. See [ADR-0019](docs/adr/0019-a-program-is-one-view-plus-the-actions-that-serve-it.md).
_Avoid_: page, controller, program name, screen

**View Anchor**:
The declaration inside one View that names an action the screen calls. It comes at two strengths and they are never merged: a markup-layer anchor (`asp-action`, `asp-controller`, `<form action>`, `asp-page`) is determined, and a URL shaped like `/Controller/Action` inside the view's own `<script>` block is a candidate rated `likely`. It is the MVC counterpart of a WebForms control event such as `OnClick="Button1_Click"`.
_Avoid_: route, form target, event handler

**Project Connection Scope**:
The directory of one project file, which is the extent over which one connection lookup table is valid. A `.cs` file belongs to the nearest project file above it, and two projects' tables are never merged — one key name is unique only inside the configuration file that declares it, and the same name in two projects can open two different databases. A file with no project file above it has no table, and its connections report unresolved. See [ADR-0018](docs/adr/0018-connection-lookup-tables-are-scoped-to-the-project-file.md).
_Avoid_: scan root scope, repository connections, appsettings table

**Application Settings File**:
The `appsettings.json` beside one project file, and the only file that supplies that Project Connection Scope's connections. Its `ConnectionStrings` section is a connection lookup table; every other outer key belongs to the Configuration Root Namespace, and the two are never merged (ADR-0008). It is read tolerantly, because a byte-order mark, `//` and `/* */` comments, and a trailing comma all occur in real files and .NET's own configuration reader accepts them all. An `appsettings.<environment>.json` beside it is not this file; see Environment Settings Override.
_Avoid_: config file, settings, connection strings file

**Configuration Root Namespace**:
The outer keys of an Application Settings File other than `ConnectionStrings` — the layer `IConfiguration["Key"]` reads. It is not a connection lookup table: a key read from it resolves to no `{server, database}` and names that as the reason, because the two namespaces are not merged even when the same key name appears in both. `Configuration["ConnectionStrings:Key"]` carries the section prefix and therefore reads the lookup table, not this namespace.
_Avoid_: app settings, root keys, configuration section

**Context Connection Registration**:
The composition root's binding of one database context type to one named connection string, written as `AddDbContext<T>(... GetConnectionString("Key") ...)` in `Program.cs` or `Startup.cs`. It is the only thing that says which database a context type opens — the type name is not the database name, exactly as a connection lookup key is not a database name (ADR-0008). A call resolves through the *declared type of its receiver*, so one class holding two context types resolves each call to its own database, and a context type the composition root never registered resolves to nothing with a stated reason.
_Avoid_: context name, DbContext database, type-name inference

**Environment Settings Override**:
A connection an `appsettings.<environment>.json` states differently from the Application Settings File beside it. It is reported as an observation and never applied. Which environment runs is a deployment-time fact a static scan cannot know, so applying one would be a guess, and omitting it would lose a real per-environment database difference.
_Avoid_: environment config, override, production connection

**Framework Label**:
The detected framework of one scan root, reported beside the scan and printed by `refresh_cli`. It states what the root is; it does not decide what the scanner reads, because parsers mount by the union of file extensions actually present. A root that holds both WebForms and MVC files reports both. A root that cannot be identified fails loudly rather than falling back to a C#-only scan. See [ADR-0021](docs/adr/0021-the-framework-label-reports-it-does-not-gate.md).
_Avoid_: project type, required parsers, framework gate
