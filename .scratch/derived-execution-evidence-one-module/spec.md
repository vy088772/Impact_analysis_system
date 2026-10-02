# One Module Answers the Derived Execution Evidence for a Scope

Status: ready-for-agent

This spec records the decisions of the grilling session of 2026-10-02 (Q1 to Q15).
It carries out ADR-0013 and ADR-0017. It writes no tickets: `to-tickets` slices
the work.

## Problem Statement

Derived Execution Evidence is the full set of rated Database Invocations and the
Execution Paths built from them, for one scope. A scope is one repository scan
crossed with one SQL Cache Identity. ADR-0013 decides that the service derives
this evidence once per scope and filters it for each request. ADR-0017 keeps a
copy on disk.

Only two endpoints obey these decisions today: `/find_by_sp` and
`/find_by_table`. The other endpoints rate the Database Invocations again on
every request:

- `/analyze` rates the files of each program. It rates again for each
  Program Screen, for each shared component, and again when it builds the
  Execution Paths.
- `/path_evidence` rates the program files again, then builds paths one
  invocation at a time until it finds the path_id.
- `/flow_chain` rates again in both directions. The backward direction rates
  every file, which is the same work as `/find_by_table`.

The ADR-0013 freshness check runs only on the two lookup paths. The other rating
calls skip it, and nothing stops a new call site from skipping it too.

`/flow_chain` in the forward direction also finds program files by a different
rule than `/analyze`. It matches the file base name only. For an MVC screen such
as RTTalentDB `JobDutyMtn`, that rule does not find `JobDutyController`. So the
forward chain for that screen is empty, while `/analyze` reports the screen. A
reading of the code found this defect. Nobody ran it yet.

An earlier brief also said that `/path_evidence` loses an `/analyze` path_id
for an MVC screen. That defect is already fixed. `/path_evidence` now selects
program files through the same helper as `/analyze`. This spec does not count it
as a problem.

## Solution

One deep module answers "the evidence for this scope". A deep module is a module
with a small interface that holds most of the logic behind it. Every endpoint
asks this module for evidence, then filters the result. The freshness rule of
ADR-0013 lives only in this module.

The module looks in memory first, then on disk. When the stored stamp matches,
the endpoint gets the retained evidence. When nothing matches, the behaviour
depends on the request:

- A request for the whole scope gets a full derivation. The module retains the
  result in memory and on disk.
- A request that names the files it needs gets a rating of those files only.
  The module does not retain that partial result.

So `/analyze` stays as fast as today when the scope is cold. It gets faster when
a lookup already derived the scope.

`/flow_chain` forward uses the same program resolution as `/analyze`. An MVC
screen then gets a forward chain.

## User Stories

1. As an analyst, I want `/analyze` to reuse the evidence that a reverse lookup
   already derived, so that a program question after a lookup answers fast.
2. As an analyst, I want `/analyze` on a cold scope to be no slower than today,
   so that the first question about a system stays inside the Answer Latency
   target.
3. As an analyst, I want `/analyze` to give the same programs, invocations,
   diagnostics, and Execution Paths as before, so that the change costs me no
   correctness.
4. As an analyst, I want `/path_evidence` to find every path_id that `/analyze`
   gave me, so that I can open the evidence of each path.
5. As an analyst, I want `/path_evidence` to find a path_id without rebuilding
   paths one invocation at a time, so that path evidence answers fast.
6. As an analyst, I want `/path_evidence` without program names to reuse the
   scope evidence, so that a second request on one scope is fast.
7. As an analyst, I want `/flow_chain` backward to reuse the scope evidence that
   `/find_by_table` uses, so that a backward chain after a table lookup is fast.
8. As an analyst, I want `/flow_chain` backward to give the same chains as
   before, so that the speed gain costs me no correctness.
9. As an analyst, I want `/flow_chain` forward to find the controller of an MVC
   screen, so that an MVC system gets a forward chain.
10. As an analyst, I want `/flow_chain` forward and `/analyze` to agree on which
    files and actions one program name owns, so that the two answers do not
    contradict each other.
11. As an analyst, I want `/flow_chain` forward to treat several screens of one
    name as one scope, so that the response shape stays one chain.
12. As the spec-rag client, I want `/flow_chain` forward to return no chain when
    the anchor method is not an action of the screen, so that I try the next
    anchor candidate as I do today.
13. As the spec-rag client, I want the response shapes of all five endpoints to
    stay the same, so that I need no change to read them.
14. As an analyst, I want every endpoint to refuse a retained result whose inputs
    changed, so that no endpoint gives me a stale answer.
15. As an analyst, I want `refresh` on any endpoint to skip both the memory copy
    and the disk copy, so that a refresh always gives me a fresh answer.
16. As an analyst, I want a question on one endpoint never to change the answer
    of a later question on another endpoint, so that the shared evidence is safe.
17. As an analyst, I want `/analyze` without a SQL graph to keep its present
    unresolved-reason wording, so that the shared evidence does not change it.
18. As an analyst, I want `/analyze` to include the invocations of shared
    components on a cold scope too, so that the partial rating misses nothing.
19. As a maintainer, I want one module to hold the scope, the stamp, the
    retention, and the disk store, so that I read the freshness rule in one
    place.
20. As a maintainer, I want a new endpoint to get evidence only through that
    module, so that a new call site cannot skip the freshness check.
21. As a maintainer, I want endpoint tests to inject fixed evidence, so that a
    test of filtering does not depend on the cache internals.
22. As a maintainer, I want module tests to run the real retention against an
    isolated disk folder, so that the freshness rule has direct tests.
23. As a maintainer, I want an ADR that states the partial-rating exception, so
    that nobody reads it later as a silent reversal of ADR-0013.
24. As a maintainer, I want the retention bound comment to state why the bound
    did not change, so that the next capacity review starts from a recorded
    reason.
25. As an operator, I want old evidence files of the previous format to count as
    a miss, so that a version change needs no manual cleanup.
26. As an operator, I want the scope count in memory to stay the same after this
    change, so that the present bound of 100 still holds.
27. As an operator, I want the eviction message to stay, so that I see when the
    catalog outgrows the bound.
28. As a maintainer, I want a failing test to prove the `/flow_chain` forward MVC
    defect first, so that the fix answers a real defect.
29. As a maintainer, I want one run of `/flow_chain` forward against the real
    RTTalentDB, so that the fixture matches a real MVC system.
30. As a maintainer, I want the Impact benchmark suite to give the same result
    before and after the change, so that I know the refactor changed no answer.

## Implementation Decisions

### The module (Q1, Q5)

- A new service module owns Derived Execution Evidence. The scope type, the
  validity stamp, the in-memory retention, the eviction, and the calls to the
  disk store move into it from the analyze service.
- The module has one entry point. It takes the scope, the per-root scans, the
  merged scan, the scan root, an optional list of needed files, and the refresh
  flag.
- The entry point returns one evidence object with four parts:
  - the rated Database Invocations,
  - the joined SQL graph,
  - a function that gives the Execution Paths of a given list of invocations,
    built on first use,
  - a function that finds one Execution Path by path_id, together with the
    invocation that produced it, or gives nothing.
- An endpoint filters the invocations first, then asks for their paths. An
  endpoint does not filter a list of built paths. The `entry_method` of a path
  can differ from the entry method that program ownership reads.
- The path depth stays at the present default of 5 for every endpoint.

### Cache behaviour (Q2)

- The module looks in memory, then on disk. A stamp match returns the retained
  evidence. The stamp keeps its five inputs and its comparison rule.
- `refresh` skips both copies, as ADR-0017 already requires.
- A miss with no needed files runs a full derivation. The module retains the
  result in memory and writes it to disk.
- A miss with needed files rates those files only. The module does not retain
  this partial result, in memory or on disk.
- This works because rating is independent per file. The observed call evidence
  index already comes from the whole scan. A path_id depends only on its own
  invocation. So a filtered full result and a partial result are equal.

### Paths and the disk format (Q6)

- The evidence keeps the Execution Paths per invocation. The path lookup uses an
  index by path_id.
- The disk store format version increases by one. A file of the old version
  counts as a miss, and the scope derives again one time.

### Read-only evidence (Q7)

- Retained evidence is read-only for every endpoint.
- The module does not copy on each request. An endpoint that changes a path
  copies it first. Today only `/analyze` without a SQL graph and without a
  Database does this: it rewrites the unresolved reason.

### Endpoints

- `/analyze` gives the module the files of all its resolutions and of their
  shared components as the needed files. It filters each resolution from that
  one result.
- `/path_evidence` with program names gives the module the needed files.
  Without program names it asks for the whole scope. It finds the path through
  the path_id index.
- `/flow_chain` backward asks for the whole scope (Q4).
- `/flow_chain` forward resolves the program name through the same Program
  Screen resolution as `/analyze`, and applies action ownership (Q3).
- When one name resolves to several screens, forward merges their files and
  actions into one scope and builds one chain (Q11).
- When the anchor method is not an owned action, forward returns no chain. The
  spec-rag client already reads that as "try the next anchor" (Q12).
- `/find_by_sp` and `/find_by_table` move to the new entry point with no change
  in behaviour.

### Retention bound (Q9)

- The bound stays at 100. Only full derivations enter the retention. Those come
  from the same scopes as before, so the scope count does not grow.
- A hit from `/analyze` moves its scope to the newest position. This only delays
  its eviction.
- The settings comment states this reasoning.

### Decision record (Q10)

- A new ADR-0040 states the partial-rating exception. It states that the
  freshness rule does not change, and that only the miss behaviour of a request
  with needed files differs from ADR-0013.

## Testing Decisions

A good test checks external behaviour: the evidence an endpoint returns, or the
answer the module gives. It does not read the retention dictionary or count
private calls through patches.

Two seams carry the tests (Q8, Q15):

- **The endpoint seam.** Each of the five endpoint functions takes an optional
  evidence source. The default is the real module. A test gives an in-memory
  source with fixed invocations and a fixed graph. These tests cover program
  matching, action ownership, the path_id lookup, the forward chain for an MVC
  screen, the empty forward chain for a foreign anchor, and the read-only rule.
- **The module seam.** Tests call the module entry point with the real retention
  and an isolated disk folder. These tests cover a stamp mismatch, `refresh`, a
  partial miss that writes nothing, an old-format file as a miss, the eviction
  order, and the per-invocation path index.

The present freshness tests move to the module seam. Today they reach into the
analyze service retention and patch the rating step.

Prior art:

- The retention fixture that isolates memory and disk for the present evidence
  tests.
- The Program Screen fixtures, which build MVC scans such as `JobDutyMtn`.
- The present path evidence program file tests, and the present evidence reuse
  tests for stored procedures and tables.

Two checks run outside the seams:

- The `/flow_chain` forward MVC defect starts with a failing test on the
  `JobDutyMtn` fixture. After the fix, one run against the real RTTalentDB must
  return a forward chain (Q13).
- The Impact benchmark suite runs before and after the change. The results must
  be equal. Three ids give different results in a worktree because of the path,
  and they are not a regression (Q14).

## Out of Scope

- A change to the five stamp inputs or to their comparison rule.
- A change to the response shape of any endpoint.
- A bound on the other in-memory caches: the scan cache and the SQL cache.
- An expiry rule for the evidence files on disk.
- A lock around a derivation. ADR-0017 already declines one.
- A change in the spec-rag client.
- The `/path_evidence` program file defect. Commit `67f1eb3` already fixed it.

## Further Notes

- The `/flow_chain` forward change is the only change that a user sees in an
  answer. An MVC screen that gave no forward chain now gives one.
- After the release, the first request on each scope is slow one time, because
  the disk format version changes.
- The brief that started this work used old line numbers. The code moved after
  it was written.
