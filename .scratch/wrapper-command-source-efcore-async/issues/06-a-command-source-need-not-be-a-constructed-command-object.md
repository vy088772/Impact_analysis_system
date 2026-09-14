# 06 — A Command Source need not be a constructed command object

**What to build:** Nothing observable changes. Every wrapper method classifies
exactly as it does today, with the same command semantics, the same terminal
sink and the same Connection Behavior Boundary. This ticket makes the next one
possible.

The Command Source resolver already states the shape this work needs: every
construct that can supply a command text and a terminal sink is recognised by
exactly one rule, and a further construct is one added rule rather than a change
to the classification flow around it. The record the rules produce does not yet
keep that promise. It carries a command object construction and requires a
command variable, and the classification flow reads the command text out of that
construction's first argument.

Ticket 08's construct has neither. Raw SQL executed through a database context's
`Database` facade constructs no command object and binds no command variable;
its command text is an argument of the execution call itself. Added as the
resolver stands, it would force a branch through the classification flow — the
exact change the resolver's own design forbids.

So the promise is made true first. A Command Source describes where a method's
command text comes from and where its terminal sink is. A constructed command
object bound to a variable becomes one way to answer that, not the only shape
the record can hold.

Make the change easy, then make the easy change. The acceptance is that nothing
moved.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] A Command Source states where a method's command text comes from and where its terminal sink is, without requiring a constructed command object bound to a variable
- [ ] The explicit command object rule, the declared command variable rule and the data adapter rule each classify exactly what they classify today
- [ ] The real shared assembly under the IQCS checkout reports byte for byte the same classified, delegated and unclassified sets it reports today (fixture-gated, skipped when the checkout is absent)
- [ ] The existing `SQLFunc` and `SQLObject` classified surfaces are asserted whole and unchanged, and their Contract Fingerprints are unchanged byte for byte
- [ ] The measured Y-DOCs stored-procedure counts hold — this ticket may not move a single one
- [ ] A new construct can be added as one further rule, without a branch in the classification flow around it
