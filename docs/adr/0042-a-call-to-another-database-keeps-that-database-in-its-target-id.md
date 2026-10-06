# A Call to Another Database Keeps That Database in Its Target Id

**Status:** Accepted
**Date:** 2026-10-06

## Context

The call target rule gave every call target the id `stored_procedure:{schema}.{name}`. The id held no Database. The calls relationship recorded the stated Database in its own `database` field.

A call to another Database can therefore get the id of a listed module of the cache. In the `eFinance` cache, `exec eFinanceD.COMMON.OpeneFinanceKey` got the id `stored_procedure:COMMON.OpeneFinanceKey`. That id is the id of the `eFinance` procedure. `eFinanceD` is a separate Database, not an alias of `eFinance`. The Execution Path builder followed the call by its id. So it used the local definition as evidence for a call to `eFinanceD`. A scan of every cache found ten such calls.

A `db..name` call, for example `exec master..xp_cmdshell`, got the id `stored_procedure:.xp_cmdshell`. Its unresolved path did not show `master`.

## Decision

A call that states another Database, or a linked server, gets a target id that keeps those parts.

- The id is the written parts in the SQL order: `stored_procedure:{database}.{schema}.{name}`. A call through a linked server adds the server: `stored_procedure:{server}.{database}.{schema}.{name}`.
- The id keeps an empty part. So `master..xp_cmdshell` gives `stored_procedure:master..xp_cmdshell`, and its schema stays empty.
- "Another Database" uses the `names_another_database` comparison. The comparison ignores case. There is no alias table.
- A call that states the cache's own Database, or states no Database, keeps the current id. Schema Resolution and the module lookup do not change.
- The Unproven Schema mark on a `db..name` call does not change.
- Table, View, and Function node ids do not change. A table node stays shared, and its relationship records the Database.
- `GRAPH_VERSION` rises from 12 to 13. The read path rejects a v12 graph.

## Consequences

- The new id never equals the id of a listed module. So the Execution Path builder gives an unresolved path with the reason `called_procedure_not_in_graph`. Its `unresolved_targets` shows the Database.
- The table walk of the SP fetcher also stops at the new id, because no node has it.
- The rebuild report tool parses the new id with the same name parser, so it reads the schema and the name without a change.
- The operator rebuilds the SQL caches with the repair tool, and then runs the index backfill.

## Alternatives considered

**Keep the id, and make each reader check the `database` field of the relationship.** Each future reader of a calls target must then repeat the check. The Execution Path builder missed this check, and the SP fetcher missed it too. So a rule that each reader must remember fails. One id that cannot match a local module needs no check.

See [ADR-0036](0036-a-temp-table-belongs-to-the-procedure-that-uses-it.md) and [ADR-0037](0037-an-unstated-schema-resolves-as-sql-server-resolves-it.md).
