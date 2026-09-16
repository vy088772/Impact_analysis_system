# 04 — Observed Call Evidence clears a method that touches no database

**What to build:** The analyzer clears a wrapper call by itself when the
evidence proves that the method it reaches touches no database. A maintainer
writes no exclusion entry for such a method, and the rule serves every System at
once.

The gateway classifies a wrapper call as `not_applicable` when two conditions
hold together. First, the call resolved to a Local Implementer. Second, the scan
holds at least one Database Invocation record for that implementer's method, and
every such record names no database receiver type.

The rule requires at least one record. A method that holds no record at all
stays in review. The scan does not record a call to another method inside the
same project, so an absence of records proves nothing. In the IQCS checkout
`ViewPath` touches no database and holds no record, and `GetListFromSysParam`
reaches a database through a second method and also holds no record. The two
look identical to this rule, so the rule clears neither.

This rule needs facts from across the whole scan, and the rating step builds one
gateway for each source file. The rating step therefore builds one index first.
The index names every class and method that touches a database receiver type.
The rating step passes that index to each gateway, so the classification stays
in the same place as every other wrapper status. This ticket adds no call graph
to the analyzer host.

Once the rule clears `SqlParam`, the hand-written exclusion entry for it becomes
redundant, and this ticket removes it. The `ViewPath` entry stays.

**Blocked by:** 01 — The ADRs and the glossary record the decisions.

**Status:** ready-for-agent

- [ ] The rating step builds one index of every class and method that touches a
      database receiver type, and passes it to each gateway
- [ ] `IUtilityService.SqlParam` (233 calls) reports `not_applicable` without any
      exclusion entry, because its implementer holds two records and neither
      names a database receiver type
- [ ] `IUtilityService.GetListFromSysParam` (14 calls) stays in review, because
      its implementer holds no record at all
- [ ] `IUtilityService.GetMstCodes` is never cleared, because its implementer
      holds a record that names a database receiver type
- [ ] `IUtilityService.ViewPath` stays in review, and its hand-written exclusion
      entry still applies
- [ ] The hand-written `SqlParam` exclusion entry is removed, and `SqlParam`
      still reports `not_applicable`
- [ ] The analyzer host is unchanged by this ticket
