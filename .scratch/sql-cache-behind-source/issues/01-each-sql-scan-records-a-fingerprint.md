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

**Open points for later tickets**

- **Ticket 02: a null recorded Fingerprint.** When the reader fails at scan start,
  the Scan Record holds `"fingerprint": null`. Ticket 02 must decide how a null
  recorded value compares with a current Fingerprint. A plain "differs" rule makes
  the row `behind_source` until the next rescan.
- **Ticket 02/03: the connection address of the check.** The check must give the
  reader the same address as the scan. If it gives none, the reader connects to
  the bare host, which is wrong for a named instance.
- **Ticket 02: documents.** CONTEXT.md has no **Fingerprint** entry yet. ADR-0045
  still says only a C# cache can be `behind_source`. The spec puts these edits in
  the Documents section, and ticket 02 names them.
- **Test gap (accepted).** The fake-cursor tests check that the query names each
  type, but not that the `CASE` puts `IF` and `TF` under `functions`. Only a real
  SQL Server can show this.
