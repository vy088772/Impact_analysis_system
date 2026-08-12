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

**Contract Preflight**:
A preliminary evidence evaluation that determines whether source or verified external implementation facts can supply reusable wrapper semantics before formal Database Invocation classification. A preflight proposal is configuration interpretation, not procedure evidence.
_Avoid_: formal invocation evidence, runtime discovery