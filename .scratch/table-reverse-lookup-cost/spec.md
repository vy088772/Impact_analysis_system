# A Table Reverse Lookup Stops Repeating Work It Has Already Done

Status: ready-for-agent

Successor to `.scratch/derived-execution-evidence-reuse/`, which produced
ADR-0013. That effort removed the repeated cost of one half of a table reverse
lookup. This spec removes the repeated cost of the other half, and it keeps the
first half's result across a process restart.

The measurement behind this spec lives in the companion repository, at
`llamaindex-spec-rag/.scratch/agent-round-waste/filter-table-accesses-measurements.md`.
Read it before you change any timing claim here.

## Problem Statement

A Cross-system Lookup for one database table costs 56 to 59 seconds on every
repeated request. The analyst waits that long for an answer the service already
computed once.

Three separate causes produce that number. Each one repeats work that has not
changed.

**The lineage index is rebuilt once for each Execution Path.**
`filter_table_accesses()` walks every Execution Path in a Derived Execution
Evidence Scope. For each path that reads through a View or a Function, it calls
`_matching_graph_read_lineage()`. That function builds four lookup dictionaries
from the SQL Execution Graph at its top, and it builds them again on every call.
The dictionaries do not depend on the path, and they do not depend on the table
name. One measured scope holds 3,719 Execution Paths, and 2,969 of them reach
that branch. The rebuild costs about 17 milliseconds, so the scope pays 51 to 54
seconds. It pays this on every request, warm or cold, because this half has no
retention at all.

**The Execution Paths are lost when the process stops.** ADR-0013 retains one
scope's Derived Execution Evidence in memory. The retention works: a second
request in the same scope pays zero seconds for path building instead of 63.59
seconds. The retention is process-local. A restart discards it, and the next
request rebuilds all 3,719 paths.

**The retention evicts a scope that is still in use.** The bound is 100 scopes.
Eviction is first-in, first-out, and a retained scope does not move on a hit. A
service that serves many analysts across many systems therefore evicts an active
scope because unrelated scopes arrived after it. Each eviction costs another
63.59 seconds on the next request.

Two supporting facts make the cost visible in the recorded runs.

The recorded routing baseline reports an Answer Latency ninetieth percentile of
163.0 seconds. The recorded target is under 30 seconds. Twenty of ninety runs
meet it. The two question groups that perform a table reverse lookup are the
slowest: the Object Kind Ambiguity group has a median of 54.6 seconds, and the
table-write group has a median of 163.2 seconds.

The Object Kind Ambiguity group records 54.6 seconds with every phase-cost field
empty, because those lookups run before the Agent exists. The companion spec
`llamaindex-spec-rag/.scratch/pre-agent-lookups-enter-the-routing-trace/` adds
the field that attributes them.

A fourth problem sits beside these three, and it grows with the deployment.
`sql_cache_store` holds every loaded SQL cache in an unbounded process cache. It
never evicts. One measured database occupies 105 MB on disk. A deployment with
200 databases therefore grows its memory use until the process restarts.

## Solution

A table reverse lookup builds its lineage index once for each request, keeps its
Execution Paths across a restart, and protects the scope an analyst is still
using.

**The lineage index is built once.** `filter_table_accesses()` builds the index
from the SQL Execution Graph before it walks the Execution Paths. The walk reads
that index. The answer does not change, because the index never depended on the
path.

**The index answers the question in one direction.** The index maps a table to
the terminal operations that reach it. A path then needs one membership test
instead of one graph walk. The index is derived from the graph alone, so one
build serves every table asked in the same request.

**Derived Execution Evidence is written to disk.** A scope that was derived once
is read back after a restart, and after an eviction, instead of being rebuilt.
The freshness rule does not relax: a stored result is served only when every
tracked input still matches.

**The retention protects what is in use.** A retained scope moves to the newest
position when it is served. An eviction then removes the scope that has been
unused for the longest time, not the scope that arrived first.

**The SQL cache stops growing without a bound.** The process cache holds a
configured number of databases. A database beyond the bound is dropped and read
from disk again when it is next needed.

**One log line records what each lookup asked.** The service records the table
name and the scope for every table reverse lookup, so a later decision about
multi-table reuse rests on measured traffic instead of on an assumption.

## User Stories

1. As an analyst asking which programs write to a table, I want the answer in
   seconds rather than a minute, so that I can check an impact before I make a
   change.
2. As an analyst asking a second question about the same table, I want the
   second answer to be fast, so that repeating a question is not punished.
3. As an analyst asking about a different table in the same system, I want the
   already-derived Execution Paths reused, so that the second table costs no
   path rebuild.
4. As an analyst whose question raises Object Kind Ambiguity, I want the
   clarification to arrive quickly, so that I am not made to wait a minute to be
   asked a question.
5. As an analyst working through a system after a service restart, I want the
   first question to be as fast as the second, so that a deployment does not
   reset my waiting time.
6. As an analyst on a shared service, I want my own scope to stay retained while
   I use it, so that another analyst's unrelated question does not slow mine.
7. As an analyst, I want the same answer as before this change, so that a faster
   lookup is not a different lookup.
8. As an analyst asking about a table reached only through a View, I want that
   table still reported, so that the faster index does not lose an indirect
   read.
9. As an analyst asking about writes, I want a Proven Writer to stay a Proven
   Writer, so that the evidence rule is unchanged by a performance change.
10. As an operator of a shared service, I want the process memory to stay
    bounded as databases are added, so that the service does not have to be
    restarted to reclaim memory.
11. As an operator, I want the number of retained databases to be configurable,
    so that I can match the bound to the machine.
12. As an operator, I want the number of retained scopes to stay configurable,
    so that the existing tuning path is unchanged.
13. As an operator, I want a stored Derived Execution Evidence file to be
    replaced in place, so that disk use follows the number of scopes and not the
    number of refreshes.
14. As an operator, I want a partly written file never to be read, so that an
    interrupted write cannot produce a wrong answer.
15. As an operator, I want two concurrent requests for one new scope to be safe,
    so that a shared service does not corrupt its own cache.
16. As an operator, I want an unreadable stored file to cause a rebuild, so that
    one damaged file cannot fail a request.
17. As an engineer, I want the stored evidence to be rejected when the C# scan
    changed, so that a stale answer is never served.
18. As an engineer, I want the stored evidence to be rejected when the SQL cache
    changed, so that a database change reaches the next answer.
19. As an engineer, I want the stored evidence to be rejected when the wrapper
    contract, the contract registry, or the review exclusions changed, so that
    every rating input is still tracked.
20. As an engineer, I want an explicit refresh to ignore the stored evidence, so
    that the one action that forces freshness keeps working.
21. As an engineer bounding the SQL cache, I want the freshness rule to compare
    content rather than object identity, so that dropping a cache entry does not
    invalidate every scope that used it.
22. As an engineer, I want the retained scope to survive a reload of the same
    unchanged SQL cache, so that memory pressure does not cause needless
    rebuilds.
23. As an engineer reading the retention code, I want the eviction comment to
    describe the rule that is in force, so that the next reader does not undo a
    deliberate change.
24. As an engineer investigating multi-table reuse, I want each table reverse
    lookup to record its table and its scope, so that the question can be
    answered from traffic.
25. As an engineer, I want the recorded log line to name the scope, so that two
    systems asking about the same table stay distinguishable.
26. As a reviewer of this change, I want the acceptance measured per phase, so
    that a slow result can be attributed to a step instead of guessed at.
27. As a reviewer, I want a cold scope and a warm scope measured separately, so
    that disk retention is not credited with a saving it did not make.
28. As a reviewer, I want the recorded baseline captured before the first
    performance change lands, so that the comparison has a starting point.
29. As the next engineer in this area, I want the disk format's freshness rule
    recorded as a decision, so that its rules are not re-derived from code.
30. As the next engineer in this area, I want the superseded candidates recorded
    as out of scope with their reasons, so that a rejected option is not
    proposed again as new.

## Implementation Decisions

**`filter_table_accesses()` builds the lineage index once and passes it in.**
The index is derived from the SQL Execution Graph only. `filter_table_accesses`
builds it before its loop and hands it to the lineage resolution.
`_matching_graph_read_lineage()` stops reading the graph directly. The graph and
the index must arrive together, so the signature shows that pairing.

**The index is built on first use inside the request.** A lookup that never
reaches the read branch builds nothing. This preserves today's behaviour, in
which a lookup that finds every match directly pays no index cost at all.

**The index maps a table to the operations that reach it.** It inverts the
`reads` and `contains` relationships that the forward walk follows today. A path
is then matched by testing whether its terminal operation appears in the entry
for the target table. The index covers every table in the graph in one build, so
a second table asked in the same request rebuilds nothing.

**The index does not infer writes.** The forward walk follows `reads` only, and
it treats a table node as terminal. The inverted index keeps both rules. Write
matching stays where it is today, against the path's own recorded writes.

**Derived Execution Evidence is stored one file per Derived Execution Evidence
Scope.** The file is replaced in place, as `sql_cache_store` and `scan_store`
already replace theirs. Disk use therefore follows the number of distinct
scopes, not the number of changes over time.

**The stored file is written atomically.** The writer writes a temporary file
and renames it over the target. A reader therefore never observes a partly
written file. Two concurrent derivations of one new scope are allowed to both
run and both write; the results are equal, so the last writer wins. No lock is
introduced, because a lock would hold a request thread while another derivation
runs.

**An unreadable stored file is treated as absent.** The reader rebuilds, exactly
as `scan_store` already treats a failed load as a cache miss.

**The stored freshness rule carries all five tracked inputs.** The in-memory
stamp tracks the repository scan, the SQL cache, the external wrapper contract,
the contract registry, and the wrapper review exclusions. The stored rule tracks
the same five. The two identity inputs change representation, because Python
object identity cannot cross a process boundary:

- the repository scan compares by the scan cache's recorded save time and source
  commit;
- the SQL cache compares by the SQL cache's recorded save time;
- the three configuration inputs keep comparing by value, as they do today,
  because they are already parsed from disk on every call.

**An explicit refresh still bypasses everything.** `refresh=True` re-derives and
replaces both the retained entry and the stored file.

**The retention becomes least-recently-used.** A served scope moves to the
newest position. Eviction still removes one entry and still prints which scope
it removed. The comment that justifies first-in, first-out is rewritten: a
round-trip sweep touches each scope once, so the two rules behave identically
there, and least-recently-used additionally protects a scope that is reused.

**The SQL cache process cache gains a bound.** `sql_cache_store` retains a
configured number of databases and drops the least recently used beyond it. The
bound has a setting, in the style of the existing retention bound.

**The SQL cache bound lands after the stored freshness rule.** Today's stamp
compares the SQL cache by object identity, and its correctness depends on that
cache never evicting. Bounding the cache first would invalidate every retained
scope for a dropped database, although its content did not change. The content
comparison introduced above removes that dependency, so it must land first.

**The retention bound is not raised.** The memory cost of one retained scope has
not been measured. Raising the bound without that number trades memory the SQL
cache bound is trying to reclaim.

**One log line records each table reverse lookup.** The service records the
requested table name and the Derived Execution Evidence Scope. It is written
where the lookup enters the service, so a lookup that runs before an Agent
exists is recorded too.

## Testing Decisions

A good test here states what a caller observes. Two things are observable: the
records a lookup returns, and whether a derivation ran again. Neither test
asserts that a dictionary was built once, because that is the implementation of
the saving and not the saving itself.

**Seams.** Three, all already in use. No new seam is proposed.

- `query_table_accesses(graph, invocations, table_name, access=...)`, where
  `tests/test_graph_queries.py` already asserts on returned access records.
- `find_by_sp()` and `find_by_table()`, driven across several scopes, with a
  counter around the derivation. `tests/test_derived_execution_evidence_retention_bound.py`
  already uses exactly this shape.
- `sql_cache_store.load_cached()`, where `tests/test_sql_cache_store.py` already
  asserts on cache behaviour.

**Prior art.** `test_query_table_accesses_resolves_view_read_lineage_without_writer`
pins the View lineage path that the index replaces, and it must keep passing
unchanged. `_count_real_derivations` in the retention test is the pattern for
proving reuse: it counts real derivations rather than inspecting what is stored.

**Cases to cover.**

1. Every existing `query_table_accesses` case returns the same records after the
   index change, including the View lineage case and the nested read case.
2. A table reached only through a Function is still reported.
3. A read that reaches the target through two levels of View is still reported.
4. A dynamic-SQL path and a non-proven path stay excluded.
5. Asking two tables in one request derives the index once and returns each
   table's own records.
6. A scope derived in one process is served from disk in the next, with no
   further derivation.
7. A changed repository scan causes a derivation, and the stored file is
   replaced.
8. A changed SQL cache causes a derivation.
9. A changed wrapper contract, contract registry, or review exclusion list
   causes a derivation.
10. `refresh=True` derives again even when a valid stored file exists.
11. An unreadable stored file causes a derivation instead of an error.
12. A partly written file is never observed, because the write is atomic.
13. A scope that is served repeatedly survives the arrival of more new scopes
    than the bound allows.
14. The oldest unused scope is the one evicted, and the eviction is still
    printed.
15. Dropping a SQL cache entry and loading the same unchanged cache again does
    not cause a scope to be derived again.
16. The SQL cache retains no more databases than its bound allows.
17. A table reverse lookup records one log line naming the table and the scope.

**Acceptance.** The acceptance run belongs to the companion repository, and it
is measured with the routing baseline. Two group medians are the criteria:

- the Object Kind Ambiguity group falls from 54.6 seconds to 10 seconds or less;
- the table-write group falls from 163.2 seconds to 45 seconds or less.

A cold scope and a warm scope are measured separately. The stored file and the
retained entry are cleared before a cold measurement, because disk retention
cannot help a scope nobody has derived.

## Out of Scope

- **Answer Latency's thirty-second target.** This spec covers the table reverse
  lookup only. The recorded baseline shows the stored-procedure group at 52.7
  seconds and the control group at 69.6 seconds, and both are dominated by agent
  rounds and synthesis. Those belong to `agent-round-waste` and to
  `context-assembly-cost`.
- **Filtering the Database Invocations before Execution Paths are built.** This
  candidate would reduce the first derivation of a new scope. It makes the
  Execution Paths depend on the table asked, which conflicts with storing one
  file per scope. It is reconsidered only if the table-write criterion fails,
  and the reasoning is recorded in Further Notes.
- **Answering the Object Kind Ambiguity probe without Execution Paths.** This
  candidate is held in reserve for the Object Kind Ambiguity criterion. It
  changes which evidence proves that the table reading matched, and the count of
  related programs is part of the Retained Interpretation term itself. It needs
  its own decision.
- **Raising the Derived Execution Evidence retention bound.** Deferred until one
  retained scope's memory cost is measured.
- **Expiring stored Derived Execution Evidence files.** A scope that is never
  asked again keeps its file. An expiry rule would add a second freshness
  concept, and it would trade a few megabytes of disk for a rebuild.
- **Changing what a table reverse lookup returns.** Every field of the response
  keeps its present meaning.
- **Bounding the repository scan process cache.** It holds 11 MB across five
  repositories in the measured deployment, so it is not urgent.
- **Re-running the routing baseline as part of this spec.** The baseline run is
  a precondition, and it is performed in the companion repository.

## Further Notes

**Order of work.** The log line and the baseline run come first. The baseline
must be captured while the service is unchanged, because it is the comparison
point for every later number. The log line is observability only, so it does not
contaminate that baseline, and landing it early starts collecting traffic
sooner. The index changes follow. Disk storage follows those. The SQL cache
bound lands last, for the reason recorded in Implementation Decisions.

**A decision record is required for disk storage.** ADR-0013 states that Derived
Execution Evidence is computed once for each scope and retained in memory.
Storing it introduces a freshness contract that is written to disk and that a
future reader cannot infer from the code. Record it as a new ADR, and add one
sentence to ADR-0013 pointing at it. The index changes need no decision record,
because they change no rule.

**Why the index change matters more than the storage change.** The recorded
measurement shows `filter_table_accesses` costing 54.18 seconds on a request
where path building already cost zero. Retention never covered that half. Disk
storage removes a cost paid on a cold scope; the index removes a cost paid on
every request.

**Why storage was pulled ahead of the filtering candidate.** A shared service
evicts a scope before it is reused, so a first derivation is the common case and
not the rare one. Storage removes the repeat; the filtering candidate only makes
each repeat cheaper.

**What the traffic log is for.** One measurement question is unanswered: how
many distinct tables one scope is asked about before its inputs change. The
recorded evaluation set cannot answer it, because its six table questions all
name one table. The answer decides whether one file per scope stays the right
shape.

**The interview that produced this spec** ran on 2026-09-03. It corrected two
earlier assumptions: that the thirty-second target was reachable within this
scope, and that bounding the SQL cache was independent of the freshness rule.
