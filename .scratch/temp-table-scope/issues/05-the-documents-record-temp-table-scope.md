# 05: The documents record Temp Table Scope

**What to build:** A future reader finds why a temp table belongs to one
procedure, why calls decide visibility in one direction, and why the expansion
over-reports instead of detecting shadowing. A canonical-object-identity agent
finds what Step 2b must keep.

See "Versions and documents" in the spec.

**Blocked by:** 04.

**Status:** done (2026-09-29)

- [x] ADR-0036 records Temp Table Scope, the call visibility rule, the direction rule, and the decision to not detect shadowing. It names the rejected alternative: an analyzer change that reports `CREATE TABLE #name`.
- [x] ADR-0033, ADR-0034, and ADR-0035 stay free for canonical-object-identity ticket 12.
- [x] `CONTEXT.md` gains a Temp Table Scope entry under SQL Execution Analysis.
- [x] The Notes of canonical-object-identity ticket 11 gain one line: Step 2b starts from the new graph version, the node lookup must keep the scope of a scoped temp node, and the calls helper is the one site that changes the call target rule.

## Notes

What this ticket changed (documents only; other tickets run in parallel):

- `docs/adr/0036-a-temp-table-belongs-to-the-procedure-that-uses-it.md`: new. It records Temp Table Scope, the call visibility rule, the direction rule, and the decision to not detect shadowing. It names the rejected alternative (an analyzer change that reports `CREATE TABLE #name`). It also records the ticket 04 decision that a temp read inside a visible writer keeps the direction of its state, and its cost.
- `CONTEXT.md`: new `Temp Table Scope` entry at the end of SQL Execution Analysis, after `Unresolved Dynamic SQL`.
- `.scratch/canonical-object-identity/issues/11-step-2b-the-read-side-separates-schemas-and-databases.md`: one line added at the end of Notes. Status and checkboxes are unchanged.
- This file.

No code changed. ADR-0033, ADR-0034, and ADR-0035 are still free for canonical-object-identity ticket 12.
