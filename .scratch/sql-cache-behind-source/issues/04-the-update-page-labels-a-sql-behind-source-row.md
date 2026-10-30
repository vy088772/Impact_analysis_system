# 04: The Update Page Labels a SQL `behind_source` Row "資料庫有變更"

**What to build:** On the update page of `llamaindex-spec-rag`, a SQL row in the `behind_source` state shows the text "資料庫有變更". A C# row in the same state keeps the text "來源有新 commit". The analyst can then see at once whether to look at the Database or at the repository.

This ticket changes `llamaindex-spec-rag` only. The frontend type already allows `behind_source` for every row, so this ticket needs no other ticket. Ticket 02 makes the state appear on the real page.

See the spec: `.scratch/sql-cache-behind-source/spec.md` (decision Q11).

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] The label of `behind_source` depends on the row kind: "資料庫有變更" for a SQL row, and "來源有新 commit" for a C# row.
- [ ] The sort order of states and the update button state do not change.
- [ ] Comments that say only C# can be `behind_source` change to include SQL, in the frontend types, the "update all" module, and the web API.
- [ ] Tests of the pure label function (prior art: the update page tests) cover the SQL label and the C# label.
