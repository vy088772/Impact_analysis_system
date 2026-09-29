# 13 — Routing expectations describe the new caches

**Spec issue:** 6, the regeneration part

**Repository:** implement this ticket in `llamaindex-spec-rag`, not in this repository.

**What to build:** Every routing expectation names a cache that exists after
Step 2a. A stale expectation that names an old three-part cache identifier is
gone, so no scoring run trusts it.

See "Cross-repository coordination" and issue 6 in the spec.

**Blocked by:** 10, and the operator action: each Database is refreshed on
another machine with the Step 2a code, and the new cache files are copied here.

**Status:** done (2026-09-29)

- [x] Before the regeneration, every cache file in the cache directory has a two-part filename.
- [x] Every routing expectation is regenerated from the new cache files.
- [x] No compatibility layer keeps the old cache identifiers.
- [x] Every cache identifier in the regenerated expectations names a file that exists in the cache directory.
- [x] The whole suite of that repository passes.

## Notes

The regeneration commit sits in `llamaindex-spec-rag`, on branch
`spec_extend_20260701`: `9ea3076`, after `7b4e813`.

- **Cache state before the regeneration.** `data/sql_cache` held seven
  two-part caches, all at SQL cache version 11: EFNETDB, ETON, PUR,
  Response, STC, SysErrorRecord, and eFinance. EFNETDB and eFinance are new.
- **The scan caches also needed a refresh.** The operator refresh copied the
  SQL caches only. The ten C# Scan Results stayed at scan cache versions 35
  to 39, and the service requires version 40 (ticket 07). The service
  therefore skipped every System, and a first regeneration emptied every
  target. We rescanned the ten roots on this machine with the local clones,
  with no pull and no SQL Server. The backup of the old scan cache sits in
  the session scratchpad only. Nine roots kept their `source_commit`.
  TTRDQ moved from `747989e` to `b7ad9f0`, the clone's commit.
- **The regeneration.** The command reused the 42 seeds of the previous
  reviewed file with `--seeds-from`. 34 rows keep their targets. Eight rows
  change. The commit message and the file's `review_notice` state the source
  line behind each change. The draft's `sources` field (local absolute
  paths) is not in the reviewed file, as before.
- **`intent_labels.json`.** Q02 cites `spDelUser` by the two-part STC cache
  id. The cited definition is the same in the new cache.
- **Verification.** Every cache id in the file names a data file and a meta
  file in `data/sql_cache`. No code in `llamaindex-spec-rag` maps a
  three-part id. Old three-part ids stay only in closed `.scratch` records
  and measurement scripts, and no scoring run reads them.
  `load_reviewed_expectation_file` loads the file. `pytest tests`: 1213
  passed, before and after. The two failures that ticket 10 recorded no
  longer occur.
- **TTRDQ answers HTTP 400.** `Y-DOCs_TTRDQ` declares no Database. With the
  old scan cache the service skipped it. With a current scan cache the
  service reaches the Database check and rejects the request. TTRDQ gives
  no target either way. This is an old gap that the rescan exposes.

**Review items left open:**

- **sp-001 loses `response.master`.** The earlier work
  (routing-expectation-independent-derivation ticket 07) named this caller
  "the defect this whole effort exists to catch", as a proven caller.
  The service now rates the call `likely`: `Response/Web.config` holds the
  `PUR` connection only inside a comment, so the call has no resolved
  Database. The C# Scan Result of that call is the same in the old and the
  new scan. The change therefore comes from the service read side, after
  2026-09-07. We did not find the commit. A `likely` match goes to
  `diagnostics`, not to `matches`, so `unproven_programs` does not show
  it. Also, `Response.Master.cs` declares the class `TTPUR`, and the
  Response project may inherit the parent site's `PUR` connection in IIS.
  **Decision (2026-09-29):** the owner confirmed that Response inherits the
  parent site's `PUR` connection in IIS, so the caller is real. The result
  of this regeneration stays, and nobody adds the caller back by hand: every
  target still comes from the caches. The service fix is
  `.scratch/inherited-web-config-connections/issues/01-a-call-in-a-nested-web-application-resolves-its-inherited-connection.md`.
  `routing_expectations_generated_vs_candidate.md` records the change at
  sp-001.
- **`program` is a generic program identity.** `TaskSchedule/Program.cs`
  reads as program `program` under the suffix rule. Any other `Program.cs`
  in Y-Docs_TTPUR gets the same identity.
