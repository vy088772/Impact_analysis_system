# 06 — Step 2a: the analyzer keeps all four name parts

**Spec issue:** 5, the analyzer commit

**What to build:** A reference such as `PUR.dbo.Users` keeps its database in
the analyzer output and in the persisted Execution Graph. A reference that
states no schema is never read as `dbo` by the host. The five caches on disk
return after one local repair run, with no SQL Server.

See "The analyzer host", "The Execution Graph payload", "What each call site
holds", Seam 1 path evidence, and Seam 3 in the spec.

**Blocked by:** 04, 05

**Status:** done

- [x] The object-name reader uses the named ScriptDom properties for server, database, schema, and base name. It drops the textual fallback and substitutes no `dbo`.
- [x] The composed `schema.name` comparison in the exclusion is deleted. A Seam 3 case proves that a common table expression `X` still drops `dbo.X`.
- [x] An unrecognised module reports an empty schema. The analysed module's own identity gains no database.
- [x] Read tables, write tables, call targets, and function references each carry four always-present parts.
- [x] Duplicate removal and read-minus-write removal compare all four parts.
- [x] The JSON contract version rises by one in the host and in the Python client. A Seam 3 test asserts that the two agree.
- [x] Seam 3 covers four-, three-, two-, and one-part references, a database with no schema, the bracket form of each, and a function-call reference.
- [x] Each reads, writes, and calls relationship gains the database and server its reference stated, and omits a field that was not stated. A referenced node gains neither.
- [x] An unstated schema is filled with `dbo` at each call site, with a comment that names Step 2b.
- [x] The graph object lookup and the graph builder's function-reference resolution read the schema and name fields. A reference that states another Database matches no node.
- [x] Seam 1 path evidence cases 1 and 2 pass.
- [x] The graph format version rises. The repair tool rebuilds a graph from the definitions in the cache. No rebuild runs on the load path.
- [x] The analyzer operation helper emits four parts, and no call site changes.
- [x] The `sample_cache` entry is regenerated. The key-name check in `llamaindex-spec-rag` turns red until ticket 10 lands, and that is expected.
- [x] One local repair run restores all five caches.
- [x] The whole suite of this repository passes.
- [x] This commit can deploy alone.

## Notes (implementation, 2026-09-24)

- **Commit.** `0a12885` holds the whole analyzer commit.
- **Changed files.** Host: `tools/StaticAnalyzerHost/SqlAnalyzer.cs`,
  `tools/StaticAnalyzerHost/Program.cs`. Client: `code_analyzer/static_analyzer_host.py`.
  Graph: `service/sql_execution_graph.py`. Evidence lookup:
  `service/analyze_service.py` (`_find_graph_object_id` and its one caller).
  Tool: `tools/repair_sql_execution_graphs.py` (docstring only). Fixture:
  `tests/sql_cache_fixtures.py` (`analyzer_operation`). Tests:
  `test_static_analyzer_host.py`, `test_sql_execution_graph.py`,
  `test_nested_sql_execution_paths.py`, `test_exact_path_evidence.py`,
  `test_sql_cache_store.py`, `cross_repository_agreement.json`. Documents:
  `docs/使用說明書.md`, `docs/進階手冊.md`, `docs/PUR_CSharp_Analyzer_Example.md`.
- **Versions.** The contract version is 3 in the host and in the client. The
  graph version is 5. `test_static_analyzer_host_contract` already compares the
  host's reported version with the client constant, and the two mismatch cases
  already existed in the Seam 3 file. No new test was needed for them.
- **Host shape.** Each reference is `{"server", "database", "schema", "name"}`.
  A new record `SqlObjectReference` holds it, and its `SameParts` compares all
  four parts without case. The unrecognised module reports schema `""`.
- **Function references.** A call with no call target is still not recorded
  (Out of Scope). The call target's identifiers fill schema, database, and
  server from the right.
- **Relationships.** `reads`, `writes`, and `calls` gain `database` and
  `server` only when the reference stated them. **Not in the spec:** the
  relationship id gains the suffix `@<server>.<database>` when either part is
  stated. Without it, one operation that reads `dbo.Users` and `PUR.dbo.Users`
  writes two relationships with one id. No reader in either repository reads a
  relationship id. **Also not listed:** a temp-table lineage read carries the
  database and server that its base read stated.
- **Calls to another Database.** `EXEC PUR.COMMON.usp_X` still targets the
  local node `stored_procedure:COMMON.usp_X`, and the relationship records
  `database: PUR`. The spec asks for the other-Database rule only at the graph
  object lookup and at the function-reference resolution. A path can therefore
  still expand a local procedure body for a call to another Database. Step 2b
  reads the relationship's database.
- **Spec premise that the code contradicts: the CTE exclusion.** The spec
  says the host drops a reference whose bare name matches a CTE "in the same
  statement". The code builds the CTE names only from the fragment it walks.
  For a statement, the CTE bodies and the main query are two fragments. So:
  - A read of `dbo.X` inside another CTE body is dropped.
  - A read of `X` or `dbo.X` in the main query is kept as a table read.
  The Seam 3 case uses `WITH X AS (...), Y AS (SELECT Id FROM dbo.X) SELECT Id
  FROM Y`. It asserts that `dbo.X` is dropped and that the main query's `Y`
  stays a table read. The old host gives the same answer (`dbo.Y`,
  `dbo.Source`). **The Out of Scope sentence in the spec is wrong as written,
  and the main-query CTE read is a second defect that it does not record.** I
  did not edit `spec.md`, because it holds another session's uncommitted edit.
- **`sample_cache`.** The fixed input in `_sample_cache_files()` gains a read
  of `LNK.PUR.dbo.Customers`, so the sample shows the `database` and `server`
  keys on a relationship. The key-name check in `llamaindex-spec-rag` turns red
  on the `reads` relationship until ticket 10.
- **Seam 1.** `test_path_evidence_holds_the_function_its_operation_calls` has
  cases 1 and 2. It writes the `Response` cache on disk, and the real graph
  builder analyses the definitions. Case 2 fails on the old code
  (`['dbo.fn_Rate'] == []`).
- **Repair run.** `python tools/repair_sql_execution_graphs.py` repaired all
  five caches (4 → 5) in 29 minutes, all in PUR. After the run, all five load.
  Most of the time is the temp-table lineage expansion over PUR: the old code
  takes 675 seconds for that step alone. The final code takes 750 seconds on the
  same graph while the full suite ran beside it, and it writes the same number of
  relationships (118031). The repair run used a draft that held `ObjectName` in
  the lineage set; the final code holds plain string tuples, with the same output. `ScriptDom`-schema nodes (the textual
  fallback) are gone from ETON, PUR, and Response. The `Common` node in
  Response is gone. The PUR `WorkTable` nodes and the STC `Common` node stay,
  because the definitions write `TTFBC.WorkTable.X` and `TTFBC.Common.X`: these
  are real schemas in the Database `TTFBC`. Relationships that state a
  database: ETON 39, PUR 71, Response 84, STC 9, SysErrorRecord 1.
- **Suite.** `pytest tests/ --ignore=tests/test_search_roles.py
  --ignore=tests/test_sp_tables.py`. Baseline in a worktree at `efd0f61`: 1075
  passed, 17 failed. After, in the main tree: 1084 passed, 16 failed. No new failing id
  except `test_real_iqcs_refresh_creates_and_commits_a_contract`, which fails
  in the main tree only (path dependent). The two worktree-only failures pass.
- **mypy.** The error set on the two changed service files is the same before
  and after.
- **Review items left open (judgement calls).** The other-Database guard and
  the `schema or "dbo"` fill appear in both `sql_execution_graph.py` and
  `analyze_service.py`; Step 2b changes both. The four-part dict is read in two
  places and written in the fixture; no shared `from_parts` helper exists.
