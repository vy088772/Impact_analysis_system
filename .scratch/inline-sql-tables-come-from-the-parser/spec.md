# Inline SQL Tables Come from the Parser

Status: ready-for-agent

Blocked by: nothing. `.scratch/unstated-schema-resolves-as-sql-server-does/spec.md`
put its CTE and alias fixes in the analyzer host, and this spec reuses them.
Tickets 01 to 09 of that spec are done. Its open ticket 10 changes the path
builder only.

## Problem Statement

An analyst asks which programs read or write a table. For SQL inside C# source
code (inline SQL), the answer comes from regular expressions, not from a SQL
parser. The regular expressions give wrong answers in two directions.

They miss real tables. This is the worse direction, because a missed writer is
worse than an extra one:

- A statement that starts with `WITH` gives no table at all. The parser
  classifies the statement by its first word, finds no known word, and drops
  the whole statement.
- A `MERGE` statement gives no table at all, for the same reason.
- `INSERT INTO t (col1, col2) ...` loses its target `t`. The pattern reads
  `t (` as a function call. ATV holds a text of this form:
  `insert into ManifestNew (R_ID,data) values(...)` gives no table. That
  text is in commented-out C# code, so it is not a real writer (ticket 08).
  The defect follows from the pattern, not from that text.

They report false tables and false writes:

- A CTE name becomes a table. `WITH Recent AS (...) SELECT ... FROM Recent`
  gives a table named `Recent`.
- The target alias of an `UPDATE` becomes a table.
  `UPDATE ord SET ... FROM dbo.Orders ord` gives a table named `ord`. The
  pattern skips a one-letter name, so only an alias of two or more letters
  shows the defect.
- A table name inside a comment or inside a string literal becomes a table.
- Every table in a statement takes the type of the statement. In
  `UPDATE t SET ... FROM t JOIN u`, the table `u` becomes a written table.

Two separate regular expression sets exist, and they disagree. The C# parser
uses one set for the C# Scan Result. The forward direction of `/flow_chain`
uses the other set on the same SQL text. The second set removes comments and
finds `INSERT INTO t (cols)`, but it reads a function as a table. So
`/flow_chain` forward and backward can name different tables for one method.
A code comment in the flow chain builder states that the two paths use "the
same rule". That statement is false.

The ten local C# Scan Results show no false CTE table and no false alias table
today: 606 of 646 inline SQL texts are simple `SELECT` statements. The ten
local Systems are a small part of more than one hundred Systems, so this is
not evidence that the defects are absent. The defects follow from the code.

A second problem is in the code. The analyzer host's SQL command takes file
paths. Its one caller, the graph build, writes each definition to a temporary
file and reads the answer by string keys. This spec adds a second caller, for
inline texts. Without a change, the temporary file code and the key reads
exist twice.

A third problem is in the code that reads the table relations. Each reader
applies its own rules, and the rules do not agree:

- `/find_by_table` resolves an unstated schema before it matches a relation.
  `/flow_chain` backward matches the same relation with no schema resolution.
- `/find_by_table` sets the reason and the Database attribution of an inline
  match in its own code. The attribution has two values there, and three
  values for a Database Invocation.
- The set of write access types exists twice in the analyze service.
- `/flow_chain` forward reads no table relation. It reads another text source
  with the second regular expression set.

This spec changes the reason, the access type, and the Database rule of a
relation. Without a change, each reader gets its own edit.

## Solution

The analyzer host already runs during a C# scan. It already records the
command text of each Database Invocation. The scan now sends each literal
command text to SQL Text Analysis. SQL Text Analysis is a new Python module
that takes SQL texts and returns a typed answer for each text. It runs the
analyzer host's SQL command, the same command that analyzes procedures, views,
and functions. The host parses the text with ScriptDom and returns the tables
that each statement reads and writes. Each table relation takes its own access
type from that answer.

The graph build gets its answer from SQL Text Analysis too. The analyzer host
stays behind SQL Text Analysis as one adapter. The SQL Execution Graph does
not change, and no SQL cache rebuilds.

The regular expressions stay as a marked fallback. They cover the SQL text
that the host does not parse: a text the host could not resolve to a literal,
a text the host did not record, a text that fails to parse, and a text that
parses but gives no read or write. A fallback relation states that it came
from a regular expression, and its access type is `UNRESOLVED`. The analyst
still sees it, and a `write_only` question counts it as not proven.

`/flow_chain` forward reads the same table relations as `/flow_chain` backward
and `/find_by_table`.

Every reader that applies a rule reads the table relations through one new
Python module, the inline table relations module. `/find_by_table` and
`/flow_chain` backward ask it which relations answer a table question.
`/flow_chain` forward and the two table lists of `/analyze` ask it for the
relations of a set of methods.

The C# Scan Result format version rises. Each System rescans locally.

## User Stories

1. As an analyst, I want inline SQL tables to come from the same parser as the SQL Execution Graph, so that one statement gives one answer in both places.
2. As an analyst, I want a CTE name inside inline SQL to never become a table, so that `/find_by_table` does not report a reader of a table that the program never reads.
3. As an analyst, I want the tables inside a CTE body to stay reads, so that the fix removes only the false table.
4. As an analyst, I want the target alias of an inline `UPDATE` or `DELETE` to become the table behind the alias, so that the real table gets the write.
5. As an analyst, I want a table name inside an SQL comment to never become a table, so that commented-out SQL does not give a reader.
6. As an analyst, I want a table name inside an SQL string literal to never become a table, so that a message text does not give a reader.
7. As an analyst, I want each table in a statement to carry its own access type, so that a table the statement only reads is not reported as written.
8. As an analyst, I want `UPDATE t ... FROM t JOIN u` to give `t` as written and `u` as read, so that `write_only` on `u` does not report this program.
9. As an analyst, I want a table that a statement writes to carry only the write, so that inline SQL follows the read and write split of the SQL Execution Graph.
10. As an analyst, I want `INSERT INTO t (cols) SELECT ... FROM s` to give `t` as written and `s` as read, so that the target of an insert with a column list is not lost.
11. As an analyst, I want the ATV `insert into ManifestNew (R_ID,data)`, which is in commented-out C# code, to stay out of `/find_by_table ManifestNew write_only=True` and to add one to its excluded count, so that a text the program never runs is never reported as a proven write.
12. As an analyst, I want a statement that starts with `WITH` to give its tables, so that a CTE query is not dropped.
13. As an analyst, I want a `SELECT ... INTO t` statement to give `t` as written, so that the target of a select-into is found.
14. As an analyst, I want inline SQL that the host cannot parse to still give its tables, so that a parser gap never becomes a missed table.
15. As an analyst, I want a table from the fallback to carry the access type `UNRESOLVED`, so that a regular expression guess is never reported as a proven write.
16. As an analyst, I want a table from the fallback to carry a reason that names the fallback, so that I can tell a parsed table from a guessed table.
17. As an analyst, I want a table from the parser to carry a reason that names the parser, so that the two sources stay separate in every answer.
18. As an analyst, I want a `write_only` question to count the fallback tables it leaves out, so that the answer does not read as a complete list.
19. As an analyst, I want inline SQL built by string concatenation to still give its tables through the fallback, so that dynamic inline SQL is not dropped.
20. As an analyst, I want a `MERGE` statement to give its tables through the fallback, so that a `MERGE` is reported until the host supports it.
21. As an analyst, I want any statement kind that the host parses but does not analyze to use the fallback, so that a future parser gap is reported and not dropped.
22. As an analyst, I want one inline SQL text to give one set of relations, so that a program does not appear twice with a parsed record and a guessed record.
23. As an analyst, I want a parsed table relation to take its Database from the rating of its Database Invocation, so that the inline SQL answer and the stored procedure answer agree on the Database.
24. As an analyst, I want a relation whose Database has candidates to match a question on any Database, so that an incomplete candidate list never hides a program.
25. As an analyst, I want a relation whose Database has candidates to show those candidates in the answer, so that I can judge the Database myself.
26. As an analyst, I want a parsed relation to keep the Evidence Status `not_applicable`, so that an unresolved Database does not remove a known write from `write_only`.
27. As an analyst, I want `/flow_chain` forward to read the same table relations as `/flow_chain` backward, so that both directions name the same tables for one method.
28. As an analyst, I want the screen table list of `/analyze` to use the corrected table relations, so that a screen does not list a CTE name or an alias as a table.
29. As an analyst, I want a `#temp` table and an `@table` variable inside inline SQL to give no table relation, so that the answer keeps the current behaviour for them.
30. As an operator, I want the C# Scan Result format version to rise, so that every C# Scan Result with the old relations reports `scan_cache_stale` until it is rescanned.
31. As an operator, I want to rescan each System locally, with no migration tool, so that the rise costs one rescan and no extra code.
32. As an operator, I want the rescan of the ten local Systems to give at least 545 parsed relations, so that I can check that the host covers the texts it covered in the measurement.
33. As a maintainer, I want the C# Scan Result to keep loading in the companion repository's restricted unpickler, so that the evaluation still runs.
34. As a maintainer, I want the flow chain builder comment about "the same rule" removed, so that no document states a false fact.
35. As a maintainer, I want one ADR to record why inline SQL tables come from the parser and why the regular expressions stay as a marked fallback, so that a later change keeps the reasons.
36. As a maintainer, I want `CONTEXT.md` to define the inline SQL table relation and its two sources, so that every document uses one term.
37. As a maintainer, I want the graph build and the C# scan to get the host's SQL answer from SQL Text Analysis, so that the temporary file code and the key reads exist once.
38. As a maintainer, I want SQL Text Analysis to return typed operations, so that no caller reads the host's answer by string keys.
39. As an operator, I want the SQL Execution Graph to stay equal when the graph build changes to SQL Text Analysis, so that no SQL cache needs a rebuild.
40. As an operator, I want a scan to stop with an error that names the source file and the text when the host fails on one inline text, so that a host defect never becomes a silent regular expression answer.
41. As a maintainer, I want an in-memory adapter of SQL Text Analysis, so that a test of the scan rules runs without `dotnet`.
42. As a maintainer, I want the host contract tests to keep reading the host's raw answer, so that a contract break shows in the host tests.
43. As a maintainer, I want `CONTEXT.md` to define SQL Text Analysis, so that every document uses one term for it.
44. As a maintainer, I want every reader that applies a rule to a table relation to read through the inline table relations module, so that a rule changes in one place.
45. As an operator, I want the move of the readers to the inline table relations module to keep every answer, so that no analyst sees a change before a rule changes.
46. As an analyst, I want `/flow_chain` backward to resolve the unstated schema of an inline table as `/find_by_table` does, so that both answers agree for one relation.
47. As a maintainer, I want one test of a write access type, so that the ranking of a match and `write_only` never disagree.
48. As a maintainer, I want the inline match to use the Database attribution rule of the Execution Path, so that `candidate` has one meaning.
49. As an analyst, I want a parsed relation with no rated Database Invocation to show the Database that the C# parser found, so that a question with no Database keeps its answer of today.
50. As an analyst, I want the `/analyze` screen table list and the shared component table list to keep their answers, so that the new module changes no screen.
51. As an operator, I want the rescan ticket to record the change of the written tables in the companion repository's routing expectations, so that an expectation change has a known cause.

## Implementation Decisions

### SQL Text Analysis

- SQL Text Analysis is a new Python module in the code analyzer package. The
  service package imports the code analyzer package, and not the reverse, so
  the graph build and the C# scan can both import it.
- Its interface has one operation. The caller gives a sequence of SQL texts.
  SQL Text Analysis returns one result for each text, in input order.
- A result holds the operations of the text and the parse errors of the text.
  Both are typed.
- A typed operation holds every field that the host reports for an operation:
  the operation type, the SQL module identity, the sequence, the branch path,
  the conditions, the `WHERE` text, the read tables, the write tables, the
  unresolved write targets, the read columns, the written columns, the
  function references, the call targets, the dynamic SQL mark, and the source
  location. Each object reference is an object name of the Canonical Object
  Identity, with its four parts.
- The source location of a typed operation holds no file path. The path of a
  temporary file never leaves SQL Text Analysis.
- SQL Text Analysis reports progress as a completed count and a total count.
  It reports no name. Each caller turns a count into its own name.
- When the host fails on one text, SQL Text Analysis raises an error that
  holds the index of that text. The error is a kind of analyzer host error.
  Each caller turns the index into its own name: the graph build names the SQL
  module, and the C# scan names the source file and the text.
- SQL Text Analysis has two adapters:
  - The host adapter writes each text to a temporary file and runs the host's
    batch SQL command. It is the only product code that reads the host's SQL
    answer by string keys. It makes the host ready before the first run. It
    alone holds the newline-safe write that keeps the source offsets aligned
    with the text.
  - The in-memory adapter holds a table from a text to its operations. It
    replaces the stub analyzer host of the SQL cache test fixtures. It starts
    no host and writes no file.
- The graph build takes SQL Text Analysis in place of the analyzer host. The
  graph repair tool gives a host to the graph build today, and it changes with
  the graph build.
- The graph build reads no string key of the host's answer. An operation node
  keeps every field it holds today, so the SQL Execution Graph payload stays
  equal. The graph format version stays 8.
- The host's own SQL methods stay public, and the host contract version does
  not change.
- SQL Text Analysis returns what the host reports and removes nothing. A
  `#temp` table stays in the answer, because the graph build makes a node for
  it (ADR-0036). The rule that turns an operation into table relations stays
  in the C# scan.

### The parsed source

- The scan sends each literal command text of a Database Invocation to SQL
  Text Analysis. The host contract does not change.
- When SQL Text Analysis raises an error for a text, the scan stops. The error
  names the source file and the text. This is not a fallback condition: the
  fallback covers a text that the host answers, not a failure of the host.
- The host reads the text as a statement outside a module. The module identity
  is `unknown`, and no module schema applies.
- Each operation that the host returns gives one relation per table:
  - A table in the operation's written tables takes the operation type:
    `INSERT`, `UPDATE`, `DELETE`, or `SELECT_INTO`.
  - A table in the operation's read tables takes `SELECT`, the value an inline
    read carries today.
  - A table that one operation writes carries only the write. The host already
    removes a written table from the read tables of its operation. This keeps
    the SQL Execution Graph rule. The read is not lost: an `UPDATE` or a
    `DELETE` with a `FROM` clause always reads its target.
- A table relation keeps the parts that the statement writes. The
  unstated-schema spec resolves an unstated schema at question time. This spec
  adds no schema resolution.
- A name that starts with `#` or `@` gives no relation. A function reference
  gives no relation. An unresolved write target gives no relation.
- A parsed relation carries the reason `inline_sql_parsed`. Its Evidence Status
  stays `not_applicable`. The Database and the schema carry their own marks,
  so the access type does not wait for them.
- A literal text that is only a procedure name parses to no operation. The
  Embedded Procedure Target already covers it, and it gives no table relation.

### The fallback source

- The C# parser keeps its regular expressions for inline SQL. A relation from
  them carries the reason `inline_sql_regex` and the access type `UNRESOLVED`.
- The fallback applies to a text when one of these conditions is true:
  - The host did not record the text. This covers a text that the host rated
    `dynamic` and a text at a site that the host does not see.
  - The host could not parse the text.
  - The host parsed the text and returned no read and no write. This covers
    `MERGE` and any other statement kind that the host does not analyze.
- A parsed text replaces the fallback relations of the same text. The match
  rule is: the same source file, and the same text after whitespace is
  collapsed. The C# parser records a line number only, not a source offset, so
  the rule compares text.
- The fallback expressions change in four ways:
  - A statement that starts with a word the parser does not classify is kept.
    This covers `WITH` and `MERGE`.
  - `INSERT INTO t (cols)` gives `t`. The function-call guard does not apply to
    the target of `INSERT INTO`.
  - SQL comments are removed before the expressions run.
  - The access type is `UNRESOLVED` for every table.
- The fallback still reads a CTE name as a table. This is accepted. The
  relation carries `UNRESOLVED`, so it never counts as a proven write.

### The Database of a relation

- A parsed relation carries the source span of its Database Invocation. The
  table answer takes the Database, the database candidates, and the Database
  attribution (`resolved`, `candidate`, or `unresolved`) from the gateway's
  rating of that invocation. The gateway rates at question time, as the
  Rating-Time Command Mode requires.
- A fallback relation keeps the Database that the C# parser finds for its
  connection, as today.
- A parsed relation also stores the Database that the C# parser finds for the
  same text. When the parser finds no such text, the stored Database is not
  resolved.
- The rating runs only when the request names a Database, as today. When a
  parsed relation has no rated Database Invocation, the table answer takes the
  stored Database. Its attribution is then `resolved` or `unresolved`. This
  rule covers a request with no Database, and a source span that no rated
  Database Invocation has.
- The table match ignores the Database for a relation with the attribution
  `candidate`, as it does for `unresolved`. The match record carries the
  database candidates and the attribution. The stored procedure path already
  reports a candidate Database this way.

### The table relation format

- The access type is per table. Its values are `SELECT`, `SELECT_INTO`,
  `INSERT`, `UPDATE`, `DELETE`, and `UNRESOLVED`. The old values were per
  statement.
- The relation gains its reason, the source span of its Database Invocation
  (empty for a fallback relation), and the Database fields above.
- The new fields use only built-in types. The companion repository's
  restricted unpickler admits a fixed list of classes, and the relation adds
  no class to it.
- The C# Scan Result format version rises by one. The version comment states
  why: an older result carries per-statement access types from regular
  expressions.

### The inline table relations module

- The inline table relations module is a new Python module in the service
  package. It holds every rule that reads a table relation. The relation stays
  a record of stored fields, and it gains no method.
- The rules cannot be methods of the relation, for two reasons:
  - The table question, the schema resolution at question time, and the rating
    of a Database Invocation are in the service package. The code analyzer
    package holds the relation, and it cannot import the service package.
  - The companion repository loads each class of the code analyzer package as
    an inert record. It reads the stored fields only, so a method of the
    relation does not reach it.
- The module has two queries:
  - The by-table query takes a C# Scan Result, a table question, and the rated
    Database Invocations. It returns one answer for each relation that matches
    the question. An answer holds the relation, the table with its resolved
    schema, the table match, the Database, the database candidates, and the
    Database attribution.
  - The by-method query takes a C# Scan Result and a test of a source file and
    a method name. It returns each relation whose file and method pass the
    test.
- The by-table query resolves an unstated schema before it matches, as Schema
  Resolution outside a module requires. The resolver of the inline schema
  moves from the analyze service into the module.
- Only the module pairs a relation with its rated Database Invocation. It
  pairs them by the source span.
- The Database attribution of an answer comes from the rule that the Execution
  Path builder applies to a Database Invocation. The inline match keeps no
  attribution rule of its own.
- The by-method query holds no ownership rule. Each caller gives its own test:
  - `/flow_chain` forward gives the reachable methods of the matched files.
  - The `/analyze` screen table list gives the actions that the screen owns.
  - The shared component table list gives the entry method of the component.
- The test of a write access type is one function in the table match module.
  The ranking of a match record and `write_only` both call it. The relation
  gains no write test: no reader asks a relation whether it is a write.
- One rule stays in `/find_by_table`: it keeps the strongest inline match of a
  file, and then compares that match with a graph match. That rule compares
  two kinds of record. It is not a rule that reads a relation.
- Three readers apply no rule, and they keep reading the stored fields: the
  relation count of the scan statistics, the merge of the scans of several
  roots, and the HTML report.

### The consumers

- `/find_by_table` builds an inline match from each answer of the by-table
  query. It uses the relation's reason and access type in place of the fixed
  `inline_sql_source_fact` reason and the statement type.
- `write_only` keeps only the write access types, as today. A fallback
  relation carries `UNRESOLVED`, so it drops out and joins the count of
  excluded records.
- `/flow_chain` backward takes its inline relations from the by-table query.
  It gets the schema resolution that `/find_by_table` has. One answer changes:
  a relation that states no schema, and that resolves to `dbo`, no longer
  answers a question that states another schema.
- `/flow_chain` forward takes the tables of the reachable methods from the
  by-method query. The forward builder takes the C# Scan Result, as the
  backward builder does. It no longer extracts tables from the method's SQL
  strings. The `inline_sql_tables` field stays, and it lists the table names
  of those relations.
- The helper that extracts tables from a definition text has no other caller,
  and it goes away. The regular expressions under it stay, because the quick
  single-procedure analyzer uses them.
- The `/analyze` screen table list and the shared component table list take
  their relations from the by-method query. Their ownership rules and their
  answers do not change. They get the corrected relations with the rescan.

### Rollout

- The format version rise makes each C# Scan Result report
  `scan_cache_stale`. The operator rescans each System locally. No migration
  tool exists: an old relation holds no per-table access type to convert.
- The unstated-schema spec landed first. This spec reuses its CTE and alias
  fixes in the host, and it needs no graph rebuild of its own.
- The change of the graph build to SQL Text Analysis lands before the scan
  calls SQL Text Analysis. That change keeps every behaviour, and no SQL cache
  rebuilds.
- The move of `/find_by_table`, the screen table list, and the shared
  component table list to the inline table relations module lands before any
  rule changes. That move keeps every answer.
- `/flow_chain` moves to the module in a separate step, because both
  directions change an answer.
- After the rescan, the operator regenerates the routing expectations of the
  companion repository. The companion repository holds its own set of write
  access types, and it reads the stored access type of each relation. A table
  whose only write evidence is a fallback relation leaves its list of written
  tables. This result is correct: a fallback write is not proven. The
  companion repository does not change.

### Documents

- A new ADR records the decision: inline SQL tables come from the analyzer
  host's SQL command; the regular expressions stay as a fallback with the
  access type `UNRESOLVED`, as ADR-0015 treats an unproven path. It states the
  fallback conditions, including the rule for a statement kind the host does
  not analyze.
- `CONTEXT.md` gains an entry for the inline SQL table relation. The entry
  names its two sources and their reasons.
- `CONTEXT.md` gains an entry for SQL Text Analysis. The new ADR states in one
  sentence that the graph build and the C# scan share it. SQL Text Analysis
  gets no ADR of its own: the change is easy to reverse.
- The `CONTEXT.md` entry for the inline SQL table relation states that every
  reader that applies a rule reads through the inline table relations module.
  The module gets no entry of its own and no ADR: it adds no domain term.
- The header text of the flow chain builder names the extraction that goes
  away. It changes with the extraction.
- The flow chain builder comment that claims "the same rule" is removed with
  the extraction it describes.

## Testing Decisions

- A good test states external behaviour: the table relations a C# source
  produces, and the record that `/find_by_table` or `/flow_chain` returns. No
  test reads a private helper or a regular expression.
- Every behaviour change starts as a failing test.
- Seam 1 is the C# Scan Result. A test scans a small C# source and reads the
  table relations. Most Seam 1 tests use the in-memory adapter of SQL Text
  Analysis and a fake of the host's C# answer, as the program refresh tests
  do. They need no `dotnet`. They cover the rule that turns an operation into
  relations, the fallback conditions, the replacement rule, and the source
  span. One Seam 1 test uses the real host, to show that the scan sends the
  text to the host. The prior art is the program refresh test file, the raw
  SQL command source test file, and the C# analysis gateway test file.
- Seam 2 is the table answer. A test builds a C# Scan Result with table
  relations and asks `/find_by_table` or `/flow_chain`. It covers the reason and
  access type on a record, the `write_only` count, the `candidate` Database
  match, and the agreement of `/flow_chain` forward and backward. The prior
  art is the table match test file and the graph reverse lookup test file.
- Seam 3 is SQL Text Analysis. A test gives a SQL text to the host adapter and
  reads the typed answer. It needs `dotnet`, and it runs the SQL command only.
  It covers what the parser says for a text. The in-memory adapter cannot show
  that: it returns the answer that the test wrote. The prior art is the
  analyzer host test file, whose CTE and alias cases all use a procedure
  definition and not a statement outside a SQL module.
- The cases at Seam 3 are statements outside a SQL module:
  - A CTE query gives no CTE name and keeps the tables in the CTE body.
  - `UPDATE ord ... FROM dbo.Orders ord JOIN dbo.Items it` writes `Orders`,
    reads `Items`, and names no `ord`.
  - A table name in a comment and in a string literal gives no table.
  - `INSERT INTO t (cols) SELECT ... FROM s` writes `t` and reads `s`.
  - `SELECT ... INTO t FROM s` writes `t` with the operation type
    `SELECT_INTO`.
  - A `MERGE` text parses and gives no operation.
  - A text that is not SQL gives a parse error and no operation.
  - A definition with Windows line ends gives source offsets that agree with
    the text.
- The cases at Seam 1 with the in-memory adapter are:
  - A written table takes the operation type, and a read table takes `SELECT`.
    Both carry `inline_sql_parsed`.
  - A `#temp` table, an `@table` variable, a function reference, and an
    unresolved write target give no relation.
  - A text that both sources see gives only the parsed relations.
  - A parsed relation carries the source span of its Database Invocation.
  - A text with a parse error gives fallback relations with `UNRESOLVED`.
  - A text with no read and no write, as a `MERGE` gives, gives fallback
    relations with `UNRESOLVED`, and its target is among them.
  - A concatenated text gives fallback relations with `UNRESOLVED`.
  - An error from SQL Text Analysis stops the scan, and the error names the
    source file and the text.
- The one Seam 1 case with the real host is: a C# source with
  `UPDATE ord ... FROM dbo.Orders ord JOIN dbo.Items it` gives `Orders` as
  `UPDATE` and `Items` as `SELECT`, and no `ord`.
- The graph build tests keep their cases. They give the in-memory adapter to
  the graph build in place of the stub analyzer host.
- The host contract tests stay as they are. They read the host's raw answer by
  string keys, because those keys are the contract.
- The change of the graph build has its own acceptance. The whole suite shows
  no new failure. Then a one-time check rebuilds the graph of each of the
  seven local SQL caches from the definitions in the cache, and compares it
  with the graph on disk. Each pair is equal. The ticket records the result.
  The check adds no tool.
- The inline table relations module gets no seam of its own. Seam 2 covers
  it, through the records of `/find_by_table`, `/flow_chain`, and `/analyze`.
- The cases that the module adds at Seam 2 are:
  - A relation that states no schema, and that resolves to `dbo`, does not
    answer a `/flow_chain` backward question that states another schema.
    `/find_by_table` gives the same result for the same relation.
  - A parsed relation with no rated Database Invocation gives a record with
    the stored Database, and the attribution `resolved` or `unresolved`.
  - The screen table list and the shared component table list give the tables
    they give today.
- The one forward test of inline tables gives its tables as table relations of
  a C# Scan Result. It no longer gives them as SQL strings of a method.
- The move of the readers to the module has its own acceptance. The whole
  suite shows no new failure. Then a one-time check takes each inline table of
  the ten local C# Scan Results, and compares the inline matches of
  `/find_by_table` before and after the move. Each pair is equal. The ticket
  records the result. The check adds no tool, and it runs before the rescan.
- The existing inline SQL table test of the C# parser keeps its case. It now
  covers the fallback expressions and states the `UNRESOLVED` access type.
- Acceptance uses real data. After the rescan of the ten local Systems:
  - `/find_by_table ManifestNew write_only=True` on ATV returns no ATV
    program, and its excluded count is one.
  - At least 545 relations carry `inline_sql_parsed`.
  - The ticket records the count of relations per reason and per access type,
    before and after, and three spot checks.
  - The ticket records the written tables of the regenerated routing
    expectations, before and after.

## Out of Scope

- The regular expressions of the quick single-procedure analyzer. The
  complexity field of the SP definition fetch uses them: 35 of 2198 local
  definitions change their complexity label because of a false table. The
  command-line fallback of the quick analyzer uses them too, and no API reads
  its result. Neither affects which program reads or writes a table.
- `MERGE` support in the analyzer host. The host parses a `MERGE` but returns no
  operation for it, for a procedure and for inline SQL. The seven SQL caches
  hold one `MERGE`, in PUR. A separate change adds it to both, and it needs a
  graph format rise. Until then, inline `MERGE` uses the fallback.
- An updatable CTE in inline SQL, as the unstated-schema spec leaves it out.
- The C# texts that the parser misreads as SQL, such as `UpdateData` or a lone
  `delete`. They give no table today and after this change.
- A change to the host contract, such as a SQL command that takes a text and
  no file. The host adapter keeps the temporary files.
- A second try of each text after a host failure. The host stops a batch at
  the first failed input, so a fallback for one text needs a run for each
  text. The 607 local host texts gave no host failure.
- A move of the host contract tests to SQL Text Analysis.
- The other three copies of the Database attribution rule: in the invocation
  record of the analyze service, in the migration report, and in the gateway.
  They read no table relation.
- The list of SQL texts that the C# parser keeps for each method. After
  `/flow_chain` forward changes, no service code reads it. A later removal
  needs no format version rise, because an old result with one more field
  still loads.
- One ownership rule for `/flow_chain` forward, the screen table list, and the
  shared component table list. Reachable methods, screen actions, and a
  component entry method are three different things.
- A change to the companion repository's set of write access types.
- A rating for a request that names no Database.

## Further Notes

- The facts behind this spec come from the ten local C# Scan Results and the
  seven SQL caches, taken on 2026-09-30:
  - 646 inline SQL texts; 583 give at least one table.
  - 545 of those 583 texts match a literal command text the host recorded, in
    the same file. 30 are in a file where the host recorded only `dynamic`
    texts. 8 have no host record.
  - ScriptDom parsed 607 host texts. 582 parsed. The 25 failures are all the
    lone word `delete`, which is not SQL.
  - 176 of 641 inline relations have no resolved Database.
  - No local relation is a false CTE or alias table. No local write was lost:
    the ATV `ManifestNew` insert, which the session took as a lost write, is
    in commented-out C# code (see the correction below).
- The grilling session behind this spec settled Q1 to Q16. It started from the
  brief `.scratch/unstated-schema-resolves-as-sql-server-does/q18-regex-extraction-brief.md`.
  Two answers changed during the session: Q5 first gave a written table a
  second relation as a read, and then followed the host rule, because the read
  is derivable from the write. Q1 put `MERGE` in scope; Q16 then covers it
  through the fallback.
- A second grilling session on 2026-09-30 added SQL Text Analysis. It settled
  Q1 to Q12. The facts behind it:
  - The graph build reads twelve string keys of an operation, and it puts the
    whole operation in the graph node. A typed answer with read and write
    tables only is not sufficient for it.
  - The host's SQL command takes file paths only. One failed input stops the
    batch. A parse failure is not a failed input: the answer holds it.
  - The Database Invocations of a scan come from the host's C# command. A
    Seam 1 test with no `dotnet` fakes that answer too.
  - 58 test lines read the host's raw SQL answer. They are host contract
    tests.
  - 44 test lines in four test files give a host to the graph build. Eight of
    them test the graph repair tool.
- One answer changed during the second session. Q1 named the new work
  "ticket 00". The issue tracker numbers tickets from 01, so Q7 changed it:
  the new ticket is 01, and the six tickets that exist become 02 to 07.
- The second session gave these inputs to the ticket step:
  - The change of the graph build to SQL Text Analysis is one ticket, and it
    is first. It keeps every behaviour. It carries one Seam 3 case: the
    definition with Windows line ends.
  - The other Seam 3 cases go with the ticket that makes the scan call SQL
    Text Analysis. A failed case there shows a host defect, and a host fix is
    feature work.
- A third grilling session on 2026-09-30 added the inline table relations
  module. It settled Q1 to Q13. The facts behind it:
  - Seven places read the table relations: `/find_by_table`, `/flow_chain`
    backward, the screen table list, the shared component table list, the
    scan statistics, the merge of scans, and the HTML report.
  - The three readers that select by method use three ownership rules.
  - The set of write access types exists twice in the analyze service. Both
    copies read a match record. No reader asks a relation for a write test.
  - The Database attribution rule with three values exists four times, for a
    Database Invocation. The inline match holds a fifth copy with two values.
  - The companion repository's restricted unpickler loads each class of the
    code analyzer package as an inert record.
  - The companion repository holds a third copy of the set of write access
    types. It reads the stored access type of each relation.
  - No test and no companion code reads the reason `inline_sql_source_fact`.
    Two places in the companion repository read `inline_sql_tables`.
  - Four test files build a table relation, one time each. One test asserts
    `inline_sql_tables`.
  - A rating with no request Database can run: it loads no SQL cache. No
    endpoint runs it today. Nothing in this session verified that it gives the
    same Database as a rating with a SQL cache.
- One proposal changed during the third session. The brief put the write
  test, the reason, and the Database attribution on the relation. Q1 put the
  rules in a service module, and Q4 put the write test on the access type.
- Q6 listed `/flow_chain` backward among the readers of the move that keeps
  every answer. Q2 gives backward a new schema resolution, so both cannot
  hold. The session closed with this rule: backward moves with forward, in the
  step that changes answers.
- The third session gave these inputs to the ticket step:
  - The move of `/find_by_table`, the screen table list, and the shared
    component table list is one ticket. It keeps every answer, and it lands
    before the rule changes.
  - `/flow_chain` forward and backward move in one ticket. That ticket depends
    on the move ticket.
  - The rescan ticket gains the routing expectations record.
- The ticket step gave eight tickets. Tickets 01 and 02 are the two moves that
  keep every answer, and they do not depend on each other. The six tickets
  that existed before became 03 to 08. This replaces the numbers that Q7 of
  the second session gave.
- Correction on 2026-10-01, after the rescan of ticket 08: user story 11 and
  its acceptance item first asked for the ATV `ManifestNew` insert in a
  `write_only` answer with the type `INSERT`, as "the real writer". The text
  is on line 131 of `ATV/PO_ManifastUploadV3.aspx.cs`, inside a `//` comment,
  so the program never runs it. The host records no Database Invocation for
  it, and the C# parser reads it from the comment as a fallback relation
  (ticket 09). The live code calls `usp_PO_ManifaseUpload_AddData`, which
  writes `ManifestNew`, but that call has only a candidate Database (`ETON`),
  so its write is not proven (ADR-0015). Story 11 and the acceptance item now
  state the behaviour that is correct for a guess: it stays out of a
  `write_only` answer and adds one to the excluded count. Ticket 08 measured
  that behaviour. The rest of the spec does not change.
