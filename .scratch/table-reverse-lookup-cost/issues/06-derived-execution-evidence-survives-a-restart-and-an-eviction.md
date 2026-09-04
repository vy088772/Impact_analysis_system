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

**Status:** done

- [x] A scope derived in one process is served from disk in the next, with no
      further derivation.
- [x] A scope evicted from memory is served from disk, with no further
      derivation.
- [x] Each scope occupies one file, replaced in place, so repeated refreshes do
      not accumulate files.
- [x] The file is written atomically, so a reader never observes a partly
      written file.
- [x] Two concurrent derivations of one new scope both complete and leave one
      valid file.
- [x] An unreadable or truncated stored file causes a derivation instead of an
      error.
- [x] A changed repository scan, SQL cache, wrapper contract, contract
      registry, or wrapper review exclusion list causes a derivation and
      replaces the file.
- [x] An explicit refresh derives again even when a valid stored file exists.
- [x] The records a lookup returns are identical to those derived in memory.
- [x] A new ADR records the stored freshness contract.
- [x] ADR-0013 carries one sentence pointing at that new ADR.

## Implementation notes

- New module `service/derived_execution_evidence_store.py`: one pickle file
  per scope under `settings.DERIVED_EXECUTION_EVIDENCE_STORE_ROOT`
  (`./data/derived_execution_evidence` by default), keyed by a sha1 hash of
  the scope's own identity fields only (not the object asked about). Atomic
  write is a unique per-call temp file + `os.replace` onto the target, no
  lock. A read that is missing, unreadable, truncated, or a different
  `_STORE_VERSION` is treated as a miss, never an error — same tolerant
  pattern `scan_store`/`sql_cache_store` already use.
- The stamp (`analyze_service._RatedInvocationsValidityStamp`) is pickled
  as-is rather than re-encoded to JSON. This turned out to give the
  "an unreadable input never matches, even itself" rule (ticket 05) for free:
  pickling a bare `object()` sentinel and unpickling it produces a new
  instance that is never `==` to anything, including another unpickled copy
  of the same original — verified directly before relying on it.
- Wired into `analyze_service._rated_execution_invocations_for_scope` (disk
  read on an in-memory miss, disk write after a real derivation) and
  `_execution_paths_for_scope` (a second disk write once Execution Paths are
  built, so a scope that only ever answered `find_by_sp()` still ends up with
  a complete file the first time `find_by_table()` asks it a question).
- `tests/derived_execution_evidence_fixtures.py`'s `RatedInvocationsRetention`
  now also points `settings.DERIVED_EXECUTION_EVIDENCE_STORE_ROOT` at a temp
  dir for the duration of the `with` block, and restores it after. This was
  required, not optional: every existing ticket 04/05/06 test uses this
  fixture, and without it they would have read and written the real
  `data/derived_execution_evidence` directory on disk.
- One pre-existing test, `test_derived_execution_evidence_retention_bound.py::test_eviction_never_changes_the_answer`,
  asserted the *old* behavior that an eviction always forces a third
  derivation. That assumption is exactly what this ticket changes on purpose
  (an evicted scope is now served from disk), so the test's assertion was
  updated from 3 derivations to 2, with a comment pointing at this ticket's
  own test file for the direct coverage.
- New test module `tests/test_derived_execution_evidence_disk_retention.py`
  (16 tests) covers every checklist item above. Before trusting it, the
  "served from disk after a restart"/"served from disk after an eviction"
  tests were checked manually by temporarily forcing
  `derived_execution_evidence_store.load()` to always return `None` and
  confirming they fail (4 of the 16 fail as expected) — this was a one-off
  verification during implementation, not a test committed to the suite.
- Full suite run: 662 passed, 12 pre-existing failures confirmed unrelated by
  reproducing them on the pre-ticket commit (wrapper-resolution and
  connection-tracking tests, untouched by this change); 2 more test files
  fail to collect in this environment for an unrelated reason (no ODBC driver
  installed).
- `/code-review` (Standards + Spec axes, run in parallel): Spec axis found
  all 11 checklist items delivered correctly, no scope creep beyond an
  unused `clear(scope)` helper. Standards axis flagged the same unused
  helper plus an internal name (`_StoredDerivedExecutionEvidence`) leaking
  into `__all__` and a mixed keyword/positional call style at the two
  `derived_execution_evidence_store.store()` call sites. All three fixed:
  `clear()` removed, `__all__` trimmed to the two real entry points
  (`load`, `store`), both call sites now pass `execution_paths` as a
  keyword. Everything else on both axes was either already correct or a
  deliberate, defensible design choice (no separate `.meta.json`
  cheap-status file, unlike `scan_store`/`sql_cache_store` — not needed
  here since nothing reads freshness without the full payload).

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
