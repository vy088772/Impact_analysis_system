# 03 — Compare contract names without regard to letter case in Contract Preflight

**What to build:** The contract registry holds one entry for each contract identity. A proposal whose name differs from an existing entry only by letter case matches that entry, instead of creating a second entry beside it.

Contract Preflight compares a proposed contract name against the registry with a case-sensitive test. Contract acceptance compares the same thing without regard to letter case. The two paths disagree. A proposal named with different capitalisation than an existing entry therefore adds a second entry. Selector lookup keys the registry by a case-folded name, so one of the two entries then disappears from lookup without any error.

Make Contract Preflight match contract acceptance.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] Contract Preflight matches a proposed contract name against an existing entry without regard to letter case.
- [ ] A proposal whose Contract Fingerprint equals an existing entry's fingerprint reuses that entry, and takes the lifecycle status `reused`.
- [ ] A proposal whose Contract Fingerprint differs from an existing entry of the same case-folded name creates one versioned entry.
- [ ] The registry never holds two entries whose names differ only by letter case.
- [ ] Selector lookup resolves every registry entry, because no case collision can discard one.
- [ ] A test stages a proposal whose name differs from an existing entry only by letter case, and asserts that the registry gains no second entry.
