# 01: Each SQL Scan Records a Fingerprint, and Old Caches Become `outdated`

**What to build:** When an analyst refreshes a SQL cache, the scan reads the Fingerprint of the Database before it reads any definition. The scan writes the Fingerprint into the Scan Record beside `saved_at`. The SQL cache format version increases by one, so every old SQL cache lists as `outdated` on the update page. One "update all" action rescans the old caches, and each rescan records a Fingerprint.

A **Fingerprint** is a small summary from the system catalog of SQL Server. It holds the latest `modify_date` and the object count for each kind group: procedures (`P`), views (`V`), functions (`FN`, `IF`, `TF`), and tables (`U`).

See the spec: `.scratch/sql-cache-behind-source/spec.md` (decisions Q1, Q5, Q6, Q7, Q8).

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] One function reads the Fingerprint of one SQL Cache Identity. It takes the identity and the optional scan account override. It returns no Fingerprint when it cannot connect or when the query fails.
- [ ] The Fingerprint query reads `sys.objects` of the scanned Database only.
- [ ] The query excludes objects where `is_ms_shipped` is 1, and the schemas `sys`, `INFORMATION_SCHEMA`, and `guest`.
- [ ] A kind group with no objects gives a count of zero and an empty latest time.
- [ ] A SQL scan calls the reader before it reads any definition.
- [ ] The Scan Record holds the Fingerprint beside `saved_at`. The other fields of the Scan Record do not change.
- [ ] The SQL cache format version increases by one. A cache with the old version lists as `outdated` in `GET /cache_freshness`.
- [ ] Tests with a fake cursor (prior art: the SQL analyzer object listing tests) cover the kind groups, the exclusions, and the empty group.
- [ ] An HTTP API test with a fake reader shows that the scan writes the Fingerprint that the reader returned at the start of the scan.
- [ ] `llamaindex-spec-rag` still reads `saved_at` from the Scan Record with no change.
