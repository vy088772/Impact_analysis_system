# 04: A temp table is visible along calls, in one direction

**What to build:** An analyst keeps the lineage of a "parent creates, child
reads" pattern and of a "parent creates, child fills" pattern. Two procedures
that call one shared procedure stay separate.

See "Call visibility" and "Expansion algorithm" in the spec, and test cases 3,
4, 5, 6, and 9.

**Blocked by:** 01, 03.

**Status:** ready-for-agent

- [ ] Write the tests first and watch them fail.
- [ ] The expansion reads calls only through the helper from ticket 01.
- [ ] A state is a pair of a scoped temp node and a direction: none, up, or down. Up then down, or down then up, is not allowed.
- [ ] The expansion does not detect shadowing. It takes the union of the visible writers.
- [ ] Test case 3 (caller to callee) passes.
- [ ] Test case 4 (callee to caller) passes.
- [ ] Test case 5 (siblings) passes.
- [ ] Test case 6 (transitive chain) passes.
- [ ] Test case 9 (undefined callee) passes.
- [ ] Each derived read keeps `confidence: "proven"`. Its `lineage` holds the chain of scoped temp node identities from the read to the base read.
- [ ] The graph format version does not rise again. No cache was refreshed between ticket 03 and this ticket.
- [ ] Test cases 1, 2, 7, 8, 10, and 11 still pass.
- [ ] The whole suite of this repository passes.
