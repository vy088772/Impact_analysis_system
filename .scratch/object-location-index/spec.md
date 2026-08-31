# Object Location Index

Status: ready-for-agent

## Problem Statement

An analyst asks "which programs call this stored procedure?" or "which programs touch this table?". The Reverse Lookup answers that question by reading the Lookup Database Set of every System in the catalog, one Database at a time. Each read opens the whole SQL cache for that Database. The `PUR` cache is 105 MB.

Today the catalog declares 7 (System, Database) pairs, and the wait is tolerable. Most Systems in the organisation have not declared their Databases yet; the expected end state is over 100 Databases. At that size the same single question opens more than 100 cache files in sequence, most of them for nothing.

The cost grows with the number of Databases in the catalog, not with the number of Databases that actually hold the object — which is almost always one or two. The analyst pays for the size of the catalog instead of the size of the answer.

## Solution

Every SQL cache gains an **Object Location Index**: a small companion record, held under the same SQL Cache Identity, listing every object name that cache can answer for. `refresh_sql_cli` writes it as part of a refresh; a backfill tool builds it for caches that already exist, without reconnecting to SQL Server.

A new endpoint, `/locate_object`, answers one question from the indexes alone: "which Databases could hold this name?". It never opens a SQL cache. `llamaindex-spec-rag` calls it once per Reverse Lookup, intersects the reply with each System's Lookup Database Set, and gets a **Candidate Database Set** — the Databases it actually needs to query.

The Candidate Database Set narrows what a search *reads*, never what a search *means*. An index answer of "not here" is authoritative and the cache is skipped unopened. An index that is missing, or older than the cache it describes, counts as absent: that Database is read in full, exactly as today. A stale index therefore makes a search slow, never wrong.

## User Stories

1. As an analyst, I want a Reverse Lookup whose cost tracks the number of Databases that hold the object, so that adding a Database to the catalog does not slow down every question about every other Database.
2. As an analyst, I want a stored-procedure Reverse Lookup that skips Databases which do not define that stored procedure, so that I do not wait for a 105 MB cache to load for nothing.
3. As an analyst, I want a table Reverse Lookup that skips Databases which never touch that table, so that the same saving applies to the table question.
4. As an analyst, I want a table Reverse Lookup to still find a table that is touched only inside a stored-procedure body, so that the index does not remove the very case the endpoint exists for.
5. As an analyst, I want a Reverse Lookup answer that is identical with and without the index, so that I never have to ask "did the index hide something?".
6. As an analyst, I want a Database whose index is missing to be read in full rather than skipped, so that a partial rollout of this feature cannot lose an answer.
7. As an analyst, I want a Database whose index is older than its cache to be read in full, so that a refresh that stopped halfway cannot lose an answer.
8. As an analyst, I want the Databases pruned by a matching index left out of the reported Completeness Boundary, so that a correct and complete answer is not labelled as possibly incomplete.
9. As an analyst, I want a Database that was declared but never scanned to stay in the reported Impact Coverage Scope, so that a genuine gap is still disclosed exactly as it is today.
10. As an operator, I want `refresh_sql_cli` to write the Object Location Index as part of the refresh it already runs, so that I do not have to remember a second command.
11. As an operator, I want the index written after the cache it describes, so that an interrupted refresh leaves the index detectably older instead of quietly wrong.
12. As an operator, I want a backfill tool that builds an Object Location Index from a cache already on disk, so that I do not have to re-scan a 105 MB Database over the network to get the benefit.
13. As an operator, I want the backfill tool to never open a SQL Server connection, so that I can run it safely without scan credentials and without load on the server.
14. As an operator, I want the backfill tool to report which caches it indexed and which it skipped, so that I can confirm the rollout is complete.
15. As an operator, I want to delete an index file at any time without breaking anything, so that I can force a fall back to the old behaviour when I suspect the index.
16. As a caller, I want `/locate_object` to answer for every cache on disk in one request, so that I do not have to ask once per System.
17. As a caller, I want `/locate_object` to report matched Databases and unindexed Databases as two separate lists, so that I can tell "this one holds it" from "I could not tell, read it".
18. As a caller, I want `/locate_object` to name each Database by its full `(server, database)` identity, so that I can match it against a Declared Database Dependency without resolving a bare name.
19. As a caller, I want to state whether I am looking for a stored procedure or a table, so that the endpoint applies the same name normalization the matching endpoint applies.
20. As a caller, I want the existing `/find_by_sp` and `/find_by_table` request and response shapes left unchanged, so that this feature cannot break a caller that has not adopted it.
21. As a caller, I want `/locate_object` to be optional, so that a caller that does not use it keeps working exactly as today.
22. As a caller, I want a `/locate_object` failure to degrade into the current full fan-out, so that an unavailable index never turns a slow answer into no answer.
23. As a reviewer, I want the index derived from the same data the endpoint searches, so that the index can never be less complete than the search it replaces.
24. As a reviewer, I want the index to be allowed to over-report a name but never to under-report one, so that every uncertainty costs one extra cache read instead of one lost answer.
25. As a reviewer, I want stored-procedure names in the index normalized by the same function `/find_by_sp` uses, so that the index cannot prune a name the endpoint would have matched.
26. As a reviewer, I want table names in the index normalized by the same function `/find_by_table` uses, so that the same guarantee holds for tables.
27. As a reviewer, I want the index to carry its SQL Cache Identity, so that an index file moved or renamed by hand is detected instead of trusted.
28. As a reviewer, I want the index to carry the SQL cache format version, so that a cache format change invalidates every index built against the old format.
29. As a reviewer, I want the acceptance measure stated as "how many SQL caches did this Reverse Lookup open?", so that the test is deterministic instead of a wall-clock timing that varies by machine.
30. As a reviewer, I want an ADR recording why we now trust an index instead of opening every cache, so that a future reader does not read ADR-0007 and conclude the code is wrong.
31. As a maintainer, I want the index build to live in one function shared by the refresh path and the backfill tool, so that the two can never produce different indexes from the same cache.
32. As a maintainer, I want the staleness rule expressed in one place, so that the endpoint and the backfill tool cannot disagree about what "stale" means.
33. As a maintainer, I want a System that declares no Database to behave exactly as it does today, so that this feature changes nothing for the nine Systems currently in that state.

## Implementation Decisions

### The Object Location Index

- One index per SQL cache, stored beside that cache under its SQL Cache Identity. Not one global aggregate file: a per-cache index keeps the existing per-cache atomic write, adds no second source of truth, and keeps the identity decoupling of ADR-0009.
- The index is **not** merged into the cache metadata record. That record is the Scan Record — it records the fact that a scan happened. An object list is a different concept and must not share the term.
- Content: two buckets.
  - The stored-procedure bucket holds procedure, function, and view names, each normalized by the same function `/find_by_sp` uses to compare an invocation.
  - The table bucket holds the cache's declared table names **and** every table-like node name in the SQL Execution Graph, each normalized by the same function `/find_by_table` uses.
- The union with graph node names is the point of the table bucket: a table reached only inside a stored-procedure body is exactly what `/find_by_table` exists to find, and a bucket built from declared tables alone would prune it away.
- Table name normalization drops the schema, so `dbo.Orders` and `sales.Orders` collapse to one key. This is already the endpoint's matching behaviour, so it changes no answer. It must be written down so nobody later assumes the index can separate schemas.
- **Over-inclusion is safe, under-inclusion is not.** When it is unclear whether a name belongs in a bucket, include it. The cost of a wrong inclusion is one extra cache read; the cost of a wrong exclusion is a lost answer.
- The index is derived from the same cache content the endpoints search. It therefore cannot be less complete than the search it replaces — including for stored procedures the graph builder failed to parse, which are absent from both.
- The index carries its SQL Cache Identity and the SQL cache format version.

### Staleness

- The guard is file modification time. A refresh writes the cache first and the index second. A reader treats the index as absent when the index is older than the cache, when the format version does not match, or when the file is missing or unreadable.
- The guard must not require reading the cache body. Hashing a 105 MB file at query time would spend exactly what the index saves.
- An absent index is never an error. The Database stays in the Candidate Database Set and is read in full.

### `/locate_object`

- Request: an object name and a kind of `sp` or `table`. No Database scope — the endpoint reads every index on disk.
- Response: `matched` and `unindexed`, each a list of full `(server, database)` identities, plus the count of indexes consulted.
  - `matched`: an index exists, is fresh, and holds the normalized name.
  - `unindexed`: a cache exists on disk but its index is absent by the staleness rule. The caller must read these in full.
  - A cache with a fresh index that does not hold the name appears in neither list. That is the pruning.
- The endpoint opens no SQL cache. A request that would require opening one is a bug, not a fallback.
- `/find_by_sp` and `/find_by_table` are unchanged. Range selection and evidence matching stay separate operations so each can be tested alone.

### The caller side (`llamaindex-spec-rag`, tracked separately)

- One `/locate_object` call per Reverse Lookup, before any fan-out. Candidate Database Set = (`matched` ∪ `unindexed`) ∩ Lookup Database Set, computed per System from that one reply.
- Pruned Databases are not a Candidate Omission and are not disclosed in the Completeness Boundary. They were searched, through the index, and the answer was no. Reporting a negative result as a gap would tell an analyst the answer may be incomplete when it is not.
- A `/locate_object` failure or timeout degrades to today's full fan-out.
- A System that declares no Database keeps today's behaviour: the request carries the system id as the cache name, the service answers HTTP 409 `sql_execution_graph_required`, and the System is skipped.

### Backfill

- A tool that reads each SQL cache already on disk, builds its index with the same shared build function the refresh path uses, and writes it. No SQL Server connection, no change to the cache content.
- It reports the caches it indexed and the caches it skipped.

### ADR

- One ADR in this repo records the decision to treat a matching Object Location Index as authoritative and skip the cache unopened. This repo owns that decision, so the ADR lives here.
- `llamaindex-spec-rag`'s ADR-0007 (`question answering reads every declared database`) gains an amendment note: the search space is unchanged, the number of caches read is not, and it points at the new ADR. A second full ADR there would create two records of one decision that can drift apart.

## Testing Decisions

A good test here asserts external behaviour: what a Reverse Lookup answers, and how many SQL caches it opened to answer. It never asserts the internal shape of an index file beyond what a caller can observe.

**Seams, highest first.** The aim is to add no new seam that is not already how this repo tests this area.

1. `analyze_service.locate_object(request) -> response` — the primary seam. Prior art: `tests/test_graph_reverse_lookup.py` already calls `analyze_service.find_by_sp()` and `analyze_service.find_by_table()` directly against a monkeypatched cache directory, and `tests/sql_cache_fixtures.py` already builds those caches. Every behaviour of matched / unindexed / pruned is testable here without HTTP.
2. `sql_cache_store` index build, write, and staleness — the file-lifecycle seam. Prior art: `tests/test_sql_cache_store.py`. This seam owns the mtime rule, the version rule, and the shared build function. Testing staleness at seam 1 would need clock manipulation through two layers; testing it here is direct.
3. The `/locate_object` route — thin. Prior art: `tests/test_path_evidence_api.py`, which tests routes only for error translation, not behaviour. One test that the route forwards and that a bad `kind` becomes HTTP 400.
4. The backfill tool. Prior art: `tests/test_repair_sql_execution_graphs.py` and `tools/repair_sql_execution_graphs.py` — same shape of tool, same shape of test.

**The acceptance test.** One test proves the equivalence that the whole design rests on: for a fixture with several caches, `find_by_sp` and `find_by_table` return byte-identical results whether the caller consults the index first or fans out over every cache. This is asserted for a match, for a miss, for a stale index, and for a missing index.

**The cost test.** One test counts SQL caches opened per Reverse Lookup and asserts the count equals the size of the Candidate Database Set, not the size of the Lookup Database Set. Wall-clock time is not asserted anywhere.

## Out of Scope

- **A C# scan-side index.** `/find_by_table` also matches inline SQL text in C# source, which uses no Database, so a SQL index cannot prune it. Scan caches are 10 MB at most against 105 MB, and a scan-side index has its own refresh path and its own staleness rules. It stays a separate piece of work.
- **Parallel fan-out.** Sending the surviving requests concurrently is a real, separate improvement. It is deliberately not bundled here, so the cost test above measures pruning alone.
- **Filling in the Declared Database Dependencies of the nine Systems that declare none.** That is catalog data entry, not a prerequisite for this work.
- **Any change to `/find_by_sp` or `/find_by_table` matching logic.** The index only decides which caches to open.
- **Indexing anything other than object names.** No columns, no parameters, no definition text.

## Further Notes

- Measured today: `PUR` 105 MB, `ETON` 856 KB, `STC` 785 KB, `Response` 695 KB, `SysErrorRecord` 40 KB. Five caches, and one of them is 99% of the bytes. `PUR` is declared by both Systems that declare anything, so it is opened on almost every Reverse Lookup. Backfilling `PUR`'s index is where nearly all of the immediate benefit is.
- The cache metadata record currently holds `cache_version`, `server`, `database`, `schema`, and `saved_at`. It holds no content hash, which is why the staleness guard uses modification time.
- `Wrong-cache Non-resolution` in `llamaindex-spec-rag`'s glossary describes rows that stay unresolved only because the search looked in a cache that does not hold the object. Pruning those caches should reduce those rows. That is a welcome side effect, not a goal, and no test asserts it.
