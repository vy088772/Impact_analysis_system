# 02: The temp table expansion finishes and reports progress

**What to build:** An operator who refreshes a Database where many procedures
share a temp table name sees the refresh pass the graph stage. The refresh
command shows a labelled `lineage` progress stage after the graph stage reaches
100%. The temp table node stays shared in this ticket, so the lineage answers do
not change yet.

See "Expansion algorithm" in the spec, and test cases 1, 7, 11, and 12.

**Repositories:** this repository, and `llamaindex-spec-rag` for the stage label.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] Write the tests first and watch them fail.
- [ ] A worklist fixed point replaces the path enumeration. It needs no depth limit.
- [ ] Test case 1 (cost): forty procedures that each run the chain `#t1` to `#t4` build in a few seconds. This ticket asserts only that the build ends.
- [ ] Test case 7 (cycle): two builds of the same payload give the same relationships.
- [ ] Test case 11 (progress): the progress callback receives the `lineage` stage after the last `graph` report and before the builder returns.
- [ ] Test case 12 (label): the refresh command in `llamaindex-spec-rag` maps the `lineage` stage key to a readable label.
- [ ] Each derived read keeps the server and database that its base read stated. The existing test for that passes with no edit.
- [ ] The graph format version does not change. Do not refresh a cache after this ticket, because ticket 03 changes the graph again.
- [ ] Tests build payloads from the shared test fixture module and read the graph version from its constant.
- [ ] The whole suite of each repository passes.
