# 01 — The graph build reads the host's answer through SQL Text Analysis

**What to build:** A maintainer changes how the code reads the host's SQL answer, and no analyst sees a change. SQL Text Analysis takes a sequence of SQL texts and returns one typed result for each text, in input order. A result holds typed operations and typed parse errors. SQL Text Analysis has two adapters: the host adapter, which runs the analyzer host, and the in-memory adapter, which a test uses. The graph build and the graph repair tool take SQL Text Analysis in place of the analyzer host. The SQL Execution Graph payload stays equal.

See "SQL Text Analysis", "Testing Decisions", and user stories 37 to 39, 41, and 42 in the spec.

**Blocked by:** None — can start immediately.

**Status:** done

- [x] A failing test comes first: the graph build takes the in-memory adapter, and it gives the graph that it gives today for the same definitions.
- [x] Seam 3, with the real host: a definition with Windows line ends gives source offsets that agree with the text.
- [x] SQL Text Analysis returns one result for each text, in input order.
- [x] A typed operation holds every field that the host reports for an operation. Each object reference is an object name of the Canonical Object Identity, with its four parts.
- [x] The source location of a typed operation holds no file path. The path of a temporary file never leaves SQL Text Analysis.
- [x] SQL Text Analysis reports progress as a completed count and a total count. The graph build still reports the name of the last SQL module of each batch.
- [x] A host failure on one text raises an error that holds the index of that text. The graph build still names the SQL module in its error.
- [x] The host adapter makes the host ready before the first run. It is the only product code that reads the host's SQL answer by string keys.
- [x] The in-memory adapter replaces the stub analyzer host of the SQL cache test fixtures. It starts no host and writes no file.
- [x] The graph repair tool gives SQL Text Analysis to the graph build.
- [x] The graph build tests keep their cases. The host contract tests do not change.
- [x] The graph format version stays 8. The host contract version does not change.
- [x] A one-time check rebuilds the graph of each of the seven local SQL caches from the definitions in the cache, and compares it with the graph on disk. Each pair is equal. This ticket records the result. The check adds no tool.
- [x] The whole suite shows no new failure.

## Comments

### 2026-09-30 — implementation notes

**The files of this ticket.** Other tickets ran in the same working tree at the same time. This ticket changed only these files:

- `code_analyzer/sql_text_analysis.py` (new)
- `service/sql_execution_graph.py`
- `tools/repair_sql_execution_graphs.py`
- `tests/test_sql_text_analysis.py` (new)
- `tests/sql_cache_fixtures.py`
- `tests/test_sql_execution_graph.py`
- `tests/test_repair_sql_execution_graphs.py`
- `tests/test_exact_path_evidence.py`
- `tests/test_execution_path_builder.py`
- `tests/test_graph_queries.py`
- `tests/test_rebuild_report.py`

**The interface.** `SqlTextAnalysis.analyze(texts, progress_callback)` is the one operation. `HostSqlTextAnalysis` is the host adapter. `InMemorySqlTextAnalysis` is the in-memory adapter. `SqlTextAnalysisError` is a kind of `StaticAnalyzerHostError`, and its `index` counts from zero. `build_sql_execution_graph()`, `repair_cache_file()`, and `repair_all_caches()` take the parameter `sql_text_analysis` in place of `host`.

**The first failing test.** `test_the_graph_build_gives_the_same_graph_through_sql_text_analysis` came first. Its expected graph is the graph that the graph build gave with the real host, at commit `154ad57`, for the same definition. The test compares the values, and it compares the JSON text, because the key order is part of the payload.

**The one-time check.** The check ran on 2026-09-30 after the last code change. It rebuilt each graph with the host adapter from the definitions in the cache. It compared the values, and it compared the JSON text that `json.dumps(..., ensure_ascii=False, indent=2)` gives. The cache store writes a cache with those arguments. Each pair is equal.

| SQL cache | SQL modules | Nodes | Relationships | Parse errors | Values equal | JSON text equal |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| EFNETDB | 0 | 21 | 0 | 0 | yes | yes |
| ETON | 88 | 303 | 449 | 0 | yes | yes |
| PUR | 1699 | 9720 | 24000 | 0 | yes | yes |
| Response | 71 | 261 | 429 | 0 | yes | yes |
| STC | 59 | 258 | 412 | 0 | yes | yes |
| SysErrorRecord | 2 | 14 | 25 | 0 | yes | yes |
| eFinance | 281 | 2601 | 4913 | 0 | yes | yes |

The spec review of this ticket did a second check. It ran the graph build of `HEAD` and the new graph build on nine SQL modules with the real host: Windows line ends, a parse error, a text that is not SQL, a text outside a SQL module, `EXEC(@x)`, a `MERGE`, temp tables, a CTE, and names that are not ASCII. The JSON text and the progress reports were equal.

**The whole suite.** The baseline at commit `154ad57` gave 16 failed tests and 2 collection errors (`tests/test_search_roles.py` and `tests/test_sp_tables.py` need a Database connection). The suite after this ticket gives the same 16 failed tests and the same 2 collection errors. No test is a new failure.

**Decisions that the spec does not state.**

1. **A text outside a SQL module gets no module name.** The host gives such a text the type `unknown`, and it takes the name from the input file name. That name is the name of a temporary file. The host adapter returns the type `unknown`, an empty schema, and an empty name. The spec has two rules here: "returns what the host reports and removes nothing", and "the path of a temporary file never leaves SQL Text Analysis". The second rule decided this case. The graph build is not affected: it writes its own module identity on each node. Ticket 03 reads the type `unknown` only.
2. **The error text names a text, not a file.** The host names the failed input by its path. The host adapter replaces the path with `text N of M`, where N counts from one. The graph build error is now `SQL analysis failed for module usp_B: sql analysis failed for input text 2 of 3: ...`. Before this ticket, the text held the path of a temporary file.
3. **The graph repair tool makes the host ready later.** Before this ticket, the tool made the host ready before it read a cache. Now the host adapter makes the host ready before its first run. A dry run, and a run where each cache is current, no longer start `dotnet`. A run that repairs a cache starts the host as before.
4. **The host adapter reads each key without a default.** The graph build read each key with a default value. The host always reports each key, so the real host gives the same result. A host answer that lacks a key now raises an error, and does not give an empty field.
5. **The result count check is in the host adapter.** Its message says "text count" in place of "module count".
6. **The in-memory adapter holds operations only.** It holds no parse error. The Seam 1 case "a text with a parse error" of ticket 03 or 04 must add that.

**The Seam 3 tests.** The spec gives this ticket one Seam 3 case, the Windows line ends. `tests/test_sql_text_analysis.py` holds three more tests with the real host: each field of a typed operation, the input order with a batch limit, and the module of a text outside a SQL module. They cover checklist items of this ticket. They do not cover the parser cases that ticket 03 owns.

**Open items for other tickets.**

- `CONTEXT.md` has no entry for SQL Text Analysis. Ticket 07 adds it.
- The spec text "returns what the host reports and removes nothing" needs the exception of decision 1. Ticket 07 can state it in the ADR.
