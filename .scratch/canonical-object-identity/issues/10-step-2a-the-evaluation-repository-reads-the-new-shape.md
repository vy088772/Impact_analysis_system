# 10 — Step 2a: the evaluation repository reads the new shape

**Spec issue:** 6

**Repository:** implement this ticket in `llamaindex-spec-rag`, not in this repository.

**What to build:** The orchestrator and the evaluation code stop sending the
removed request field, read the new C# Scan Result, and name caches with two-part
filenames. The evaluation fixture module matches the new cache shape, and its
key-name check turns green again.

See "The extraction sites", "One SQL cache holds one Database",
"Cross-repository coordination", and issue 6 in the spec.

**Blocked by:** 05, 09

**Status:** done (2026-09-29), except the deployment item in the last line

- [x] The orchestration client and the refresh CLI no longer send `db_schema`. The refresh CLI has no schema option.
- [x] The cache identity test reads the two-part `sql_cache_identity` list and passes.
- [x] The restricted unpickler admits the Canonical Object Identity module.
- [x] The routing-expectations reader reads the bare name from a relation's `table` field and splits no string.
- [x] The evaluation fixture module writes the new cache shape and two-part filenames. The key-name check against `sample_cache` passes.
- [x] The whole suite of that repository passes.
- [ ] This ticket deploys together with tickets 06 to 09.

Note: the regeneration of the routing expectations is not part of this ticket. Ticket 13 does it after the operator refresh.

## Notes

All work sits in `llamaindex-spec-rag`, on branch `spec_extend_20260701`, in
four commits after `2ac8052`:

- `1f4d453`: `sql_cache_identity.cache_key`, `cache_filename`, and
  `cache_meta_filename` take `(server, database)`. The refresh request sends
  no `db_schema`, and its `database` field is the two-part key.
  `refresh_sql_database` and `refresh_sql` lose their schema parameter.
  `ScanTarget` loses its schema field, and the CLI loses `--schema`. A new
  test states that argparse rejects `--schema`.
- **A defect this commit also fixes.** The CLI matched a candidate against
  `/scan_records` by `(server, database, db_schema)`. After ticket 09 the
  service returns no `db_schema`, so no candidate matched a record, and the
  chooser showed every candidate as never scanned. The existing test
  `test_candidates_are_ordered_by_server_independent_of_scan_state` turned red
  when its Scan Record lost `db_schema`, and it passes now.
- `47afb97`: The fixture module writes no cache-wide `schema` and no meta
  `schema`. Each listed object takes its schema from its written name, and
  an unstated one reads as `dbo`, as the service's own builder does.
  `relationship()` takes `database` and `server`, and holds each one only
  when it is stated. `GRAPH_VERSION = 5`, `CACHE_VERSION = 11`.
- `72e24d5`: The unpickler admits `("canonical_object_identity",
  "ObjectName")` and nothing else from that module. It loads the value as the
  mirror `ObjectName`. `object_key` takes that value directly. The service
  also stores `unique_tables` as a set of `ObjectName`, which the ticket does
  not name. Without the `object_key` change, that set reads as the text of
  each value's repr.
- `2371e1f`: Review fixes. The `CONTEXT.md` Scan Target entry names no
  schema. The two scan-result tests restore `sys.modules` through one context
  manager.
- **Tests.** The scan-result tests pickle stand-in classes under the service's
  own import paths (`code_analyzer.project_scanner.ProjectScanResult`,
  `CSharpTableRelation`, `canonical_object_identity.ObjectName`). A manual
  check also pickled a real `ProjectScanResult` with the service's classes and
  `HIGHEST_PROTOCOL`, and the reader loaded it: the three-part write table
  kept its bare name.
- **Suite.** `pytest tests`: 1209 passed, 2 failed. The two failures are the
  same two that ticket 05 records, and neither touches a changed file.
- **mypy.** No new error. The gated `sql_cache_identity.py` passes.
  `rag_client.py` has 7 errors and `routing_expectations.py` has 5, before and
  after.

**Review items left open:**

- An old C# Scan Result that still holds `table_name` loads, but it gives no
  write table and raises no error. The evaluation reader does not check the
  scan cache version. The next scan replaces every such file.
- No test in `llamaindex-spec-rag` fails when the service renames a field of
  `ObjectName` or of a C# table relation. `sample_cache` covers the SQL cache
  only, not the C# Scan Result.
- `docs/adr/0005` and `docs/adr/0014` of `llamaindex-spec-rag` still state the
  `(server, database, schema)` identity. Ticket 12 owns the documents.
- `evaluation/Impact_analysis/results/routing_expectations.json` and
  `intent_labels.json` still hold three-part cache ids. Ticket 13 regenerates
  them.
- The deployment item stays open. It is an operator action, not code.
