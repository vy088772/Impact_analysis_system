# An Unstated Schema Resolves as SQL Server Resolves It

Status: ready-for-agent

This spec covers two repositories. This repository holds the analysis service.
The companion repository, `llamaindex-spec-rag`, holds the orchestrator and the
evaluation code. Only this repository changes code. The companion repository
regenerates one expectation file.

## Problem Statement

An analyst asks which programs read or write a table, and which Execution Paths
a program reaches. The answer is wrong in four ways today.

First, a reference that states no schema carries no schema at all. The
canonical-object-identity work decided never to fill `dbo`, because nothing in
the source text proves the schema. So `Delete UserProgram` inside
`COMMON.ModuleList_Update` gives a target with an empty schema. The table match
then matches that target against every schema and marks it Unproven Schema.
The analyst sees a mark on almost every answer: 9845 references in the seven
local caches state no schema. Yet SQL Server resolves each of them to exactly
one object, by a fixed rule.

Second, an unqualified procedure call links to every listed procedure with that
bare name. One call can then give several Execution Paths, and at most one of
them is true. ADR-0035 rejects that shape for a table target, so the two rules
disagree.

Third, the analyzer reads a common table expression (CTE) as a table. In
`WITH Table1 AS (...) SELECT ... FROM Table1`, the graph records a read of a
table named `Table1`. The seven caches hold 231 such reads, and the temp table
lineage carries some of them further. One of them names a real table:
`EOR.AEBudgetLog_Summary_Qry` reads the CTE `Table1`, and eFinance lists the
table `test.Table1`. `/find_by_table test.Table1` therefore reports a reader
that never reads that table.

Fourth, the analyzer takes the target of an `UPDATE` or a `DELETE` as written.
In `update B1 ... from BSPL.BudgetBalanceSheet B1`, the graph records a write to
a table named `B1`. The real table stays a read. The seven caches hold 330
such writes, and 80 of them hide a write to a real table. A `write_only`
question then misses a real writer. A missed writer is worse than an extra one.

The operator confirmed how this shop resolves a name. Every login has the
default schema `dbo`. Inside a module in schema `S`, SQL Server looks for
`S.name`, then `dbo.name`, and fails when neither exists. The seven caches
agree: every listed target that states no schema resolves by this rule, with
no exception once the CTE defect is removed.

## Solution

The graph builder resolves every reference that states no schema, by the rule
SQL Server applies. A resolved schema is proven, so it carries no Unproven
Schema mark. Each reference records how its schema was found. The Unproven
Schema mark stays only where the rule cannot decide.

The analyzer stops reading a CTE name as a table, and it writes the object an
`UPDATE` or `DELETE` alias names instead of the alias.

The graph format version rises to 8. The repair tool rebuilds every local
graph, and the index backfill tool rebuilds every index. A rebuilt graph
invalidates every stored Derived Execution Evidence file. The fix for that last
point already landed before this spec (commit `08dd048`).

## User Stories

1. As an analyst, I want a reference that states no schema to take the schema SQL Server would take, so that the answer names one table and not every table with that bare name.
2. As an analyst, I want a resolved schema to carry no Unproven Schema mark, so that the mark means "nothing can decide" again.
3. As an analyst, I want `Delete UserProgram` inside `COMMON.ModuleList_Update` to write `COMMON.UserProgram`, so that `/find_by_table COMMON.UserProgram` reports that writer as proven.
4. As an analyst, I want `Delete UserProgram` inside a `dbo` module to write `dbo.UserProgram`, so that `/find_by_table COMMON.UserProgram` does not report it.
5. As an analyst, I want a module's own schema checked before `dbo`, so that the rule matches SQL Server inside a procedure, a view, and a function.
6. As an analyst, I want a name that exists in neither the module's schema nor `dbo` to keep the Unproven Schema mark, so that an unlisted or broken reference is reported and not dropped.
7. As an analyst, I want a name that the cache does not list at all to keep the Unproven Schema mark, so that a temp table or an object of another Database is not guessed.
8. As an analyst, I want an unqualified procedure call to reach one procedure, so that one call gives one Execution Path.
9. As an analyst, I want an unqualified call that no listed procedure answers to keep one path with the mark, so that one unknown fact stays one fact.
10. As an analyst, I want a view read inside a module to resolve by the same rule, so that the lineage of a view starts from the right view.
11. As an analyst, I want a reference inside a view or a function to resolve against that view's or that function's own schema, so that the lineage below it is right.
12. As an analyst, I want the lookup to cross object kinds inside one schema, so that `FROM X` finds a view `S.X` before a table `dbo.X`, as SQL Server does.
13. As an analyst, I want an unqualified `sp_` or `xp_` name that the cache does not list to resolve to the `sys` schema, so that a system procedure never becomes a fake `dbo` node.
14. As an analyst, I want an unqualified `sp_` name that the cache does list to link to that listed procedure, so that a user procedure with that prefix is still found.
15. As an analyst, I want a `db..name` reference to a Database with no local cache to keep the Unproven Schema mark, so that no listing is assumed.
16. As an analyst, I want each resolved reference to record its schema source (`written`, `module_schema`, `default_schema`, or `system`), so that I can tell a written schema from a resolved one.
17. As an analyst, I want every `/find_by_table` record to carry the schema source, so that the answer itself shows how its schema was found.
18. As an analyst, I want an inline C# SQL table that states no schema to resolve to `dbo` when that Database lists `dbo.name`, so that the C# answer follows the same rule.
19. As an analyst, I want an inline C# SQL table that `dbo` does not hold to keep the mark, so that the C# answer does not guess.
20. As an analyst, I want the inline C# SQL rule to read the Object Location Index, so that the question never opens a whole cache.
21. As an analyst, I want a C# call to a procedure that states no schema to resolve to `dbo`, so that the SP Catalog follows the same rule.
22. As an analyst, I want the quick single-procedure analyzer to take the stated schema, else `dbo`, so that it follows the same rule and no longer picks "the one schema that holds it".
23. As an analyst, I want a CTE name to never become a table read, so that `WITH X AS (...) SELECT ... FROM X` reads only the tables inside the CTE.
24. As an analyst, I want a CTE name to win over a real table with the same name inside its statement, so that `test.Table1` no longer reports `EOR.AEBudgetLog_Summary_Qry`.
25. As an analyst, I want the CTE rule to hold for `SELECT`, `SELECT ... INTO`, `INSERT`, `UPDATE`, and `DELETE`, so that no statement kind keeps the defect.
26. As an analyst, I want a recursive CTE and several CTEs in one statement to obey the same rule, so that no CTE shape keeps the defect.
27. As an analyst, I want the tables that a CTE body reads to stay reads, so that the fix removes only the false read.
28. As an analyst, I want an `UPDATE` or `DELETE` alias of a table to write that table, so that `update B1 ... from BSPL.BudgetBalanceSheet B1` writes `BSPL.BudgetBalanceSheet`.
29. As an analyst, I want an alias target that states no schema to resolve by the same schema rule, so that the write names one table.
30. As an analyst, I want an alias of a `#temp` table to write that temp table node, so that the temp table lineage still works.
31. As an analyst, I want an alias of an `@table` variable to write nothing, as a direct write to that variable does today, so that no fake table appears.
32. As an analyst, I want an alias of a subquery or a CTE to record an unresolved target, so that the analyzer never guesses the table behind it.
33. As an analyst, I want a written table to stop counting as a read too, so that the fix keeps the current read and write split.
34. As an analyst, I want a `write_only` question to find the 80 writers that an alias hid, so that no real writer is missed.
35. As an operator, I want the graph format version to rise to 8, so that every graph with the old rule is rejected until it is rebuilt.
36. As an operator, I want the repair tool to rebuild every graph without SQL Server, so that the rise costs seconds and no rescan.
37. As an operator, I want the index backfill tool to run after the repair, so that every Object Location Index holds the resolved full keys.
38. As an operator, I want a rebuilt graph to invalidate every stored Derived Execution Evidence file, so that no answer comes from an old graph. (Done in `08dd048`.)
39. As an operator, I want a report of what the rebuild changed in each cache, so that I can check the scale before I trust the answers.
40. As an operator, I want the report to count resolved schemas, removed CTE reads, corrected alias writes, and remaining Unproven Schema marks, so that each fix shows its own effect.
41. As an operator, I want the default schema to be one constant, `dbo`, so that no per-System setting has to be kept up.
42. As a maintainer, I want one ADR to record the rule, its source, and its evidence, so that the reversal of "never fill `dbo`" keeps its reasons.
43. As a maintainer, I want ADR-0035 to state the three cases that still carry the mark, so that the two ADRs agree.
44. As a maintainer, I want `CONTEXT.md` to define Schema Resolution, so that every document uses one term.
45. As a maintainer, I want the canonical-object-identity spec to point to this spec where Step 2b is replaced, so that a reader of the old spec finds the new rule.
46. As a maintainer, I want the ADR to state that name comparison ignores case, so that a future case-sensitive Database shows where to change.
47. As a maintainer, I want the ADR to state that dynamic SQL resolves against the user's default schema, so that a future dynamic SQL resolver follows SQL Server.
48. As a maintainer, I want the ADR to record that the source text for a static `EXEC` inside a module is ambiguous, so that one site changes if the shop sees another behaviour.
49. As an evaluator, I want the companion repository's routing expectations regenerated from the rebuilt caches, so that the evaluation measures the new answers.
50. As an evaluator, I want the regenerated file's changes reviewed against this spec's predictions, so that an unexpected change becomes its own ticket.

## Implementation Decisions

### The resolution rule

- The rule follows the SQL Server name resolution that Microsoft documents. The
  order is: the `sys` schema for a system name, then the active default schema,
  then `dbo`. The active default schema is the module's own schema for a
  reference inside a procedure, a view, or a function. It is the login's
  default schema everywhere else. This shop's login default schema is `dbo`.
- The default schema is one constant, `dbo`. No per-Database or per-System
  setting exists.
- The lookup reads the cache's object listing. It crosses object kinds: one
  schema holds one namespace for tables, views, procedures, and functions. The
  seven caches hold no name that two kinds share inside one schema.
- A reference inside a module in schema `S` resolves to `S` when the listing
  holds `S.name`, else to `dbo` when the listing holds `dbo.name`.
- A reference outside a module resolves to `dbo` when the listing holds
  `dbo.name`. Inline C# SQL and a C# call to a procedure are outside a module.
- An unqualified name that starts with `sp_` or `xp_` resolves to `sys` when the
  listing holds that name in neither `S` nor `dbo`. SQL Server checks `sys`
  first; the listing holds no `sys` object, so a listed user procedure with that
  name still wins. Microsoft discourages that prefix for user procedures.
- A name that the listing does not hold in `S` or `dbo` keeps an empty schema
  and the Unproven Schema mark. This covers a temp table, a table variable, an
  object of another Database, and a broken reference.
- A `db..name` reference keeps an empty schema and the mark when that Database
  has no local cache. Microsoft states that the other Database uses the module
  schema owner's default schema there, which is `dbo` in this shop. A later
  change can resolve it against that Database's cache.
- A resolved schema is proven. It carries no Unproven Schema mark and does not
  lower the Evidence Status.
- A static `EXEC` inside a module resolves like any other statement, against the
  module's schema first. The Microsoft text excludes "dynamic SQL, a.k.a.
  EXECUTE statements". This spec reads that as dynamic SQL only. The seven
  caches hold no unqualified static call from a non-`dbo` module, so both
  readings give the same answer today.
- Name comparison ignores case, as the Canonical Object Identity rule does.
  SQL Server compares names under the Database collation. A case-sensitive
  collation is out of scope.

### The schema source

- Every read, write, call, and function reference in the graph records a
  schema source. The values are `written`, `module_schema`, `default_schema`,
  `system`, and `unresolved`. The value sits on the relationship, beside the
  Database the relationship states.
- A table match record from `/find_by_table` carries the same field under the
  same name. A located-database row does not; the index keeps full keys only.

### The graph builder

- The graph builder resolves each reference when it adds an operation. It needs
  the module's schema and the listing, and it has both.
- The resolved schema becomes the node's schema. The node id follows from it,
  as for a written schema.
- The call rule changes. An unqualified call links to the one procedure the rule
  names. It no longer links to every listed procedure with that bare name. This
  closes the open decision that the canonical-object-identity spec recorded
  against ADR-0035.
- A View or Function read resolves by the same rule before the builder looks for
  a listed node.
- The graph format version rises to 8. The version comment states why: a v7
  graph gives a no-schema target an empty schema and marks it.

### The analyzer host

- The CTE names of a statement come from the whole statement, including its
  `WITH` clause. The main query, the `INSERT` source, and the `UPDATE` and
  `DELETE` `FROM` clauses all skip those names. Today only the fragment being
  walked supplies them, so the main query never sees them.
- A CTE name wins over a real object with the same name inside its statement.
- The target of an `UPDATE` or a `DELETE` that names an alias of the `FROM`
  clause becomes the object behind that alias. The analyzer then treats it as a
  direct write to that object:
  - A real table: a write to that table, with its written parts.
  - A `#temp` table: a write to that temp table.
  - An `@table` variable: no write, as a direct write to a variable gives today.
  - A subquery or a CTE: an unresolved target.
- The written object stops counting as a read, as the current read and write
  split does for a direct write.

### The C# side

- The SP Catalog resolves a C# call that states no schema to `dbo` when the
  catalog holds `dbo.name`. Otherwise the call keeps the Unproven Schema match
  reason.
- The quick single-procedure analyzer takes the schema the name states, else
  `dbo`. Its query for "the one schema that holds the name" is removed. The
  `schema` argument keeps no default, so a missed caller raises `TypeError`.
- The inline C# SQL table match resolves a target that states no schema at
  question time. It asks the Object Location Index of the connection's Database
  whether `dbo.name` exists. It opens no cache.

### Rollout

- The local caches rebuild in this order: repair tool, index backfill tool.
- A rebuilt graph invalidates every stored Derived Execution Evidence file.
  The validity stamp holds the graph version beside the Scan Record's save
  time. This landed before this spec, in `08dd048`.
- The companion repository regenerates its routing expectations from the
  rebuilt caches. It changes no code: it compares names by bare key and reads
  no schema.
- Another operator machine runs the repair tool and the index backfill tool
  once.

### Documents

- A new ADR, 0037, records the rule, the Microsoft sources, the operator's
  confirmation, and the evidence from the seven caches. It states what it
  reverses: the canonical-object-identity decision never to fill an unstated
  schema.
- ADR-0035 gains an amendment. The Unproven Schema mark stays for three cases
  only: a name the listing does not hold, a `db..name` reference to a Database
  with no cache, and a name that neither the module's schema nor `dbo` holds.
- `CONTEXT.md` gains a Schema Resolution entry. The Canonical Object Identity
  entry keeps its keys and states that a reference is resolved before it is
  keyed. The Unproven Schema entry lists the three cases.
- The canonical-object-identity spec gains one line at its top that names this
  spec as the replacement of Step 2b's "never fill `dbo`".

## Testing Decisions

- A good test states external behaviour: the graph a definition produces, the
  record `/find_by_table` returns, the reference the analyzer host reports. No
  test reads a private helper or a node index.
- Every behaviour change starts as a failing test.
- The analyzer host seam covers the CTE fix and the alias fix. The prior art is
  the analyzer host test file, which feeds SQL text to the host and reads the
  reported references. It needs `dotnet`.
- The graph builder seam covers the resolution rule. The prior art is the graph
  builder test file and the shared cache fixture module, which build a cache
  payload with a listing and a graph.
- The table match seam covers the schema source on a record and the inline C#
  SQL rule. The prior art is the table match test file (Seam 1 of the
  canonical-object-identity spec).
- The C# analysis gateway tests cover the SP Catalog rule. The unstated schema
  test file covers the quick analyzer.
- Two real cases become tests, with their definition text trimmed to the
  statement that matters: `EOR.AEBudgetLog_Summary_Qry` for the CTE, and
  `BSPL.sp_BSprocess` for the alias.
- The golden `path_id` test stays unedited. A resolved schema changes node ids,
  not the Path Identity formula; a changed golden value is a defect.
- Acceptance adds a rebuild report. Before and after the repair, each cache
  counts resolved schemas by schema source, CTE reads, alias writes, and
  remaining Unproven Schema marks. The ticket records the numbers and three
  spot checks. The expected scale: about 9800 resolved schemas, 231 CTE reads
  removed, and 330 alias writes corrected.
- The fixture shape check keeps its rules. A test that needs a schema source
  states it through the fixture module.

## Out of Scope

- An updatable CTE: `WITH c AS (SELECT ... FROM T) UPDATE c ...` writes `T`. The
  seven caches hold none. The analyzer records an unresolved target, and no
  table is guessed.
- The CTE and alias defects in the regex extraction of inline C# SQL and of the
  quick analyzer's fallback. That extraction is a separate mechanism. A
  separate brief describes it.
- A trigger. The listing holds no trigger, so no trigger resolves.
- Dynamic SQL. The tool does not resolve an `EXEC(@sql)` target today. When it
  does, the names inside it resolve against the login's default schema, not
  the module's schema.
- A case-sensitive collation.
- A synonym. The listing holds none.
- A `db..name` reference to a Database that has a local cache. It keeps the
  mark in this spec.

## Further Notes

- Sources for the rule: "Ownership and user-schema separation in SQL Server"
  (Microsoft Learn), and the archived SQL Programmability team posts "Name
  resolution, default schema, implicit schema", Parts I to III (Microsoft
  Learn). Part I defines the active default schema. Part III gives the object
  algorithm, the `sys` first rule for system names, and the cross-Database
  default schema.
- Evidence from the seven local caches, taken on 2026-09-30 from v7 graphs:
  9845 listed references resolve to the module's schema or `dbo`, 3107 names
  are unlisted, and 3 references resolve to neither. All 3 are the CTE
  `Table1`. No reference names an object that both `S` and `dbo` hold.
- The grilling session behind this spec settled Q1 to Q30. Q18 (the regex
  extraction) and Q30 (the evidence invalidation) left this spec: Q18 as a
  brief, Q30 as the commit `08dd048`.
