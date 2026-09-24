# 02 — Every test cache payload comes from one fixture module

**Spec issue:** 1

**What to build:** A test gets a SQL cache payload, a format version, and an
analyzer operation from one fixture module only. A check fails when a test
states one of those shapes anywhere else. After this ticket, a shape change in
Step 2a breaks one file instead of twenty-three. No behaviour changes.

See "One test fixture module" in the spec. It states the five commits, the
four check rules, and the proof.

**Blocked by:** 01

**Status:** done

- [x] Before the first commit, one suite run records every test identifier and its outcome.
- [x] Commit 1 adds the payload builder, the Execution Graph helper, the analyzer operation helper, the write helper's SQL Cache Identity argument, and the legacy-key helper. It changes no call site.
- [x] The payload builder takes each object as a written name and parses it with the Canonical Object Identity module. A name that states no schema takes `dbo`, and the builder's documentation states why this is not a comparison-key default.
- [x] The Execution Graph payload keeps its own helper. The builder does not own both format versions.
- [x] The write helper writes the meta file through the cache store's own meta writer.
- [x] Commit 2 moves the payload shape: seventeen files, the reader stubs, and the seven hand-written current filenames.
- [x] The seven legacy-key call sites use the separately named legacy-key helper.
- [x] Commit 3 moves the graph format version and the contract version onto their constants. The twelve stale graph versions become the constant. It adds the two contract mismatch cases to the Seam 3 file, one for each raise.
- [x] Commit 4 moves the analyzer operation shape. Five files use the operation helper. The graph builder's test and the analyzer host's test keep writing the shape out in full.
- [x] Commit 5 adds the check. It reads every Python file under the test directory, excludes its own file by path, and holds the four named rules.
- [x] The three decompile-wrapper files move their contract version onto the constant.
- [ ] After the last commit, a second suite run reports the same outcome for every identifier in the first run. The only new identifiers are the two contract mismatch cases. — every first-run identifier holds its outcome; the check file adds six more new identifiers (see Comments)
- [x] No other ticket lands between the two suite runs.

## Comments

**Implementation notes (2026-09-24)**

- **Commits.** `0d92d46` adds the helpers. `94acea3` moves the payload
  shape. `ab51da5` moves the two version constants and adds the two
  mismatch cases. `9e317a0` moves the operation shape. `1d4878b` adds the
  check. `2e6f1f4` holds the review follow-ups. The ticket file itself lands
  in a separate docs commit.
- **Suite proof.** The first run ran on `3290098`, before the first commit.
  The second run ran after `1d4878b`. Both runs used `pytest tests/
  --ignore=tests/test_search_roles.py --ignore=tests/test_sp_tables.py`,
  because those two files need a live database at collection. The
  comparison used JUnit XML, by identifier. All 1069 first-run identifiers
  report the same outcome (1053 passed, 16 failed in both runs). No other
  commit landed between the two runs.
- **New identifiers.** The second run holds eight new identifiers, not two.
  Two are the contract mismatch cases. Six are the tests of the check file
  itself: three rule checks over the directory, and three small cases that
  prove each rule fires. The check is a test file, so it cannot join the
  suite without new identifiers. The ticket line stays unchecked for this
  reason.
- **Builder name (a user decision).** The spec does not say which name the
  builder writes. The user chose to keep each name exactly as the test wrote
  it, such as `dbo.usp_SaveOrder`. The builder also writes a per-object
  `schema` field. It parses that field with the Canonical Object Identity
  module, and an unstated schema gives `dbo`. No code reads that field yet.
  A mapping entry can override it: one test states
  `{"usp_SaveOrder": {"schema": "sales"}}`, as the test stated before.
- **Builder input.** Each object list takes written names, or a mapping from
  a written name to the other fields of its entry. The builder always writes
  all four object lists. `graph=None` writes no `sql_execution_graph` key,
  which is the dump's shape before the graph builder runs. `schema` sets the
  cache-wide field, and one test uses `sales` there.
- **Operation helper.** `analyzer_operation` writes every field of the host's
  `SqlOperation`: `operation_type`, `sequence`, `branch_path`, `conditions`,
  `where`, the four reference lists, the two column lists, and `dynamic_sql`.
  `**fields` adds node fields such as `id`, `type`, and `module_id`. A
  converted node therefore gains empty fields that it did not state before.
  No outcome changed.
- **Write helper.** `write_cache` takes a `CacheIdentity` and writes the meta
  file with `sql_cache_store.write_meta`. `cache_version` rewrites only that
  one field after the write, for the stale-version cases. The legacy-key
  helper keeps its own meta format on purpose: a legacy cache has no
  `server` field.
- **Shared wrapper.** The identical wrapper is `_cached_sql_graph` in the
  program-screen and shared-component tests. It moves to the fixture module
  as `cache_with_procedures`. Two derived-evidence files also hold an
  identical `_graph`. That helper holds no payload key, so it stays.
- **Graph versions.** Every graph literal that stated a version now comes
  from `execution_graph()`. Two graph literals in the execution path builder's
  test state no `database`, so only their version changed to `GRAPH_VERSION`.
  The repair test and the graph builder's test keep `GRAPH_VERSION - 1`.
- **Check rules as built.** Rule one flags a dict literal that holds
  `procedures`, `views`, `functions`, or `sql_execution_graph`, or that holds
  `tables` together with `database`. It also flags a subscript store of any
  of those keys. Rule two flags a version value, a `graph_version=` or
  `contract_version=` keyword, or a version comparison that holds a bare
  number and does not name the constant. Rule four flags a dict literal that
  holds a reference key: `read_tables`, `write_tables`, `call_targets`, or
  `function_references`. Over the tree at `3290098`, the check reports 27
  files. The spec counts 23; the check also counts the fixture module's own
  helpers and graph-only files.
- **Filenames left in place.** The migration test asserts on the migration
  tool's target filenames. Those assertions state the tool's output, and
  ticket 03 deletes that tool. The identity tests that pin the filename rule
  also keep their literal strings.
- **Code review.** The Standards review found one stray blank line in an
  import block, which is fixed. The Spec review found that the check read
  only the top level of the test directory. The check now reads it
  recursively. Both fixes are in `2e6f1f4`. The Standards review also named
  the repeated `id`/`type`/`module_id` fields at `analyzer_operation` call
  sites. They stay, because they are graph-node fields, not operation fields.
