# 03 — A stopped run with an answer shows its report path

**What to build:** When the agent stops with no analyzed code but with a finalized answer, the command line prints the report path. The heading says the answer is finalized. The heading "analyzed no code" appears only when no answer exists. The person always finds the report. The work is in the `llamaindex-spec-rag` repository.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] The empty-scope branch picks its heading from the real state of the result.
- [ ] A test of the command line output shows the report path and the finalized heading for an empty scope with an answer.
- [ ] A test shows the old heading for an empty scope with no answer.
- [ ] The non-empty scope output does not change.
