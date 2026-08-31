# 03 — Backfill an Object Location Index for caches already on disk

**What to build:** An operator runs one command and every SQL cache already on disk gains an Object Location Index, without re-scanning any Database over the network. The command needs no scan credentials and puts no load on any SQL Server.

This matters because of where the cost actually sits: of the five caches on disk, `PUR` is 105 MB and the other four together are under 2.5 MB. `PUR` is declared by both Systems that declare anything, so it is opened on nearly every Reverse Lookup. Without a backfill, the one cache that most needs an index is the last to get one, and the feature delivers almost nothing until somebody re-scans a 105 MB Database.

**Blocked by:** 01.

**Status:** ready-for-agent

- [ ] The tool builds each index with the same shared build function the refresh path uses. There is no second way to build an index.
- [ ] The tool opens no SQL Server connection.
- [ ] The tool does not modify any cache content — only writes the index beside it.
- [ ] The tool reports which caches it indexed and which it skipped, so an operator can confirm the rollout is complete.
- [ ] Re-running the tool is safe and rebuilds the index.
- [ ] Deleting an index by hand afterwards breaks nothing: the affected Database falls back to being read in full.
- [ ] Tested following the prior art of the repo's existing cache-repair tool and its test.
