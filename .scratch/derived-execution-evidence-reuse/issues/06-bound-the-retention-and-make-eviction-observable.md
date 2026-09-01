# 06 — Bound the retention and make eviction observable

**What to build:** A stated, justified limit on how much Derived Execution
Evidence is retained at once, and a trace whenever that limit forces something
out.

Two systems carry repository scans today and any limit would do. The catalog is
expected to reach roughly one hundred systems, each declaring around four
Databases. A single Cross-system Lookup visits every system once before coming
back to the first, so a limit below the number of systems visited would evict
every derivation before the next question could reuse it. The reuse would then
buy nothing while still costing the memory it took to build, and nothing in the
service's behaviour would say so — it would simply be slow again, and the obvious
conclusion would be that the reuse never worked.

That silent failure is what this ticket exists to prevent. The number matters
less than writing it down against the thing that determines it, and than making
the moment it is crossed visible.

**Blocked by:** 05 (there is nothing to bound until both halves are retained).

**Status:** done

- [x] Retention has an explicit limit rather than growing without bound
- [x] The limit is documented against the number of systems one Cross-system
      Lookup visits, including the reasoning that a smaller limit evicts entries
      before they can be reused and makes the reuse worthless
- [x] The limit is adjustable without a code change, so a growing catalog does
      not need an edit to raise it
- [x] Reaching the limit and evicting is recorded observably, so a service whose
      reuse has stopped working reports it instead of merely being slow
- [x] Eviction never changes an answer: an evicted scope derives again on its next
      request and returns the same result
- [x] Exceeding the limit is exercised by a test that asserts the eviction, the
      record of it, and the unchanged answer
- [x] The pre-existing unbounded in-memory retention of repository scans and SQL
      caches is left alone; this ticket bounds only what this effort introduced,
      and notes the pre-existing risk rather than silently changing it

**Note:** The bound lives as `settings.DERIVED_EXECUTION_EVIDENCE_RETENTION_LIMIT`
in `config/settings.py` — `DERIVED_EXECUTION_EVIDENCE_RETENTION_LIMIT`, default
`100`, read from the environment so raising it as the catalog grows past roughly
one hundred systems needs no code change. The default and the surrounding comment
are both written against the number this ADR-0013 already names: a single
Cross-system Lookup visits every system in the catalog once before returning to
the first, so a bound below that visit count would evict a scope before the
lookup could ever reuse it — spending the memory and the derivation cost for
nothing.

`service/analyze_service.py`'s `_rated_invocations_retention` (ticket 04's
per-scope retention dict, extended by ticket 05 to also carry Execution Paths)
changed from a plain `dict` to `collections.OrderedDict`, so insertion order is
available to evict by. A new `_evict_for_new_scope(scope)`, called from
`_rated_execution_invocations_for_scope()` immediately before a *new* scope is
inserted, is a no-op whenever `scope` is already retained — replacing an
existing entry's value (a stamp mismatch or an explicit `refresh`) never grows
the dict, so it never needs to evict — and otherwise pops the oldest entry
(`popitem(last=False)`) only once the dict is already at the configured limit.
FIFO by insertion order was chosen over LRU-on-read: a Cross-system Lookup's
access pattern is one round-trip sweep touching every scope once before
returning to the first, so the scope inserted longest ago is exactly the one
the sweep is about to revisit last — FIFO reproduces that ordering without the
extra bookkeeping an LRU-on-read policy would need for no behavioural gain
under this access pattern.

Eviction is recorded with a `print()`, matching the convention this file and
its neighbours (`scan_store.py`, `sql_cache_store.py`) already use for
non-fatal, ops-visible events rather than introducing a new logging mechanism
for one ticket. The message names both the evicted scope and the new scope
that displaced it (`database`, `db_server`, `repo_roots`), so a maintainer
reading server output can tell which system's derivation was just discarded
before it could be reused. Tests assert against this output with `capsys`,
the same fixture `tests/test_program_refresh.py` already uses to assert a
different print-based trace.

Eviction cannot change an answer by construction: the evicted scope is simply
absent from `_rated_invocations_retention` afterward, so its next request
takes the same "nothing retained yet" path a scope's very first request always
takes — same rating step, same path-building step, same response. No new
`else` branch exists for "this scope used to be retained."

The pre-existing unbounded retention this effort's own retention sits next to
— `_scan_cache` in this file, and the process-level caches inside
`scan_store.py` and `sql_cache_store.py` that `_RatedInvocationsValidityStamp`
already documents comparing by object identity — is untouched. The comment
above `_rated_invocations_retention` says so explicitly, so a future reader
does not mistake this ticket's bound for having addressed those too.

Added `tests/test_derived_execution_evidence_retention_bound.py` (2 tests),
self-contained like `tests/test_derived_execution_evidence_reuse_table.py`
rather than importing fixtures from ticket 04's test module. Both turn the
limit down to a small number via `monkeypatch.setattr(analyze_service.settings,
"DERIVED_EXECUTION_EVIDENCE_RETENTION_LIMIT", ...)` so eviction is exercised
without needing anything near the real catalog size:
`test_exceeding_the_limit_evicts_the_oldest_scope_and_records_it` sets the
limit to 2, drives three distinct scopes (one `database` value each, everything
else fixed), and asserts the oldest scope is gone from the retention dict, the
other two remain, and the captured `print()` output names the evicted database.
`test_eviction_never_changes_the_answer` sets the limit to 1, drives a scope out
and back in, and asserts the rating step actually ran again (derivation-call
counter, ticket 04's idiom) while the response's matches are identical to the
scope's first-ever answer.

Ran the new file, the full `derived-execution-evidence-reuse` test set (tickets
03–05, 29 tests), and the full suite before and after this change (`git stash
push -u` on the three changed/new files, then pop) — the failing-test list is
identical both sides, the same 12 pre-existing failures named in tickets
03–05's own notes, none touching this change (605 passed after vs. 603 before,
the difference being this ticket's own 2 net-new tests).
