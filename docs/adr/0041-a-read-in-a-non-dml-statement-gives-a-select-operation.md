# A Read in a Non-DML Statement Gives a SELECT Operation

**Status:** Accepted
**Date:** 2026-10-06

## Context

An analyst asks which procedures read a table. A procedure can read the table only inside a non-DML statement. A non-DML statement is a T-SQL statement that is not SELECT, INSERT, UPDATE, DELETE, MERGE, or EXEC. Examples are `SET @x = (SELECT ... FROM T)`, `DECLARE @x int = (SELECT ... FROM T)`, and `RETURN (SELECT ... FROM T)`.

The analyzer host made an operation only for a DML statement or an EXEC statement. A subquery in a SET statement is not a SELECT statement, so the host made no operation. The SQL Execution Graph then had no reads relationship for that table. A consistency check of 8 SQL caches found 201 real omissions, for example `dbo.sp_SO_UpdateInvFlag` in PUR.

## Decision

A non-DML statement that refers to at least one table, view, or user-defined function gives one operation.

- The rule is general. It does not list statement types.
- The operation has the operation type `SELECT`. The graph stores it as a `dml_operation` node.
- The operation collects the tables, columns, and function references of the whole statement with the collectors of a SELECT statement. So Schema Resolution, the CTE rule, and the table-variable rule apply without change.
- One statement gives one operation, even when it holds two subqueries.
- The rule also applies to a DDL statement that refers to an object, for example a CHECK constraint that calls a function.
- A statement that refers to no object, for example `SET @x = GETDATE()`, gives no operation.
- The source location covers the full statement. The branch path is the branch path outside the statement.
- A statement that holds other statements, such as a block, gives its operations through those statements.
- `GRAPH_VERSION` rises from 11 to 12. The read path rejects a v11 graph.

IF predicates and WHILE predicates follow in a later ticket. They use the same operation type.

## Consequences

- Each new operation is a terminal operation, so it adds an Execution Path. The count of paths in an answer can increase.
- The sequence of a later operation in a changed module can increase. An operation id holds its sequence, so these ids change.
- The operator rebuilds the SQL caches with the repair tool.
- The C# Scan Result cache version does not change. A C# project keeps its old inline SQL relations until the operator rescans it.
- A `SELECT` operation can now come from a statement that is not a SELECT statement. The source location shows the statement type through the definition text.

## Alternatives considered

**A separate operation type, for example `CONDITION_READ`.** Each reader of the operation type would need a change. The source location already shows the statement type. So the new type adds a cost and no fact.

See [ADR-0001](0001-sql-execution-graph.md) and [ADR-0037](0037-an-unstated-schema-resolves-as-sql-server-resolves-it.md).
