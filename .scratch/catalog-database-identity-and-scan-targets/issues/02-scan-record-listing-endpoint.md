# 02 — Expose Scan Records Through a Read-Only Listing

**What to build:** The caller can ask the analysis service which Databases it has actually scanned and when. A new read-only endpoint lists every SQL cache the service holds, each with its server, database, schema, and Scan Record. The Database Registry keeps recording intent and never gains a scan timestamp, so the two records cannot drift apart.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] A read-only endpoint returns one row per SQL cache held on disk, carrying server, database, schema, and the recorded scan time.
- [ ] Rows are ordered deterministically by server, then database, then schema.
- [ ] The listing enumerates cache data files. A cache whose Scan Record is missing or unreadable is still listed, with its scan time reported as absent — never omitted from the listing.
- [ ] Scan Record files are never themselves reported as caches.
- [ ] A Database that the Database Registry does not list, but which has a cache on disk (scanned by direct server/database targeting), appears in the listing.
- [ ] The endpoint opens no database connection, runs no analysis, and mutates no cache.
- [ ] No Scan Record is written into, mirrored into, or derived from the Database Registry by this ticket or any other.
- [ ] The caller gains a client function for the listing. Nothing calls it yet — ticket 04 is its first consumer.
- [ ] Tests exercise the listing function directly, following this repo's existing service-level test convention and its cache-root fixtures. The HTTP route is a thin pass-through and is not separately tested; this repo's suite has no API-level test precedent.
- [ ] Tests cover: every cache present with its four fields; a data file with a missing or unreadable Scan Record listed with an absent scan time; Scan Record files excluded; and deterministic ordering.
