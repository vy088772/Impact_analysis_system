# 02 — A method that delegates to a sibling is reported as delegated, not as a gap

**What to build:** A wrapper method that constructs no command of its own, and
whose only database contact is a call to another method declared on the same
type, is reported as a **Delegated Method** naming the sibling it delegates to
— a third outcome beside "classified" and "unclassified".

Today such a method lands in the same bucket as a method whose construct the
resolver genuinely failed to understand. Two different facts are read from one
bucket: a fully-traced delegation blocks Contract creation exactly as an
unexplained gap does.

A Delegated Method counts as understood. The set of unclassified public methods
— the set that blocks Contract creation — keeps its current meaning: a method
the resolver could not account for by any rule.

Measured outcome: the shared `SQLDbContext`'s four delegating methods
(`usp_ExecCmdGetFisrtValueAsync`, `usp_ExecCmdGetDataTableAsync`,
`usp_ExecCmdGetJsonObjectAsync`, `usp_ExecCmdGetJsonObjectListAsync`) move out
of the unclassified set and name the sibling each one calls.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] A method with no command construct of its own, whose only database contact is a call to a method declared on the same type, is reported as delegated and names that sibling method
- [ ] A delegating method that also inspects or reshapes the sibling's result is still reported as delegated — the rule does not require a bare pass-through, because none of the four real methods is one
- [ ] A method that has both its own command construct and a sibling call is classified by its own Command Source; delegation is consulted only for a method that produced no Command Source
- [ ] A method that touches a database type and yields neither a Command Source nor a delegation stays unclassified, exactly as it does today
- [ ] A Delegated Method and an unclassified method are reported under different names, and the behaviour surface completeness check counts a Delegated Method as understood
- [ ] A Delegated Method does not inherit its sibling's database target; the delegation record states where to look, and nothing more
- [ ] The real shared assembly under the IQCS checkout reports its four delegating methods as delegated, each naming its sibling (fixture-gated, skipped when the checkout is absent)
- [ ] `CONTEXT.md` gains **Delegated Method**, defined against "unclassified public method" so the two can never be conflated
- [ ] The existing `SQLFunc` and `SQLObject` classified surfaces are unchanged, asserted whole — neither assembly gains a delegated method it did not have
