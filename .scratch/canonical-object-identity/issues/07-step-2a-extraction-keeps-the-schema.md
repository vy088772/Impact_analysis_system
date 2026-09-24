# 07 — Step 2a: the three extraction sites keep the schema

**Spec issue:** 5, the extraction commit

**What to build:** The three sites that read a table name from source text or
from SQL Server keep the schema, the database, and the written case. Inline
C# SQL that reads `PUR.dbo.Users` is reported instead of removed as a schema
name.

See "The extraction sites", Seam 2, and Seam 5 in the spec.

**Blocked by:** 06

**Status:** done

- [x] The native dependency query also selects the referenced schema, database, and server.
- [x] The C# parser stops converting SQL text to upper case. Its patterns capture a name of up to four parts and pass it to the parse function.
- [x] The C# parser's filter that removes `DBO`, `SYS`, and `INFORMATION_SCHEMA` is deleted.
- [x] Each C# table relation holds the value in a field named `table`. The field `table_name` is removed.
- [x] The C# Scan Result holds each relation as it is. The scan cache version rises.
- [x] The two shared-component readers call the case-preserving variant. The two inline C# SQL comparisons call the bare-key function until Step 2b. No answer changes.
- [x] The Step 1 comments that name Step 2a at these sites are removed.
- [x] Seam 2: a native row for `PUR.dbo.Users` gives one value with that database, schema, and name. With no native row, the regex reader gives the schema `COMMON` for `COMMON.AVM`.
- [x] Seam 5: the expected values change to three values, `PUR.dbo.Users`, `[COMMON].[AVM]`, and `Orders`, each in its written case.
- [x] The whole suite of this repository passes.
- [ ] This commit deploys together with ticket 10. (Open: ticket 10 is not done.)

## Notes (implementation, 2026-09-24)

- **Commit.** One commit holds the whole extraction commit. Its message names
  each test file it changes.
- **Changed files.** Extraction: `code_analyzer/sql_analyzer.py`,
  `code_analyzer/csharp_parser.py`. Values: `code_analyzer/models.py`
  (`SQLQuery.tables`, `ProjectAnalysisResult.referenced_tables`),
  `code_analyzer/project_scanner.py` (`CSharpTableRelation.table`,
  `unique_tables`). Displayed strings: `project_scanner.py`,
  `report_generator.py`, `smart_file_finder.py`, `sql_analyzer.py`,
  `csharp_parser.py`. Readers: `service/analyze_service.py`,
  `service/flow_chain_builder.py`. Version: `service/scan_store.py` (39 → 40).
- **Values reach the pickle.** `SQLQuery.tables`,
  `SimplifiedSPInfo.referenced_tables`, and `CSharpTableRelation.table` hold
  `ObjectName` values, as the ticket 04 decision requires.
  `extract_tables_from_definition` returns values too. Its one caller,
  `flow_chain_builder._inline_sql_tables`, calls `bare_name`, so the
  `inline_sql_tables` answer keeps its shape.
- **Displayed strings use `bare_name`.** The relation's `to_dict`, the
  spreadsheet export, the HTML report's table list, the summary dictionary, and
  every terminal list. So `COMMON.AVM` and `dbo.AVM` still show as one row in the
  HTML report, as before.
- **Test expectation that changed.** `test_graph_reverse_lookup.py`: a relation
  parsed from `dbo.SOrder` now shows `SOrder` in `program.tables`, because the
  shared-component readers call `bare_name`. The old parser never produced a
  schema on a relation, so no real answer loses a schema. A real answer changes
  from `SORDER` to `SOrder` (written case).
- **Pattern changes that the ticket does not list.** The code review found them.
  - A name followed by `(` is a function and is not a table. This keeps the old
    result for `OPENQUERY(`, `OPENJSON(`, and `OPENROWSET(`. **Change:**
    `FROM dbo.fn_Split(@x)` gave `FN_SPLIT` before and now gives nothing. A case
    in Seam 5 covers `OPENQUERY` and `OPENJSON`.
  - `\bFROM` no longer matches inside a word such as `DATEFROM`.
  - `FROM Users;` and `FROM Users)` now give `Users`. The old pattern needed a
    space or the end of the text after the name.
  - `[Order Details]` gives the whole name.
- **Step 2b comments.** The two inline C# SQL comparisons gained one comment
  each that names Step 2b. The ticket does not ask for it. It follows ticket 06,
  which marks each temporary rule with the step that removes it.
- **Suite.** `pytest tests/ --ignore=tests/test_search_roles.py
  --ignore=tests/test_sp_tables.py`. Main tree after: 1087 passed, 16 failed,
  the same count as after ticket 06. Baseline in a worktree at `ecda5f8`: 1028
  passed, 15 failed, 57 skipped. Differences by id, none from this change:
  `test_real_iqcs_refresh_creates_and_commits_a_contract` fails in the main tree
  only (path dependent). The three `test_sqldbcontext_real_calls_resolve.py`
  failures skip in the worktree (no IQCS checkout). In the main tree they fail
  with `KeyError: 'sqldbcontext-53e5d16df832'` in the wrapper registry. Three
  worktree-only failures pass in the main tree.
- **mypy.** The error set on the changed files is the same before and after.
- **Deployment.** The scan cache version rejects every C# Scan Result on disk.
  `llamaindex-spec-rag` cannot read a new C# Scan Result until ticket 10 admits
  `canonical_object_identity` in its restricted unpickler, and its
  routing-expectations reader still reads `table_name`. Deploy with ticket 10.
- **Review items left open (judgement calls).** About 15 sites call
  `bare_name(...)` to display a name; no shared display helper exists. The
  regex reader in `sql_analyzer.py` and the C# parser still use two different
  patterns. `CSharpTableRelation.database` (the connection's Database) sits
  beside `table.database` (the Database the SQL states); Step 2b decides which
  one the match reads.
