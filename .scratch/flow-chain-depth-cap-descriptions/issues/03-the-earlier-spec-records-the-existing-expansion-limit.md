# 03 — The earlier spec records the existing expansion limit

**What to build:** A future engineer who reads `.scratch/retire-dead-flow-chain-surface/spec.md` learns that the server already has an expansion limit for nested stored procedures. The engineer also learns why `max_sp_depth` was removed and why the limit stays. The reader of ticket 03 of that spec finds a pointer to this spec. See `../spec.md` for the content of each rewrite.

**Blocked by:** 01 — A test proves where a truncated forward path goes.

**Status:** ready-for-agent

- [ ] The rewrite changes the original text in place. It does not append a separate correction section
- [ ] User story 11 says that the forward chain lists the SP chain up to the server expansion limit, and that the description tells the agent where a truncated path goes
- [ ] User story 16 says that the future engineer learns why the field was removed and why the existing expansion limit stays
- [ ] The Further Notes paragraph "Why remove `max_sp_depth` and not give it an effect" no longer says that the graph gives the full nested SP chain for each path
- [ ] That paragraph says that the server has a separate expansion guard, `max_call_depth` with the value 5, and that the guard reports each truncated path as `call_expansion_truncated`
- [ ] That paragraph says that a change to the guard needs its own spec
- [ ] That paragraph keeps the sentence that rejects the "no caller uses the field" argument
- [ ] The Implementation Decisions entry for the spec-rag client agrees with the corrected user story 11
- [ ] No other part of the earlier spec changed
- [ ] Ticket 03 of the earlier spec has one new line in its Comments that points to this spec
- [ ] The status and the checklist of ticket 03 of the earlier spec did not change

**Note:** this ticket changes only Markdown in the `Impact_analysis_system` repository. If ticket 01 recorded a different behavior, write the rewrite to match the recorded behavior.
