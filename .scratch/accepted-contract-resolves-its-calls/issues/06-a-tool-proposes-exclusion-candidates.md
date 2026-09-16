# 06 — A tool proposes exclusion candidates with their evidence

**What to build:** A maintainer approves a list instead of reading source code.
A new tool reads a scan result and the exclusion registry, and proposes the
entries a maintainer might add. It reports only the candidates that the
automatic rules did not already decide, so the list holds the decisions that
need a person.

Each candidate carries its evidence: the call count, and whether any System ever
resolved that receiver type and method name. A maintainer judges a candidate
from the report alone.

The tool chooses a tier for each candidate. It proposes the Global Exclusion
Tier when the receiver type is empty or names a known framework type. It
proposes the System's own tier otherwise. A maintainer confirms a placement
instead of deciding it.

The tool emits a registry fragment that a maintainer pastes directly into the
registry. The tool only reads. It never edits the registry itself.

**Blocked by:** 04 — Observed Call Evidence clears a method that touches no
database. 05 — One exclusion decision serves every System.

**Status:** ready-for-agent

- [ ] The tool reports no candidate that Observed Call Evidence already cleared
- [ ] The tool reports no candidate that an existing exclusion entry already
      covers, in either tier
- [ ] Each candidate carries its call count and whether any System ever resolved
      that receiver type and method name
- [ ] The tool proposes the global tier for a candidate whose receiver type is
      empty or names a known framework type
- [ ] The tool proposes the System's own tier for every other candidate
- [ ] The emitted fragment matches the registry format, and a maintainer pastes
      it without editing its shape
- [ ] The tool writes nothing to the registry, and running it twice changes no
      file
