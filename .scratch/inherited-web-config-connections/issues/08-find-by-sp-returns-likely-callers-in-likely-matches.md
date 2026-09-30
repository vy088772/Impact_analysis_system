# 08 — `/find_by_sp` returns likely callers in `likely_matches`

**What to build:** A client of `/find_by_sp` sees each `likely` caller of the
procedure in a new list. Current clients see no change in `matches` or
`diagnostics`. See the spec, section "`/find_by_sp` contract".

**Blocked by:** None — can start immediately

**Status:** done (2026-09-30)

- [x] The response gains the list `likely_matches`. Each entry has the shape of
      a `matches` entry, with the Evidence Status `likely` and the rating
      reason.
- [x] `matches` holds only `proven` callers.
- [x] `diagnostics` does not change.
- [x] An `unresolved` call does not go into `likely_matches`.
- [x] A `likely` call goes into `likely_matches` only when the service finds
      its source file. If not, the call stays in `diagnostics` only.
- [x] The split by Evidence Status stays inside the `/find_by_sp` service
      function. This ticket adds no shared function for the split.
- [x] `/analyze`, `/find_by_table`, and the flow chain endpoint do not change.
- [x] The OpenAPI document shows the new field.
- [x] Seam B test: one `likely` call and one `proven` call to the same
      procedure. The test checks all three lists.
- [x] Seam B test: one `likely` call with no source file. The test checks that
      the call shows in `diagnostics` only.

## Comments

### 2026-09-30 — implementation notes

- Files of this ticket: `service/analyze_service.py` (the `find_by_sp`
  function only), `service/schemas.py` (`FindBySPResponse` only),
  `docs/openapi/openapi.json`, and the new test file
  `tests/test_find_by_sp_likely_matches.py`.
- The test file holds four tests. Two are the Seam B cases. One checks that an
  `unresolved` call goes into no list. One checks the OpenAPI document.
- The no-source-file test replaces the rating step. A service scan rates only
  a file that it holds, so a real scan cannot give a call with no source file.
- `find_by_sp` leaves each `None` value out when it builds an entry. A `likely`
  call has no Database and no connection source, and the entry schema holds
  text fields. The entry then shows `database: ""` and
  `connection_source: ""`. A `proven` entry does not change.
- A `likely` entry gives `procedure_name` as the SP Catalog keys it, in lower
  case (`usp_shared`). The gateway sets this value, and `diagnostics` shows the
  same value. A client must compare the name without case. Ticket 09 reads
  this field.
- A `likely` entry also carries `unresolved_reason` with the rating reason
  (`unique_across_catalogs`). The serializer sets it for each call that is not
  `proven`. This ticket did not change that.
- The glossary entry Executed Procedure Name says that a rating below `proven`
  answers nothing for `/find_by_sp`. The sentence is about an Embedded
  Procedure Target and stays true. The glossary does not yet say that
  `/find_by_sp` lists `likely` callers. This is a gap for a later
  domain-modeling session.
- Full suite: no failure comes from this ticket. These failures are also on a
  clean copy of HEAD or need a real checkout:
  `test_wrapper_projection_matches_analyze_and_reverse_lookup_surfaces`, and
  `test_retention_fixture_snapshots_and_restores_around_a_test` when another
  test file runs before it.
- The commit holds only the hunks of this ticket. Parallel sessions also
  changed `service/analyze_service.py`, and their hunks stay uncommitted.
