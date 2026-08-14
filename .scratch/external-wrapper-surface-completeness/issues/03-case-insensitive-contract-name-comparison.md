# 03 — Compare contract names without regard to letter case in Contract Preflight

**What to build:** The contract registry holds one entry for each contract identity. A proposal whose name differs from an existing entry only by letter case matches that entry, instead of creating a second entry beside it.

Contract Preflight compares a proposed contract name against the registry with a case-sensitive test. Contract acceptance compares the same thing without regard to letter case. The two paths disagree. A proposal named with different capitalisation than an existing entry therefore adds a second entry. Selector lookup keys the registry by a case-folded name, so one of the two entries then disappears from lookup without any error.

Make Contract Preflight match contract acceptance.

**Blocked by:** None — can start immediately.

**Status:** resolved

- [x] Contract Preflight matches a proposed contract name against an existing entry without regard to letter case.
- [x] A proposal whose Contract Fingerprint equals an existing entry's fingerprint reuses that entry, and takes the lifecycle status `reused`.
- [x] A proposal whose Contract Fingerprint differs from an existing entry of the same case-folded name creates one versioned entry.
- [x] The registry never holds two entries whose names differ only by letter case.
- [x] Selector lookup resolves every registry entry, because no case collision can discard one.
- [x] A test stages a proposal whose name differs from an existing entry only by letter case, and asserts that the registry gains no second entry.

## Answer

`_stage_complete_proposals` in `service/contract_preflight.py` named a new contract with the case-sensitive test `name in entries or name in staged_names`. Because `_slug` case-folds every proposal name, a registry entry written with its own spelling (for example `SQLFunc`) never matched the proposal name `sqlfunc`, so the refresh staged a second entry beside it.

Preflight now uses `_find_casefold`, mirroring `service/contract_acceptance.py:253`. A helper pair carries the rule: `_taken_contract_name` returns the spelling a registered or staged contract already holds, and `_unused_revision_name` builds the versioned name from that spelling. The reuse path was already keyed on Contract Fingerprint alone, so it needed no change; a test now guards it.

Two deliberate divergences from contract acceptance, both reported by the review and both kept:

- Contract acceptance falls back to the proposal's spelling for its second and third revision names, while preflight keeps the registry's spelling for all of them. A mixed stem cannot produce a case twin either way, but one stem is the honest expression of the rule this ticket enforces.
- Contract acceptance escalates its revision name inside a `while` loop that cannot terminate if the full-fingerprint name is taken. `_unused_revision_name` walks the same three rungs, then appends an ordinal, so a taken name is never overwritten and the walk always ends. The old preflight `while` loop shared the acceptance hang; a collision at the full fingerprint would otherwise have replaced an immutable entry at `entries.update(staged_names)`.

Cross-module extraction of the shared naming rule into one function used by both preflight and acceptance was raised by the Standards review and declined as outside this ticket.

Validation: three tests added to `tests/test_refresh_contract_preflight.py` — a case-different proposal with a matching fingerprint reuses the one entry; a case-different proposal with a differing fingerprint versions it without a case twin, and every resulting entry still resolves through `normalize_contract_selector`; an occupied twelve-character revision name steps to the sixteen-character rung without overwriting the occupant. The second test fails on the parent commit with `['SQLFunc', 'sqlfunc']`. Repository suite: `363 passed`, with 11 pre-existing failures and 2 live-DB collection errors (`test_search_roles.py`, `test_sp_tables.py`, missing ODBC driver) — all confirmed identical on a clean worktree at the parent commit, none introduced by this change.
