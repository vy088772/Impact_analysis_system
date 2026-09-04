# 06 — Derived Execution Evidence survives a restart and an eviction

**What to build:** A Derived Execution Evidence Scope that was derived once is
read back after a service restart, and after an eviction, instead of being
built again. The analyst asking the first question of the day waits as long as
the analyst asking the second.

Path building costs 63.59 seconds for one measured scope of 3,719 Execution
Paths. ADR-0013 already avoids paying it twice, but only inside one process and
only for as long as the retention holds the scope. A restart discards it. A
shared service serving many analysts evicts it. Both send the next request back
to a full rebuild of a result that is still correct.

The evidence is written to disk, one file for each scope, replaced in place.
Disk use then follows the number of distinct scopes, not the number of times
they are refreshed. A scope nobody asks about again keeps its file; no expiry
rule is added.

The freshness rule does not relax. A stored result is served only when all five
tracked inputs still match, using the content comparison ticket 05 introduced.
An explicit refresh ignores the stored file entirely.

The service is concurrent, so two requests can derive one new scope at the same
time. Both are allowed to run and both are allowed to write, because their
results are equal. The write is atomic, so a reader never sees a partly written
file, and no lock is taken, because a lock would hold a request thread while
another derivation runs.

**Blocked by:** 05 — Retention freshness compares recorded content, not object
identity.

**Status:** ready-for-agent

- [ ] A scope derived in one process is served from disk in the next, with no
      further derivation.
- [ ] A scope evicted from memory is served from disk, with no further
      derivation.
- [ ] Each scope occupies one file, replaced in place, so repeated refreshes do
      not accumulate files.
- [ ] The file is written atomically, so a reader never observes a partly
      written file.
- [ ] Two concurrent derivations of one new scope both complete and leave one
      valid file.
- [ ] An unreadable or truncated stored file causes a derivation instead of an
      error.
- [ ] A changed repository scan, SQL cache, wrapper contract, contract
      registry, or wrapper review exclusion list causes a derivation and
      replaces the file.
- [ ] An explicit refresh derives again even when a valid stored file exists.
- [ ] The records a lookup returns are identical to those derived in memory.
- [ ] A new ADR records the stored freshness contract.
- [ ] ADR-0013 carries one sentence pointing at that new ADR.

## Notes

Seam: `find_by_sp()` and `find_by_table()` with a derivation counter, as in
ticket 05. A restart is simulated by clearing the in-memory retention, not by
starting a process.

Prior art for the file layout: `sql_cache_store` and `scan_store` both key a
file by a stable identity and replace it in place, and both write a small
metadata file beside the payload. Follow that shape.

Prior art for tolerating a bad file: `scan_store` treats a failed load as a
cache miss and rebuilds. Copy that, and do not let a damaged file fail a
request.

The atomic write is a temporary file renamed over the target on the same file
system. `sql_cache_store` writes directly today, which is acceptable there
because it writes only during an explicit refresh. This ticket writes on every
cold derivation, so direct writing is not acceptable.

The ADR is required because the stored contract is a rule written to disk that
a future reader cannot infer from the code. It belongs beside ADR-0013, which
states the in-memory version of the same rule.

Do not key the file by anything but the scope. A key that included the table
asked about would multiply the files, and it would contradict the decision that
one derivation serves every table in a scope.
