# 01 — A call in a nested web application resolves its inherited connection

**Status:** done (2026-10-01)

**Found in:** canonical-object-identity ticket 13 (2026-09-29), when the
routing expectations were regenerated.

**Problem:** The service no longer proves a real stored-procedure caller, and
the routing expectations lose it.

- `Y-DOCs/Response/Response.Master.cs:116` calls `dbo.[usp_CheckProgramAuth]`
  through `ConfigurationManager.ConnectionStrings["PUR"]` (line 91).
- `Y-DOCs/Response/Web.config:14` holds the `PUR` connection only inside an
  XML comment. The file declares `PUR-FAQ` only.
- In IIS, Response runs as a child application of the TTPUR site. A child
  application inherits the parent site's `<connectionStrings>`. So at run
  time the call opens `PUR`, which `TTPUR/Web.config:40` declares. The owner
  of the system confirmed this on 2026-09-29.
- The service reads Response's own `Web.config` only. It finds no `PUR`
  entry, so the call has no resolved Database. `usp_CheckProgramAuth` exists
  in one catalog only (PUR), so the call gets the rating `likely`, reason
  `unique_across_catalogs` (`code_analyzer/csharp_analysis_gateway.py`, near
  line 3376).
- `/find_by_sp` puts a `likely` call in `diagnostics`, not in `matches`. The
  routing-expectation lookup reads `matches` only, so the caller also does
  not show in `unproven_programs`. It disappears with no trace.

**The result changed after 2026-09-07.** The reviewed routing expectations of
2026-09-07 held `response.master` in sp-001 as a proven caller.
routing-expectation-independent-derivation ticket 07 named it "the defect
this whole effort exists to catch". The C# Scan Result of this call is the
same in the old scan (version 36) and the new scan (version 40):
`database_source=None`, `connection_variable='obj'`, the same Database
Invocation record. So the change comes from the service read side, not from
the scan. We did not find the commit.

**What to decide:**

1. Which service change after 2026-09-07 stopped proving this call, and was
   the old proof right for the right reason, or right by accident?
2. How the analyzer learns that a web application inherits its parent's
   connections. The repository does not hold the IIS configuration, so the
   parent-child relation is not in the source text. The rule must work for
   every system, with no list per system (ADR-0008, ADR-0018).
3. Whether a `likely` caller must show in the `/find_by_sp` answer, so that
   the routing-expectation lookup can list it under `unproven_programs`
   instead of dropping it.

**Done when:**

- [x] The service proves the `usp_CheckProgramAuth` call in
      `Response/Response.Master.cs` against `PUR`, or a written decision says
      why it must not.
- [x] The rule is general: no system name, no path, and no Database name is
      fixed in code or configuration.
- [x] In `llamaindex-spec-rag`, a regeneration with `--seeds-from` puts
      `response.master` back in sp-001 with no hand edit. The file's
      `review_notice` and `routing_expectations_generated_vs_candidate.md`
      record the change.

**Related:** canonical-object-identity ticket 13;
`llamaindex-spec-rag/evaluation/Impact_analysis/results/routing_expectations_generated_vs_candidate.md`
(sp-001); ADR-0008 (Web.config connection string resolution); ADR-0018
(connection lookup tables are scoped to the project file).

## Comments

### 2026-09-30 — Q1 result and link to the spec

- Spec: `../spec.md` (inherited-web-config-connections). Tickets 02 to 10 of
  that effort answer Q2 and Q3 of this issue.
- Q1 result: the commit that changed the sp-001 result was not found. The
  ADR-0018 commit did not change the `Web.config` path. The `find_by_sp` filter
  that keeps a non-proven call out of `matches` has not changed since
  2026-08-12. The grilling session stopped the search (spec, "Out of Scope").
- Q2: the analyzer reads the IIS URL of each project file and resolves a key
  through the Parent Application chain (ADR-0038).
- Q3: `/find_by_sp` lists a `likely` caller in `likely_matches`, and
  `llamaindex-spec-rag` lists it under `unproven_programs` (tickets 08, 09).
- Ticket 10 proved the call and restored `response.master` in sp-001 by
  regeneration.

### 2026-10-01 — closed after the review of the whole effort

- Each "Done when" box is complete. Ticket 10 proved the call against `PUR`.
  The rule holds no System name, no path, and no Database name. The
  regeneration restored `response.master` in sp-001.
- One part of Q1 stays open: "was the old proof right for the right reason,
  or right by accident?" The spec does not answer it. Its "Further Notes"
  name one hypothesis that nobody examined: the service remap of a single
  Legacy Connection Label onto the selected Database. A later ticket can
  examine it.
