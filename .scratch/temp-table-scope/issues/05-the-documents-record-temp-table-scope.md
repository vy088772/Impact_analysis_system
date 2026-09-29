# 05: The documents record Temp Table Scope

**What to build:** A future reader finds why a temp table belongs to one
procedure, why calls decide visibility in one direction, and why the expansion
over-reports instead of detecting shadowing. A canonical-object-identity agent
finds what Step 2b must keep.

See "Versions and documents" in the spec.

**Blocked by:** 04.

**Status:** ready-for-agent

- [ ] ADR-0036 records Temp Table Scope, the call visibility rule, the direction rule, and the decision to not detect shadowing. It names the rejected alternative: an analyzer change that reports `CREATE TABLE #name`.
- [ ] ADR-0033, ADR-0034, and ADR-0035 stay free for canonical-object-identity ticket 12.
- [ ] `CONTEXT.md` gains a Temp Table Scope entry under SQL Execution Analysis.
- [ ] The Notes of canonical-object-identity ticket 11 gain one line: Step 2b starts from the new graph version, the node lookup must keep the scope of a scoped temp node, and the calls helper is the one site that changes the call target rule.
