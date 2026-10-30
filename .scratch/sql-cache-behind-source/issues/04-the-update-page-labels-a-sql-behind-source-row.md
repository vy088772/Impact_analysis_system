# 04: The Update Page Labels a SQL `behind_source` Row "資料庫有變更"

**What to build:** On the update page of `llamaindex-spec-rag`, a SQL row in the `behind_source` state shows the text "資料庫有變更". A C# row in the same state keeps the text "來源有新 commit". The analyst can then see at once whether to look at the Database or at the repository.

This ticket changes `llamaindex-spec-rag` only. The frontend type already allows `behind_source` for every row, so this ticket needs no other ticket. Ticket 02 makes the state appear on the real page.

See the spec: `.scratch/sql-cache-behind-source/spec.md` (decision Q11).

**Blocked by:** None (can start immediately)

**Status:** done (2026-10-30)

- [x] The label of `behind_source` depends on the row kind: "資料庫有變更" for a SQL row, and "來源有新 commit" for a C# row.
- [x] The sort order of states and the update button state do not change.
- [x] Comments that say only C# can be `behind_source` change to include SQL, in the frontend types, the "update all" module, and the web API.
- [x] Tests of the pure label function (prior art: the update page tests) cover the SQL label and the C# label.

## Comments

**Implementation notes (2026-10-30)**

- **Branch and commits.** This ticket changes `llamaindex-spec-rag` only, on the branch
  `feat/sql-cache-fingerprint`. `f7196f4` adds the label, `0490057` holds the review follow-ups, and `2f155fc` changes the tooltip.
- **Label.** `freshnessLabel(state)` in `impact_web/frontend/src/updates.ts` takes a `CacheState`
  (the kind and the freshness of a cache). One table, `BEHIND_SOURCE_LABELS`, holds the two words
  for `behind_source`: 資料庫有變更 for SQL and 來源有新 commit for C#. The other states have one
  label for both kinds.
- **No change to sort or button.** `WORST_FIRST` and `refreshButtonState` stay the same. The CSS class
  `freshness-behind_source` stays the same, so a SQL row gets the same dashed caution pill.
- **Comments.** `api/types.ts`, `update_all.py` and `api.py` now say that SQL can be `behind_source`.
  The detail of the check (C# reads the remote repository, SQL reads the Fingerprint) is in one place,
  the comment on `CacheFreshness`.
- **Tests.** `updates.test.ts` covers the SQL label, the C# label, and the equal labels of the other
  states. The full frontend suite (393), `vue-tsc`, and the Python suite (2531, without the
  Windows-only `test_conversion_encrypted_file.py`) pass.

**Review follow-ups (2026-10-30)**

The Standards review and the Spec review ran after the first commit.

- **Fixed: the pin menu showed the wrong word.** `PinSelector.vue` showed 來源有新 commit for a system
  whose only `behind_source` cache is SQL. `freshnessBySystem` now returns the kind of the worst
  cache with its state. When a C# cache and a SQL cache have the same worst state, the C# cache wins,
  in the same order as the update page.
- **Fixed: two places for one label.** The first commit kept `freshnessLabel(freshness)` and added
  `cacheFreshnessLabel(row)` with an override. Now one function and one table hold the words.
- **Fixed: one explanation in five comments.** The check detail was in five comments. Now only
  `CacheFreshness` has it, and the other comments say "查 `behind_source`".
- **Fixed: DESIGN.md.** The Freshness tag entry in `impact_web/frontend/DESIGN.md` records the two
  labels and the rule of the pin menu.
- **Fixed after a user decision: the tooltip of "update all".** `UPDATE_ALL_TITLE` named only the C#
  rows. The user decided to change the text. It is now
  更新「需要更新」的快取與比 ESP 舊的規格書；「來源有新 commit」的 C# 與「資料庫有變更」的 SQL 不會動.
  `llamaindex-spec-rag` commit `2f155fc` changes the constant, its test, the header entry in
  DESIGN.md, and the title line in `.scratch/spec-update-web/spec.md` (with a note on the change).
  The done ticket 07 of `spec-update-web` keeps the old text, because it records history.
