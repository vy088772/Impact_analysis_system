# 02 — Expose Scan Records Through a Read-Only Listing

**What to build:** The caller can ask the analysis service which Databases it has actually scanned and when. A new read-only endpoint lists every SQL cache the service holds, each with its server, database, schema, and Scan Record. The Database Registry keeps recording intent and never gains a scan timestamp, so the two records cannot drift apart.

**Blocked by:** None — can start immediately.

**Status:** done

- [x] A read-only endpoint returns one row per SQL cache held on disk, carrying server, database, schema, and the recorded scan time.
- [x] Rows are ordered deterministically by server, then database, then schema.
- [x] The listing enumerates cache data files. A cache whose Scan Record is missing or unreadable is still listed, with its scan time reported as absent — never omitted from the listing.
- [x] Scan Record files are never themselves reported as caches.
- [x] A Database that the Database Registry does not list, but which has a cache on disk (scanned by direct server/database targeting), appears in the listing.
- [x] The endpoint opens no database connection, runs no analysis, and mutates no cache.
- [x] No Scan Record is written into, mirrored into, or derived from the Database Registry by this ticket or any other.
- [x] The caller gains a client function for the listing. Nothing calls it yet — ticket 04 is its first consumer.
- [x] Tests exercise the listing function directly, following this repo's existing service-level test convention and its cache-root fixtures. The HTTP route is a thin pass-through and is not separately tested; this repo's suite has no API-level test precedent.
- [x] Tests cover: every cache present with its four fields; a data file with a missing or unreadable Scan Record listed with an absent scan time; Scan Record files excluded; and deterministic ordering.

**Implementation notes:**
- `Impact_analysis_system`: `service/sql_cache_store.list_caches()` enumerates `data/sql_cache/*.json` (excluding `*.meta.json`), pairs each data file with its sibling meta file for `scanned_at` (falls back to filename-derived identity when meta is missing/unreadable), sorted by `(server, database, schema)`. `GET /scan_records` (`service/api.py`) is a thin pass-through returning `ScanRecordListResponse` (`service/schemas.py`). `docs/openapi/openapi.json` regenerated. Tests added to `tests/test_sql_cache_store.py` (5 new cases). Since `Impact_analysis_system` never reads the Database Registry at all, "a cache not in the Registry still appears" holds by construction — no registry-specific test was needed on this side.
- `llamaindex-spec-rag`: `impact_orch/rag_client.list_scan_records()` added as a plain GET wrapper, unwired — matches the "no new test seam" testing decision (rag_client's other HTTP wrappers have no direct test precedent either; ticket 04 will cover it through its own mocking).
