# 07 — The documents record the decision

**What to build:** A maintainer reads why inline SQL tables come from the parser and why the regular expressions stay. A new ADR records the decision, the fallback conditions (including the rule for a statement kind that the host does not analyze), the `UNRESOLVED` access type of a fallback relation with its link to ADR-0015, and the facts from the ten local C# Scan Results. The ADR states in one sentence that the graph build and the C# scan share SQL Text Analysis. `CONTEXT.md` gains an entry for the inline SQL table relation and an entry for SQL Text Analysis.

See "Documents" and user stories 35, 36, and 43 in the spec.

**Blocked by:** 01, 03, 04, 05, 06 (each document states behaviour the code must already have).

**Status:** done

- [x] The ADR takes the next free number and states what it adds to ADR-0015.
- [x] The ADR lists the three fallback conditions.
- [x] The ADR states that a written table carries only the write, and why the read is not lost.
- [x] The ADR states in one sentence that the graph build and the C# scan share SQL Text Analysis. SQL Text Analysis gets no ADR of its own.
- [x] The `CONTEXT.md` entry for the inline SQL table relation names its two sources, and it uses the reasons `inline_sql_parsed` and `inline_sql_regex` as the code does.
- [x] That entry states that every reader that applies a rule reads through the inline table relations module. The module gets no entry of its own and no ADR.
- [x] `CONTEXT.md` gains an entry for SQL Text Analysis.
- [x] Every statement in the documents agrees with the code. Check each one against the code, not against the spec only.

**Notes:**

Files this ticket changed (other tickets run in parallel; these are the only ones):

- `docs/adr/0039-inline-sql-tables-come-from-the-parser.md` (new). ADR-0038 was the last number.
- `docs/adr/0015-an-unproven-execution-path-is-reported-not-dropped.md`: one "See also" line to ADR-0039, as ADR-0008 and ADR-0018 point to ADR-0038.
- `CONTEXT.md`: new entry **SQL Text Analysis** (after SQL Execution Graph) and new entry **Inline SQL Table Relation** (after Embedded Procedure Target).

Statements that follow the code, not the spec text:

- The fallback keeps a statement that starts with `WITH` or `MERGE` only. The spec says "a word the parser does not classify". Ticket 04 narrowed it (`csharp_parser._is_kept_statement`), and the ADR states why.
- The replacement key removes SQL comments and `--`, then collapses whitespace (`project_scanner._collapse_whitespace`). The spec says "whitespace is collapsed" only.
- The scan skips the literal text of a stored procedure invocation (`_is_formal_sp_invocation`). The ADR states it.
- The host removes a written table from the read tables of an `UPDATE` or a `DELETE` only (`SqlAnalyzer.RemoveWrittenTables`). An `INSERT ... SELECT` that reads its own target keeps the read. The ADR states the rule for `UPDATE` and `DELETE` only.
- The three fallback conditions apply to a whole text. A text with a `SELECT` and a `MERGE` counts as parsed, so its `MERGE` target is missed. A text whose only table is a `#temp` table counts as parsed and gives no relation. The ADR lists both under Consequences.
- A text outside a SQL module gets the module type `unknown` and no module name (ticket 01, decision 1). The `CONTEXT.md` entry of SQL Text Analysis states it as the result of the rule that no temporary file path leaves the module. The ADR keeps one sentence on SQL Text Analysis.
- The companion repository's `_WRITE_ACCESS_TYPES` (`impact_orch/table_lookup.py`) holds no `UNRESOLVED`. So the ADR states that a table with only fallback write evidence leaves its list of written tables. Ticket 08 records the real change.

The facts of the ten local C# Scan Results come from the spec (2026-09-30) and from the one-time check of ticket 02 (641 relations, each with the statement type `SELECT`). Ticket 08 has not run, so the ADR gives no count after the rescan.

Verification: no test reads `CONTEXT.md` or an ADR. Each new link resolves to a file. The inline SQL tests (`test_inline_sql_*`, `test_flow_chain_inline_tables.py`, `test_sql_text_analysis*.py`) give 53 passed. The whole suite (worktree, `--continue-on-collection-errors`) gives 2 failed, 1439 passed, 2 errors: the same two path-dependent ids and the same two collection errors as ticket 06.

Review: the `code-review` skill is not available in this session, so the review ran inline against this checklist and the code. It found no defect.
