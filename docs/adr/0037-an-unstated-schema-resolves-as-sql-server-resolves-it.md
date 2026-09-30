# An Unstated Schema Resolves as SQL Server Resolves It

**Status:** Accepted
**Date:** 2026-09-30

## Context

The canonical-object-identity work decided never to fill an unstated schema with `dbo`. Nothing in the source text of a reference proves the schema. So a reference that states no schema kept an empty schema. The table match then marked it with Unproven Schema.

That decision cost too much. The seven local SQL caches hold 9845 references that state no schema and that the object listing resolves. The analyst saw the mark on almost every answer. The mark then said nothing.

SQL Server does not guess. It resolves each name by a fixed rule. The operator confirmed how this shop uses that rule. Every login has the default schema `dbo`. Inside a module in schema `S`, SQL Server looks for `S.name`, then `dbo.name`. It fails when neither exists.

## Decision

The graph builder resolves every reference that states no schema. This is Schema Resolution. The rule has three steps, in this order:

1. The module's own schema holds the name. The reference resolves to that schema. This step applies inside a procedure, a view, or a function.
2. The `dbo` schema holds the name. The reference resolves to `dbo`. A reference outside a module starts at this step.
3. The name is an unqualified call, it starts with `sp_` or `xp_`, and steps 1 and 2 found nothing. The call resolves to the `sys` schema.

SQL Server checks `sys` first for a system name. The listing holds no `sys` object, so a listed user procedure with that prefix wins in both orders. The rule therefore checks `sys` last.

Five more points define the rule:

- The default schema is one constant, `dbo`. No per-Database or per-System setting exists.
- The lookup reads the object listing of the cache. It crosses object kinds. One schema holds one namespace for tables, views, procedures, and functions.
- A name that the listing holds in neither schema keeps an empty schema. This covers a temp table, a table variable, an object of another Database, and a broken reference.
- A `db..name` reference keeps an empty schema. This holds also when the Database is the cache's own Database.
- A resolved schema is proven. It carries no Unproven Schema mark and does not lower the Evidence Status.

Every read, write, call, and function relationship records its schema source. The values are `written`, `module_schema`, `default_schema`, `system`, and `unresolved`. A module in `dbo` that reads a name held by `dbo` records `module_schema`. The value `default_schema` means one of two cases. Either the rule fell back from another schema to `dbo`, or the reference sits outside a module.

An unqualified call now links to the one procedure that the rule names. It no longer links to every listed procedure with that bare name. This closes the open decision that the canonical-object-identity spec recorded against [ADR-0035](0035-an-unproven-schema-marks-one-execution-path.md). One call gives one Execution Path.

## What this reverses

This decision reverses one part of the canonical-object-identity work: the decision never to fill an unstated schema. The Canonical Object Identity module still fills nothing. It parses a name and keeps an empty part as "not stated". The graph builder fills the schema, after the parse and before the key. The Canonical Object Identity module takes no default-schema argument.

## Sources

- "Ownership and user-schema separation in SQL Server" (Microsoft Learn).
- The archived SQL Programmability team posts "Name resolution, default schema, implicit schema", Parts I to III (Microsoft Learn). Part I defines the active default schema. Part III gives the object algorithm, the `sys` first rule for system names, and the cross-Database default schema.
- The operator's confirmation, described in the Context section.

## Evidence

The evidence comes from the seven local caches. The date is 2026-09-30. The graphs have version 7.

- 9845 listed references resolve to the schema of the module or to `dbo`.
- 3107 names are unlisted.
- 3 references resolve to neither schema. All 3 are the common table expression `Table1`. That expression is not a table. A separate change removes those reads.
- No reference names an object that both `S` and `dbo` hold. So the order of the two steps changes no answer today.

## Assumptions

- Name comparison ignores case. SQL Server compares names under the Database collation. A case-sensitive collation is out of scope. A future case-sensitive Database shows where to change.
- Dynamic SQL resolves against the default schema of the login, not the schema of the module. The tool resolves no dynamic SQL target today. A future resolver follows this rule.
- The Microsoft text on a static `EXEC` inside a module is ambiguous. It excludes "dynamic SQL, a.k.a. EXECUTE statements". This rule reads that phrase as dynamic SQL only. A static `EXEC` resolves against the schema of the module first.
- The seven caches hold no unqualified static call from a module outside `dbo`. Both readings of the text give the same answer today. If the shop sees another behavior, one site changes.
- A `db..name` reference uses the default schema of the module schema owner in the other Database. That is `dbo` in this shop. The rule reads no listing of that Database, so nothing proves it.

## Consequences

- The Unproven Schema mark remains in three cases only. [ADR-0035](0035-an-unproven-schema-marks-one-execution-path.md) lists them.
- A rebuilt graph replaces every v7 graph. The graph format version rises to 8. The repair tool rebuilds the graphs, and the index backfill tool rebuilds the indexes.
- A node id changes when a resolved schema replaces an empty schema. The formula of the Path Identity does not change.
- The Object Location Index of a rebuilt cache holds the resolved full keys.
