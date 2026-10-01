# Inline SQL Tables Come from the Parser

**Status:** Accepted
**Date:** 2026-10-01

## Context

An analyst asks which programs read or write a table. Inline SQL is SQL text inside C# source code. For inline SQL, the C# parser found the tables with regular expressions. For a stored procedure, a view, or a function, the SQL Execution Graph finds the tables with the analyzer host's SQL command. That command parses the text with ScriptDom.

The regular expressions missed real tables. A missed writer is worse than an extra writer:

- A statement that starts with `WITH` or `MERGE` gave no table. The parser dropped each statement whose first word it did not classify.
- `INSERT INTO t (col1, col2) ...` gave no `t`. The pattern read `t (` as a function call. ATV holds a text of this form: `insert into ManifestNew (R_ID,data) values(...)`. That text is in commented-out C# code, so it is not a real writer.

The regular expressions also gave false tables and false writes:

- A CTE name became a table.
- The target alias of an `UPDATE` became a table. In `UPDATE ord SET ... FROM dbo.Orders ord`, the table was `ord`.
- A table name inside an SQL comment or inside an SQL string literal became a table.
- Each table took the type of its statement. In `UPDATE t SET ... FROM t JOIN u`, the table `u` became a written table.

`/flow_chain` forward used a second set of regular expressions on the same text. The two sets disagreed, so forward and backward could name different tables for one method.

The ten local C# Scan Results gave these facts on 2026-09-30:

- The scans hold 646 inline SQL texts. 583 of them give at least one table.
- 545 of the 583 texts match a literal command text that the host recorded in the same file. 30 texts are in a file where the host recorded only `dynamic` texts. 8 texts have no host record.
- The host received 607 recorded texts, and 582 of them parsed. Each of the 25 failures is the lone word `delete`, which is not SQL.
- The scans hold 641 inline relations, and each one has the statement type `SELECT`. 176 of them have no resolved Database.
- No local relation is a false CTE table or a false alias table. No local write was lost. The ATV `ManifestNew` insert first looked like a lost write, but it is in commented-out C# code (correction of 2026-10-01, after the rescan).

The ten local Systems are a small part of more than one hundred Systems. So the local data does not show that the defects are absent. The defects follow from the code.

## Decision

Inline SQL tables come from the analyzer host's SQL command. The regular expressions stay as a marked fallback. The graph build and the C# scan share SQL Text Analysis, so both read one typed answer of the host's SQL command.

### The parsed source

- The C# scan sends each literal command text of a Database Invocation to the host. It skips the literal text of a stored procedure invocation, because that text is a procedure name.
- The host reads each text as a statement outside a SQL module.
- Each table of an operation gives one relation with its own access type. A written table takes the operation type: `INSERT`, `UPDATE`, `DELETE`, or `SELECT_INTO`. A read table takes `SELECT`.
- A table that an `UPDATE` or a `DELETE` operation writes carries only the write. The host removes that table from the read tables of the operation. The SQL Execution Graph has the same rule.
- The read is not lost. An `UPDATE` or a `DELETE` must find the rows that it changes, so the write includes the read.
- A name that starts with `#` or `@` gives no relation. A function reference and an unresolved write target give no relation.
- A parsed relation carries the reason `inline_sql_parsed` and the source span of its Database Invocation. Its Evidence Status stays `not_applicable`.
- A parsed relation takes its Database from the rating of its Database Invocation. With no rated invocation, it takes the Database that the C# parser found for its connection.
- When the host fails on one text, the scan stops. The error names the source file and the text. A host failure is not a fallback condition.

### The fallback source

- The C# parser keeps its regular expressions. Each relation from them carries the reason `inline_sql_regex` and the access type `UNRESOLVED`.
- The fallback relations of a text stay when one of these three conditions is true:
  1. The scan did not send the text to the host. The host rated the text `dynamic`, or the host does not see the call site.
  2. The host reports a parse error for the text.
  3. The host parses the text, and no operation of the text reads or writes a table.
- Condition 3 covers `MERGE`. It also covers each statement kind that the host does not analyze, now or later. So a gap in the host gives a fallback relation, and never a missed table.
- The three conditions apply to a whole text, not to one statement of the text.
- A parsed text replaces the fallback relations of the same text. Two texts are the same when they are in one source file and have one match key. The match key is the text after the scan removes SQL comments and `--`, and collapses whitespace. The C# parser records a line number and no source offset, so the rule compares text.
- The fallback expressions changed in four ways:
  - A statement that starts with `WITH` or `MERGE` stays. Other unknown first words still drop the statement, because prose that contains `select` would give a false table.
  - `INSERT INTO t (cols)` gives `t`.
  - The expressions remove SQL comments before they find tables.
  - Each table has the access type `UNRESOLVED`.
- The fallback still reads a CTE name as a table. This is accepted, because `UNRESOLVED` never counts as a proven write.

### What this adds to ADR-0015

ADR-0015 reports an unproven Execution Path and does not drop it. This decision applies the same rule to an inline SQL table relation. A regular expression guess proves no read and no write, so its access type is `UNRESOLVED`. `/find_by_table` still reports the relation. A `write_only` question leaves it out and adds it to the count of excluded records. An unproven Execution Path carries the mark in its Evidence Status. A fallback relation keeps the Evidence Status `not_applicable`, and its access type and its reason carry the mark.

## Consequences

- The C# Scan Result format version rose. Each System rescans locally. No migration tool exists, because an old relation holds no per-table access type.
- One inline SQL text gives one set of relations. A program never appears twice, with a parsed record and a guessed record.
- A text that holds a `SELECT` and a `MERGE` counts as parsed, because the `SELECT` reads a table. The fallback does not apply to it, so the `MERGE` target is missed.
- A text whose only table is a `#temp` table counts as parsed. It gives no relation and no fallback relation.
- The companion repository reads the stored access type of each relation with its own set of write access types. `UNRESOLVED` is not in that set. So a table whose only write evidence is a fallback relation leaves its list of written tables. This result is correct, because a fallback write is not proven.
- `MERGE` support in the host is a separate change. It needs a graph format rise. Until then, an inline `MERGE` uses the fallback.
- The quick single-procedure analyzer keeps its own regular expressions. This decision does not change them.

## Alternatives considered

**Fix the regular expressions and keep them as the only source.** A regular expression cannot find a CTE name, an alias, or the access type of each table without a parser. The SQL Execution Graph already has a parser that answers these questions.

**Remove the regular expressions.** A text that the host does not parse would then give no table. This includes dynamic SQL, `MERGE`, and each future gap in the host. A missed table is worse than a marked guess.

**Give a written table a second relation as a read.** The read follows from the write, so the second relation adds no fact. It would also break the read and write split of the SQL Execution Graph.

**Keep the statement type on a fallback relation.** A guess would then count as a proven write in a `write_only` answer.

See [ADR-0015](0015-an-unproven-execution-path-is-reported-not-dropped.md) and [ADR-0001](0001-sql-execution-graph.md).
