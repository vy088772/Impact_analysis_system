# The Object Location Index States Its Own Format Version; an Incomplete One Is Absent

**Status:** Accepted
**Date:** 2026-09-29

## Context

[ADR-0012](0012-object-location-index-authoritative-pruning.md) makes a fresh Object Location Index authoritative. A Database whose index does not hold a name drops out of the Candidate Database Set, and the caller skips its cache unopened. The index must therefore never under-report a name.

The index borrowed the SQL cache format version. The loader counted an index as absent when that version differed from the version of this build. The version described the cache shape, not the index shape.

The read-side step of the canonical-object-identity work (`.scratch/canonical-object-identity/`) changed the index shape and not the cache shape. Each kind of object gained a bare bucket and a full bucket. The cache format version had no reason to rise. An index with one bucket then read as fresh. A full-key question missed it, and the caller skipped a cache that holds the answer. That is the authoritative under-report that ADR-0012 forbids.

## Decision

- Each persisted shape has its own version constant. The cache keeps `_SQL_CACHE_VERSION` and the payload field `cache_version`. The index gains `_INDEX_VERSION` and the payload field `index_version`. Both constants sit in the cache store.
- The index payload drops the cache format version field. A cache whose format version rose is unreadable, so its Database answers nothing, whether the index prunes it or not. The modification-time rule already ages the index out after the next refresh.
- The index version starts at 1. An index written before this decision has no version field, so it counts as absent.
- The loader compares the stated version for exact equality. An older version and a newer version both count as absent. A newer version reaches disk when a deployment rolls back, and a reader must not trust a shape it cannot read.
- An index that misses a bucket counts as absent. It never counts as an index with an empty bucket. The loader cannot know which bucket a reader will ask for, so it requires all four buckets, and each bucket must be a list.
- The whole staleness rule stays in the one loader function. The backfill tool reads no index file and compares no version. It rebuilds every index and overwrites the old one.

## Consequences

- A change to the index shape raises `_INDEX_VERSION` alone. Every index on disk then counts as absent, and every Database degrades to `unindexed` until the backfill tool runs.
- The backfill tool rebuilds every index from the caches on this machine. It opens no SQL Server connection, so an index version rise needs no operator refresh. A rerun of the tool is the recovery path after each index version rise.
- A change to the cache shape raises `_SQL_CACHE_VERSION` alone. The index does not need to follow, because an unreadable cache answers nothing.
- The version is a property of the file, not of the index content. The in-memory index value holds no version field.
- The degrade reasons of ADR-0012 change: "built against a different cache format version" becomes "states no index version, or another index version, or misses a bucket". The guarantee of ADR-0012 does not change. A stale or incomplete index makes a search slow, never wrong.
