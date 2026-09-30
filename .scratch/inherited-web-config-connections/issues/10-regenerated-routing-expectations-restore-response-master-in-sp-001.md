# 10 — Regenerated routing expectations restore `response.master` in sp-001

**What to build:** A regeneration of the routing expectations with the real
Y-DOCs repository puts `response.master` back in sp-001 as a proven caller,
with no hand edit. This ticket is the acceptance of the whole spec.

**Blocked by:** 05 — A child web application resolves a connection its Parent
Application declares; 09 — spec-rag lists likely callers under
`unproven_programs`

**Status:** done (2026-09-30)

- [x] Rescan Y-DOCs on this machine, because ticket 05 raised the scan cache
      version.
- [x] The `usp_CheckProgramAuth` call in the Response master page resolves to
      the `PUR` Database, names the TTPUR `Web.config` as the declaring file,
      and has the Evidence Status `proven`.
- [x] `/find_by_sp` for `usp_CheckProgramAuth` lists the Response master page
      in `matches`.
- [x] In `llamaindex-spec-rag`, a regeneration with `--seeds-from` puts
      `response.master` back in sp-001 with no hand edit.
- [x] The `review_notice` of the generated file and the generated-versus-
      candidate report record the sp-001 change.
- [x] Issue 01 records the Q1 result: the commit that changed the sp-001 result
      was not found. The ADR-0018 commit did not change the `Web.config` path.
      The `find_by_sp` filter that keeps a non-proven call out of `matches` has
      not changed since 2026-08-12. Issue 01 also links to this spec.

## Comments

### 2026-09-30 — implementation notes

- Rescan: all 10 scan caches (not only Y-DOCs) went from version 42 to 43 on
  this machine. The backup is `data/scan_cache_backup_v42_20260930`. The
  rescan took about 15 minutes.
- Scan result: in the C# Scan Result of Y-DOCs/Response, `Response.Master.cs`
  has the connection `obj` = Database `PUR`, `declared_in` =
  `TTPUR/Web.config`. `QuestionInput.aspx.cs` and `QuestionReply.cs` also
  resolve to `PUR` the same way.
- `/find_by_sp` for `usp_CheckProgramAuth` (system `Y-Docs_TTPUR`, Database
  `PUR`): `matches` holds 6 entries, and one is `response.master`
  (`Response/Response.Master.cs`, `PUR`, `proven`).
- A process from 16:12 already held port 8800 with the old memory cache. It
  answered `skipped: true` for each system. I stopped it and started the
  service again. A service that starts before the rescan has the same problem.
- Regeneration: `--seeds-from` the reviewed file, written to a scratch path,
  then compared. Only sp-001 differs from the reviewed file: `response.master`
  joins `matched_programs` and `required_programs` and leaves
  `unproven_programs`. The other 41 rows keep their targets. The new
  `review_notice` paragraph, the review fields, and the report update are the
  only edits by hand. They are text, not targets.
- The regeneration prints a warning for `Y-DOCs_TTRDQ` (`find_by_sp needs
  database`). It does not change a target. This ticket did not look into it.
- Commit: `llamaindex-spec-rag` branch `spec_extend_20260701`, `4b4cd06`.
  Tests with `routing` or `expectation` in the name: 133 passed.
- Issue 01 now records the Q1 result and links to the spec.
- Not done: the glossary entry for the status `likely` (see the notes of
  tickets 08 and 09).
