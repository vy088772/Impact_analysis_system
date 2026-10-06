# A Read Inside a Non-DML Statement Gives a SELECT Operation

Status: ready-for-agent

This spec records the accepted decisions Q1 through Q9 from the discussion on 2026-10-06.
The source of the problem is `problems.md` in this directory, problem 1.
It covers Impact_analysis_system only.
It creates no implementation tickets.

## Problem Statement

An analyst asks `/find_by_table` which stored procedures read a table.
The answer can omit a procedure that reads the table.
The omission occurs when the procedure reads the table only inside a non-DML statement.

A **non-DML statement** is a T-SQL statement that is not SELECT, INSERT, UPDATE, DELETE, MERGE, or EXEC.
Examples are `IF EXISTS (SELECT ... FROM T)`, `SET @x = (SELECT ... FROM T)`, and `IF dbo.fnCheck(@id) = 1`.

The SQL Text Analysis host makes an operation only for a DML statement or an EXEC statement.
For an IF statement or a WHILE statement, the host keeps the predicate only as text in the branch path.
For a SET, DECLARE, or RETURN statement, the host visits the subquery, but the subquery is not a SELECT statement.
So the host makes no operation, and the SQL Execution Graph has no reads relationship or uses relationship for that object.

A consistency check of 8 SQL caches and 2401 modules found 209 candidate omissions.
Manual review removed 8 candidates as false positives of the check.
The check after the rebuild (ticket 03) found a ninth false positive: `vendors` in `dbo.usp_DevQryContrast_Qry2` (PUR) sits only inside a string that a `set` statement builds, so it is dynamic SQL (problem 4).
So 200 omissions are real.
The confirmed examples are `COMMON.CheckProgramAuth` in eFinance and `dbo.sp_SO_UpdateInvFlag` in PUR.

The same host also parses inline SQL in C# code.
So an inline SQL text such as `IF EXISTS (SELECT ... FROM T) UPDATE ...` loses the read of `T` in the C# Scan Result.

## Solution

A non-DML statement that refers to at least one object gives one operation.
An object is a table, a view, or a user-defined function.
The operation has the operation type `SELECT`, and it reads each object that the statement refers to.

The analyst then sees the omitted procedures in the `/find_by_table` answer and the `/find_by_sp` answer.
Each new operation also ends its own Execution Path.

## User Stories

1. As an analyst, I want `/find_by_table T` to list a procedure that reads `T` inside `IF EXISTS (...)`, so that I can see every procedure that a change to `T` affects.
2. As an analyst, I want `/find_by_table T` to list a procedure that reads `T` inside `IF (SELECT ...) <> ''`, so that a scalar predicate does not hide a read.
3. As an analyst, I want `/find_by_table T` to list a procedure that reads `T` inside `SET @x = (SELECT ... FROM T)`, so that a variable assignment does not hide a read.
4. As an analyst, I want `/find_by_table T` to list a procedure that reads `T` inside `DECLARE @x int = (SELECT ... FROM T)`, so that a declaration with a value does not hide a read.
5. As an analyst, I want `/find_by_table T` to list a function that reads `T` inside `RETURN (SELECT ... FROM T)`, so that a scalar function does not hide a read.
6. As an analyst, I want `/find_by_table T` to list a procedure that reads `T` inside a WHILE predicate, so that a loop condition does not hide a read.
7. As an analyst, I want the graph to record a uses relationship for `IF dbo.fnCheck(@id) = 1`, so that a direct function call in a predicate does not hide the function.
8. As an analyst, I want a function in a predicate to give the same relationships as a function in a SELECT statement, so that predicate references and query references agree.
9. As an analyst, I want `/find_by_sp` to show the reads of a procedure in its predicates, so that the forward answer agrees with the reverse answer.
10. As an analyst, I want a read inside a predicate of a nested IF to carry the branch path of the enclosing IF, so that I see the condition under which the read occurs.
11. As an analyst, I want a read inside an IF predicate to carry the branch path outside that IF, so that the path does not claim that the read occurs only in the THEN branch.
12. As an analyst, I want the source location of a predicate read to cover only the predicate, so that the Path Evidence shows the predicate and not the full THEN body.
13. As an analyst, I want the source location of a SET, DECLARE, or RETURN read to cover the full statement, so that the Path Evidence shows the assignment.
14. As an analyst, I want one operation for one statement that holds two subqueries, so that one statement gives one entry in the Execution Path order.
15. As an analyst, I want a read of a `#temp` table inside a predicate to expand to the base tables behind the writers of that temp table, so that the Temp Table Scope applies to predicate reads as it applies to other reads.
16. As an analyst, I want a statement such as `SET @x = GETDATE()` to give no operation, so that statements without an object do not add empty entries.
17. As an analyst, I want a statement such as `SET @x = (SELECT 1)` to give no operation, so that a subquery without an object does not add an empty entry.
18. As an analyst, I want a schema that the predicate read does not state to resolve as SQL Server resolves it, so that predicate reads follow the same Schema Resolution as other reads.
19. As an analyst, I want a CTE name inside a predicate to give no table read, so that predicate reads follow the same CTE rule as other reads.
20. As an analyst, I want a table variable inside a predicate to give no table read, so that `@t` does not appear as a table.
21. As an analyst, I want an inline SQL text with `IF EXISTS (SELECT ... FROM T)` to give a read of `T` with the access type `SELECT`, so that the C# Scan Result records the read.
22. As an analyst, I want a parsed predicate read in inline SQL to replace the regex fallback relations of the same text, so that the Inline SQL Table Relation rule applies without change.
23. As an operator, I want a SQL cache built before this change to be rejected, so that no answer comes from a graph that omits predicate reads.
24. As an operator, I want the repair tool to rebuild the 8 SQL caches, so that I do not run a full SQL refresh.
25. As an operator, I want the C# Scan Result cache to stay valid, so that I do not rescan every system now.
26. As an operator, I want a C# project to get predicate reads when it is next scanned, so that the inline SQL result improves without a forced rescan.
27. As a maintainer, I want an ADR that explains why a predicate read has the operation type `SELECT`, so that nobody changes it back as a bug.
28. As a maintainer, I want the ADR to record the rejected separate operation type, so that the trade-off is visible.
29. As a maintainer, I want the graph design document to define the new operation source, so that the document agrees with the graph.
30. As a maintainer, I want the consistency check to report only the 9 known false positives after the change, so that I can confirm that the 200 omissions are gone.

## Implementation Decisions

### The rule

- A non-DML statement gives one operation when it refers to at least one object. An object is a table, a view, or a user-defined function.
- The reference can come from a subquery or from a direct function call.
- A non-DML statement that refers to no object gives no operation.
- The rule is general. It does not list statement types. It applies to IF and WHILE predicates, SET, DECLARE, RETURN, PRINT, RAISERROR arguments, and each other non-DML statement.
- The rule changes nothing for DML statements and EXEC statements. Their subqueries already give reads.
- The rule changes nothing for the body of IF, WHILE, and TRY/CATCH. The host still visits the body as before.

### The operation

- The operation type is `SELECT`. The graph stores the operation as a `dml_operation` node, as for each other `SELECT`.
- The operation adds no new field. The source location identifies the statement type through the definition text.
- One statement gives one operation. The operation collects the objects of every subquery and every function call in the statement.
- The operation collects tables, columns, and function references with the same collectors as a `SELECT` statement. So Schema Resolution, the CTE rule, the table-variable rule, and the temp-table rule apply without change.
- For an IF predicate or a WHILE predicate, the source location covers the predicate only. For each other statement, the source location covers the full statement.
- The branch path is the branch path outside the statement. An IF predicate occurs before its branch, so the predicate read does not carry the `IF ...` entry of its own IF.
- The operation takes its sequence from its start offset, as each other operation does. So each later operation of the module can get a higher sequence number.

### Version and rebuild

- `GRAPH_VERSION` rises from 11 to 12. The read path rejects a v11 graph.
- The version history comment states the v12 change and why a v11 graph omits predicate reads.
- The operator rebuilds the 8 SQL caches with the existing repair tool.
- Derived Execution Evidence keys on the graph version, so the version rise invalidates it. No separate step is necessary.
- The C# Scan Result cache version does not change. A C# project that the operator does not rescan keeps its old inline SQL relations. A rescan gives the predicate reads.
- The analyzer host contract version does not change. The host answer keeps the same shape.

### Documents

- A new ADR, ADR-0041, records the rule and the choice of the `SELECT` operation type.
- The ADR records the rejected option: a separate operation type, for example `CONDITION_READ`. The ADR states why: each reader of the operation type then needs a change, and the source location already identifies the statement type.
- The ADR consequences state that the C# Scan Result cache keeps old relations until a rescan.
- The graph design document states that a `dml_operation` of type `SELECT` can come from a non-DML statement.

## Testing Decisions

- A good test sends a SQL text through a public seam and checks the operations or the graph relationships. It does not check the visitor internals.
- The tests use two existing seams. Neither seam is new.
- **Seam 1, SQL Text Analysis with the real host.** Synthetic SQL texts check the rule:
  - IF EXISTS predicate.
  - IF scalar subquery predicate.
  - WHILE predicate.
  - SET with a subquery.
  - DECLARE with a subquery.
  - RETURN with a subquery in a scalar function.
  - A direct function call in an IF predicate.
  - A nested IF: the predicate read of the inner IF carries the branch path of the outer IF only.
  - One statement with two subqueries gives one operation.
  - The source location of an IF predicate read covers the predicate only.
  - `SET @x = GETDATE()` and `SET @x = (SELECT 1)` give no operation.
  - A CTE name and a table variable inside a predicate give no table read.
  - An inline SQL text with `IF EXISTS` gives the read in the C# scan path.
- Prior art for seam 1: the host tests for MERGE and for UPDATE subqueries in the static analyzer host test module. Prior art for the inline path: the inline SQL regex fallback test module.
- **Seam 2, SQL Execution Graph build with real definitions.** Regression tests use two confirmed cases:
  - `COMMON.CheckProgramAuth` reads `COMMON.UserProgram` (EXISTS).
  - `dbo.sp_SO_UpdateInvFlag` reads `POrder` (SET).
- Prior art for seam 2: the MERGE regression test for `usp_SO_Management_Save` in the SQL Execution Graph test module.
- A temp-table case checks that a `#temp` read in a predicate expands through the Temp Table Scope.
- After the rebuild, the operator runs the consistency check script in this directory. The expected result is the 9 known false positives and no other omission:
  - The CTE name candidate.
  - 6 candidates in `dbo.usp_SupplierProfile_Qry_Confirm` (PUR), inside a block comment.
  - 1 candidate in `dbo.spApproveBat` (STC), inside a nested block comment.
  - 1 candidate in `dbo.usp_DevQryContrast_Qry2` (PUR), inside a string that a `set` statement builds.
- The consistency check script does not change.

## Out of Scope

- Problem 4 of `problems.md`: Unresolved Dynamic SQL. It needs its own design.
- The over-report of the Temp Table Scope that `problems.md` problem 2 describes. ADR-0036 makes it a deliberate choice.
- The empty database in the call target of `master..xp_cmdshell`, from `problems.md` problem 3.
- The plain-text password in the source SQL of `dbo.usp_FreightImport_Sure`. The user tells the database owner. It is not a code change.
- Each item above gets its own issue in `.scratch/`. This spec does not create them.
- An expansion of a scalar function call to the tables that the function reads. Today a scalar function gives only a uses relationship from the module, in a SELECT statement too. Only a view or a function in a reads relationship expands to its tables.
- A fix of the consistency check script for nested comments and quotes inside comments.
- A rise of the C# Scan Result cache version and a forced rescan of every system.
- The items under "未涵蓋" in `problems.md`: C# to SQL mapping, read and write direction, column level, and cross-database references.

## Further Notes

- Each new operation is a terminal DML operation. So each one adds an Execution Path. The count of Execution Paths in an answer can increase.
- The sequence numbers of later operations in a changed module can increase. An operation id holds its sequence, so these ids change. The graph version rise rejects each stored id from v11.
- The Inline SQL Table Relation rule keeps regex fallback relations when no operation reads or writes a table. A text that now gives a predicate read has an operation, so its parsed relations replace the fallback relations.
