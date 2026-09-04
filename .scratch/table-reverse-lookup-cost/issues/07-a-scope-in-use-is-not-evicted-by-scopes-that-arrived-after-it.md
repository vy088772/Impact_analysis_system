# 07 — A scope in use is not evicted by scopes that arrived after it

**What to build:** A retained Derived Execution Evidence Scope that keeps its
place while analysts keep using it. An analyst working through one system stops
being slowed down by other analysts asking about unrelated systems.

The retention bound is 100 scopes and eviction is first-in, first-out. A
retained scope does not move when it is served, so its position depends only on
when it arrived. On a shared service that is the wrong rule: an analyst who
asks twenty questions about one system can still lose that scope, because a
hundred unrelated scopes arrived in between. Each such eviction costs the next
request a full rebuild of a result that was correct and in use.

Eviction becomes least-recently-used. A served scope moves to the newest
position. The bound, the setting that controls it, and the message printed when
a scope is evicted all stay as they are.

The comment that justifies first-in, first-out must be rewritten rather than
deleted. Its reasoning is sound for the case it describes: a Cross-system
Lookup sweep touches each scope once, and there the two rules behave
identically because arrival order and use order are the same. Least-recently-used
matches that case equally and additionally protects a reused scope. Say that,
so the next reader does not undo this change believing it was a mistake.

**Blocked by:** 02 — The routing baseline is recorded before the first
performance change.

**Status:** done

- [x] A scope that is served moves to the newest position in the retention.
- [x] With the bound reached, the scope unused for the longest time is the one
      evicted.
- [x] A scope served repeatedly survives the arrival of more new scopes than
      the bound allows.
- [x] A sweep that touches each scope exactly once evicts in the same order it
      does today.
- [x] The retention bound and its setting are unchanged.
- [x] An eviction is still printed, naming the evicted scope and the new one.
- [x] Eviction still changes no answer: an evicted scope derives again and
      returns the same records.
- [x] The comment describing the eviction rule states the rule now in force and
      why it is safe for the sweep case.

## Notes

Seam: `find_by_sp()` driven across several scopes with the bound lowered, as
`tests/test_derived_execution_evidence_retention_bound.py` already does. That
file's two existing tests describe the behaviour being changed; extend it
rather than starting a new file.

The retention bound is not raised in this ticket. One retained scope's memory
cost has not been measured, and raising the bound without that number would
consume the memory ticket 08 is reclaiming.

This ticket is independent of the stored evidence. Storage removes the cost of
an eviction; this ticket reduces how often a useful scope is evicted at all.
Both are wanted, and neither replaces the other.

## Implementation note

`_rated_invocations_retention` stayed an `OrderedDict`; only the write path
changed. A new `_retain()` helper is now the single place that assigns into
it -- it sets the value, then calls `move_to_end(scope)`, which covers both a
brand-new key (already at the back) and a stale key being refreshed (moved
there). The in-memory-hit path (`_rated_execution_invocations_for_scope`)
calls `move_to_end(scope)` directly, since it does not write a new value.
`_evict_for_new_scope` itself is unchanged: `popitem(last=False)` already
pops "the front," and the front now means least-recently-served because
every serve moves its scope to the back.

Extended `tests/test_derived_execution_evidence_retention_bound.py` with two
tests: one asserting a re-served scope is the newest key in the dict, one
asserting a scope re-served before each new arrival survives across two new
scopes at bound=2 (a case a plain first-in-first-out bound would not
survive). Both existing tests in that file still pass unchanged. Full
project test run: 664 passed, 12 pre-existing failures unrelated to this
change (confirmed by reproducing two of them on `git stash`) plus 2
collection errors in `tests/test_search_roles.py` / `tests/test_sp_tables.py`
from a missing local ODBC driver, also pre-existing.
