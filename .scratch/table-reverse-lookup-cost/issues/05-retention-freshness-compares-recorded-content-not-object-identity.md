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

**Status:** ready-for-agent

- [ ] The repository scan is compared by its recorded save time and source
      commit rather than by object identity.
- [ ] The SQL cache is compared by its recorded save time rather than by object
      identity.
- [ ] The three configuration inputs keep comparing by value.
- [ ] Dropping a SQL cache from memory and reading the same unchanged content
      again does not cause a scope to be derived a second time.
- [ ] Dropping a repository scan from memory and reading the same unchanged
      content again does not cause a scope to be derived a second time.
- [ ] A changed repository scan still causes a derivation.
- [ ] A changed SQL cache still causes a derivation.
- [ ] A changed wrapper contract, contract registry, or wrapper review
      exclusion list still causes a derivation.
- [ ] An explicit refresh still derives again and replaces what is retained.
- [ ] The comment on the validity stamp describes the rule now in force.

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
