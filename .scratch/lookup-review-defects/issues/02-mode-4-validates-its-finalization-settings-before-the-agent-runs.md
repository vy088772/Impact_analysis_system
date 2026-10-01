# 02 — Mode 4 validates its finalization settings before the agent runs

**What to build:** In mode 4, a wrong finalization setting fails before the agent starts, as in the other modes. The person does not wait for a full analysis to see the error. The message names the wrong setting. The work is in the `llamaindex-spec-rag` repository.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] Mode 4 builds its finalization options before the agent run.
- [ ] A new test at the mode 4 entry shows that a wrong setting raises and the fake agent runner records zero calls. This is the one new seam of the spec.
- [ ] The error message names the wrong setting.
- [ ] A correct setting gives the same result as before.
- [ ] Mode 4 and the other modes validate settings at the same point in the run.
