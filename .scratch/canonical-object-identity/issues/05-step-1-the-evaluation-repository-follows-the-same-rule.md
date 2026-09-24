# 05 — Step 1: the evaluation repository follows the same rule

**Spec issue:** 4

**Repository:** implement this ticket in `llamaindex-spec-rag`, not in this repository.

**What to build:** The orchestrator and the evaluation code compute name keys,
server keys, and cache filenames exactly as this repository does. The
Candidate Database Set keeps a cache whose Database name differs only in case.
Every hand-built test cache in that repository comes from one fixture module,
and a test turns red when its shape drifts from the cache this repository
writes.

See "Cross-repository coordination", "Two sites that keep the schema", "The
read side", "The evaluation repository's fixture module", and issue 4 in the
spec.

**Blocked by:** 04, and `llamaindex-spec-rag` ticket `database-invocation-identity-is-the-call-site/issues/01`

**Status:** done

- [x] A mirror module in the orchestration package holds the same value type, parse function, and two key functions. The three sites use it.
- [x] The mirror module passes Seam 4 over the shared fixture file's `object_names` list, read by relative path. A missing file fails the test.
- [x] The server rule strips a `tcp:` prefix and a `,port` suffix. The cache identity test reads the three-part `sql_cache_identity` list and passes.
- [x] The test that compared a computed filename against a file on disk is deleted.
- [x] The function that lists the cache data files sits in the SQL cache identity module. Both cache-directory readers call it. It excludes both the meta and the index suffixes.
- [x] That reader's own test gains an index file beside the data file, and its name names both ignored kinds.
- [x] The Candidate Database Set key folds the Database name with `casefold`. A test declares `pur`, the located row states `PUR`, and the Candidate Database Set keeps that Database. The module docstring states the new rule.
- [x] The intersection reads `server` and `database` only.
- [x] One fixture module under the test directory builds every hand-built cache. The cache writers test, the cache-derived lookup test, and the routing expectations test use it. Filenames come from the SQL cache identity function.
- [x] A test compares the key set of the fixture module's output with the `sample_cache` entry at each level: the data file's top level, the Execution Graph, each node type, a relationship, and the meta file. It compares no value.
- [x] The two sites under "Two sites that keep the schema" do not change. Each gains one test with the pairs `dbo.spFoo`/`spFoo` and `COMMON.spFoo`/`dbo.spFoo`, and each test expects two identities.
- [x] The whole suite of that repository passes.

## Notes

All work sits in `llamaindex-spec-rag`, on branch `spec_extend_20260701`, in
six commits after `270685b`:

- `e5e7f0f`: The mirror module is `impact_orch/canonical_object_identity.py`,
  with `ObjectName`, `parse`, `bare_key`, and `full_key`. It has no
  `bare_name` and no `part_key`, because no site in that repository needs
  them. `mypy.ini` gates it. The three sites call `bare_key`:
  `routing_expectations.object_key`, `context_builder._sp_name_core`, and
  `path_selection._object_leaf`. They keep their names because other code
  calls them. `_sp_name_core` moves from `lower` to `casefold`.
  `tests/test_canonical_object_identity.py` is Seam 4.
- `89eb0d3`: `sql_cache_identity.normalize_server` gains the `tcp:` rule and
  the `,port` rule. The module now owns `DATA_SUFFIX`, `META_SUFFIX`,
  `INDEX_SUFFIX`, `cache_meta_filename`, `meta_file_of`, and
  `cache_data_files`. `sql_cache_writers._cache_json_paths` is deleted.
  `load_cache_object_inventory` used to admit index files, and it now calls
  `cache_data_files`. The routing test is now
  `test_cache_inventory_reads_sql_objects_and_ignores_meta_and_index_files`.
  It fails on the old reader.
- `6bea900`: The Candidate Database Set key folds the Database name with
  `casefold`. Two tests are new: `pur`/`PUR`, and a row with `schema` and
  `stated_database` that intersects on `server` and `database` only.
- `aed6b72`: `tests/test_chain_entry_schema_identity.py` holds one test for
  each of the two sites. It uses both pairs. It fails when either site keys
  on the bare name.
- `44b91fb`: The fixture module is `tests/_sql_cache_fixtures.py`. The
  key-set check is `tests/test_sql_cache_fixtures.py`. Test cache ids are now
  `server.topmost.com.tw__<DB>__dbo`, from `cache_id()`. Step 2a (ticket 10)
  changes the filename in `cache_key` and the shapes in this one module. The
  fixture keeps `GRAPH_VERSION = 4` and `CACHE_VERSION = 10` as constants.
  The readers do not check them.
- `2ac8052`: The Candidate Database Set docstring names the repository of
  ADR-0012. The code review found this.

**Suite.** `pytest tests` gives 1203 passed and 2 failed. Both failures also
occur without this change, and neither touches a changed file:
`test_path_evidence_wiring::test_clients_route_the_sql_cache_by_database_name_not_system_id`
fails at `270685b` in the main tree (`KeyError: 'database'`).
`test_source_resolver_databases::test_the_shipped_catalog_declares_databases_as_full_identities`
fails because of the shipped catalog data. mypy passes.

**Review items left open:**

- The `CONTEXT.md` of `llamaindex-spec-rag` defines Canonical Object Identity
  more widely, with system and object type. Ticket 12 owns the glossary.
- Three test files each build the relative path to the agreement file.
- Test node ids for tables are still written as `"table:dbo.X"`.
