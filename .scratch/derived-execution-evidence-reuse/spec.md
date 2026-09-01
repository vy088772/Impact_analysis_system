# Reuse Derived Execution Evidence Instead Of Rebuilding It Per Request

Status: ready-for-agent

Companion to `llamaindex-spec-rag/.scratch/agent-specification-lookup-without-synthesis/`,
which names this work and explicitly excludes it: "The first cause is the table
reverse lookup rebuilding its evidence on every request. That is a separate
effort and is out of scope for this spec." This spec is that effort.

## Problem Statement

An analyst asks which programs touch a database table and waits about ninety
seconds. The same analyst asking any other shape of question waits about fifteen.

The phase-1 routing baseline measured 180 runs. Questions naming a table sit at
88–97 seconds and never once finish inside thirty. Repetition does not help:
the same question asked three times against the same running service took 91.0,
86.9, and 87.1 seconds. Nothing got faster the second time, so nothing was being
reused.

The reason is that the reverse lookup derives its evidence from zero on every
request, and that derivation does not depend on what was asked.

Answering "which programs touch table X" takes four steps. Two are already
cheap: the repository scan and the SQL cache are both held in memory after their
first load, so neither is re-read from disk. The other two are not:

- Every raw C# fact in the entire repository scan is re-rated into Database
  Invocations, for every file the scan found, regardless of which table was
  named.
- Every Execution Path in the whole SQL Execution Graph is then rebuilt from
  those invocations.

Only after both finish does the requested table name appear, as a filter over
the finished result. Two questions naming two different tables, against the same
repository scan and the same SQL cache, do this identical work twice and throw
one copy away. The stored-procedure reverse lookup shares the same first step,
which is why it sits in the fifteen-second population rather than the ninety-
second one: it skips the path-building half.

The repository has no name for the thing being rebuilt. Without a name, the fact
that it is question-independent stays invisible, and the natural fix — derive it
once per scope — has nothing to attach itself to.

There is also a hazard that a naive fix would introduce. The SQL cache and the
repository scan are already reused in memory, and reusing a stale one only makes
an answer slower, because the Object Location Index falls back to reading the
whole cache. Reusing stale *derived* evidence is not like that. The derived
evidence is the evidence: a stale copy does not slow an answer down, it makes
the answer wrong, and nothing in the response would show it.

## Solution

Name the artifact, derive it once per scope, and refuse to serve it once any
input behind it has moved.

**Derived Execution Evidence** enters the glossary as the rated Database
Invocations and the Execution Paths built from them for one repository scan and
one SQL cache. It is independent of which stored procedure or table a question
names; the name only filters it at the end.

The reverse lookups stop rebuilding it. Both the rating step and the path-
building step are derived once for a scope and reused by every later request in
the same scope. The scope is the identity of everything that can change the
result: the repository scan roots, the complete Database identity the request
routes to, and the wrapper contract selector in force.

Reuse is guarded, not assumed. Each retained derivation carries a validity stamp
of the artifacts it was built from — the repository scan, the SQL cache, and the
configuration files that shape wrapper rating. A request whose stamp does not
match derives again. An explicit refresh always derives again and replaces what
was there. This mirrors the freshness rule the Object Location Index already
uses, with one deliberate difference in consequence: an Object Location Index
that is out of date costs a slower search, and out-of-date Derived Execution
Evidence would cost a wrong answer, so this check may never be skipped as an
optimisation.

Retention is bounded and the bound is visible. Today two systems carry scan
caches and any bound would do. The catalog is expected to reach roughly one
hundred systems, each declaring around four Databases. A single Cross-system
Lookup visits each system once, so a bound smaller than the number of systems
visited would evict every derivation before the next question could reuse it,
and the reuse would silently buy nothing. The bound therefore has to be stated
against that number rather than picked, and reaching it has to leave a trace
rather than quietly discarding work.

Success is measured as **Answer Latency**, `llamaindex-spec-rag`'s term for the
wall-clock time from an analyst submitting a question to seeing the answer, with
its recorded target of the ninetieth percentile under thirty seconds. This
repository does not invent a second, service-side measure: a service that got
faster while the analyst's wait did not is the outcome most worth not
mistaking for success. A baseline is recorded before any behaviour changes, so
the improvement is a comparison rather than a claim.

The reverse lookups keep their present answers exactly. This work changes how
often evidence is derived, never what the evidence says.

## User Stories

1. As an analyst, I want a question naming a database table to come back in
   under thirty seconds nine times out of ten, so that I can ask a follow-up in
   the same sitting instead of switching tasks while I wait.
2. As an analyst, I want the second question I ask about a different table in
   the same system to be fast, so that exploring a change does not cost a full
   wait per table.
3. As an analyst, I want the answer to a table reverse lookup to be exactly what
   it is today, so that the speed-up costs me no confidence in the result.
4. As an analyst, I want a stored-procedure reverse lookup to get faster too, so
   that the two reverse questions behave consistently.
5. As an analyst, I want an answer produced after a repository refresh to
   reflect the refreshed code, so that a faster service never answers from
   evidence that no longer matches the source.
6. As an analyst, I want an answer produced after a SQL cache refresh to reflect
   the refreshed database objects, so that rescanning a database actually
   changes what I am told.
7. As an analyst, I want a changed wrapper contract, contract registry, or
   wrapper review exclusion to take effect on the next question, so that
   configuration I just edited is not silently ignored.
8. As an analyst, I never want a wrong answer in exchange for a fast one, so
   that I do not have to re-verify results I was told were current.
9. As an analyst, I want a table with no matches to still report no matches, so
   that reuse cannot manufacture or hide a hit.
10. As an analyst, I want `write_only` to keep filtering exactly as it does
    today, so that a question about who writes a table is unaffected.
11. As a maintainer, I want one name for the evidence that gets rebuilt, so that
    a future reader can see at a glance that it does not depend on the question.
12. As a maintainer, I want the scope identity to include everything that can
    change the derived evidence, so that two requests that should differ can
    never share one derivation.
13. As a maintainer, I want the validity stamp to cover the repository scan, the
    SQL cache, and the configuration that shapes rating, so that no input can
    move without invalidating what was built from it.
14. As a maintainer, I want an explicit refresh to always re-derive, so that the
    one action a person takes to force freshness cannot be served from
    retention.
15. As a maintainer, I want the retention bound justified against the number of
    systems one Cross-system Lookup visits, so that a later catalog growth does
    not turn the reuse into a no-op without anybody noticing.
16. As a maintainer, I want eviction to be observable, so that a service whose
    reuse has stopped working reports it instead of merely being slow again.
17. As a maintainer, I want the reasoning behind trading memory for latency
    recorded as a decision, so that a future reader does not undo it as
    unnecessary caching.
18. As a maintainer, I want the difference between a stale index and stale
    derived evidence written down, so that nobody copies the index's tolerant
    fallback into a place where it would produce a wrong answer.
19. As a maintainer, I want the reverse lookups' existing responses left
    untouched, so that the caller repository needs no coordinated change.
20. As a reviewer, I want a test proving the derived evidence is produced once
    across repeated requests in one scope, so that the improvement is asserted
    as a count rather than a stopwatch reading.
21. As a reviewer, I want a test proving two different table names in one scope
    share one derivation, so that the question-independence claim is enforced
    rather than assumed.
22. As a reviewer, I want a test proving each invalidation trigger causes a
    re-derivation, so that every freshness rule is exercised individually
    instead of collectively.
23. As a reviewer, I want a test proving the answer is identical with reuse and
    without it, so that the equivalence claim is enforced by the suite.
24. As a reviewer, I want retained state not to leak between tests, so that a
    passing suite cannot depend on the order its tests ran in.
25. As a reviewer, I want a recorded before measurement and a recorded after
    measurement, so that the result is a comparison and not an assertion.
26. As an operator, I want the memory cost to be bounded, so that a long-running
    service does not grow without limit as questions arrive.

## Implementation Decisions

- **Derived Execution Evidence** is added to this repository's domain glossary.
  It names the rated Database Invocations and the Execution Paths built from
  them for one repository scan and one SQL cache, and states that it is
  independent of the object a question names.
- Both halves are reused, not just the first. Rating alone would leave the path-
  building half of the ninety seconds in place, and both halves were confirmed
  to be independent of the requested name.
- The reuse scope identity is the repository scan roots, the complete Database
  identity the request routes to, and the wrapper contract selector. These are
  exactly the inputs that change what is derived.
- Reuse applies to the call sites that derive over the whole repository scan.
  The two call sites that derive over a subset of files selected by the requested
  program names are left alone in this effort. Deriving per file, so that whole-
  scan and subset callers could share entries, is a plausible later refinement
  and is deliberately not attempted here: it would have to prove per-file
  decomposition equivalent to today's result first, and the measured cost sits
  entirely in the whole-scan call sites.
- Each retained derivation carries a validity stamp covering the repository
  scan, the SQL cache it was joined against, and the configuration inputs read
  during rating — the external wrapper contract, the contract registry, and the
  wrapper review exclusions. A mismatch on any one of them re-derives.
- An explicit refresh bypasses retention and replaces the retained entry. It is
  never served from retention.
- The freshness check is a correctness rule, not a performance option. The
  Object Location Index may treat an out-of-date index as absent and fall back
  to a full read because the answer is unchanged either way. Derived Execution
  Evidence has no such property, and this asymmetry is recorded in an ADR.
- Retention is bounded. The bound is expressed and justified against the number
  of systems a single Cross-system Lookup visits, because a bound below that
  number evicts every entry before it can be reused. Reaching the bound is
  recorded observably rather than handled silently.
- An ADR records the decision to reuse Derived Execution Evidence per scope
  rather than rebuild it per request, the memory-for-latency trade-off, and the
  asymmetry against the Object Location Index's tolerant staleness rule.
- Responses of both reverse lookups are unchanged in shape and content. The
  caller repository requires no coordinated change for this effort.
- Answer Latency, defined in `llamaindex-spec-rag`'s glossary, is the acceptance
  measure. It is referenced as that repository's term and not redefined here,
  following the existing cross-repository convention for shared vocabulary.

## Testing Decisions

A good test here asserts what a reverse lookup returns, and how many times the
service derived evidence to return it. It does not assert elapsed time, and it
does not reach past the reverse-lookup interface to inspect how a derivation is
stored.

**Seams, highest first.**

1. `analyze_service.find_by_table()` and `analyze_service.find_by_sp()` — the
   primary seam, and already the seam this area is tested at. Prior art:
   `tests/test_graph_reverse_lookup.py` drives both functions directly with
   fixture scans and SQL caches and asserts on the returned matches.
2. A counter over the evidence-derivation step, observed through that same
   seam. Prior art for asserting that work did *not* happen:
   `tests/test_locate_object.py` proves the SQL cache body is never opened by
   making an open fail the test. The same shape applies here — the assertion is
   "derivation ran once", not "derivation was fast".
3. Retained-state isolation between tests. Prior art:
   `tests/sql_cache_fixtures.py` already snapshots, clears, and restores the SQL
   cache's in-memory retention around a test; retained derivations need the same
   treatment so no test can pass because of another test's leftovers.

**The equivalence test.** The same question returns the same matches with reuse
active and with it defeated — for a table with matches, a table with none, a
`write_only` query, and a stored-procedure lookup.

**The reuse test.** Two consecutive requests in one scope derive evidence once.
Two requests naming different tables in one scope also derive once, which is
what proves the derivation is question-independent.

**The invalidation tests.** One test per trigger, each asserting a second
derivation happened and the answer reflects the new input: repository scan
changed, SQL cache changed, external wrapper contract changed, contract registry
changed, wrapper review exclusions changed, and an explicit refresh requested.

**The bound test.** Exceeding the retention bound evicts, records the eviction
observably, and still returns the correct answer.

**No test asserts a wall-clock duration.** Latency is measured by the separate
before and after measurement runs, not by the unit suite.

## Out of Scope

- **A persisted index from object name to the scans that hold it.** Agreed as
  the companion effort and deliberately separated. Reuse stops a scope from
  re-deriving; that index stops an irrelevant scope from being touched at all.
  At roughly one hundred systems both are needed, and the index is what keeps a
  single Cross-system Lookup's working set small enough for reuse to survive.
  It gets its own spec, and it stores object-name presence only — the full
  match record stays where it is built.
- **Parallel or concurrent request handling.** Considered and dropped: it
  multiplies the same expensive work across threads instead of removing it. It
  may be reconsidered after this effort is measured.
- **Anything in the caller repository.** The client-side items settled alongside
  this — hoisting the object-location call above the per-system loop, the
  glossary treatment of reverse-lookup naming, the coverage-disclosure boundary
  of the reverse lookups, and positioning an analyst-supplied system as optional
  narrowing rather than a required step — all belong to `llamaindex-spec-rag`
  and are tracked there.
- **Deriving per file so subset callers share entries.** Noted as a possible
  refinement; not attempted.
- **Any change to what the reverse lookups return.**

## Further Notes

- The stored-procedure reverse lookup shares the rating step but not the path-
  building step, which is consistent with it sitting in the fifteen-second
  population. It should improve, by less.
- The measured numbers behind this spec come from the phase-1 routing baseline
  in the caller repository: 180 observations, mode 4 median 22.0 seconds,
  ninetieth percentile 91.0 seconds, table-naming questions 88–97 seconds with
  none under thirty, everything else median 15.2 seconds.
- Repetition producing 91.0, 86.9, and 87.1 seconds for one question is the
  direct evidence that nothing is reused today. If a later change makes those
  three numbers diverge, that is the signal reuse has started working.
- The caller repository's latency measurement entry point already exists and can
  run one routing mode, at fewer than three repetitions, with final answer
  synthesis enabled. The before and after measurements use it rather than adding
  a measurement to this repository.
- Outcome: the target was missed. Ticket 07 records the after measurement —
  table-naming ninetieth percentile 82.2 seconds against a target of under
  thirty. The derivation reuse works and saves under two seconds per question.
  Final answer synthesis, at a median of 54.8 seconds, is where the wait is.
