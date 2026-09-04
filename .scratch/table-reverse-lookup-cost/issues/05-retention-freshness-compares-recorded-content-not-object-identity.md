# 05 — Retention freshness compares recorded content, not object identity

**What to build:** A retained Derived Execution Evidence Scope that stays valid
when its inputs are unchanged, even if those inputs were dropped from memory
and read again. The freshness decision stops depending on a Python object
staying alive.

Today two of the five tracked inputs — the repository scan and the SQL cache —
are compared by object identity. That works only because both process caches
are unbounded and never evict, so the same object comes back on every call. The
comment on the validity stamp states that dependency in as many words.

Two later tickets break it. Bounding the SQL cache in memory means a dropped
database is read again as a new object, which would invalidate every scope that
used it although its content did not change. Storing evidence on disk means the
comparison has to survive a process boundary, where object identity has no
meaning at all.

This ticket is the prefactor that removes the dependency, before either of
those tickets needs it. The repository scan compares by its recorded save time
and source commit. The SQL cache compares by its recorded save time. The three
configuration inputs keep comparing by value, because they are already parsed
from disk on every call.

**Blocked by:** 02 — The routing baseline is recorded before the first
performance change.

**Status:** done

- [x] The repository scan is compared by its recorded save time and source
      commit rather than by object identity.
- [x] The SQL cache is compared by its recorded save time rather than by object
      identity.
- [x] The three configuration inputs keep comparing by value.
- [x] Dropping a SQL cache from memory and reading the same unchanged content
      again does not cause a scope to be derived a second time.
- [x] Dropping a repository scan from memory and reading the same unchanged
      content again does not cause a scope to be derived a second time.
- [x] A changed repository scan still causes a derivation.
- [x] A changed SQL cache still causes a derivation.
- [x] A changed wrapper contract, contract registry, or wrapper review
      exclusion list still causes a derivation.
- [x] An explicit refresh still derives again and replaces what is retained.
- [x] The comment on the validity stamp describes the rule now in force.

## Notes

Seam: `find_by_sp()` and `find_by_table()` driven across several scopes, with a
counter around the derivation. `tests/test_derived_execution_evidence_retention_bound.py`
already uses this shape, and `_count_real_derivations` there is the pattern —
count real derivations rather than inspecting what is retained.

Both stores already write the values this ticket needs. The SQL cache writes a
save time beside each cached database. The repository scan writes a save time
and a source commit beside each scanned root. Read those; do not invent a new
identity.

A source commit is the better signal of the two for the scan: two scans taken
at different times from unchanged code carry the same commit, and should not
force a derivation.

An input with no recorded value must not silently compare equal to another
input with no recorded value. Missing is not a match.

ADR-0013 is unchanged by this ticket. The rule it states — one derivation for
each scope, served only when every tracked input still matches — is the rule
being preserved, not altered.

## Resolution

`_RatedInvocationsValidityStamp` (`service/analyze_service.py`) now carries
`scan_freshness`/`sql_cache_freshness` instead of `scan_identity`/
`sql_cache_identity`. Both read recorded state off disk through two new
functions added for this ticket — `scan_store.cached_saved_at()` and
`sql_cache_store.cached_saved_at()` — mirroring the already-existing
`scan_store.cached_commit()`. Neither derives a new identity: both simply
read the `saved_at`/`source_commit` fields the stores already write to their
`.meta.json` files on every save.

A scan's freshness is `(saved_at, source_commit)`; a missing `saved_at` (no
meta recorded at all) never compares equal to another missing reading — each
such call returns a fresh `object()` sentinel instead — so an unreadable
recording can never be mistaken for "unchanged" (`_freshness_or_sentinel` /
`_scan_freshness`). A present `saved_at` with no `source_commit` (no `.git`
under the root) is a legitimate, stable value and compares normally — this is
what keeps non-git repositories reusable across requests instead of forcing a
derivation on every single one.

Three existing test fixtures (`tests/test_derived_execution_evidence_reuse.py`,
`tests/test_derived_execution_evidence_reuse_table.py`,
`tests/test_derived_execution_evidence_retention_bound.py`) had their `_wire()`
helpers updated to stub the two new reads with fixed, explicit values —
without this, a stubbed `_get_scan`/`load_cached` never touches the real
disk-backed store, so the freshness read would find nothing recorded and
always return a sentinel, forcing every request to re-derive and breaking
every reuse assertion in those files. Two new tests were added to
`test_derived_execution_evidence_reuse.py` specifically for this ticket's
new behavior: dropping the scan/SQL cache from memory and re-reading a
brand-new object with unchanged content still reuses (this is exactly what
object-identity comparison would have gotten wrong). `test_sql_cache_store.py`
gained direct coverage for `sql_cache_store.cached_saved_at()`.

Full suite: 646 passed, 12 pre-existing failures unrelated to this ticket
(confirmed identical on the base branch before this change), 2 collection
errors in `test_search_roles.py`/`test_sp_tables.py` from a missing local
ODBC driver (also pre-existing, unrelated).

**Decision recorded during code review:** the scan's save time and source
commit are compared together (both must match to reuse), not commit alone.
This note's own example ("two scans... from unchanged code carry the same
commit, and should not force a derivation") reads as if commit alone should
excuse a differing save time. It does not, on purpose: a partial refresh
(`scan_store.save_scan`, driven by `analyze_service`'s program-refresh flow)
can change a scan's real content and its recorded save time without the
repository's git commit moving at all — a dirty working tree, or files
refreshed ahead of a commit. Letting a matching commit excuse a differing
save time would let exactly that change go undetected, which is the
wrong-answer risk ADR-0013 forbids trading for a latency win. Requiring both
to match only ever costs one extra derivation it did not strictly need; it
never serves a stale one. Confirmed with the user before implementing.
