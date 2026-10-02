# The Full SQL Cache Identity Crosses The HTTP Seam

Status: ready-for-agent

This spec records the decisions from the grilling session of 2026-10-02. It
covers two repositories: this one (the Impact server) and `llamaindex-spec-rag`
(the client). It writes no tickets: `to-tickets` slices the work.

The issue that started this work described an older state of the code. The
lookup-review-defects tickets 04, 05 and 09 already added the `db_server` field,
the `ambiguous_database` code and the `AMBIGUOUS_DATABASE` reason. This spec
covers only the part that remains.

## Problem Statement

A person who asks "which programs call this stored procedure" or "which programs
use this table" can get an answer from the wrong Database.

- The catalog of a System declares each Database as a full `(server, name)`
  pair (spec-rag ADR-0003). The client knows the full identity.
- The client sends the first reverse lookup request with the Database name only.
  It sends the declared host only after the server answers with
  `ambiguous_database`.
- Example: the catalog declares `PUR` on `vmsystest07`. The disk holds no cache
  for that pair. The disk holds a cache for `PUR` on `vmsystest08`. The server
  finds one cache with that name, and it answers from `vmsystest08`. Nothing in
  the answer shows the mistake.
- The client removes duplicate declared Databases by name only. A System that
  declares `PUR` on two hosts gets one lookup, and the second Database
  disappears from the answer without a trace.

On the server, the code that turns a request into a SQL Cache Identity exists in
four places. Each copy branches on an optional server. One reverse lookup reads
the cache directory two times for the same identity.

## Solution

The client sends the declared host on the first request of every Database that
has a declared host. The server builds the SQL Cache Identity once, at the top of
each request handler. Every function below the handler receives a SQL Cache
Identity, not a Database name and an optional server.

From the user's side:

- A Database that the user has not scanned on the declared host shows as "not
  scanned". The answer never comes from a cache on another host.
- A System that declares the same Database name on two hosts gets an answer
  from both hosts.
- All other answers stay the same.

The HTTP field `db_server` stays optional. The optional server stops at the
request boundary. It does not go below the handler. This replaces the sentence
"removes the optional server at the source" in the original issue.

## User Stories

1. As an analyst, I want a reverse lookup to read the cache of the declared host, so that I never get callers from a Database on another host.
2. As an analyst, I want a Database that has no cache on its declared host to show as "not scanned", so that I know which scan to run.
3. As an analyst, I want "not scanned" to name the declared host, so that I scan the correct host.
4. As an analyst, I want a System that declares one Database name on two hosts to get answers from both hosts, so that no callers disappear.
5. As an analyst, I want each of those two Databases to appear on its own in the list of skipped Databases, so that I can see which host has no scan.
6. As an analyst, I want an unchanged answer for a System whose Databases have unique names, so that this change does not move results I already trust.
7. As an analyst, I want a System with no declared Database to keep its current behavior, so that older Systems still answer.
8. As an analyst, I want a declared Database with a blank host to keep its current behavior, so that a catalog gap gives the same answer as today.
9. As an analyst, I want a blank-host Database that has caches on two hosts to keep the `AMBIGUOUS_DATABASE` reason, so that I know a host is missing from the catalog.
10. As an analyst, I want `/path_evidence`, `/flow_chain` and `/analyze` to keep "not scanned" for a Database on two hosts with no host named, so that their error meaning does not change.
11. As an operator, I want one reverse lookup request per declared Database, so that the request ceiling of a run is not used by retries.
12. As an operator, I want a reverse lookup to list the cache directory at most one time, so that the lookup stays fast with many caches.
13. As an operator, I want a request that names a host to read no directory listing, so that the answer does not depend on other cache files.
14. As an operator, I want the server to normalize the requested host in the same way for every endpoint, so that `VMSYSTEST07` and `vmsystest07` read the same cache.
15. As a maintainer of the client, I want the declared catalog to be the only source of the host, so that no function parameter can replace the catalog value.
16. As a maintainer of the client, I want the `db_server` parameter of `find_by_sp` and `find_by_table` removed, so that a lookup has one identity source.
17. As a maintainer of the client, I want the retry after `ambiguous_database` removed, so that the lookup loop has one request per Database.
18. As a maintainer of the client, I want the list of lookup Databases to remove duplicates by the full `(server, name)` pair, so that two hosts never merge into one.
19. As a maintainer of the client, I want the client to keep the `AMBIGUOUS_DATABASE` handling, so that a blank-host request still records its reason.
20. As a maintainer of the server, I want each request handler to state if it asks with a host or reads the disk, so that the branch is visible at the call site.
21. As a maintainer of the server, I want the SQL Execution Graph loader to receive a SQL Cache Identity, so that it has no optional server.
22. As a maintainer of the server, I want the SP catalog builder to receive a SQL Cache Identity, so that it has no optional server.
23. As a maintainer of the server, I want the refresh path to state its disk lookup at its own call site, so that the one caller without a host is easy to find.
24. As a maintainer of the server, I want the derived execution evidence scope to carry the identity that the handler built, so that the validity stamp does not build it again.
25. As a maintainer of the server, I want the separate ambiguity check removed, so that a reverse lookup does not read the disk two times.
26. As a maintainer of the server, I want the ambiguity refusal to stay before any source scan, so that an ambiguous request costs one directory listing.
27. As a maintainer of the server, I want no helper that takes an optional server, so that the decision of the canonical-object-identity spec stays true.
28. As a maintainer of both repositories, I want the HTTP contract unchanged, so that I can deploy the client and the server in any order.
29. As a maintainer of both repositories, I want the code `ambiguous_database` unchanged, so that neither repository must change its name for it.
30. As a reviewer, I want each repository change in its own slice, so that I can review each change alone.

## Implementation Decisions

### Client (`llamaindex-spec-rag`)

- The lookup fan-out sends the declared host of each candidate Database on the
  first request. It no longer sends a first request with no host.
- The lookup fan-out no longer retries with the declared host after
  `ambiguous_database`. One candidate Database gets one request.
- A candidate with a blank host sends no `db_server`, as today. This covers the
  `system_id` fallback candidate and a declared Database with a blank server.
  The server then reads the disk. A 409 `ambiguous_database` on such a request
  records the `AMBIGUOUS_DATABASE` reason in `databases_skipped`, as today.
- The `skip_ambiguous_database` flag stays. Only the two reverse lookups set it.
- The no-Database fallback query (all candidates skipped) does not change.
- `find_by_sp` and `find_by_table` lose their `db_server` parameter. The
  payload builder receives the host from the candidate only.
- The resolver of lookup Databases removes duplicates by the `(server, name)`
  pair, not by the name only. Declared order stays.
- The resolver of the single connection target (the first declared Database)
  does not change.

### Server (Impact)

- The request schemas do not change. `db_server` stays optional. A blank value
  counts as no host, as today.
- Each request handler builds the SQL Cache Identity one time, at its top:
  - With a host, it uses the pure identity constructor.
  - With no host, it uses the disk lookup function, which can return an
    identity, nothing, or an ambiguous-server value.
  - The branch stays at each call site. No new function takes an optional
    server (canonical-object-identity spec, the decision that reverted
    a362aac).
- The two reverse lookups (`/find_by_sp`, `/find_by_table`) refuse an
  ambiguous-server value with HTTP 409 `ambiguous_database`. The refusal stays
  before any source scan and before the `cache_only` skip.
- `/path_evidence`, `/flow_chain` and `/analyze` treat an ambiguous-server value
  as no cache. They answer "not scanned", as `CONTEXT.md` states today.
- The separate ambiguity check function goes away. The handler identity replaces
  it.
- The SQL Execution Graph loader takes a SQL Cache Identity (or no identity). It
  no longer takes a Database name and an optional server.
- The SP catalog builder takes a SQL Cache Identity (or no identity). The public
  SP catalog loader for the refresh path and the wrapper discovery tool calls
  the disk lookup function at its own call site.
- The derived execution evidence scope carries the identity that the handler
  built, in place of its normalized `db_server` field. It keeps the Database
  name for the inputs that use the name only, such as the wrapper review
  exclusions. The validity stamp reads the identity from the scope. It does not
  build the identity again.
- The retention key of the scope must still separate two Databases that have
  the same name on different hosts.

### Contract between the repositories

- No HTTP field, status code or error code changes. The two slices have no
  dependency on each other. They can merge and deploy in any order.

## Testing Decisions

- A good test calls the public entry point and checks the external result: the
  HTTP response, the payload on the wire, or the `databases_skipped` list. A
  good test does not call the private loaders or check how many times a private
  function runs. One exception: a test can count directory listings through the
  cache store, because "one listing" is a stated requirement.
- No new test seam. Each repository uses the seam it has today.

Server tests use the FastAPI `TestClient` against the HTTP endpoints. Prior art
is the lookup `db_server` API test module with its `two_hosts` and `one_host`
fixtures, and the exact path evidence test module.

- A request names `vmsystest07`. Only `vmsystest08` has a cache for the
  Database. The answer is `sql_execution_graph_required`. No match comes from
  `vmsystest08`.
- A request names no host. Two hosts hold the Database. The answer is 409
  `ambiguous_database`. The cache store lists the directory one time.
- `/path_evidence` and `/flow_chain` with no host for a Database on two hosts
  still answer "not scanned".
- The current tests in the lookup `db_server` API module stay green.

Client tests mock `httpx.post` and call `find_by_sp` and `find_by_table`. Prior
art is the lookup `db_server` test module in `llamaindex-spec-rag`.

- The catalog declares `PUR` on `vmsystest07`. The first and only request
  carries `db_server=vmsystest07`.
- The catalog declares `PUR` on `vmsystest07` and on `vmsystest08`. The client
  sends two requests, one for each host.
- A candidate with a blank host sends no `db_server`. A 409 on it gives the
  `AMBIGUOUS_DATABASE` reason.
- The current declared-host retry tests change to the new rule: the declared
  host goes on the first request, and no retry follows.

Each slice starts with a failing test, then the change.

## Out of Scope

- A required `db_server` on any HTTP request.
- A new reason code or a new name for `ambiguous_database`.
- The 409 refusal on `/path_evidence`, `/flow_chain` or `/analyze`.
- A registry check of declared pairs on the question-answering path (spec-rag
  ADR-0003 keeps that check on the scan path only).
- The single connection target resolver and the scan command.
- Any return of the reverted one-helper approach (a362aac).

## Further Notes

- Related ADRs: Impact ADR-0009 and ADR-0033; spec-rag ADR-0003 and ADR-0007.
- The `CONTEXT.md` entry **Ambiguous Database** stays correct after this work.
  Update it only if an implementer finds a statement that no longer holds.
- The derived execution evidence scope is a retention key. The implementer must
  keep its equality rules when the field changes from a host to an identity.
- Two of the user-visible effects need the client slice: the correct host and
  the second same-name Database. The server slice alone changes no answer. It
  removes the duplicate identity code and the second directory listing.
