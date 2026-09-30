# 05 — An unqualified call reaches one procedure

**What to build:** An analyst follows a program into the procedures it reaches, and one unqualified call gives one Execution Path. The graph builder resolves a call that states no schema by the rule of ticket 04 and links it to the one procedure the rule names. An unqualified `sp_` or `xp_` name that the listing does not hold resolves to the `sys` schema and becomes no user node. This closes the conflict with ADR-0035 that the canonical-object-identity spec recorded as an open decision.

See "The resolution rule" (the `sys` rule and the static `EXEC` reading), "The graph builder", and user stories 8, 9, 13, 14 in the spec.

**Blocked by:** 04 — A read or write with no schema resolves as SQL Server does (the call rule uses that ticket's resolution).

**Status:** ready-for-agent

- [ ] A failing graph builder test comes first: a `COMMON` module calls `GetBudgetVersion` with no schema while `COMMON` and `Mitoosi` both hold it, and exactly one call relationship reaches `COMMON.GetBudgetVersion`.
- [ ] A call that no listed procedure answers gives one path with the Unproven Schema mark.
- [ ] An unqualified `sp_` or `xp_` name that the listing does not hold records schema `sys` and schema source `system`, and creates no `dbo` node. The seven caches' `sp_OACreate` and `sp_executesql` calls are the cases.
- [ ] A listed user procedure whose name starts with `sp_` still gets the link.
- [ ] A static `EXEC` inside a module resolves against the module's schema first.
- [ ] The open-decision bullet in the canonical-object-identity spec points to this ticket as its resolution.
- [ ] The golden `path_id` test stays unedited and passes.
- [ ] The whole suite shows no new failure.
