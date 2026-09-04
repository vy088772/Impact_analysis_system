# 08 — The SQL cache holds a bounded number of databases in memory

**What to build:** A service whose memory use stops growing as more databases
are queried. An operator can add databases to a deployment without having to
restart the service to reclaim memory.

The SQL cache holds every database it has loaded in an unbounded process cache
that never evicts. One measured database occupies 105 MB, while four others in
the same deployment occupy under 1 MB each. The cost is therefore uneven and
hard to predict: a deployment with 200 databases grows until the process ends,
and a few large databases dominate the total.

The cache retains a configured number of databases and drops the least recently
used beyond that. A dropped database is read from disk again when it is next
needed, which is fast, because it is a file read rather than a database
connection.

This is safe only after ticket 05. Before that ticket, dropping a database
would invalidate every retained scope that used it, because the freshness rule
compared the cache by object identity. With content comparison in force, a
dropped and reloaded database with unchanged content keeps every scope valid.

**Blocked by:** 05 — Retention freshness compares recorded content, not object
identity.

**Status:** done

- [x] The SQL cache retains no more databases in memory than its bound allows.
- [x] The database unused for the longest time is the one dropped.
- [x] The bound is configurable, in the style of the existing retention bound.
- [x] A dropped database is read from disk again when next needed, and returns
      the same content.
- [x] Dropping and reloading an unchanged database causes no scope to be
      derived again.
- [x] A cached entry that fails its validity check is still discarded, as it is
      today.
- [x] No answer changes as a result of the bound.

## Notes

Seam: `sql_cache_store.load_cached()`, where `tests/test_sql_cache_store.py`
already asserts on cache behaviour. Assert the observable claims — how many
databases are retained, and that a reload returns equal content — rather than
reaching for the cache structure itself where a test can avoid it.

Validate with a deterministic assertion on the number retained, not by
measuring process memory. Measured resident memory moves for reasons unrelated
to this bound, so it cannot serve as an acceptance criterion. Measure it once
by hand afterwards if a figure is wanted for the record.

The repository scan's own process cache is out of scope. It holds 11 MB across
five repositories in the measured deployment, so it is not urgent.

Choose a default bound that keeps the measured deployment fully cached, so this
ticket changes nothing for a small installation and only takes effect where the
database count is large.

## Implementation Notes

`sql_cache_store._mem_cache` changed from a plain `dict` to an `OrderedDict`,
bounded by the new `settings.SQL_CACHE_MEMORY_RETENTION_LIMIT` (default 20;
the measured deployment has 5 databases on disk, so this default leaves 4x
headroom and changes nothing for it). Eviction mirrors
`analyze_service._rated_invocations_retention` / `_evict_for_new_scope`
(ticket 06/07) exactly: `move_to_end()` on every hit and every write,
`popitem(last=False)` to drop the least-recently-used entry, one printed line
per eviction naming the evicted and the new `(server, database, schema)`.

Both call sites (`load_cached()`, `get_or_dump()`) now route through
`_retain_in_mem_cache(identity, data)` instead of writing `_mem_cache`
directly. Eviction only ever touches the in-memory copy — the disk-backed
cache (`_save()`/`_load()`) is untouched, so a dropped database is re-read
from disk on its next request rather than re-derived from SQL Server, and the
existing "invalid entry gets discarded" path in `load_cached()` is unchanged.

"Dropping and reloading an unchanged database causes no scope to be derived
again" is not a new test in this ticket — it's the composition of two
already-tested behaviours: this ticket proves a reload after eviction returns
identical content, and ticket 05's content-comparison freshness rule (already
merged, in `service/analyze_service.py`) is what makes identical content read
as "unchanged" instead of invalidating a scope.

Tests added to `tests/test_sql_cache_store.py` (5 new, 57 total in that file;
669 passed / 0 new failures across the full suite — the 12 pre-existing
failures are unrelated live-DB/environment issues, confirmed present on the
branch before this change too):
- bound is respected across more databases than it allows
- least-recently-used (not first-arrived) is the one evicted, eviction is
  printed
- a re-served database survives more new arrivals than the bound
- a database evicted from memory reloads from disk with identical content
- eviction never makes a still-cataloged database unreadable

Reviewed with `/code-review` (Standards + Spec axes, both passed with only
judgement-call notes). Two Standards suggestions were applied: the two new
functions now take `CacheIdentity` instead of a raw cache-key string (so the
eviction log prints structured `server`/`database`/`schema` fields, matching
`CacheIdentity`'s own documented convention), and their docstrings were
written in Traditional Chinese to match the rest of this file (they had
picked up English docstrings from mirroring `analyze_service.py`, which is
English-documented).
