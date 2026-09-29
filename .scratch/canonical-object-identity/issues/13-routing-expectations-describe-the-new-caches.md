# 13 — Routing expectations describe the new caches

**Spec issue:** 6, the regeneration part

**Repository:** implement this ticket in `llamaindex-spec-rag`, not in this repository.

**What to build:** Every routing expectation names a cache that exists after
Step 2a. A stale expectation that names an old three-part cache identifier is
gone, so no scoring run trusts it.

See "Cross-repository coordination" and issue 6 in the spec.

**Blocked by:** 10, and the operator action: each Database is refreshed on
another machine with the Step 2a code, and the new cache files are copied here.

**Status:** ready-for-agent

- [ ] Before the regeneration, every cache file in the cache directory has a two-part filename.
- [ ] Every routing expectation is regenerated from the new cache files.
- [ ] No compatibility layer keeps the old cache identifiers.
- [ ] Every cache identifier in the regenerated expectations names a file that exists in the cache directory.
- [ ] The whole suite of that repository passes.
