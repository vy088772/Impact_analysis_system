# A Matching Object Location Index Is Authoritative; a Stale One Degrades to Slow, Never to Wrong

**Status:** Accepted
**Date:** 2026-08-31

## Context

`/find_by_sp` and `/find_by_table` answer "which programs use this stored procedure/table?" by opening every SQL cache in the caller's Lookup Database Set, one Database at a time. The largest cache measured so far (`PUR`) is 105 MB. The catalog today declares 7 (System, Database) pairs; most Systems have not declared any yet, and the expected end state is over 100 Databases. The cost of one question therefore grows with the size of the catalog, not with the size of the answer — almost always one or two Databases actually hold a given object.

Ticket 01 ([issue 01](../../.scratch/object-location-index/issues/01-build-write-and-stale-the-object-location-index.md)) added the Object Location Index: a small companion record beside each SQL cache, listing every stored-procedure/view/function and table name that cache can answer for, normalized the same way the two reverse-lookup endpoints already normalize a query name. The index is derived from the same content the endpoints search, and it is built to over-report rather than under-report a name.

Ticket 02 needed to decide what a caller may conclude from that index alone, before deciding whether the caller is allowed to skip opening a cache on the strength of it.

## Decision

`/locate_object` answers "which Databases could hold this name?" from the indexes alone, and never opens a SQL cache to do it. A Database whose index is fresh and holds the normalized name is reported as `matched`; a Database whose index is missing, unreadable, older than the cache it describes, or built against a different cache format version is reported as `unindexed` — the caller must read that Database's cache in full, because the service cannot say. A Database whose index is fresh and does **not** hold the name appears in neither list: that omission is the pruning, and it is authoritative — the caller may skip that cache unopened.

This rests on the guarantee ticket 01 already built: the index can over-report a name (costing one extra cache read) but can never under-report one (which would cost a lost answer). A stale index therefore cannot make an answer wrong — it can only fail to prune, which makes the caller do exactly what it does today. Trusting a *fresh, matching* index is safe for the same reason: staleness is checked by file modification time before the index's content is ever read, and a version or identity mismatch (a file moved or renamed by hand) also degrades to `unindexed` rather than being trusted.

## Consequences

- A caller (`llamaindex-spec-rag`) may narrow its Lookup Database Set to a Candidate Database Set — `matched ∪ unindexed`, intersected with what it already declares — and skip a cache that is neither, without asking the analysis service to prove anything further. That caller's own ADR-0007 ("question answering reads every declared database") is amended, not superseded, by a note pointing here: the search space stays the Lookup Database Set, only the number of caches actually opened changes.
- `/locate_object`'s own request/response shape and `/find_by_sp`/`/find_by_table`'s existing shapes are independent of each other. Range selection (which Databases to open) and evidence matching (what a given cache's content proves) stay two separate operations, each testable alone.
- A partial rollout — a cache refreshed before ticket 01, or a backfill (ticket 03) that has not reached every existing cache yet — degrades every affected Database to `unindexed`, never to a wrong `matched`/omitted answer. The feature can therefore roll out incrementally without a flag day.
- If a future change to the cache format or to either endpoint's matching rule is not reflected in `build_object_location_index()`, the index can silently under-report again despite this ADR's guarantee. That guarantee is only as good as ticket 01's shared-normalization-function discipline continuing to hold for every future change to either endpoint.
