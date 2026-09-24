# The Analyzer Resolves a DML Target to the Table It Names

Status: needs-triage

This spec records two defects in the SQL analyzer host. The
`canonical-object-identity` work found both at ticket 06 and did not fix them,
because one step of that work carries one behaviour change. Its Out of Scope
section points here. This spec has not been through a grilling session. Treat
the direction under "Solution" as a proposal, not a decision.

## Problem Statement

An analyst asks which programs write one table. The answer can omit a stored
procedure that writes that table with a literal `UPDATE` or `DELETE`. The
analyst cannot see that anything is missing.

A second, smaller defect adds table nodes that no Database holds. They make
the graph noisier, and they can give a false match when a real table has the
same name.

### Defect 1: an alias becomes the written table

T-SQL lets an `UPDATE` or `DELETE` name an alias as its target. The `FROM`
clause of the same statement binds that alias to a real table:

```sql
UPDATE A SET Status = 1
FROM Annual AS A INNER JOIN wrkAnnual AS W ON A.AnnualYear = W.AnnualYear
```

The host reads the target fragment alone. It records `A` as the written table,
and it records `Annual` as a read. The graph builder then creates the table
node `table:dbo.A` and a `writes` relationship to it. No relationship says that
this procedure writes `Annual`.

This loses a write. ADR-0012 prefers an over-reported write to a lost one.

### Defect 2: a common-table-expression read becomes a table read

The host drops a read whose bare name matches a common table expression. It
reads the common-table-expression names only from the fragment it walks. One
statement's common-table-expression bodies are one fragment, and its main
query is another. So:

- A read of `Y` in the main query of `WITH Y AS (...) SELECT ... FROM Y` stays
  a table read. The graph builder creates `table:dbo.Y`.
- A read of `dbo.X` inside the body of `Y` is dropped when the same statement
  also defines a common table expression `X`. If `dbo.X` is a real table, that
  read is lost.

The same fragment rule is likely to affect an `UPDATE` or `DELETE` whose target
is a common table expression. That write lands on a node named after the
common table expression, not on the base table. This is not measured yet.

## Measurement (2026-09-24, the five caches on this machine)

The graphs were repaired to graph version 5 at ticket 06. The count used a
script over each cache file. It is a heuristic: it matches the target name
against an alias in the text after the first `FROM` of the operation.

- Only PUR and STC hold defect 1. In PUR, 184 `UPDATE` or `DELETE` operations
  write an alias of a `FROM` table. 93 of them hide a real listed table: 42
  tables in 51 modules. For 37 (procedure, table) pairs the graph records no
  write of that table at all. Examples: `usp_Annual_PUR_AnnualExpand_Expand`
  writes `Annual`, `usp_Evaluate_PilotRequoteIssue_Publish` writes `POrder`,
  and `usp_CDCU_RMPriceCount_Delete` writes `RMPriceMaster`. STC holds one
  operation, which writes `GCD` through an alias.
- The rest of the 184 hide a temp table, such as `#Data`. Those writes feed the
  temp-table lineage expansion, so they can hide a base-table read as well.
- Only PUR holds defect 2. It has 22 table nodes that are common-table-expression
  names, with 193 direct reads in 114 modules. The temp-table lineage adds 2774
  derived reads to them.

A pinned host test exists for defect 2:
`test_a_common_table_expression_drops_a_schema_qualified_read_of_the_same_bare_name`
in `tests/test_static_analyzer_host.py`. A fix makes it fail first. That is the
signal to update this spec and the `canonical-object-identity` Out of Scope
section.

## Solution (proposal)

- The host builds one binding table for each DML statement, from its `FROM`
  clause: each alias to the reference it names, with all four name parts. An
  `UPDATE` or `DELETE` target that names an alias records the bound reference
  as the written table. The bound reference leaves the read list only when the
  statement does not also read it elsewhere.
- The host collects the common-table-expression names of the whole statement
  once. It passes the same set to every fragment of that statement: the main
  query, each body, and the target.
- A target or a read that names a common table expression records nothing
  itself. Whether the host follows the expression to its base tables is an open
  question below.
- The contract version and the graph version rise. The repair tool rebuilds the
  graphs from the cached definitions, with no SQL Server.

## Open questions

1. Does a write through an updatable common table expression record the base
   table of the expression? That needs the host to resolve the expression's
   own `FROM` clause.
2. Should a read of `dbo.X` inside a body still be dropped when the statement
   defines a common table expression `X`? T-SQL cannot qualify a common table
   expression name, so a schema-qualified read always names a real object.
3. Is the alias count above exact? A test over the real host output, not a
   text heuristic, should state it before a fix lands.
4. Does this land before or after Step 2b of `canonical-object-identity`? Step
   2b reads the database from each relationship. This fix changes which
   relationship a write produces.
