# 02 — The spec-rag flow-chain description states the truncation

**What to build:** In the `llamaindex-spec-rag` repository, the docstring of the client function for `/flow_chain` tells a mode 3 agent the truth about the forward chain. A caller has no depth parameter. The server stops the expansion at a nesting that is too deep or at a stored-procedure call cycle. The truncated path goes to `diagnostics` and not to `stored_procedures` or `tables`. The return-value line lists `diagnostics`. The behavior of the function does not change. See `../spec.md` (in the `Impact_analysis_system` repository) for the agreed text and the reason.

**Blocked by:** 01 — A test proves where a truncated forward path goes.

**Status:** ready-for-agent

- [ ] The forward-direction paragraph no longer says "沒有深度控制：圖上記錄了幾層就回幾層"
- [ ] The forward-direction paragraph contains the agreed text from `../spec.md`, Implementation Decisions
- [ ] The docstring names the reasons `call_expansion_truncated` and `stored_procedure_call_cycle`
- [ ] The docstring does not state the numeric expansion limit
- [ ] The forward-direction sentence about the method call chain, the SP chain, and the tables of each SP stays
- [ ] The backward-direction sentence still says that column matching is approximate and not a guarantee
- [ ] The return-value line lists `diagnostics`. The other listed fields do not change
- [ ] Only the docstring changed. The function signature and body did not change
- [ ] The declared-databases flow-chain tests pass without modification
- [ ] No test file changed
- [ ] mypy on the changed file, run with the project virtual environment, has no new error compared to the commit before this ticket
- [ ] The full spec-rag test suite has no new failure compared to the commit before this ticket

**Note:** do the work and the commit in the `llamaindex-spec-rag` repository, not in `Impact_analysis_system`. The client module uses LF line endings. Keep them. Mark this ticket done in this file, in the `Impact_analysis_system` repository. If ticket 01 recorded a different behavior, write the docstring to match the recorded behavior, not the agreed text.
