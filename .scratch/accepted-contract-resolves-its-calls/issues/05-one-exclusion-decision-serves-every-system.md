# 05 — One exclusion decision serves every System

**What to build:** A maintainer reviews a framework method once, and that
decision applies to every System. Today the wrapper review exclusion registry
holds one list for each System, so the same decision about the same framework
method is reviewed again for each new System. A maintainer expects to manage
about one hundred Systems, and that does not scale.

The registry gains a Global Exclusion Tier under the key `_global`. An entry
there applies to every System.

A System's own entry wins over a global entry for the same receiver type and
method name. This leaves an escape route for a name that means something
different in one System.

The framework entries already recorded for one System move to the global tier.
Those entries describe framework behavior, and framework behavior does not change
between Systems. An entry that names a System's own custom type stays in that
System's list.

**Blocked by:** 01 — The ADRs and the glossary record the decisions.

**Status:** ready-for-agent

- [ ] An entry under `_global` applies to a System that has no list of its own
- [ ] An entry under `_global` applies to a System that has a list of its own,
      alongside that System's entries
- [ ] A System's own entry wins over a global entry for the same receiver type
      and method name
- [ ] `_global` is never treated as a System identifier when a System is looked
      up by name
- [ ] The framework entries already recorded for one System move to the global
      tier, and that System reports the same exclusions as before the move
- [ ] An entry naming a System's own custom type stays in that System's list
