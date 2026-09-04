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

**Status:** ready-for-agent

- [ ] The SQL cache retains no more databases in memory than its bound allows.
- [ ] The database unused for the longest time is the one dropped.
- [ ] The bound is configurable, in the style of the existing retention bound.
- [ ] A dropped database is read from disk again when next needed, and returns
      the same content.
- [ ] Dropping and reloading an unchanged database causes no scope to be
      derived again.
- [ ] A cached entry that fails its validity check is still discarded, as it is
      today.
- [ ] No answer changes as a result of the bound.

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
