# 02 — One module reads, remaps, and builds a connection source entry

**What to build:** One module in the analyzer package knows the two shapes of
a connection source entry. A connection source entry is the value that the C#
Scan Result holds for one connection variable of one source file. The project
scanner, the gateway, and the analysis service read, remap, and build an entry
only through that module. No analysis answer changes. This ticket is step 0 of
the spec. See the spec, sections "Delivery order", "Connection source entry",
and "Testing Decisions" (Seam D).

**Blocked by:** None — can start immediately

**Status:** done (2026-09-30)

- [x] The module has five functions: `database_of`, `server_of`,
      `has_resolved_shape`, `with_database`, and `resolved_entry`.
- [x] `database_of` gives the Database name as text with no space at each end.
      It gives empty text when the entry has no Database.
- [x] `server_of` gives the server. It gives no value when the server is
      absent or blank, and for a Legacy Connection Label.
- [x] `has_resolved_shape` is true for a mapping and false for a bare string.
      Its description states that a key-as-name guess also has the mapping
      shape.
- [x] `with_database` copies each field of a mapping and replaces only the
      Database. For a Legacy Connection Label, it gives the new Database name
      as a bare string.
- [x] `resolved_entry` builds the stored form from a Database and a server.
      The result has the same fields and values as the entry that the project
      scanner writes today.
- [x] The stored form stays a plain mapping. A typed description records its
      fields. The scan cache version does not rise.
- [x] The project scanner builds each entry with `resolved_entry`. Its two
      private entry helpers go away.
- [x] The gateway reads an entry with the module. It keeps its rule that
      treats `unknown` and `unresolved` as no Database. It keeps its search
      for a connection expression with no regard to case.
- [x] The analysis service loses its three private entry helpers. It keeps the
      decision of which entries to remap.
- [x] The execution path builder declares the correct type for its entries.
- [x] The coverage report and the wrapper discovery tool do not change.
- [x] Seam D tests: one new test file covers the seven cases of the spec.
- [x] The current tests do not change, and all pass. The gateway tests and the
      execution path integration tests still give a Legacy Connection Label.
- [x] Take the test baseline in the same directory as the change. The results
      of three tests depend on the path of the working directory.
- [x] This ticket adds no ADR and changes no glossary entry.

## Comments

### 2026-09-30 — implementation notes

- The module is `code_analyzer/connection_source_entry.py`. The typed
  description is `ResolvedConnectionSource`. `ConnectionSourceEntry` is the
  type of an entry in one of the two shapes.
- The test file is `tests/test_connection_source_entry.py`.
- Files that this ticket changed: `code_analyzer/project_scanner.py`,
  `code_analyzer/csharp_analysis_gateway.py`, `service/analyze_service.py`
  (the three helpers and their call sites only), and
  `service/execution_path_builder.py` (one import and one type only).
- Other sessions changed `service/analyze_service.py` and
  `service/execution_path_builder.py` at the same time. The commit of this
  ticket holds only the lines of this ticket.
- The project scanner had two callers of its Database helper. The two callers
  now call `database_of`. The server helper had no caller.
- Test baseline, in this directory, before the change: 17 failed, 2 collection
  errors. After the change: 16 failed, 1279 passed, 2 collection errors. Each
  failure that stays is in the baseline. Another session repaired the one test
  that left the list (`test_sql_execution_graph.py`).
- The two collection errors are `test_search_roles.py` and
  `test_sp_tables.py`. They need a live database. Run the suite with
  `--continue-on-collection-errors`, or they stop it.
- Three edge results changed. No scan writes these values today.
  - `with_database` does not add a `server` field to a mapping that has none.
    The old service helper added `server: None`. `server_of` gives no value in
    the two cases.
  - The gateway gives no Database for a Database name that is only spaces. It
    gave empty text before.
  - The project scanner removes the space at each end of a Database name that
    it reads from an entry for its statistics and its formal SP list.
- The four changed source files use CRLF line ends. Keep CRLF when a script
  writes them.
