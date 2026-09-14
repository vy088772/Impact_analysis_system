# 05 — A Contract Transaction is reported, and a skipped one names why

**What to build:** A refresh that commits a Contract Transaction says so on the
operator's screen. A refresh that skips one names the gate that stopped it.

The automatic write path is already complete and already tested end to end. A
full refresh decompiles an external wrapper, stages a contract proposal, and
commits the external wrapper registry and the system catalog as one recoverable
unit. `refresh_source` returns that outcome. The `/refresh` response model does
not declare the field, so the API drops it silently, and `refresh_cli` never
prints it. An operator cannot tell a committed transaction from a skipped one.
The path looks absent only because its result never reaches the screen.

The skip reason is worse than absent. The outcome defaults to `not_required`
whenever any gate fails. Today's real IQCS state is "required, but preflight
failed", and the operator reads `not_required` — the literal opposite. This is
the failure mode the wrapper review rules already forbid: two different facts
read from one bucket.

The printed line carries the status and the contract names only. The transaction
identifier and the changed file paths already live in the manifest the Contract
Transaction writes. Printing them on every refresh would crowd out the wrapper
review rows an operator actually reads.

This ticket is sequenced first because it makes every later ticket's outcome
visible. It gates none of them: their acceptance is assertable on the returned
value alone.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] The `/refresh` response carries the Contract Transaction outcome as a declared, typed field — a later rename fails a test rather than silently emptying the line
- [ ] `refresh_cli` prints one line for the Contract Transaction, carrying the status and the contract names
- [ ] A refresh that commits prints a committed status naming the contracts it wrote
- [ ] A refresh skipped because Contract Preflight failed reports `preflight_failed`, not `not_required`
- [ ] A refresh skipped because it was scoped to named programs reports `program_scope`
- [ ] A refresh skipped because no system identifier was given reports `no_system_id`
- [ ] A refresh where no Contract needed committing still reports `not_required`, so the word keeps its literal meaning
- [ ] A refresh that reaches no external wrapper at all prints no Contract Transaction line, so an unrelated refresh gains no noise
