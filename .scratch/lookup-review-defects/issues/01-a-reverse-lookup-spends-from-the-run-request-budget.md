# 01 — A reverse lookup spends from the run request budget

**What to build:** A stored-procedure lookup and a table lookup count against the one request budget of the agent run. When the budget is spent, the lookup lists each System it did not read, with the reason "request ceiling reached". The run does not stop and does not raise. The person sees which Systems have no answer and why. The work is in the `llamaindex-spec-rag` repository.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] Both lookups receive the budget of the agent run and pass it to the shared cross-system lookup. Neither creates its own budget.
- [ ] A test at the cross-system lookup entry shows that a spent budget puts each unread System in `unread_systems` with the new reason.
- [ ] The run continues after the ceiling is reached, and the Systems already read keep their answers.
- [ ] A stored-procedure lookup and a table lookup in the same run draw from the same budget.
- [ ] The report and the agent answer name the new reason in plain words.
- [ ] An existing reason ("request failed", "not scanned") keeps its meaning.
