# 04 — Step 1: every site in this repository uses one name rule

**Spec issue:** 3

**What to build:** Nineteen sites in this repository stop re-deriving a name
key and call the Canonical Object Identity module. The one intended behaviour
change is that every site folds case with `casefold`. No displayed string
changes. The sixteen static-analyzer sites lose their `dbo` default, and the
three extraction sites return values instead of strings.

See "The `dbo` default in the static analyzer", "Which sites the module
absorbs", "What each call site holds", "The extraction sites", "The behaviour
change in Step 1", and issue 3 in the spec.

**Blocked by:** 03

**Status:** done

- [x] Before any merge, a check confirms that the two modules the first two preconditions delete do not exist.
- [x] Commit 1 adds only the golden test with four fixed inputs, one of them bracketed. It passes on the code before the commit.
- [x] Commit 2 removes the `dbo` default from the sixteen static-analyzer sites. The eight callers that stated nothing now pass `dbo`. The interactive menu's two paths carry a comment that names Step 2a. The other six carry a comment that names Step 2b. The native dependency dictionary method keeps its default.
- [x] Commit 3 moves the nineteen sites onto the module and changes the container type at the three extraction sites.
- [x] The five call sites under "What each call site holds" keep the value, not a string.
- [x] The two splitter call sites apply `dbo` themselves, with a comment that names the step that removes it. The default never enters the module.
- [x] Each place that turns an extraction value back into a string uses the case-preserving variant, with a comment that names Step 2a.
- [x] The cache store and the migration report change their imports and keep their own logic.
- [x] The shared fixture file gains the `sql_cache_identity` list with three-part filenames. The cache store test file reads it.
- [x] The shared fixture file gains the `sample_cache` entry: a data file and a meta file that the payload builder, the graph helper, and the meta writer produce from one fixed input. A test fails when the committed sample differs from that output.
- [x] Seam 5 gains the C# parser case with today's output: `AVM` and `ORDERS`, and no `Users`.
- [x] Seam 4 gains the two cases that guard the C# analysis gateway's procedure name and schema merge.
- [x] The golden test passes after every commit with no edit to the test.
- [x] The whole suite passes.

## Notes (implementation, 2026-09-24)

- **Commits.** `1e11ade` adds the golden test alone. `766f479` removes the `dbo`
  defaults. `d2c253b` moves the name-key sites onto the module. The golden test
  passes after each commit with no edit.
- **Precondition check.** Before commit 3, `ls service/fk_resolver.py
  service/dependency_fetcher.py` found neither file. Both precondition specs mark
  every issue done. No test guards this check.
- **Site count drift.** `service/sp_call_fetcher.py` no longer exists. The
  flow-chain retire spec deleted it (`18737ff`, `383ebfe`). So 17 sites exist,
  not 19. (Corrected by the code review after issue 13: the case-preserving
  variant does have callers. Issue 07 gave it seven, three in `csharp_parser.py`
  and four in `sql_analyzer.py`.)
- **`dbo` default count drift.** 15 sites exist, not 16: 13 in
  `code_analyzer/sql_analyzer.py`, the `SimplifiedSPInfo.schema` field, and
  `models.StoredProcedureAnalysis.schema`. The native dependency dictionary
  method no longer exists.
- **Nine callers, not eight.** The menu's single-procedure path makes two
  calls, `get_all_procedures("dbo")` and `quick_analyze_sp(sp_name, "dbo")`.
  Both name Step 2a. The live script `tests/test_sp_tables.py` also passes `dbo`.
- **Decision (user): values stop before the pickle.** The three extraction
  sites return `set[ObjectName]`. Each caller converts the values with
  `bare_name` before it stores them in `SQLQuery.tables` or
  `SimplifiedSPInfo.referenced_tables`. Both fields reach the pickled C# Scan
  Result, and the evaluation repository's restricted unpickler
  (`routing_expectations._RestrictedScanCacheUnpickler`) rejects any class
  outside `code_analyzer.*`. Issue 6 admits the module. So the spec's listed
  conversion places (summary dictionary, terminal output, spreadsheet export,
  relation table name) stay unchanged. **Step 2a must store the values and
  admit the module in the unpickler in the same deployment.**
- **Decision (user): `PUR..usp_Load` states no schema.** The old gateway schema
  function dropped empty parts, so it read `PUR` as the schema, and the catalog
  lookup missed. The module keeps the empty middle part. This is a second
  behaviour change. `test_a_database_qualified_procedure_name_states_no_schema`
  covers it. The same rule reaches three more places: the two splitters (graph
  node ids, the cached object lookup) and `migration_report._normalize_procedure`
  (`pur.usp_load` becomes `dbo.usp_load`).
- **New module function `part_key`.** It keys one part written alone (a schema
  or a database): it removes brackets, strips, and casefolds, and it keeps dots.
  It replaces `execution_path_builder._normalize_schema`, `_normalize_database`,
  and the gateway's `normalize_schema_name`. The gateway's procedure schema is
  `part_key(parse(x).schema) or None`. The mirror module in
  `llamaindex-spec-rag` does not need it for its three sites.
- **Known differences, no plausible input.** The code review found these.
  - The two splitters stripped a double quote. `parse` strips only brackets.
    The analyzer host reports ScriptDom identifier values, and the listing
    reports `sys.objects` names. Neither holds quotes.
  - The `path_id` database key now removes brackets. A connection Database name
    holds none.
  - `_procedure_name_hint` now strips the whitespace around each part.
- **Which step removes each default.** In `sql_execution_graph.py`, a listed
  name takes the cache-wide schema until the listing commit of Step 2a. A
  reference (call target, read or write table, function) names Step 2b. In
  `analyze_service.py`, the cached object lookup names Step 2a (listing
  commit), and the graph object lookup names Step 2b.
- **The five value-holding sites.** `sp_fetcher._qualified_node_name`,
  `execution_path_builder._qualified_name` and `_qualified_invocation_name`
  return `ObjectName`, and the two splitters became `parse` at each call site.
  In the builder, every current use turns the value back into text with
  `_written_name`, because each use is a displayed string today.
- **Fixture file.** `sql_cache_identity` holds six cases: a plain host, a named
  instance, `tcp:` with a port, a dotted host with schema `COMMON`, `Y Docs`,
  and `A__B`. `sample_cache` holds `data_file` and `meta_file`. The fixed input
  is `_sample_cache_files()` in `tests/test_sql_cache_store.py`. Its docstring
  says how to regenerate the entry.
- **Seam 4.** It gains `part_key` cases and the two gateway cases
  (`usp_Load`, `[COMMON].[usp_Load]` → schema key and name key). It takes over
  the deleted gateway test `test_normalize_procedure_name_strips_schema_and_brackets`.
- **Seam 5.** `tests/test_csharp_parser_inline_sql_tables.py` asserts
  `{"AVM", "ORDERS"}` and passes on the code before commit 3 too.
- **Suite.** The command is `pytest tests/ --ignore=tests/test_search_roles.py
  --ignore=tests/test_sp_tables.py`, and the comparison is by test id. The
  baseline ran in a worktree at `e32e59b`: 1059 passed and 17 failed. After:
  1076 passed and 16 failed. Every new id is a new case. Three ids differ, and
  each one depends on the checkout path, not on this change:
  `test_real_iqcs_refresh_creates_and_commits_a_contract` fails in the main
  tree on the code at `766f479` as well. `test_refresh_does_not_write_wrapper_registry_or_system_catalog`
  and `test_decompile_wrapper_classifies_sqlfunc_dll_end_to_end` fail in the
  worktree and pass in the main tree.
- **mypy.** The error set on the changed files is the same before and after.
- **Glossary.** `CONTEXT.md` has no Canonical Object Identity entry yet.
  Ticket 12 owns it.
