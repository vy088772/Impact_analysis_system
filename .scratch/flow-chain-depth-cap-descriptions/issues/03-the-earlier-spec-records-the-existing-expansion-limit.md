# 03 — The earlier spec records the existing expansion limit

**What to build:** A future engineer who reads `.scratch/retire-dead-flow-chain-surface/spec.md` learns that the server already has an expansion limit for nested stored procedures. The engineer also learns why `max_sp_depth` was removed and why the limit stays. The reader of ticket 03 of that spec finds a pointer to this spec. See `../spec.md` for the content of each rewrite.

**Blocked by:** 01 — A test proves where a truncated forward path goes.

**Status:** done

- [x] The rewrite changes the original text in place. It does not append a separate correction section
- [x] User story 11 says that the forward chain lists the SP chain up to the server expansion limit, and that the description tells the agent where a truncated path goes
- [x] User story 16 says that the future engineer learns why the field was removed and why the existing expansion limit stays
- [x] The Further Notes paragraph "Why remove `max_sp_depth` and not give it an effect" no longer says that the graph gives the full nested SP chain for each path
- [x] That paragraph says that the server has a separate expansion guard, `max_call_depth` with the value 5, and that the guard reports each truncated path as `call_expansion_truncated`
- [x] That paragraph says that a change to the guard needs its own spec
- [x] That paragraph keeps the sentence that rejects the "no caller uses the field" argument
- [x] The Implementation Decisions entry for the spec-rag client agrees with the corrected user story 11
- [x] No other part of the earlier spec changed
- [x] Ticket 03 of the earlier spec has one new line in its Comments that points to this spec
- [x] The status and the checklist of ticket 03 of the earlier spec did not change

**Note:** this ticket changes only Markdown in the `Impact_analysis_system` repository. If ticket 01 recorded a different behavior, write the rewrite to match the recorded behavior.

## Comments

### 2026-09-29 — implemented

- Changed files: `.scratch/retire-dead-flow-chain-surface/spec.md` (user stories 11 and 16, the spec-rag client entry in Implementation Decisions, the Further Notes paragraph "Why remove `max_sp_depth` and not give it an effect") and ticket 03 of that spec (one comment line). No other part changed.
- Ticket 01 recorded the behavior that this spec expects, so the rewrite follows the spec text. A code check confirms the premise: `service/execution_path_builder.py:26` sets `max_call_depth: int = 5`, `service/execution_path_builder.py:156` gives `call_expansion_truncated`, and `flow_chain_builder` passes no limit.
- The rewrite uses the term "expansion limit" everywhere. The spec text for the Further Notes paragraph says "expansion guard". The code review found three names for one concept, so this ticket uses one term. The meaning did not change.
- Further Notes: the paragraph has 6 sentences. The "no caller uses the field" rejection stays word for word. The sentence "the field's description says that it limits a behavior that does not exist" changed to "its description claims a depth control that the caller does not have", because the expansion limit exists. Only the caller control does not exist.
- The comment line in the earlier ticket 03 uses a relative path, like the `../spec.md` link in the body of that ticket. The words "records the correction of" point to the spec. Ticket 02 of this spec holds the spec-rag commit.
- Open point from the code review, not changed: the heading "Why remove `max_sp_depth` and not give it an effect" no longer has a reason for "not give it an effect". The old reason ("a depth limit would cut facts that the graph holds") was the wrong premise. The spec gives no new reason, so this ticket does not invent one.
- Open point from the code review, not changed: the rewritten user story 11 names only the truncation case. The cycle case (`stored_procedure_call_cycle`) follows the same route to `diagnostics`. The ticket did not ask for it.
