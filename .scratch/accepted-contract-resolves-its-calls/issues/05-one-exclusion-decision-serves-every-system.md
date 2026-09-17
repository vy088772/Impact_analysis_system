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

**Status:** done

**Note:** `load_wrapper_review_exclusions()` in
`code_analyzer/csharp_analysis_gateway.py` now merges the `_global` tier with
a System's own list, keyed by `(receiver_type, method_name)`; the System's own
entry wins on a matching key. A new `_wrapper_review_exclusion_key()` helper
computes that key and is shared with `_normalize_wrapper_review_exclusions()`
so the key shape has one definition. `config/wrapper_review_exclusions.json`
moved STC's 17 framework-method entries (Add, Combine, Create, Exists,
FindByValue, FindControl, Format, GetExtension, HtmlEncode, IndexOf, Join,
MapPath, Replace, SendMail, Write, DataTable.Select, string.Replace) to
`_global`. STC's own `bindConsignee` (a local helper, not framework) and
IQCS's own `ViewPath`/`IUtilityService` (an application-defined interface, not
framework) stayed in their System's list. Reviewed via `/code-review`
(Standards + Spec axes, both parallel sub-agents): Spec axis found full
checklist coverage with correct classification and no scope creep; Standards
axis flagged one Duplicated Code judgement call, now fixed by the shared key
helper above.

- [x] An entry under `_global` applies to a System that has no list of its own
- [x] An entry under `_global` applies to a System that has a list of its own,
      alongside that System's entries
- [x] A System's own entry wins over a global entry for the same receiver type
      and method name
- [x] `_global` is never treated as a System identifier when a System is looked
      up by name
- [x] The framework entries already recorded for one System move to the global
      tier, and that System reports the same exclusions as before the move
- [x] An entry naming a System's own custom type stays in that System's list
