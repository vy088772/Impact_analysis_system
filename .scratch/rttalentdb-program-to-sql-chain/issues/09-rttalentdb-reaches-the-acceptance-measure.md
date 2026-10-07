# 09 — RTTalentDB reaches the acceptance measure

**What to build:** Evidence that the forward and backward chains work on a
real MVC system. Each action that `truth.json` lists is either fully matched,
or it is on a named list of misses with a reason that the source confirms.

The measure is 227 of 227 RTTalentDB actions fully matched by
`compare_flow.py`, and the same for the backward probe of ticket 07, except
the named list. Known reasons:

- A stored procedure reached only through a helper parameter (ADR-0020).
- An ambiguous implementation (ticket 06).
- Unresolved Dynamic SQL (for example
  `usp_RPT_SkillClassificationPersonnelDetailQry`).

`truth.py` is a probe, not an oracle. It follows every implementer of an
interface, and the Local Implementer rule follows none of an ambiguous one.
Check each mismatch against the source before you put it on the list or fix
the chain.

See ADR-0044.

**Blocked by:** 05, 06, 07

**Status:** in-progress (2026-10-07)

- [ ] Each forward miss is on the list with a reason and a source location
- [ ] Each backward miss is on the list with a reason and a source location
- [ ] A miss with no known reason gets a fix, or a new ticket that names it
- [ ] The final numbers of both probes are in this ticket
