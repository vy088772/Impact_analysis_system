# 03: A temp table belongs to the procedure that uses it

**What to build:** An analyst who asks about a table reached through `#tmp` in
one procedure no longer receives the base tables of an unrelated procedure that
also uses `#tmp`. Each `#name` temp table becomes one node for each module that
uses it. A `##name` global temp table stays one node for the Database.

See "Temp Table Scope" in the spec, and test cases 1, 2, 8, and 10.

**Blocked by:** 02.

**Status:** ready-for-agent

- [ ] Write the tests first and watch them fail.
- [ ] The node identity of a `#name` temp table holds the plain table identity and the owning module identity. It comes from the node identity function that builds every other node.
- [ ] A scoped node keeps `type: "table"`, keeps the written name in `name`, and gains `scope_module_id`.
- [ ] The node lookup key of a scoped node contains the scope. One module that writes `#Tmp` and reads `#tmp` still produces one node.
- [ ] Test case 1 (cost) now also asserts that each procedure's final read resolves only to its own base table.
- [ ] Test case 2 (isolation) passes.
- [ ] Test case 8 (global temp table) passes.
- [ ] Test case 10 (node shape) passes, and every relationship resolves to a known node.
- [ ] One test with the real analyzer host proves `SELECT ... INTO #name` then `SELECT ... FROM #name` in one procedure.
- [ ] The Object Location Index still holds the same temp table names.
- [ ] The graph format version rises by one. The version comment states the scoped node identity and the new expansion.
- [ ] The whole suite of this repository passes.
