# 04 — Rebuild the STC contract from the current assembly

**What to build:** The system `STC` binds to a contract that covers every public database operation of its wrapper assembly. The call that the analyzer could not resolve now holds the Evidence Status `proven`, and it leaves the review list.

The three previous tickets change how the system builds a contract. They do not change a contract that already exists. A valid Wrapper Contract Selector disables decompilation for the whole refresh, so a bound system never re-examines its assembly. This ticket runs the one manual procedure that rebuilds the contract for `STC`.

This ticket changes stored configuration. Take a backup first.

**Blocked by:** 01, 02, 03 — the rebuild must produce a complete contract under a correct name, so every code change lands first.

**Status:** ready-for-agent

- [ ] Back up the contract registry and the system catalog before any change.
- [ ] Remove the incomplete contract entry for the `SQLFunc` receiver from the registry.
- [ ] Clear the Wrapper Contract Selector for `STC` in the system catalog.
- [ ] Refresh `STC` once.
- [ ] Contract Onboarding creates a contract that holds three `CreateTable` overloads.
- [ ] The refresh writes the new selector value back to the system catalog for `STC`.
- [ ] The Database Invocation for the two-argument `CreateTable` call holds the Evidence Status `proven`, and it carries a mode and a terminal sink.
- [ ] The unresolved evidence count for `STC` drops by one.
- [ ] The review candidate count for `STC` drops by one.
- [ ] Record the previous and the new contract name, so that a reader can trace the change.
