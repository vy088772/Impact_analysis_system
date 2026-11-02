# 01: Each SQL Scan Records a Fingerprint, and Old Caches Become `outdated`

**What to build:** When an analyst refreshes a SQL cache, the scan reads the Fingerprint of the Database before it reads any definition. The scan writes the Fingerprint into the Scan Record beside `saved_at`. The SQL cache format version increases by one, so every old SQL cache lists as `outdated` on the update page. One "update all" action rescans the old caches, and each rescan records a Fingerprint.

A **Fingerprint** is a small summary from the system catalog of SQL Server. It holds the latest `modify_date` and the object count for each kind group: procedures (`P`), views (`V`), functions (`FN`, `IF`, `TF`), and tables (`U`).

See the spec: `.scratch/sql-cache-behind-source/spec.md` (decisions Q1, Q5, Q6, Q7, Q8).

**Blocked by:** None (can start immediately)

**Status:** done (2026-10-30)

- [x] One function reads the Fingerprint of one SQL Cache Identity. It takes the identity and the optional scan account override. It returns no Fingerprint when it cannot connect or when the query fails.
- [x] The Fingerprint query reads `sys.objects` of the scanned Database only.
- [x] The query excludes objects where `is_ms_shipped` is 1, and the schemas `sys`, `INFORMATION_SCHEMA`, and `guest`.
- [x] A kind group with no objects gives a count of zero and an empty latest time.
- [x] A SQL scan calls the reader before it reads any definition.
- [x] The Scan Record holds the Fingerprint beside `saved_at`. The other fields of the Scan Record do not change.
- [x] The SQL cache format version increases by one. A cache with the old version lists as `outdated` in `GET /cache_freshness`.
- [x] Tests with a fake cursor (prior art: the SQL analyzer object listing tests) cover the kind groups, the exclusions, and the empty group.
- [x] An HTTP API test with a fake reader shows that the scan writes the Fingerprint that the reader returned at the start of the scan.
- [x] `llamaindex-spec-rag` still reads `saved_at` from the Scan Record with no change.

## Comments

**Implementation notes (2026-10-30)**

- **Branch and commits.** Impact_analysis_system, branch `feat/sql-cache-fingerprint`:
  `88a02dc` adds the reader, the Scan Record field, and format version 12.
  `38d9be7` holds the review follow-ups. llamaindex-spec-rag, branch
  `feat/sql-cache-fingerprint`: `d506428` updates the test fixture only.
- **Where the code is.** `SQLAnalyzer.read_fingerprint()` in
  `code_analyzer/sql_analyzer.py` runs the query. `sql_cache_store.read_fingerprint()`
  is the one reader. `get_or_dump()` calls it before it reads any definition.
  `write_meta()` writes the `fingerprint` field beside `saved_at`.
- **Fingerprint shape.** The keys are `procedures`, `views`, `functions`, and `tables`.
  Each entry holds `count` and `latest_modified`. The time is ISO text with
  microseconds, for example `2026-10-01T09:00:00.000000`. An empty group holds
  `{"count": 0, "latest_modified": ""}`.
- **Schema exclusion.** The query drops `is_ms_shipped = 1` in SQL. The schema rule
  runs over the returned rows, with the same rule as the object listing. So the
  rule also drops the `db_` prefix schemas. The spec says: "the same as the
  object listing of the SQL analyzer".
- **Extra parameter.** The reader also takes an optional `connection_server`. The
  scan gives the raw catalog address, so a named instance (`host\instance`)
  connects correctly. With no value, the reader uses `identity.server`, which has
  no instance part.
- **Cross-repository agreement.** `tests/cross_repository_agreement.json` now shows
  version 12 and a sample Fingerprint. The spec-rag fixture follows it. The
  spec-rag reader (`sql_cache_writers.py`) did not change and still reads `saved_at`.
- **Suite proof.** Impact: `pytest tests/ --ignore=tests/test_search_roles.py
  --ignore=tests/test_sp_tables.py` gives 2019 passed and 1 failed. The failure is
  `test_external_wrapper_contract_identity.py::test_the_shipped_sqlobject_contract_states_its_required_parameter_counts`.
  It also fails on `fff4592`, before this ticket. spec-rag: 2529 passed;
  `test_conversion_encrypted_file.py` fails at collection on its base commit too.
- **Review follow-ups (fixed in `38d9be7`).** The reader had two identical exception
  handlers; now it has one. The reader tests used class attributes for state; now
  they use one instance fake. A test imported `client` inside a function; now the
  import is at module level.

**Open points for later tickets** (first pass; see the second pass below for their outcome)

- Ticket 02 must decide how a null recorded Fingerprint compares.
- The check must give the reader the connection address of the scan.
- CONTEXT.md and ADR-0045 do not mention the Fingerprint.
- No test shows that `IF` and `TF` count under `functions`.

**Review follow-ups, second pass (2026-10-30)**

The user asked to fix every finding of the Spec review and the Standards review.
Commits: `44e4dd9` fixes the first review. A later commit on this branch fixes
the review of `44e4dd9`. The notes above describe the first pass; where they
differ, these notes win.

- **User decision: a null recorded Fingerprint.** The scan still succeeds and
  records `"fingerprint": null`. A null recorded Fingerprint never gives
  `behind_source`. The next successful scan records a value. The spec and
  ticket 02 now state this rule.
- **A typed Fingerprint.** `code_analyzer/sql_fingerprint.py` holds `Fingerprint`
  and `FingerprintEntry` as frozen dataclasses. Times are `datetime` values, so
  no code compares times as text. `Fingerprint.from_rows()` puts each catalog
  row in its kind group. `to_dict()` gives the JSON form of the Scan Record.
  That form did not change, and the spec-rag agreement tests still pass.
- **The query excludes the schemas.** The SQL now holds
  `LOWER(s.name) NOT IN ('guest', 'information_schema', 'sys')` and
  `NOT LIKE 'db[_]%'`. Both come from the constants of the object listing.
  The query groups by `o.type`. A fake-cursor test now shows that `FN`, `IF`,
  and `TF` count under `functions`, and that a type outside the groups counts
  nowhere.
- **Scan Connection.** `ScanConnection(server, user_id, password)` holds the
  connection address and the scan account override. The reader requires one,
  so it never falls back to the bare host. `get_or_dump()` takes one too, and
  the scan and the reader build the analyzer in one function. The first-pass
  note "Extra parameter" no longer applies.
- **Tests.** The tests read `CACHE_VERSION` from `tests/sql_cache_fixtures.py`,
  not the private constant of the cache store.
- **Documents.** CONTEXT.md adds **Fingerprint** and **Scan Connection**, and the
  Scan Record entry names the Fingerprint. ADR-0045 has an amendment of
  2026-10-30. It records the decision and says that ticket 02 builds the check.
  Ticket 02 keeps the ADR item and the Cache Freshness item open, and adds
  items for the null rule, the connection address, and `Fingerprint.from_dict()`.
- **Kept on purpose.** The excluded-schema rule has two forms: a Python check
  for the object listing and an SQL condition for the Fingerprint. Both read the
  same constants. `_save()` keeps its default `fingerprint=None`, because many
  tests call it with no Fingerprint.
- **Accepted gap.** A fake cursor cannot run SQL. Only a real SQL Server can
  show that the `WHERE` condition drops the right rows.
