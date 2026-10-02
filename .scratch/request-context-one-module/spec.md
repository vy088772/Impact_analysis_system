# One Module Turns a Request into a Ready Context

Status: ready-for-agent

This spec records the decisions of the grilling session of 2026-10-02 (Q1 to Q10)
and the seam check. It writes no tickets: `to-tickets` slices the work.

## Problem Statement

Five handlers of the analyze service start with the same prelude. The handlers
are `/analyze`, `/path_evidence`, `/find_by_sp`, `/find_by_table`, and `/flow_chain`.
Each prelude does the same steps in the same order:

1. Find the SQL Cache Identity of the Database.
2. Skip the request when `cache_only` is set and a scan root has no scan cache.
3. Resolve the scan roots of the source.
4. Get one Scan for each root.
5. Merge the Scans into one logical Scan.
6. Pick one root for later path work.
7. Build the Derived Execution Evidence scope.

The `cache_only` rule exists as three copies: `/find_by_sp`, `/find_by_table`, and
`/flow_chain`. The text of each copy is the same. A change to the rule needs
three edits, and a missed edit makes the endpoints disagree.

The prelude is also hard to test. Tests reach the prelude only through module
globals of the service. About 171 references patch `resolve_scan_roots`,
`_get_scan`, and `find_cache_identity` by name. Each new handler test must know
which globals the prelude reads.

Two small differences hide inside the copies. `/find_by_sp` and `/find_by_table`
refuse an Ambiguous Database. The other three handlers read it as "not scanned".
`/path_evidence` raises when the source has no roots. The other four handlers do not.

## Solution

One module turns a request into a ready context. The module takes a request and
two stores. It returns one of two results: a ready context, or a `Skipped` marker.

The ready context holds the scan roots, the Scan of each root, the merged Scan,
the chosen root, the SQL Cache Identity result, and the scope. The `cache_only`
rule lives in this one module. Each handler calls the module first, then does its
own work.

The two stores are ports. The scan store port covers source resolution, root
resolution, scan retrieval, and the scan cache check. The cache store port covers
the SQL Cache Identity lookup. Each port has a real adapter and an in-memory
adapter. Handler tests use the in-memory adapters.

The user of the HTTP API sees no change. Every response stays the same.

## User Stories

1. As a maintainer, I want one place that decides the `cache_only` skip, so that a change to the rule needs one edit.
2. As a maintainer, I want `/find_by_sp`, `/find_by_table`, and `/flow_chain` to share the skip rule, so that the three endpoints never disagree.
3. As a maintainer, I want the skip rule to check every candidate root of a multi-folder source, so that a partly scanned system never returns stale partial matches.
4. As a maintainer, I want the skip rule to run without a clone or a pull, so that a skipped request costs one directory listing.
5. As a maintainer, I want the skip rule to be off when `refresh` is set, so that a refresh request always scans.
6. As a maintainer, I want the Ambiguous Database refusal to come before the skip rule, so that the refusal still costs one directory listing and happens before any source scan.
7. As an API caller of `/find_by_sp`, I want the same 409 `ambiguous_database` answer as today, so that my client code keeps working.
8. As an API caller of `/find_by_table`, I want the same 409 `ambiguous_database` answer as today, so that my client code keeps working.
9. As an API caller of `/analyze`, I want a Database on several hosts with no host named to answer "not scanned", so that my client sees no new error.
10. As an API caller of `/flow_chain`, I want the same "not scanned" answer for that Database, so that the endpoint keeps its documented behavior.
11. As an API caller of `/path_evidence`, I want the same "not scanned" answer for that Database, so that the endpoint keeps its documented behavior.
12. As an API caller, I want a skipped `/find_by_sp` request to return the same skipped response, so that my client still detects "not analyzed yet".
13. As an API caller, I want a skipped `/find_by_table` request to return the same skipped response, so that my client still detects "not analyzed yet".
14. As an API caller, I want a skipped `/flow_chain` request to return the same skipped response, so that my client still detects "not analyzed yet".
15. As an API caller of `/path_evidence`, I want the same `source_not_found` error when the source has no roots, so that my error handling keeps working.
16. As a maintainer, I want each handler to build its own skipped response, so that the three response types stay different.
17. As a maintainer, I want the module to return a marker for a skip, so that the module does not use an exception for normal flow.
18. As a maintainer, I want the merged Scan logic to live in one place, so that a fix to the merge reaches all five handlers.
19. As a maintainer, I want the root choice for a multi-root source to live in one place, so that all five handlers pick the same root.
20. As a maintainer, I want the scope to come from the module, so that every handler builds the scope with the same roots and the same SQL Cache Identity.
21. As a maintainer, I want the module to keep the Derived Execution Evidence scope contract of ADR-0013, so that evidence reuse keeps working.
22. As a test author, I want to give a handler an in-memory scan store, so that my test does not patch a module global.
23. As a test author, I want to give a handler an in-memory cache store, so that my test does not patch a module global.
24. As a test author, I want one in-memory adapter for source resolution, scan retrieval, and the scan cache check, so that I set up one object for the whole scan side.
25. As a test author, I want the in-memory adapters to live beside the real adapters, so that other test directories can use them.
26. As a test author, I want to test the skip rule through the handler, so that my test checks the response and not the module internals.
27. As a test author, I want a test that a partly scanned multi-folder source skips, so that the "every root" rule has a guard.
28. As a test author, I want a test that `refresh` bypasses the skip, so that the order of the two flags has a guard.
29. As a test author, I want a test that an Ambiguous Database refuses before any scan call, so that the order of the steps has a guard.
30. As a reviewer, I want the old patches to disappear from the handler tests, so that no test depends on the private names of the service.
31. As a reviewer, I want the refresh code paths to stay as they are, so that this change has a small blast radius.
32. As a reviewer, I want no change in any API response, so that I can review the change as a pure refactor.
33. As a maintainer, I want the handler to take the stores as optional arguments, so that the call sites in the API layer stay the same.
34. As a maintainer, I want the real adapters to wrap the existing functions, so that the change adds no new behavior to the scan or the cache.
35. As a future maintainer, I want the new module to have a short, clear contract, so that a new handler can start with one call.
36. As a future maintainer, I want a new handler to get the `cache_only` rule by calling the module, so that I cannot forget it.

## Implementation Decisions

- Scope (Q1): all five handlers use the new module. The handlers are `/analyze`, `/path_evidence`, `/find_by_sp`, `/find_by_table`, and `/flow_chain`.
- New module: one module builds the request context. Its entry point takes the request and the two stores as keyword arguments. It returns a ready context or a `Skipped` marker (Q3, Q10).
- Ready context fields: the scan roots, the Scan of each root, the merged Scan, the chosen root, the SQL Cache Identity result, and the scope (Q8, Q10).
- The SQL Cache Identity result keeps the raw lookup answer. That answer may be an identity, an Ambiguous Database answer, or nothing. Each handler decides what to do with it (Q2). `/find_by_sp` and `/find_by_table` refuse. The other three read it as "not scanned".
- Step order stays as it is today: identity lookup, then the `cache_only` check, then root resolution, then scans (Q10). The Ambiguous Database refusal must still come before any scan.
- The `Skipped` marker carries no response. Each handler builds its own skipped response, because the three response types differ (Q3).
- The `cache_only` check runs only when `cache_only` is set and `refresh` is not set. It checks every candidate root, and any missing scan cache causes a skip. It must not clone or pull.
- Two ports (Q5). The scan store port holds source resolution, candidate-root peek, root resolution, scan retrieval, the scan cache check, and the repository directory lookup. The cache store port holds the SQL Cache Identity lookup.
- Each port has a real adapter and an in-memory adapter. The real adapters wrap the existing repository manager, scan store, and SQL cache store functions. They add no behavior.
- Injection (Q4): each handler takes the stores as optional arguments. The default is the real adapter. This is the same pattern as the existing `evidence_source` argument. The API layer does not change.
- The adapters module holds the real and the in-memory adapters together (Q9).
- `/path_evidence` keeps its "no roots" check in the handler. The check raises the same `source_not_found` error as today.
- Each handler keeps its own SQL execution graph requirement. That requirement reads the SQL cache and does not belong to the request context.
- Refresh paths stay as they are (Q7). The two refresh functions that always scan with `refresh` set do not use the new module. The service keeps the names that those functions need.
- The Derived Execution Evidence scope is built in the new module. If candidates 8 or 9 change how the scope is built, this decision needs a second look (Q8, provisional).

## Testing Decisions

- A good test checks external behavior only. It calls a handler and asserts on the response, or on the error the handler raises. It does not assert on the fields of the request context.
- One seam (seam check): the handler call. Each test passes in-memory adapters to the handler. No test calls the request context module directly.
- Prior art: `tests/test_derived_execution_evidence_reuse.py` and `tests/test_derived_execution_evidence_reuse_table.py`. Both tests call a handler and give fixed evidence through `evidence_source`.
- Migration (Q6): the same change moves all handler tests that patch `resolve_scan_roots`, `_get_scan`, or `find_cache_identity` to the in-memory adapters. No old patch stays alive for the five handlers.
- Tests that cover the refresh paths keep their patches. The service keeps the names those tests patch.
- New behavior tests, all through the handler seam: a skip for each of the three skipping endpoints, a skip when one root of a multi-folder source has no cache, no skip when `refresh` is set, an Ambiguous Database refusal before any scan call, and "not scanned" for the other three endpoints.
- Compare against the baseline of the full test suite. Some tests give different results in a worktree because of sibling paths. Run the comparison in the main directory.

## Out of Scope

- The refresh code paths of the service.
- Any change to the API request or response schemas.
- A change to how the Ambiguous Database answer maps to an HTTP status.
- A change to the `cache_only` rule itself. This spec moves the rule and does not change it.
- Candidates 8 and 9. The grilling session did not learn what they cover.
- A third port for repository resolution.
- Writing tickets.

## Further Notes

- Line numbers on the original card are out of date. The service file has 4,038 lines. Find the five handlers by name.
- The files of this repository mix CRLF and LF line endings. Edit files in a way that keeps each file's line endings. Check the change with a diff stat before you commit.
- Commit on the local main line only. Do not push, and do not open a branch for each ticket.
- User-facing change of the whole spec: none. Every endpoint returns the same response as before.
